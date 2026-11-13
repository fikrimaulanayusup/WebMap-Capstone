# Konteks Proyek Capstone: WebGIS Deteksi Tumpahan Minyak

> **Untuk Claude Desktop.** Dokumen ini adalah ringkasan pekerjaan yang sudah dilakukan bersama Claude Code
> di repositori prototipe (Oktober–November 2026). Gunakan sebagai konteks saat membantu menyusun
> **proposal capstone**. Proposal berisi *rencana dan metodologi*, jadi bedakan dengan jelas antara
> **yang sudah dibangun di prototipe** dan **yang masih rencana**. Semua angka di bawah berasal dari uji
> yang benar-benar dijalankan; jangan menambah angka atau klaim yang tidak ada di sini.

---

## 1. Gambaran singkat

WebGIS (prototipe) untuk mencari citra satelit gratis berdasarkan rentang tanggal dan area peta,
menampilkannya sebagai layer peta, lalu **mengklasifikasikan tumpahan minyak (*oil slick*)**:

- **Sentinel-1 (SAR)** → model deep learning **U-Net**, 5 kelas: laut, tumpahan minyak, *look-alike*, kapal, darat.
- **Sentinel-2 (optik)** → model deep learning **MariNeXt** (dataset MADOS), 15 kelas + kelas awan.

Keluaran klasifikasi: peta kelas (overlay), tabel luas per kelas, poligon tiap petak minyak (luas,
probabilitas rata-rata/maksimum), dan unduhan `classes.tif`, `oil_spill_prob.tif`, `oil_spill.geojson`.

Lokasi uji/validasi yang relevan untuk Indonesia: **Karawang, sumur YYA-1 Pertamina (12 Sep 2019,
tile T48MYU)**; kandidat lain: **Teluk Balikpapan (Maret–April 2018)**; area uji lain: Teluk Jakarta, Batam.

### Masalah yang diangkat
- SAR: minyak tampak gelap karena meredam gelombang, tetapi banyak fenomena lain juga gelap
  (*look-alike*): area angin lemah, perairan terlindung di balik pulau, sel hujan, *upwelling*, lapisan biogenik.
- Optik: awan dan *sunglint* bisa terbaca sebagai minyak; citra bersunglint berada di luar sebaran data latih.
- Luas saja belum cukup untuk penanggulangan; dibutuhkan ketebalan/volume, kondisi metocean, kandidat
  sumber (kapal/AIS), dan prediksi penyebaran → komponen rencana.

---

## 2. Status komponen

| Komponen | Status |
|---|---|
| Pencarian & tampilan Sentinel-1 / Sentinel-2 | ✅ Sudah di prototipe |
| Deteksi SAR (U-Net, model dari notebook dosen) | ✅ Sudah di prototipe |
| Deteksi optik (MariNeXt + ACOLITE) | ✅ Sudah di prototipe |
| Masker awan Sentinel-2 (skrip dari dosen pembimbing) | ✅ Sudah di prototipe |
| Tampilan Landsat 8 (Planetary Computer) | ✅ Sudah (hanya tampilan, bukan analisis) |
| Pencarian lokasi (OpenStreetMap Nominatim) | ✅ Sudah |
| Estimasi ketebalan dari termal Landsat | 📝 Rencana |
| Estimasi volume (*Bonn Agreement*) | 📝 Rencana (prototipe belum menghitung volume) |
| Data metocean (angin, arus, gelombang) | 📝 Rencana |
| Data AIS (kandidat kapal sumber) | 📝 Rencana |
| Simulasi penyebaran OpenOil (OpenDrift) | 📝 Rencana |
| Publikasi layanan OGC WMS/WFS (GeoServer) | 📝 Rencana pengembangan — prototipe memakai tile XYZ, **bukan** WMS |

---

## 3. Data dan sumber (semua yang sudah dipakai gratis, tanpa akun)

