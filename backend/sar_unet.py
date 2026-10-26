"""Klasifikasi SAR Sentinel-1 dengan U-Net dari WebGIS kating (5 kelas, Oil Spill Detection Dataset).

Model: `models/saved_unetmodel_tf` di folder WebGIS kating (Keras 2.10, optimizer Adam), dimuat
apa adanya di env conda `unet`. Evaluasi pada 110 gambar uji dataset: IoU minyak 39,6%
(F1 56,7%), laut 94,8%, look-alike 40,5%, kapal 22,1%, darat 91,2%.

Alur:
  1. sigma0 VV terkalibrasi pada 10 m -> dB -> median 7 x 7 (redam speckle); kotak yang terlalu
     besar untuk 10 m (80 km) otomatis dibaca dari overview 20 m;
  2. dB dipetakan ke 0-255 dengan rentang tetap -35..0 dB (sama dengan ekspor SNAP); piksel tanpa
     data diisi nilai laut tipikal (median), bukan 0;
  3. dipotong per ~12,5 x 6,5 km (seukuran gambar latih 1250 x 650 piksel 10 m), tumpang
     tindih 50%; tiap potongan diperkecil ke 256 x 256 dengan cv2 di env `unet`;
  4. probabilitas digabung dengan bobot kosinus agar batas potongan tidak tampak;
  5. pembersihan morfologi seperti app.py kating; semua kelas (termasuk Darat) murni dari model,
     tanpa masker darat dan tanpa batas luas petak minimum;
  6. hasil dipetakan ke UTM 10 m.
Paper dataset (Krestenitis dkk., 2019, doi:10.3390/rs11151762): VV terkalibrasi, median 7 x 7,
transformasi linear dB -> kecerahan (rentang tidak disebut), di-rescale ke 1250 x 650 pada
beberapa tingkat zoom; ukuran piksel latih tidak tetap.
"""

import os
from pathlib import Path

import numpy as np
from rasterio.enums import Resampling
from scipy import ndimage

from . import jobs, sar
from .geo import DetectionError, analysis_box, lonlat_grid
from .results import summarise

MODEL_DIR = Path(os.environ.get("SAR_UNET_MODEL", r"C:\Akademik\Capstone\WEBGIS KATING\webgis\models\saved_unetmodel_tf"))
UNET_ENV = os.environ.get("SAR_UNET_ENV", "unet")
RUNNER = Path(__file__).resolve().parent / "unet_runner.py"

AOI_SIZES_KM = (20, 40, 80)
RES_M = 10
TILE_M = (6500, 12500)  # tinggi x lebar potongan, seukuran gambar latih 650 x 1250 piksel 10 m
MEDIAN_SIZE = 7  # filter speckle (piksel)
DB_RANGE = (-35.0, 0.0)  # sigma0 dB yang dipetakan ke 0-255 (sama dengan ekspor SNAP pengguna)
# Mode prediksi (TTA). Pada 110 gambar uji, tanpa bobot kelas: cepat (tanpa TTA) minyak 39,6% / mIoU 57,6%;
# standar (flip) minyak 38,8% / mIoU 59,7% / kapal 25,3%; akurat (multi-skala + flip) minyak 38,6% /
# mIoU 57,4% / kapal 12,3%.
MODES = ("cepat", "standar", "akurat")
STAGES = ["Kalibrasi σ⁰ Sentinel-1", "U-Net: segmentasi 5 kelas", "Menyusun hasil"]

# Kelas keluaran model + 1 (0 = tanpa data); warna resmi dataset.
CLASSES = [
    ("Sea Surface", "Laut", "#000000"),
    ("Oil Spill", "Tumpahan minyak", "#00ffff"),
    ("Look-alike", "Look-alike", "#ff0000"),
    ("Ship", "Kapal", "#994c00"),
    ("Land", "Darat", "#009900"),
]
SEA, OIL, LOOKALIKE, SHIP, LAND = 1, 2, 3, 4, 5


def start_job(item: dict, bbox, max_km: int, mode: str = "standar") -> str:
    if max_km not in AOI_SIZES_KM:
        raise DetectionError(f"Ukuran kotak SAR harus salah satu dari {AOI_SIZES_KM} km.")
    if mode not in MODES:
        raise DetectionError(f"Mode prediksi harus salah satu dari {MODES}.")
    if not MODEL_DIR.is_dir():
        raise DetectionError(f"Model U-Net tidak ditemukan di {MODEL_DIR}.")
    aoi = analysis_box(bbox, item["bbox"], max_km)
    return jobs.start("sar-unet", STAGES, aoi, lambda job: _run(job, item, aoi, mode))


