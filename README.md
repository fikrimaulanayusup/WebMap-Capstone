# Web-Map Tumpahan Minyak — Prototipe

WebGIS yang mencari citra Sentinel-2 (optik) dan Sentinel-1 GRD (radar) di AWS Open Data
berdasarkan **rentang tanggal** dan area peta, menampilkannya langsung dari bucket S3 sebagai
layer peta, lalu **mengklasifikasikan oil slick**: Sentinel-2 dengan model deep learning
MariNeXt (MADOS), Sentinel-1 dengan model deep learning U-Net (arsitektur kating, dilatih ulang dengan Keras 3).

## Menjalankan

Dari folder proyek ini (PowerShell):

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --port 8000
```

Lalu buka <http://127.0.0.1:8000>.

Jika folder `.venv` belum ada (mis. di komputer lain), buat dulu dengan Python 3.10+:

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
```

## Cara pakai

1. Klik menu **Citra Satelit** di kiri. Panel citra terbuka dan langsung mencari dengan filter
   bawaan (Sentinel-2, 7 hari terakhir, awan ≤ 50%).
2. Chip di atas panel (mis. **Sentinel-2**) menunjukkan sensor hasil filter. Klik **ikon filter**
   di sebelahnya untuk mengganti sensor, tanggal **Dari – Sampai** (atau tombol 3/7/14/30 hari),
   tutupan awan maksimum (Sentinel-2), atau arah orbit (Sentinel-1), lalu **Terapkan**.
3. Pencarian memakai area yang terlihat di peta. Setelah menggeser peta, klik **Cari di area ini**.
4. Hasil dikelompokkan per tanggal. Klik sebuah citra untuk menampilkannya, atau
   **Tampilkan semua** untuk seluruh citra pada tanggal itu.
5. Panel *Tampilan citra*: transparansi untuk semua sensor; untuk Sentinel-1 juga polarisasi
   (VV/VH) dan kontras. Lapisan minyak tampak sebagai bercak **gelap** di citra radar, paling
   jelas di VV.

## Pencarian lokasi

Kotak **Cari lokasi** di kiri atas peta: ketik nama tempat lalu tekan **Enter** (dicari lewat
OpenStreetMap Nominatim melalui `/api/geocode`; maks. 1 permintaan per detik sesuai aturan pakai
Nominatim, hasil di-cache), atau ketik koordinat `lat, lon` (mis. `-6.05, 106.75`) yang langsung
dikenali tanpa permintaan ke internet. Pilih hasil dengan klik atau panah atas/bawah + Enter;
peta langsung pindah ke lokasi itu (tanpa penanda).

## Deteksi oil spill

Panel ini berdiri sendiri; menu **Citra Satelit** tidak perlu dibuka.

1. Buka menu **Deteksi Oil Spill** dan pilih sensor: **Sentinel-2 (MariNeXt)** atau
   **Sentinel-1 (U-Net SAR)**.
2. **Area analisis**: pilih ukuran kotak maksimum (MariNeXt: 10, 20, atau 40 km; U-Net SAR:
   20, 40, atau 80 km), klik **Gambar kotak**, lalu tarik di peta. Klik sekali di peta untuk
   menaruh kotak seukuran pilihan di titik itu. Kotak yang ditarik lebih besar dari batas dipotong otomatis.
   Kotak yang sudah ada bisa **ditarik untuk dipindah**; daftar citra dicari ulang setelah dilepas.
3. **Tanggal**: Dari–Sampai (bawaan 30 hari terakhir) dan, untuk Sentinel-2, batas awan.
4. **Citra**: citra yang menutupi kotak dicari otomatis setiap kali kotak, tanggal, atau sensor
   berubah. Daftar diurutkan: menutupi kotak penuh → awan paling sedikit → paling baru. Citra
   teratas (label *terbaik*) sudah terpilih dan langsung ditampilkan di peta; pilih yang lain
   bila perlu.