| Data | Sumber | Fungsi |
|---|---|---|
| Sentinel-1 GRD IW, polarisasi VV | AWS Open Data, bucket `sentinel-s1-l1c` (Frankfurt), dicari lewat STAC Earth Search | input U-Net |
| Sentinel-2 L1C | AWS `sentinel-s2-l1c` (Frankfurt) | input MariNeXt setelah ACOLITE |
| Sentinel-2 L2A | AWS, koleksi `sentinel-2-c1-l2a` (Oregon) | tampilan warna asli + input masker awan |
| Copernicus DEM GLO-90 | AWS `copernicus-dem-90m` | masker darat (MariNeXt) |
| Landsat 8 Collection 2 L2 | Microsoft Planetary Computer (gratis, token anonim otomatis) | tampilan; rencana analisis termal |
| Dataset latih SAR | Krestenitis dkk. (2019): 1.112 gambar 1250×650 (1.002 latih, 110 uji), 5 kelas, dari kejadian EMSA CleanSeaNet | training U-Net |
| Dataset/model optik | MADOS & MariNeXt (Kikaki dkk., 2024), bobot model 2 | model optik (bobot jadi, tidak dilatih ulang) |

Fakta penting sumber data:
- **Sentinel-1 GRD IW:** ukuran piksel 10 m, tetapi **resolusi spasial ±20 × 22 m**. Jangan tulis "resolusi 10 m".
- **Landsat di AWS (`usgs-landsat`) berbayar** (*requester pays*, perlu akun AWS + kartu kredit). Di Planetary Computer gratis.
- **Landsat 8 Level-1 tidak tersedia gratis tanpa login** (Planetary Computer hanya punya L2; USGS perlu akun EROS).
  Alternatif: produk L2 sudah memuat `ST_TRAD` (radiansi band 10 di sensor, setara L1) sehingga koreksi
  atmosfer bisa dilakukan sendiri; `ST_ATRAN`, `ST_URAD`, `ST_DRAD` dari USGS bisa dipakai sebagai pembanding validasi.
- Sumber alternatif Sentinel: Copernicus Data Space Ecosystem.

---

## 4. Metodologi

### 4a. SAR: Sentinel-1 → U-Net (sudah di prototipe)

Pra-pemrosesan:
1. **Kalibrasi radiometrik ke σ⁰** dengan LUT `sigmaNought`, setelah **derau termal** (LUT range × azimuth) dikurangkan:
   σ⁰ = max(DN² − N, 10⁻⁶) / A²σ.
2. **Konversi ke dB** (10·log₁₀ σ⁰), resolusi 10 m (kotak 80 km dibaca dari overview 20 m).
3. **Filter median 7 × 7** untuk meredam speckle (sesuai pembuatan dataset Krestenitis).
4. **Normalisasi rentang tetap −35..0 dB → 0–255:** `(clip(dB, −35, 0) + 35) / 35 × 255`.
   Piksel tanpa data diisi nilai laut tipikal (median), bukan 0.
5. **Pemotongan** per ~12,5 × 6,5 km (1250 × 650 piksel) dengan tumpang tindih 50%; potongan dengan data < 20% dilewati.
6. Tiap potongan di-resize ke 256 × 256, disalin ke 3 kanal, dibagi 255 (sama dengan cara training model).
7. Prediksi U-Net; probabilitas diperbesar kembali dan digabung dengan **bobot kosinus** agar batas potongan tidak tampak.
   Opsi *test-time augmentation* (TTA): *cepat* (tanpa TTA), *standar* (4 varian flip), *akurat* (flip + multi-skala).
8. Kelas = argmax probabilitas; kelas minyak dan look-alike dibersihkan dengan morfologi (buka 1×, tutup 2×, kernel 3×3).
9. Hasil dipetakan ke UTM 10 m; poligon minyak diekspor ke GeoJSON beserta luas.

Temuan tentang normalisasi (bahan pembahasan/keterbatasan):
- Paper dataset hanya menyebut "transformasi linear dB → kecerahan" **tanpa menyebut rentang dB**. Rentang −35..0 dB adalah pilihan
  (mengikuti ekspor SNAP), bukan nilai yang terbukti sama dengan data latih.
- Analisis histogram 1.112 gambar dataset: dataset **tidak** dinormalisasi min–max/persentil per gambar; polanya cocok dengan
  **rentang tetap + clip**. Rentang dataset diperkirakan **sekitar −32..−9 dB**, sehingga input WebGIS lebih gelap dan
  kontrasnya lebih rendah. Tekstur laut dataset juga jauh lebih kasar (std lokal 34 vs 5 tingkat abu-abu). Belum diuji
  pada kejadian tumpahan nyata, jadi rentang belum diubah.
- Min–max per kotak terbukti buruk: 5,1% darat palsu di Teluk Meksiko dan pulau-pulau Batam hampir hilang.
- Laut sangat tenang bisa jatuh di bawah −35 dB sehingga hitam seperti minyak (contoh Laut Tyrrhenia, median −40 dB).

