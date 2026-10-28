"""Prediksi MariNeXt dengan penggabungan jendela yang halus; dijalankan di env conda `mados`.

python marinext_runner.py --mados_dir <repo MADOS> --input <folder rhorc> --model_path <berkas atau folder .pth>
                          --output <folder hasil> [--stride 120] [--tta False]

Repositori MADOS tidak diubah: `marinext/predict.py` diimpor apa adanya (baca 11 band rhorc,
isi NaN + standarisasi, muat model, TTA, tulis classes.tif / oil_spill_prob.tif). Yang diganti
hanya `sliding_window`, yaitu cara jendela 240 x 240 digabung:

  predict.py asli : rata-rata bobot sama -> tepi jendela (konteks kurang) ikut berbobot penuh,
                    tampak sebagai garis kisi tiap `stride` piksel di perairan yang membuat ragu;
  di sini          : citra dipad cermin (TILE - stride) piksel, tiap jendela dikali jendela
                    spline orde 2 (tepi ~0, tengah tinggi), lalu dibagi jumlah bobot per piksel.

Jendela spline mengikuti Smoothly-Blend-Image-Patches (Vooban Inc., G. Chevalier, MIT License,
https://github.com/Vooban/Smoothly-Blend-Image-Patches), dengan normalisasi jumlah bobot
sebenarnya agar benar untuk citra yang tidak persegi.
"""

import argparse
import os
import sys

import numpy as np


def _triang(m: int) -> np.ndarray:
    """Sama dengan scipy.signal.triang(m)."""
    n = np.arange(1, (m + 1) // 2 + 1)
    if m % 2 == 0:
        w = (2 * n - 1.0) / m
        return np.r_[w, w[::-1]]
    w = 2 * n / (m + 1.0)
    return np.r_[w, w[-2::-1]]


def spline_window_2d(size: int, power: int = 2) -> np.ndarray:
    """Jendela spline orde 2 (Vooban `_spline_window`), diperluas ke 2D."""
    intersection = size // 4
    outer = (np.abs(2 * _triang(size)) ** power) / 2
    outer[intersection:-intersection] = 0
    inner = 1 - (np.abs(2 * (_triang(size) - 1)) ** power) / 2
    inner[:intersection] = 0
    inner[-intersection:] = 0
    w = inner + outer
    w = w / np.average(w)
    return np.outer(w, w).astype("float32")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mados_dir", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--model_path", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--stride", type=int, default=120)
    parser.add_argument("--batch", type=int, default=8)
    parser.add_argument("--tta", default="False")
    args = parser.parse_args()

    sys.path.insert(0, os.path.join(args.mados_dir, "marinext"))
    import predict as P  # noqa: E402  (repo MADOS, tidak diubah)
    import torch  # noqa: E402

    def smooth_sliding_window(image, models, device, stride, batch, tta):
        tile = P.TILE
        C, H, W = image.shape
        pad = tile - stride  # = TILE * (1 - 1/subdivisions); tiap piksel asli tercakup penuh
        padded = np.pad(image, ((0, 0), (pad, pad), (pad, pad)), mode="reflect")
        Hp, Wp = padded.shape[1:]
        positions = [(y, x) for y in P.window_starts(Hp, stride) for x in P.window_starts(Wp, stride)]
        weight_tile = spline_window_2d(tile)
        prob_sum = np.zeros((len(P.labels), Hp, Wp), dtype=np.float32)
        weight = np.zeros((Hp, Wp), dtype=np.float32)
        with torch.no_grad():
            for i in P.tqdm(range(0, len(positions), batch), desc="predicting (smooth)"):
                chunk = positions[i:i + batch]
                tiles = np.stack([padded[:, y:y + tile, x:x + tile] for y, x in chunk])
                probs = P.predict_tiles(models, torch.from_numpy(tiles).to(device), tta).cpu().numpy()
                for (y, x), p in zip(chunk, probs):
                    prob_sum[:, y:y + tile, x:x + tile] += p * weight_tile
                    weight[y:y + tile, x:x + tile] += weight_tile
        out = prob_sum / np.maximum(weight, 1e-6)
        return out[:, pad:pad + H, pad:pad + W]

    P.sliding_window = smooth_sliding_window
    P.main({"input": args.input, "model_path": args.model_path, "output": args.output,
            "stride": args.stride, "batch": args.batch, "tta": args.tta.lower() in ("1", "true", "yes")})


if __name__ == "__main__":
    main()