5. Klik **Klasifikasi dengan MariNeXt** (atau **Klasifikasi SAR dengan U-Net**). Yang
   dianalisis tepat area kotak. **Hapus** membersihkan hasil dari peta.

Kedua model berjalan di latar belakang server, satu pekerjaan sekaligus (`backend/jobs.py`);
panel menampilkan tahap dan waktunya. Hasilnya sama bentuknya: peta kelas (overlay), tabel luas
per kelas, poligon tiap petak Oil Spill (luas, probabilitas rata-rata/maksimum), dan unduhan
`classes.tif`, `oil_spill_prob.tif`, `oil_spill.geojson`. Folder kerja tiap pekerjaan ada di
`cache/jobs/<id>/` dan disimpan untuk 20 pekerjaan terakhir (yang lebih lama dihapus otomatis).

### Optik: MariNeXt (Sentinel-2)

Model deep learning MariNeXt dari repositori MADOS (`<induk proyek>\Deep Learning\mados-master`),
model 2 (sama dengan WebGIS kating), 15 kelas. Kodenya di `backend/marinext.py`; repositori MADOS dan ACOLITE **tidak diubah**.
Bobot model 2 (`trained_models/2/marinext_2.pth`) disalin ke `models/marinext_2.pth` di folder proyek
dan dibaca dari sana (identik, hasil klasifikasi sama 100%); repo MADOS tetap dibutuhkan untuk kodenya
(`predict.py`, `mmseg`, `utils`).

Alur satu klasifikasi (berjalan di latar belakang; panel menampilkan tahap dan waktunya):

1. **Area analisis**: kotak yang digambar pengguna, dipotong dengan jejak citra (maks. 10, 20,
   atau 40 km per sisi, sesuai pilihan).
2. **L1C**: citra dipilih dari katalog L2A (hanya untuk mencari dan menampilkan warna asli 10 m;
   nilai pikselnya tidak dipakai model), lalu produk Sentinel-2 **L1C** dari akuisisi yang sama
   (bucket AWS `sentinel-s2-l1c`) dicari lewat Earth Search. Band L1C (JPEG2000) sendiri terlalu
   lambat untuk tile peta (tile pertama ±7 menit). Hanya 13 band untuk area analisis yang diunduh, lalu disusun menjadi folder SAFE yang
   bisa dibaca ACOLITE (metadata asli; band berupa VRT bernama `.jp2` yang menunjuk potongan
   GeoTIFF lokal).
3. **ACOLITE Python** (env conda `acolite`, kode di `<induk proyek>\Acolite\acolite-main`)
   dijalankan dengan setelan yang sama seperti data latih MADOS: `s2_target_res=10`,
   `output_rhorc=True`, `l2r_export_geotiff=True`.
4. **`marinext/predict.py`** (env conda `mados`) dijalankan apa adanya pada 11 band rhorc.
5. **Hasil**: peta 15 kelas (overlay), tabel luas per kelas, poligon tiap petak Oil Spill
   (luas, probabilitas rata-rata/maksimum), dan unduhan `classes.tif`,
   `oil_spill_prob.tif`, `oil_spill.geojson`. Daratan (Copernicus DEM) dibuang dari hasil
   karena model hanya dilatih di permukaan laut.

Waktu (CPU laptop, langkah 60): ~5 menit untuk kotak 10 km, ~15 menit untuk 20 km, dan ~45 menit
untuk 40 km (butuh ~2 GB RAM bebas). Satu tile Sentinel-2 penuh (110 km) tidak
didukung: `predict.py` akan butuh ~13 GB RAM. Folder kerjanya (`cache/jobs/<id>/`) menyimpan
rhorc, hasil, dan log ACOLITE/predict.

**Validasi — Karawang, 12 Sep 2019 (T48MYU, tumpahan Pertamina YYA-1)**, dibandingkan dengan
ACOLITE + `predict.py` yang dijalankan manual pada area yang sama (keduanya memakai model 1; dengan model 2 luas Oil Spill WebGIS menjadi 4,07 km²):