### 4b. Model U-Net SAR (notebook training dari dosen)

Model yang dipakai mengikuti **notebook training dari dosen** (`oil-spill-detection.ipynb`, dijalankan di Kaggle):

| Aspek | Nilai |
|---|---|
| Arsitektur | U-Net polos, filter 16–256, dropout 0,1/0,1/0,2/0,2/0,3/0,2/0,2/0,1/0,1, ±1,94 juta parameter |
| Input | seluruh gambar 1250×650 di-resize ke 256 × 256, 3 kanal, ÷255 |
| Loss / optimizer | categorical cross-entropy, Adam (LR 0,001 tetap) |
| Epoch / batch | 100 / 16, `validation_split = 0,1` |
| Augmentasi | tidak ada |
| Model yang dipakai | bobot epoch terakhir (100) |
| Framework | TensorFlow/Keras (model di WebGIS dimuat dengan Keras 3), training dengan GPU Kaggle |

Model kakak tingkat (kating) dilatih dengan resep yang sama (terbukti dari konfigurasi SavedModel: arsitektur, loss,
optimizer identik, dan 5.700 langkah = 57 langkah/epoch × 100 epoch).

Catatan kritis notebook (berguna untuk bagian keterbatasan/pengembangan, sudah dibuktikan):
- Mask label di-resize **bilinear** lalu warnanya dicocokkan persis → piksel tepi objek jatuh ke kelas laut.
  Pada data uji, 6,4% piksel label minyak dan 24% label kapal hilang.
- Metrik di notebook (precision/recall/F1 ≈ 0,95) memakai rata-rata **berbobot**, didominasi kelas laut (~90% piksel),
  sehingga tidak menggambarkan kemampuan deteksi minyak. Gunakan **IoU per kelas** sebagai metrik utama.
- Pengecilan ke 256 × 256 membuat kapal selebar 10–20 piksel tinggal 2–4 piksel → IoU kapal rendah.

### 4c. Optik: Sentinel-2 → MariNeXt (sudah di prototipe)

1. **Area analisis:** kotak yang digambar pengguna (maks. 10, 20, atau 40 km per sisi).
2. **Data L1C:** citra dipilih dari katalog L2A, lalu produk L1C akuisisi yang sama dicari; hanya 13 band area kotak yang diunduh.
3. **Koreksi atmosfer ACOLITE** (`s2_target_res=10`, `output_rhorc=True`) → reflektansi ρ_rc 11 band, sama seperti data latih MADOS.
4. **Prediksi MariNeXt** (`predict.py` MADOS, model 2) dengan penggabungan jendela spline orde 2 dan langkah 60 piksel
   untuk menghilangkan artefak garis kisi tiap 1,2 km.
5. **Masker awan:** 13 band L2A akuisisi yang sama → U-Net MobileNetV2 CloudSEN12 (skrip `cloud_detector.py` dari dosen
   pembimbing) → awan tebal, awan tipis, dan bayangan awan diperlebar 3 piksel (30 m) menjadi kelas ke-16
   **Awan / bayangan awan**, sehingga tidak terhitung sebagai minyak. Offset reflektansi L2A baseline ≥ 04.00 (−1000) dibuang dulu.
6. **Masker darat** dari Copernicus DEM (model hanya dilatih di permukaan laut).

**Validasi Karawang, 12 Sep 2019 (tumpahan YYA-1)**, WebGIS vs pemrosesan manual ACOLITE + `predict.py` pada area sama:

| | WebGIS (AWS, baseline N0208) | Manual (SAFE N0500) |
|---|---|---|
| Luas Oil Spill | 3,788 km² | 3,839 km² |
| Kesesuaian kelas semua piksel | 92,3% | |
| IoU Oil Spill | 88,7% (96,9% dengan toleransi 1 piksel) | |

(Perbandingan ini memakai model 1; dengan model 2 luas Oil Spill WebGIS 4,07 km².)

