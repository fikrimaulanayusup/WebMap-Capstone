"""Deteksi awan Sentinel-2 L2A (CloudSEN12, U-Net MobileNetV2); dijalankan di env conda `mados`.

python cloud_runner.py --input <stack.tif> --model <bobot .pth> --output <cloud_mask.tif>

Diadaptasi dari `cloud_detector.py` (dari dosen pembimbing; model asal:
earthnet-minicuber/provider/s2/cloudmask.py). Arsitektur, bobot, urutan band, normalisasi,
padding cermin ke kelipatan 32, dan prediksi seluruh citra sekaligus sama dengan aslinya;
bedanya hanya masukan berupa GeoTIFF 13 band yang sudah diurutkan (dibuat di marinext.py),
jadi tidak perlu xarray/rioxarray.

Seluruh citra sengaja diprediksi sekali jalan: model ini sangat bergantung pada konteks
(medan pandang ~500 piksel), sehingga prediksi per potongan 1024 px menimbulkan garis
sambungan yang jelas. RAM puncak (CPU): kotak 20 km ~2 GB, 40 km ~4 GB, ~30 detik.

Urutan band masukan (sama dengan CloudDetector.bands):
  B01 B02 B03 B04 B05 B06 B07 B8A B09 B11 B12 AOT WVP
Nilai: reflektansi L2A x 10000 (offset baseline >= 04.00 sudah dibuang), AOT/WVP DN mentah.

Keluaran uint8: 0 cerah, 1 awan tebal, 2 awan tipis, 3 bayangan awan, 255 tanpa data.
"""

import argparse
from pathlib import Path

import numpy as np
import rasterio
import torch

MODEL_URL = "https://nextcloud.bgc-jena.mpg.de/s/qHKcyZpzHtXnzL2/download/mobilenetv2_l2a_all.pth"
BANDS = ["B01", "B02", "B03", "B04", "B05", "B06", "B07", "B8A", "B09", "B11", "B12", "AOT", "WVP"]
SCALE = np.array(11 * [10000.0] + [65535.0, 65535.0], dtype="float32")[:, None, None]
NODATA = 255


def load_model(path: Path, device):
    import segmentation_models_pytorch as smp

    if not path.is_file():  # unduh sekali, lalu disimpan di folder models proyek
        path.parent.mkdir(parents=True, exist_ok=True)
        torch.hub.download_url_to_file(MODEL_URL, str(path))
    model = smp.Unet(encoder_name="mobilenet_v2", encoder_weights=None, classes=4, in_channels=len(BANDS))
    model.load_state_dict(torch.load(path, map_location="cpu"))
    return model.eval().to(device)


def _pad32(x: torch.Tensor):
    """Padding cermin ke kelipatan 32, persis seperti cloud_detector.py."""
    _, _, h, w = x.shape
    h_pad, w_pad = (h // 32 + 1) * 32, (w // 32 + 1) * 32
    top, bottom = (h_pad - h) // 2, (h_pad - h + 1) // 2
    left, right = (w_pad - w) // 2, (w_pad - w + 1) // 2
    # mode reflect butuh padding < sisi citra; potongan sangat kecil memakai replicate
    mode = "reflect" if max(top, bottom) < h and max(left, right) < w else "replicate"
    return torch.nn.functional.pad(x, (left, right, top, bottom), mode=mode), (top, left, h, w)


@torch.no_grad()
def predict(model, image: np.ndarray, device) -> np.ndarray:
    x, (top, left, h, w) = _pad32(torch.from_numpy(image)[None].to(device))
    return model(x).argmax(dim=1)[0, top:top + h, left:left + w].cpu().numpy().astype("uint8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    with rasterio.open(args.input) as src:
        if src.count != len(BANDS):
            raise SystemExit(f"Masukan harus {len(BANDS)} band ({' '.join(BANDS)}), bukan {src.count}.")
        stack = src.read().astype("float32")
        profile = src.profile
    invalid = (stack[:11] <= 0).all(axis=0)  # di luar sapuan sensor / tanpa data L2A
    image = np.nan_to_num(stack / SCALE, nan=0.0).astype("float32")
    del stack

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = load_model(Path(args.model), device)
    mask = predict(model, image, device)
    mask[invalid] = NODATA

    profile.update(count=1, dtype="uint8", nodata=NODATA, compress="deflate", predictor=1)
    with rasterio.open(args.output, "w", **profile) as dst:
        dst.write(mask, 1)
        dst.set_band_description(1, "cloud_mask")
        dst.update_tags(1, classes="0=clear,1=thick_cloud,2=thin_cloud,3=cloud_shadow,255=nodata")
    counts = {name: int((mask == v).sum()) for v, name in enumerate(("clear", "thick", "thin", "shadow"))}
    print("cloud mask:", counts, "nodata:", int(invalid.sum()))


if __name__ == "__main__":
    main()