| | WebGIS (AWS, baseline N0208) | Manual (SAFE N0500) |
|---|---|---|
| rhorc, bias rata-rata semua band | 0,0000 | — |
| Luas Oil Spill | 3,788 km² | 3,839 km² |
| Kesesuaian kelas semua piksel | 92,3% | |
| IoU Oil Spill | 88,7% (96,9% dengan toleransi 1 piksel) | |

Selisih berasal dari geolokasi produk: data 2019 di AWS adalah baseline asli N0208, sedangkan
SAFE manual adalah reprocessing N0500 (geolokasi diperhalus, bergeser ~0,4–0,7 piksel).

**Penggabungan jendela (garis kisi).** `predict.py` memprediksi per jendela 240×240 dengan
stride 120 dan merata-rata jendela dengan bobot sama; tepi jendela (konteks kurang) ikut berbobot
penuh sehingga di perairan yang membuat model ragu muncul garis kisi tiap 1,2 km (WebGIS kating
sama). WebGIS ini menjalankan MariNeXt lewat `backend/marinext_runner.py`: `predict.py` diimpor
apa adanya (repo MADOS tidak diubah) dan hanya `sliding_window` yang diganti — citra dipad
cermin 120 piksel, tiap jendela dikali **jendela spline orde 2** (Smoothly-Blend-Image-Patches,
Vooban, MIT), lalu dibagi jumlah bobot per piksel. Jendela digeser **60 piksel** (bukan 120):
model punya bias posisi di dalam jendela (tengah vs pinggir jendela diberi kelas berbeda), dan
bobot spline saja hanya memindahkan pola garis menjadi bercak di tengah jendela; dengan langkah
60 tiap piksel dirata-rata dari 16 posisi berbeda sehingga bias itu terhapus. TTA tidak dipakai:
rotasi/cermin tidak mengubah posisi di dalam jendela.

| Langkah (spline, tanpa TTA) | 15 Okt 2026 T48MYU (sunglint) | 12 Sep 2019 T48MXU | Karawang |
|---|---|---|---|
| Pola berulang* langkah 120 / **60** / 40 | 32,9 / **12,1** / 1,6 | 2,1 / **0,6** / 0,5 | 0,7 / **0,7** / 0,7 |
| Oil Spill (km²) langkah 120 / **60** / 40 | 0,045 / **0,012** / 0,015 | 25,66 / **25,38** / 25,43 | 3,95 / **3,90** / 3,82 |
| Waktu tahap MariNeXt, kotak 10 km | 49 / **180** / 439 dtk | | |

\* varians rata-rata kelas per posisi (x mod 120, y mod 120) dibagi varians tanpa pola; ≤ ~1 =
tidak berulang. Tabel di bawah membandingkan `predict.py` asli dengan versi spline langkah 120.

| Uji (model 2, tanpa TTA) | Rasio garis kisi* asli → halus | Oil Spill asli → halus | Kesesuaian kelas |
|---|---|---|---|
| 12 Sep 2019 T48MXU (perairan keruh) | 7,95 → **1,09** | 38,6 → 25,7 km² | 85,0% |
| 15 Okt 2026 T48MYU (sunglint) | 5,85 → **1,00** | 14,3 → 37,1 km² | 52,3% |
| Validasi Karawang (rhorc manual) | 1,21 → **0,99** | 4,09 → 3,95 km² (IoU 80%) | 90,8% |

\* perubahan kelas di baris/kolom tepi jendela dibagi di tempat lain; 1 = tidak ada pola kisi.
Citra bersunglint berada di luar sebaran data latih; hasilnya tidak andal dengan cara
penggabungan mana pun (pada langkah 60 pola berulangnya pun masih tersisa, 12,1).

Persyaratan di komputer: conda dengan env `acolite` (dibuat dari
`environment.yml` ACOLITE lewat channel conda-forge) dan env `mados`; LUT ACOLITE di
`acolite-main\data\LUT` (tautan ke LUT instalasi `acolite_py_win`).