### 4d. Rencana: estimasi ketebalan dari termal Landsat 8/9
- Data: Landsat 8/9 band 10 (10,6–11,19 µm); asli 100 m, didistribusikan 30 m. Band 11 Landsat 8 terdampak *stray light*.
- Konsep: suhu dihitung ulang dari `ST_TRAD` dengan koreksi atmosfer sendiri dan **emisivitas minyak (~0,96–0,97)** vs air (~0,99):
  - L_permukaan = (TRAD − URAD − τ·(1−ε)·DRAD) / (τ·ε)
  - T = K2 / ln(K1 / L_permukaan + 1), dengan K1 = 774,8853 dan K2 = 1321,0789 (band 10)
  - ΔT = T_minyak − T_air → **kelas ketebalan relatif** (tebal / tipis / tidak terdeteksi), bukan angka milimeter.
- Parameter atmosfer (τ, L↑, L↓): NASA Atmospheric Correction Parameter Calculator, atau profil ERA5 + model transfer radiatif.
- Keterbatasan: hubungan ΔT–ketebalan tidak searah (siang hari minyak tebal lebih hangat, minyak tipis lebih dingin, ada
  rentang menengah yang tak terlihat); resolusi termal 100 m; Landsat jarang memotret laut lepas; waktu lintas ±10.00
  waktu lokal berbeda dengan Sentinel-1 (±06.00/18.00). Koreksi atmosfer bawaan L2 di laut terlihat bermasalah
  (scene 122/063 Laut Jawa: aerosol hasil interpolasi, band merah mendekati nol) — argumen untuk koreksi sendiri.
- Rujukan konsep: Fingas & Brown (penginderaan jauh tumpahan minyak).

### 4e. Rencana: volume, metocean, AIS, OpenOil
- **Volume:** ketebalan per poligon menurut *Bonn Agreement Oil Appearance Code* (kode 1 *sheen* 0,04–0,30 µm; 2 *rainbow*
  0,30–5,0 µm; 3 *metallic* 5–50 µm; 4 *discontinuous true colour* 50–200 µm; 5 *continuous true colour* > 200 µm).
  Volume = Σ luas × ketebalan, dilaporkan sebagai **rentang** karena SAR saja tidak mengukur ketebalan.
- **Metocean:** angin 10 m, arus permukaan, tinggi gelombang, *Stokes drift* (NetCDF) dari Copernicus Marine Service dan
  ERA5 (alternatif NOAA GFS). Dua fungsi: (1) kontrol kualitas deteksi — SAR paling andal pada angin ±3–10 m/s; di bawah
  ±3 m/s muncul *look-alike*, di atas ±10 m/s minyak teraduk; (2) *forcing* untuk OpenOil.
- **AIS:** MMSI, posisi, waktu, SOG, COG; kapal dalam ±1–3 jam dan radius penyangga dari poligon ditandai kandidat sumber.
  **Perhatian:** Global Fishing Watch *Vessel Presence* berupa **grid kepadatan kapal**, bukan titik per kapal; atribut
  per kapal (MMSI, SOG, COG) butuh penyedia data AIS titik lain.
- **OpenOil (OpenDrift):** masukan arus, angin, gelombang, jenis minyak (NOAA ADIOS), lokasi awal dari poligon deteksi,
  volume awal; keluaran lintasan partikel dan neraca massa (permukaan, menguap, terdispersi, terdampar).

---

## 5. Evaluasi model U-Net SAR (model kating, resep notebook dosen)

Dievaluasi ulang dengan skrip `evaluate_unet.py` pada **110 gambar uji** dataset Krestenitis, protokol sama dengan paper:
gambar ukuran asli, label asli tanpa resize, tanpa augmentasi, tanpa morfologi. IoU dalam %:

| Kelas | Paper U-Net (ResNet-101) | Paper DeepLabv3+ | **Model kating** |
|---|---|---|---|
| Laut | 93,90 | 96,43 | 94,86 |
| Tumpahan minyak | 53,79 | 53,38 | **41,69** |
| Look-alike | 39,55 | 55,40 | 40,72 |
| Kapal | 44,93 | 27,63 | 23,58 |
| Darat | 92,68 | 92,44 | 92,11 |
| **mIoU** | 64,97 | 65,06 | **58,59** |

- Tumpahan minyak: **precision 71,4%, recall 50,1%** → bila model menandai minyak umumnya benar, tetapi sekitar separuh
  piksel minyak terlewat, sehingga luas tumpahan cenderung **lebih kecil** dari kenyataan.
- Dengan TTA flip: mIoU 60,61% (minyak 40,95%, kapal 26,32%).
- Dengan protokol lama (label diperkecil ke 256 × 256) angkanya: laut 94,8 / minyak 39,6 / look-alike 40,5 / kapal 22,1 /
  darat 91,2 / mIoU 57,6 — angka inilah yang tercantum di README prototipe. Untuk proposal, gunakan tabel protokol paper di atas.