def _window_starts(size: int, tile: int) -> list[int]:
    if size <= tile:
        return [0]
    starts = list(range(0, size - tile + 1, max(1, tile // 2)))
    if starts[-1] + tile < size:
        starts.append(size - tile)
    return starts


def _run(job: jobs.Job, item: dict, aoi, mode: str) -> dict:
    job.stage(0)
    scene = sar.read_sigma0(item, aoi, RES_M)
    valid = np.isfinite(scene.sigma0)
    if valid.sum() < 1000:
        raise DetectionError("Hampir tidak ada data SAR di dalam kotak.")
    db = 10 * np.log10(np.where(valid, scene.sigma0, np.nanmedian(scene.sigma0)))
    db = ndimage.median_filter(db, size=MEDIAN_SIZE).astype("float32")

    lon, lat = lonlat_grid(scene.grid)
    west, south, east, north = aoi
    inside = valid & (lon >= west) & (lon <= east) & (lat >= south) & (lat <= north)

    # Rentang dB tetap ke 0-255, sama dengan ekspor SNAP pengguna: (clip(dB, -35, 0) + 35) / 35 * 255.
    # Piksel tanpa data sudah berisi median sigma0 (nilai laut tipikal), bukan 0: nilai 0 (hitam)
    # dibaca model sebagai minyak/look-alike.
    lo, hi = DB_RANGE
    image = np.round((np.clip(db, lo, hi) - lo) / (hi - lo) * 255).astype("uint8")

    # Potongan seukuran gambar latih dengan tumpang tindih 50%.
    h, w = image.shape
    th, tw = min(h, round(TILE_M[0] / scene.grid.res_m)), min(w, round(TILE_M[1] / scene.grid.res_m))
    windows = [(r, c) for r in _window_starts(h, th) for c in _window_starts(w, tw)
               if valid[r:r + th, c:c + tw].mean() > 0.2]
    if not windows:
        raise DetectionError("Hampir tidak ada data SAR di dalam kotak.")
    job.stage(1)
    src, dst = job.dir / "unet_input.npz", job.dir / "unet_probs.npy"
    np.savez(src, image=image, windows=np.array(windows, dtype="int64"), tile=np.array([th, tw]), mode=mode)
    jobs.conda_run(UNET_ENV, [str(RUNNER), str(MODEL_DIR), str(src), str(dst)],
                   RUNNER.parent, job.dir / "unet.log", timeout=30 * 60)
    probs = np.load(dst)  # (N, 256, 256, 5)

    # Gabung: perbesar kembali ke ukuran potongan, bobot kosinus agar tepi potongan berbobot kecil.
    weight_tile = np.outer(np.hanning(th + 2)[1:-1], np.hanning(tw + 2)[1:-1]).astype("float32") + 1e-3
    prob_sum = np.zeros((5, h, w), dtype="float32")
    weight_sum = np.zeros((h, w), dtype="float32")
    zoom = (th / probs.shape[1], tw / probs.shape[2])
    for (r, c), p in zip(windows, probs):
        for k in range(5):
            up = ndimage.zoom(p[..., k].astype("float32"), zoom, order=1, grid_mode=True, mode="nearest")[:th, :tw]
            prob_sum[k, r:r + th, c:c + tw] += up * weight_tile
        weight_sum[r:r + th, c:c + tw] += weight_tile
    covered = weight_sum > 0
    prob = prob_sum / np.maximum(weight_sum, 1e-6)
    del prob_sum

    job.stage(2)
    classes = (np.argmax(prob, axis=0) + 1).astype("uint8")
    # Seperti app.py kating: minyak & look-alike dibuka 1x lalu ditutup 2x (kernel 3 x 3).
    for value in (OIL, LOOKALIKE):
        m = ndimage.binary_opening(classes == value, structure=np.ones((3, 3), bool), iterations=1)
        m = ndimage.binary_closing(m, structure=np.ones((3, 3), bool), iterations=2)
        classes[m] = value
    classes[~(inside & covered)] = 0
    oil_prob = np.where(classes > 0, prob[OIL - 1], np.nan).astype("float32")
    del prob

    profile = sar.utm_profile(aoi, RES_M)
    classes_utm = sar.to_utm(classes, scene.grid, profile, Resampling.nearest, 0)
    prob_utm = sar.to_utm(oil_prob, scene.grid, profile, Resampling.bilinear, np.nan)
    # Tanpa petak minimum: setiap petak minyak, sekecil apa pun, dijadikan poligon.
    result = summarise(classes_utm, prob_utm, profile, job.dir / "result", job.id, CLASSES, OIL, min_oil_pixels=1)
    result.update(model="U-Net SAR", polarization=scene.polarization, scene_id=item["id"],
                  product=item["properties"].get("s1:product_identifier", item["id"]),
                  aoi=[round(v, 5) for v in aoi], tiles=len(windows))
    for path in (src, dst):
        path.unlink(missing_ok=True)
    return result