Lokasi bawaan tidak terikat ke `C:\`:
- repo MADOS dan ACOLITE dicari relatif terhadap **folder induk proyek**:
  `<induk>\Deep Learning\mados-master` dan `<induk>\Acolite\acolite-main` (di laptop pengembang
  induknya `C:\Akademik\Capstone`); susunan folder `Capstone` bisa disalin ke drive mana pun;
- `conda.exe` dicari berurutan: `MARINEXT_CONDA`, `CONDA_EXE` (terisi bila server dijalankan dari
  Anaconda Prompt), lalu `miniconda3` / `anaconda3` / `miniforge3` di `C:\`, folder user,
  `AppData\Local`, dan `C:\ProgramData`;
- kedua model dibaca dari `models\` di folder proyek.

Bila folder MADOS, ACOLITE, atau model tidak ditemukan, klasifikasi langsung ditolak dengan pesan
lokasinya. Semua lokasi bisa diubah lewat variabel lingkungan `MARINEXT_CONDA`, `MARINEXT_ACOLITE_DIR`, `MARINEXT_MADOS_DIR`,
`MARINEXT_ACOLITE_ENV`, `MARINEXT_MADOS_ENV`, dan `MARINEXT_MODEL` (berkas `.pth`; bila diisi folder,
semua `.pth` di dalamnya dipakai sebagai ensemble).

### SAR: U-Net (Sentinel-1)

Model bawaan: **`models/unet_oilspill.keras`**, U-Net dengan arsitektur yang sama seperti model
kating, dilatih ulang dengan **Keras 3** (Kaggle, Keras 3.13.2, 100 epoch, Adam) pada
*Oil Spill Detection Dataset* (Krestenitis dkk.), 5 kelas: laut, tumpahan minyak, look-alike,
kapal, darat. Kodenya di `backend/sar_unet.py` (alur) dan `backend/unet_runner.py` (prediksi,
dijalankan di env conda `unet3`: Python 3.12, `tensorflow` 2.21.0, Keras 3.15.1, `numpy` 2.5,
`opencv-python-headless` 5.0). Model ini **belum dievaluasi** pada 110 gambar uji; angka evaluasi
di bawah adalah milik model kating.

Model kating asli (`C:\Akademik\Capstone\WEBGIS KATING\webgis\models\saved_unetmodel_tf`, SavedModel
Keras 2.10) masih bisa dipakai dengan `SAR_UNET_MODEL=<folder itu>` dan `SAR_UNET_ENV=unet`
(env lama: Python 3.10, `tensorflow-cpu` 2.10.1, `numpy` 1.23.5, `opencv-python-headless` 4.7).
SavedModel ini tidak bisa dibaca TensorFlow ≥ 2.16 / Keras 3: `load_model` menolak formatnya, dan
`tf.saved_model.load` gagal karena state optimizer Keras 2 ikut tersimpan. `unet_runner.py` memilih
cara memuat sesuai jenisnya: berkas `.keras`/`.h5` lewat `load_model`, folder SavedModel lewat
signature `serving_default` (hasilnya identik dengan cara lama, selisih 0).

Gambar latih dataset adalah potongan Sentinel-1 1250 × 650 piksel, oleh kating diperkecil ke
256 × 256. Alurnya:

1. Kalibrasi radiometrik ke σ⁰ dengan LUT `sigmaNought`, setelah derau termal (LUT range ×
   azimuth) dikurangkan (`backend/sar.py`). Diubah ke dB pada 10 m, dihaluskan median 7 × 7.
   Kotak 80 km terlalu besar untuk 10 m (batas 6000 piksel per sisi) sehingga otomatis dibaca
   dari overview 20 m.
2. dB dipetakan ke 0–255 dengan **rentang tetap −35..0 dB**:
   `(clip(dB, −35, 0) + 35) / 35 × 255`, sama dengan ekspor SNAP. Piksel tanpa data diisi nilai
   laut tipikal (median), bukan 0, karena nilai 0 (hitam) dibaca model sebagai minyak/look-alike.
   Batasan: target sangat terang (kapal besar, struktur ±16 dB) menjadi putih jenuh dan bisa
   terbaca sebagai darat (contoh Teluk Jakarta di bawah).

   Perbandingan rentang (mode standar; % piksel kotak):

   | Citra | Rentang | Minyak | Look-alike | Darat |
   |---|---|---|---|---|
   | Teluk Jakarta 12 Okt 2026, 20 km | **−35..0** / −35..+5 / −35..+10 | **0,22** / 0,13 / 0,11 | **0,05** / 0,92 / 2,08 | **4,86** / 2,43 / 0,12 |
   | Batam 10 Okt 2026, 20 km (banyak pulau) | **−35..0** / −35..+5 / −35..+10 | **0,75** / 0,65 / 0,59 | **8,75** / 10,86 / 13,35 | **5,03** / 4,80 / 1,88 |
   | Teluk Meksiko 29 Jul 2026, 80 km | **−35..0** / −35..+5 / −35..+10 | **0,21** / 0,26 / 0,15 | **17,6** / 20,6 / 25,0 | **0** / 0 / 0 |

   Rentang lebih lebar menghilangkan "darat" palsu dari target terang, tetapi menggelapkan semua
   piksel: daratan asli berkurang dan look-alike bertambah. Min–max seluruh kotak memberi 5,1%
   darat palsu di Teluk Meksiko dan pulau Batam hampir hilang (0,01%).
3. Dipotong per ~12,5 × 6,5 km (1250 × 650 piksel 10 m) dengan tumpang tindih 50%; potongan
   yang datanya < 20% dilewati. Tiap potongan diperkecil ke 256 × 256 (`cv2.resize`), disalin
   ke 3 kanal, dibagi 255.
4. Probabilitas tiap potongan diperbesar kembali dan digabung dengan bobot kosinus agar batas
   potongan tidak tampak.
   **Penyesuaian saat prediksi** (`unet_runner.py`, pilihan *Mode prediksi* di panel):
   - *akurat*: tiap potongan juga diprediksi pada zoom-out 2× (jendela 2× lebih besar
     berisi konteks sekitarnya) dan zoom-in 2× (4 sub-potongan), masing-masing dalam 4 varian
     flip; 24 prediksi per potongan dirata-rata. Dasarnya: data latih dibuat multi-skala
     (zoom 1–3) dan diaugmentasi flip (Krestenitis dkk., 2019).
   - *standar* (bawaan): 4 varian flip saja.
   - *cepat*: tanpa TTA, satu prediksi per potongan (seperti kating); IoU minyak sama baiknya
     (39,6%), kelas lain sedikit lebih rendah.
5. Kelas = probabilitas terbesar (argmax, tanpa bobot kelas — sama dengan kating dan paper).
   Minyak dan look-alike lalu dibersihkan morfologi (buka 1×, tutup 2×,
   kernel 3 × 3) seperti `app.py` kating. Semua kelas, termasuk Darat, murni hasil model: tanpa
   masker darat DEM dan tanpa batas luas petak minimum (setiap petak minyak menjadi poligon).
6. Hasil dipetakan ke UTM 10 m. Di overlay, laut berwarna hitam seperti legenda dataset; hanya
   area tanpa data yang transparan.

Urutan kelas keluaran (0 laut, 1 minyak, 2 look-alike, 3 kapal, 4 darat) diperiksa pada data
uji dataset; peta warna di `usetrainedmodel.py` kating tidak sesuai dengan urutan ini, yang di
`app.py` sesuai.

**Evaluasi model kating pada 110 gambar uji dataset** (praproses kating):

| Kelas | IoU (Adam, dipakai) | IoU (Nadam) |
|---|---|---|
| Laut | 94,8% | 95,4% |
| Tumpahan minyak | 39,6% (F1 56,7%) | 40,1% |
| Look-alike | 40,5% | 42,3% |
| Kapal | 22,1% | 14,4% |
| Darat | 91,2% | 90,6% |

Recall minyak sekitar 48%: kira-kira separuh piksel minyak terlewat. Model Nadam bisa dipakai
dengan variabel lingkungan `SAR_UNET_MODEL`; env bisa diganti dengan `SAR_UNET_ENV`.

**Dengan TTA saat prediksi** (model Adam, tanpa bobot kelas; 110 gambar uji, grid 256 × 256,
tanpa morfologi):

| Konfigurasi | Minyak | Look-alike | Kapal | Laut | Darat | mIoU | F1 minyak | Recall minyak |
|---|---|---|---|---|---|---|---|---|
| Tanpa TTA | 39,6 | 40,5 | 22,1 | 94,8 | 91,2 | 57,6 | 56,7 | 48,2 |
| **Standar** (flip) | 38,8 | 45,2 | 25,3 | 95,4 | 93,8 | 59,7 | 55,9 | 44,7 |
| Multi-skala saja | 39,2 | 44,2 | 12,5 | 95,4 | 93,5 | 57,0 | 56,3 | 45,6 |
| **Akurat** (multi-skala + flip) | 38,6 | 45,6 | 12,3 | 95,6 | 94,7 | 57,4 | 55,7 | 42,9 |

Tanpa bobot kelas, TTA tidak menaikkan IoU minyak, tetapi memperbaiki look-alike, laut, darat
(dan kapal pada mode standar). Bila probabilitas minyak diberi bobot (dipilih dari data latih),
IoU minyak naik ke 47,9% (standar, bobot 3) dan 50,9% (akurat, bobot 2,5); bobot ini tidak
dipakai karena kating maupun paper tidak memakainya. Sebagai pembanding, U-Net (ResNet-101) di
paper dataset mencapai IoU minyak 53,8%.

Waktu (CPU laptop, 10 m): kotak 20 km ~20 detik (standar) / ~25 detik (akurat), 40 km ~35 /
~70 detik, 80 km ~1,5 / ~5 menit. Pertama kali membuka sebuah area bisa lebih lama karena data
diunduh dari AWS.

### Batasan yang perlu dicatat di laporan

- **MariNeXt**: hasil hanya sebaik model dan data latihnya (MADOS). Awan tidak punya kelas di
  MADOS dan tidak dimasker, jadi area berawan bisa diberi kelas laut apa pun. Garis batas jendela
  prediksi (lihat catatan model) memengaruhi luas.
- **U-Net SAR**: IoU minyak model kating pada data uji hanya ~40% (model Keras 3 bawaan belum
  dievaluasi), dan belum divalidasi pada kejadian
  tumpahan nyata di citra AWS; hasilnya kandidat untuk diperiksa visual. Menurut paper dataset
  (Krestenitis dkk., 2019, *Remote Sensing* 11(15):1762, https://doi.org/10.3390/rs11151762),
  gambar latih dibuat dari VV terkalibrasi, median 7 × 7, transformasi linear dB → kecerahan,
  dan di-*rescale* ke 1250 × 650 pada beberapa tingkat zoom (multi-skala). **Rentang dB tidak
  disebutkan** (−35..0 dB di sini mengikuti ekspor SNAP) dan **ukuran piksel latih tidak tetap**,
  sehingga potongan 1250 × 650 piksel 10 m adalah pilihan, bukan nilai pasti. Look-alike SAR yang
  paling sering: area angin lemah, perairan terlindung di balik pulau, sel hujan, *upwelling*,
  dan lapisan biogenik.
- Masker darat DEM 90 m hanya dipakai MariNeXt; pulau sangat kecil dan gosong pasir bisa tidak
  termasker. U-Net SAR tidak memakai masker darat: kelas Darat murni dari model, sehingga bisa
  muncul darat palsu di laut atau sebaliknya.
- SAR dianalisis pada 10 m (kotak 80 km: 20 m), maks. 80×80 km. Median 7 × 7 menghapus slick
  yang lebih sempit dari ~30–40 m dan sebagian besar kapal kecil. MariNeXt
  selalu 10 m, maks. 40×40 km.
- Volume belum dihitung. Volume memerlukan asumsi ketebalan (mis. *Bonn Agreement Oil
  Appearance Code*); luas poligon di GeoJSON bisa menjadi masukannya.

## Sumber data

Katalog scene (pencarian tanggal + bbox): STAC API Earth Search,
`https://earth-search.aws.element84.com/v1`.