- Selisih terhadap paper terbesar di **minyak (−12 poin)** dan **kapal (−21 poin)**. Penyebab yang paling mungkin:
  pengecilan gambar ke 256 × 256, kapasitas model ~26× lebih kecil (1,94 vs 51,5 juta parameter), tanpa augmentasi,
  epoch lebih sedikit. Pertukaran akurasi minyak vs look-alike juga dilaporkan paper (hlm. 12).
- Hasil training bervariasi antar-run: resep yang sama yang dilatih ulang menghasilkan mIoU 53,35%. Untuk rencana
  evaluasi yang kuat, latih beberapa kali (mis. 3 seed) dan laporkan rata-rata ± simpangan baku.

**Metrik evaluasi yang direncanakan:** IoU per kelas, mIoU, precision, recall, F1 per kelas (bukan F1 berbobot);
pembanding Krestenitis dkk. (2019) Tabel 4. Belum ada validasi pada kejadian tumpahan nyata di citra AWS → hasil SAR
diperlakukan sebagai kandidat yang diperiksa visual.

---

## 6. Arsitektur sistem dan teknologi

- **Frontend:** Leaflet (HTML/JavaScript), basemap OpenStreetMap.
- **Backend:** Python FastAPI + Uvicorn: pencarian citra (STAC), tile peta XYZ dinamis dari Cloud-Optimized GeoTIFF
  (rio-tiler), antrean pekerjaan klasifikasi di latar belakang (satu pekerjaan sekaligus), cache potongan file (maks. 5 GB).
- **Pengolahan geospasial:** GDAL, rasterio, shapely, numpy, scipy. Proyeksi tampilan EPSG:3857, analisis dalam UTM.
- **Lingkungan Python:**
  - `.venv` (Python 3.12) — server web.
  - `acolite` (conda-forge) — koreksi atmosfer Sentinel-2.
  - `mados` (Python 3.8, PyTorch 1.11 CPU, mmcv-full 1.6.0, GDAL) — MariNeXt dan masker awan.
  - `unet3` (Python 3.12, TensorFlow 2.21, Keras 3.15) — U-Net SAR.
- **Perangkat keras:** semua inferensi berjalan di CPU laptop; training di GPU Kaggle.
- **Waktu proses (CPU laptop):** MariNeXt ~5 / 15 / 45 menit untuk kotak 10 / 20 / 40 km; U-Net ~20 detik (20 km),
  ~35 detik (40 km), ~1,5 menit (80 km), belum termasuk unduhan pertama.

---

## 7. Batasan dan risiko

- U-Net SAR: IoU minyak ~42%, recall ~50%; belum divalidasi pada kejadian tumpahan nyata.
- Rentang dB data latih tidak diketahui pasti; tekstur input WebGIS berbeda dari dataset (*domain gap*).
- Tidak ada normalisasi sudut datang (*incidence angle*) dan tidak ada koreksi terrain sebelum model.
- Median 7 × 7 menghapus slick yang lebih sempit dari ~30–40 m dan sebagian besar kapal kecil.
- U-Net tidak memakai masker darat DEM; kelas darat murni dari model (bisa muncul darat palsu).
- MariNeXt: maks. 40 × 40 km, 10 m; citra bersunglint tidak andal; masker awan juga menghapus minyak di bawah kabut tipis;
  masker darat DEM 90 m bisa melewatkan pulau sangat kecil.
- Volume belum dihitung (butuh asumsi ketebalan).
- **Jaringan:** unduhan dari bucket AWS Frankfurt/Oregon lambat dari ISP pengguna (±60–240 KB/detik, padahal internet
  lokal ±3,7 MB/detik). Penyebabnya jalur internasional ISP, bukan AWS. Jika backend dipasang di region AWS yang sama
  dengan bucket, unduhan menjadi nyaris instan. Untuk demo: jalankan klasifikasi lebih dulu agar data sudah di cache.

---

## 8. Tabel spesifikasi teknis (versi singkat yang sudah disusun untuk proposal)

