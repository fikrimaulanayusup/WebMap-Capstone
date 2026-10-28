"""Prediksi U-Net SAR; dijalankan di env conda `unet3` (TensorFlow 2.21 / Keras 3) untuk model
.keras, atau env `unet` (TensorFlow 2.10) untuk SavedModel kating.

python unet_runner.py <model .keras | folder SavedModel> <input.npz> <output.npy>

input.npz : image uint8 (H, W) citra SAR 8-bit, windows int (N, 2) pojok kiri-atas potongan,
            tile (th, tw) ukuran potongan, mode "cepat" | "standar" | "akurat"
output.npy: float16 (N, 256, 256, 5), probabilitas kelas 0 laut, 1 minyak, 2 look-alike,
            3 kapal, 4 darat per potongan (urutan diverifikasi pada data uji dataset latih)

Praproses sama dengan pelatihan kating (usetrainedmodel.py): cv2.resize ke 256 x 256
(interpolasi bawaan), kanal yang sama disalin menjadi 3 kanal, dibagi 255.

Penyesuaian saat prediksi (diuji pada 110 gambar uji dataset):
  cepat  : tanpa TTA, satu prediksi per potongan (seperti kating);
  standar: rata-rata 4 varian flip (asli, horizontal, vertikal, keduanya);
  akurat : untuk tiap flip, rata-rata 3 skala -- potongan asli, zoom-in 2x (4 sub-potongan) dan
           zoom-out 2x (jendela 2x lebih besar berisi konteks sekitarnya) -- seperti data latih
           yang dibuat multi-skala (Krestenitis dkk., 2019).
"""

import os
import sys

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import tensorflow as tf  # noqa: E402

FLIPS = ((False, False), (True, False), (False, True), (True, True))
# Input 256 x 256 per panggilan model.predict (~200 MB float32). Panggilan yang sedikit tapi besar
# jauh lebih cepat: tiap panggilan predict punya overhead tetap.
INPUTS_PER_CALL = 256


def _flip(a, fx, fy):
    a = a[:, ::-1] if fx else a
    return a[::-1] if fy else a


def _inputs(big, ph, pw, th, tw, mode):
    """Input 256 x 256 untuk satu jendela besar (sudah di-flip): [tile] atau [besar, tile, 4 sub]."""
    tile = big[ph:ph + th, pw:pw + tw]
    if mode != "akurat":
        return [cv2.resize(tile, (256, 256))]
    h2, w2 = th // 2, tw // 2
    subs = [tile[r * h2:(r + 1) * h2 if r == 0 else th, c * w2:(c + 1) * w2 if c == 0 else tw]
            for r in range(2) for c in range(2)]
    return [cv2.resize(big, (256, 256)), cv2.resize(tile, (256, 256))] + [cv2.resize(s, (256, 256)) for s in subs]


def _combine(p, big_shape, ph, pw, th, tw, mode):
    """Hasil model untuk satu varian -> probabilitas pada grid 256 x 256 potongan."""
    if mode != "akurat":
        return p[0]
    bh, bw = big_shape
    y0, y1 = round(ph / bh * 256), round((ph + th) / bh * 256)
    x0, x1 = round(pw / bw * 256), round((pw + tw) / bw * 256)
    zoom_out = cv2.resize(p[0][y0:y1, x0:x1], (256, 256), interpolation=cv2.INTER_LINEAR)
    zoom_in = np.zeros_like(p[1])
    for i in range(4):
        r, c = divmod(i, 2)
        zoom_in[r * 128:(r + 1) * 128, c * 128:(c + 1) * 128] = cv2.resize(p[2 + i], (128, 128), interpolation=cv2.INTER_AREA)
    return (zoom_out + p[1] + zoom_in) / 3


def _predictor(model_path: str, batch: int = 16):
    """Fungsi x (N, 256, 256, 3) -> probabilitas (N, 256, 256, 5).

    - Berkas `.keras` / `.h5` (mis. U-Net yang dilatih ulang dengan Keras 3): `load_model` biasa.
    - Folder SavedModel kating (Keras 2.10): graf dipanggil lewat signature `serving_default`.
      Keras 3 tidak bisa memuat folder ini dengan `load_model`, dan TensorFlow >= 2.16 gagal
      memuatnya sama sekali karena state optimizer Keras 2 ikut tersimpan; folder ini tetap
      butuh env TensorFlow 2.10.
    """
    if os.path.isfile(model_path):
        model = tf.keras.models.load_model(model_path, compile=False)
        return lambda x: model.predict(x, batch_size=batch, verbose=0)

    serve = tf.saved_model.load(model_path).signatures["serving_default"]
    (name,) = serve.structured_input_signature[1]

    def predict(x):
        out = [next(iter(serve(**{name: tf.constant(x[i:i + batch])}).values())).numpy()
               for i in range(0, len(x), batch)]
        return np.concatenate(out)
    return predict


def main(model_path: str, src: str, dst: str):
    predict = _predictor(model_path)
    data = np.load(src)
    image, windows = data["image"], data["windows"]
    th, tw = (int(v) for v in data["tile"])
    mode = str(data["mode"])
    ph, pw = (th // 2, tw // 2) if mode == "akurat" else (0, 0)
    padded = np.pad(image, ((ph, ph), (pw, pw)), mode="reflect")
    out = np.empty((len(windows), 256, 256, 5), dtype="float16")

    flips = ((False, False),) if mode == "cepat" else FLIPS
    tiles_per_call = max(1, INPUTS_PER_CALL // (len(flips) * (6 if mode == "akurat" else 1)))
    for start in range(0, len(windows), tiles_per_call):
        chunk = windows[start:start + tiles_per_call]
        bigs, inputs = [], []
        for r, c in chunk:
            big = padded[r:r + th + 2 * ph, c:c + tw + 2 * pw]
            bigs.append(big.shape)
            for fx, fy in flips:
                inputs += _inputs(np.ascontiguousarray(_flip(big, fx, fy)), ph, pw, th, tw, mode)
        x = np.repeat(np.stack(inputs)[..., None], 3, axis=-1).astype("float32") / 255.0
        probs = predict(x)
        per_variant = len(inputs) // (len(chunk) * len(flips))
        k = 0
        for i, shape in enumerate(bigs):
            acc = 0
            for fx, fy in flips:
                p = _combine(probs[k:k + per_variant], shape, ph, pw, th, tw, mode)
                acc = acc + _flip(p, fx, fy)
                k += per_variant
            out[start + i] = acc / len(flips)
    np.save(dst, out)
    print(f"{len(windows)} potongan diprediksi (mode {mode})")


if __name__ == "__main__":
    main(*sys.argv[1:4])