| Sensor | Koleksi STAC | Bucket S3 (dibaca anonim lewat HTTPS) | Yang ditampilkan |
|---|---|---|---|
| Sentinel-2 L2A | `sentinel-2-c1-l2a` | `e84-earth-search-sentinel-data`, `us-west-2` | Warna asli (TCI) 10 m |
| Sentinel-2 L1C | `sentinel-2-l1c` | `sentinel-s2-l1c`, `eu-central-1` | Input MariNeXt (lewat ACOLITE) |
| Sentinel-1 GRD | `sentinel-1-grd` | `sentinel-s1-l1c`, `eu-central-1` | Amplitudo VV/VH 10 m |

Untuk masker darat MariNeXt dipakai Copernicus DEM GLO-90 (bucket `copernicus-dem-90m`, `eu-central-1`).

Tidak perlu akun atau kredensial AWS.

## Struktur

```
backend/main.py          API: /api/search (STAC), /api/tiles (tile PNG), /api/marinext,
                         /api/sar-unet, /api/jobs/<id> (status & berkas hasil)
backend/marinext.py      klasifikasi MariNeXt: L1C AWS -> ACOLITE -> predict.py MADOS (Sentinel-2)
backend/sar_unet.py      klasifikasi U-Net SAR: σ⁰ -> dB −35..0 -> potongan -> U-Net 5 kelas (Sentinel-1)
backend/unet_runner.py   prediksi U-Net, dijalankan di env conda `unet3` (Keras 3)
backend/sar.py           pembacaan & kalibrasi σ⁰ Sentinel-1 GRD, reproyeksi ke UTM
backend/jobs.py          antrean pekerjaan latar belakang (satu sekaligus) & pemanggil conda
backend/results.py       ringkasan hasil: GeoTIFF, GeoJSON poligon, overlay PNG, luas per kelas
backend/geo.py           grid, masker darat Copernicus DEM, kotak analisis
backend/sources.py       daftar bucket S3 dan cara membuka/mengambil filenya
backend/remote_cache.py  unduhan paralel + cache potongan file COG di disk
frontend/                index.html, app.js, style.css (Leaflet)
models/                  unet_oilspill.keras (U-Net SAR, Keras 3), marinext_2.pth (MariNeXt model 2)
cache/                   potongan COG yang sudah diunduh (aman dihapus, maks. 5 GB)
cache/jobs/              folder kerja & hasil per pekerjaan klasifikasi (20 terakhir)
```

## Catatan teknis

- **Tampilan Sentinel-1 belum dikalibrasi.** Layer citra menampilkan `20·log10(DN)`, bukan σ⁰.
  Cukup untuk melihat citra; klasifikasi U-Net memakai σ⁰ terkalibrasi (`backend/sar.py`).
- **Sentinel-1 GRD masih dalam geometri sensor** dan digeoreferensikan dengan GCP; backend me-warp-nya
  ke Web Mercator saat membuat tile (tanpa koreksi medan — tidak masalah di laut).
- **Kecepatan.** Bucket berada di Frankfurt dan Oregon. Tampilan pertama sebuah area butuh beberapa detik
  karena data diunduh; setelah itu dilayani dari folder `cache/`. Jika backend dipasang di
  region AWS yang sama dengan bucket, unduhan ini menjadi nyaris instan.
- Pencarian dibatasi 300 scene terbaru per permintaan.
"# WebMap-Capstone" 