| Komponen | Spesifikasi teknis | Sumber/perangkat |
|---|---|---|
| Citra SAR | Sentinel-1 C-band, mode IW, GRD, piksel 10 m (resolusi ±20 × 22 m), polarisasi VV. Pra-pemrosesan: koreksi derau termal, kalibrasi σ⁰, konversi dB, filter median. | AWS Open Data (STAC Earth Search); Copernicus Data Space Ecosystem |
| Citra optik | Sentinel-2 MSI, band 10 m (visible, NIR) dan 20 m (*red-edge*, SWIR). Koreksi atmosfer ACOLITE. Untuk konfirmasi visual, delineasi, dan pembeda *look-alike*. | AWS Open Data (STAC Earth Search); ACOLITE |
| Citra termal | Landsat 8/9 TIRS band 10 (100 m, didistribusikan 30 m). Selisih suhu minyak terhadap air laut sebagai indikator ketebalan relatif. | Microsoft Planetary Computer; USGS EarthExplorer |
| Deteksi tumpahan (*deep learning*) | U-Net pada Sentinel-1, 5 kelas (minyak, *look-alike*, kapal, darat, laut); MariNeXt pada Sentinel-2. Evaluasi: IoU per kelas, mIoU, precision, recall, F1. Keluaran peta kelas dan poligon tumpahan. | Dataset Krestenitis dkk. (2019); MariNeXt/MADOS (Kikaki dkk., 2024); TensorFlow/Keras, PyTorch |
| Estimasi ketebalan dan volume | Ketebalan relatif menurut *Bonn Agreement Oil Appearance Code*; volume = luas poligon × ketebalan, dilaporkan sebagai rentang. | *Bonn Agreement*; poligon hasil deteksi |
| Data metocean | Angin, arus permukaan, tinggi gelombang (NetCDF) pada waktu terdekat dengan akuisisi; juga untuk menyaring *look-alike* (deteksi andal pada angin ±3–10 m/s). | Copernicus Marine Service, ERA5, NOAA |
| Data AIS | MMSI, posisi, waktu, SOG, COG, identitas kapal; kapal di sekitar tumpahan dalam ±1–3 jam dari akuisisi ditandai kandidat sumber. | Global Fishing Watch (kepadatan kapal); penyedia data AIS titik |
| OpenOil | Masukan arus, angin, gelombang, jenis minyak, lokasi awal dari poligon deteksi, waktu simulasi. Keluaran lintasan, distribusi partikel, fraksi menguap/terdispersi/terdampar. | OpenDrift, modul OpenOil |
| Dashboard WebGIS | Menampilkan citra, peta deteksi, luas, estimasi ketebalan dan volume, AIS, metocean, hasil simulasi. Unduhan GeoTIFF dan GeoJSON. | Leaflet, FastAPI (Python) |

---

## 9. Hal yang JANGAN ditulis di proposal

- Jangan tulis resolusi Sentinel-1 "10 m" tanpa keterangan (10 m adalah ukuran piksel).
- Jangan klaim prototipe memakai "standar OGC WMS".
- Jangan klaim GFW *Vessel Presence* menyediakan MMSI/SOG/COG per kapal.
- Jangan pakai F1 berbobot (≈ 0,95) sebagai ukuran kemampuan deteksi minyak.
- Jangan klaim rentang −35..0 dB "sama dengan data latih" (tidak terbukti).
- Jangan sebut ketebalan/volume, metocean, AIS, OpenOil sebagai fitur yang sudah jadi.
- Jangan campur dengan hasil `hasil_unet (4).zip` (dataset MARIDA, *marine debris*) — itu proyek lain, bukan oil spill.

---

## 10. Referensi yang muncul (cek ulang detail bibliografinya)

- Krestenitis, M. dkk. (2019). Oil Spill Identification from Satellite Images Using Deep Neural Networks. *Remote Sensing*, 11(15), 1762. https://doi.org/10.3390/rs11151762
- Kikaki, K. dkk. (2024). MADOS / MariNeXt (Marine Debris and Oil Spill dataset & model).
- Dagestad, K.-F. dkk. (2018). OpenDrift.
- Röhrs, J. dkk. (2018). OpenOil.
- *Bonn Agreement Aerial Operations Handbook* (Oil Appearance Code).
- Fingas, M. & Brown, C. — tinjauan penginderaan jauh tumpahan minyak.
- ACOLITE (RBINS) — koreksi atmosfer perairan.
- CloudSEN12 / SEnSeIv2 — model deteksi awan Sentinel-2.
- Smoothly-Blend-Image-Patches (Vooban, MIT) — penggabungan jendela prediksi.
