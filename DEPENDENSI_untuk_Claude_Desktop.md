# Dependensi Perangkat Lunak Proyek Capstone: WebGIS Deteksi Tumpahan Minyak

> **Untuk Claude Desktop.** Dokumen ini berisi daftar library (dependensi) tiap environment prototipe WebGIS,
> untuk dimasukkan ke **proposal capstone bagian Standar / Spesifikasi Perangkat Lunak**.
> Pakai bersama `KONTEKS_PROPOSAL_untuk_Claude_Desktop.md`.
>
> Semua versi diambil dari environment yang **benar-benar terpasang** di laptop pengembang (`pip list` dan
> `conda list`, 12 November 2026), dan hanya paket yang **dipakai langsung oleh kode** yang dicantumkan
> (dependensi turunan seperti aws-c-*, libtiff, fonts tidak dimasukkan). **Jangan menambah paket atau
> mengubah versi** yang tidak ada di sini.

---

## 1. Ringkasan environment

| Environment | Python | Fungsi |
|---|---|---|
| Frontend (browser) | – | Antarmuka peta WebGIS |
| `.venv` | 3.12.10 | Server web: API, pencarian citra (STAC), tile peta dinamis, antrean pekerjaan |
| conda `acolite` | 3.14.10 | Koreksi atmosfer Sentinel-2 L1C → reflektansi ρ_rc |
| conda `mados` | 3.8.20 | Inferensi MariNeXt (Sentinel-2) dan masker awan |
| conda `unet3` | 3.12.16 | Inferensi U-Net SAR (Sentinel-1) |

**Alasan environment dipisah:** MariNeXt memerlukan PyTorch 1.11 dan MMCV-full 1.6.0 yang hanya berjalan
pada Python 3.8, sedangkan U-Net memakai Keras 3 pada Python 3.12. Server web menjalankan keduanya sebagai
proses terpisah melalui `conda run`. ACOLITE dipasang dari channel conda-forge sesuai `environment.yml`
bawaan ACOLITE.

---

## 2. Tabel dependensi (format proposal: Nama Paket | Versi)

Nomor tabel ditulis X; sesuaikan dengan urutan di proposal.

**Tabel X.1. Dependensi Frontend WebGIS**

| Nama Paket | Versi |
|---|---|
| HTML5, CSS3, JavaScript | – |
| Leaflet | 1.9.4 |
| OpenStreetMap (basemap) | – |

**Tabel X.2. Dependensi Server Web (`.venv`)**

| Nama Paket | Versi |
|---|---|
| Python | 3.12.10 |
| FastAPI | 0.162.0 |
| Uvicorn | 0.54.0 |
| Pydantic | 2.14.2 |
| HTTPX | 0.28.1 |
| Rasterio | 1.5.2 |
| GDAL | 3.12.2 |
| rio-tiler | 7.9.6 |
| Morecantile | 6.2.0 |
| PySTAC | 1.15.2 |
| NumPy | 2.5.4 |
| SciPy | 1.18.1 |
| Shapely | 2.2.0 |
| PyProj | 3.8.0 |

**Tabel X.3. Dependensi Koreksi Atmosfer Sentinel-2 (env `acolite`)**

| Nama Paket | Versi |
|---|---|
| Python | 3.14.10 |
| ACOLITE | GitHub (RBINS) |
| GDAL | 3.13.3 |
| NumPy | 2.5.4 |
| SciPy | 1.18.1 |
| PyProj | 3.8.0 |
| Pyresample | 1.35.0 |
| netCDF4 | 1.7.4 |
| h5py | 3.16.0 |
| pyhdf | 0.11.7 |
| pygrib | 2.1.8 |
| scikit-image | 0.26.0 |
| Matplotlib | 3.11.2 |
| Cartopy | 0.26.0 |
| Requests | 2.34.2 |
| aiohttp | 3.14.5 |
| Zarr | 3.4.2 |
| fsspec | 2026.9.0 |

**Tabel X.4. Dependensi MariNeXt dan Masker Awan Sentinel-2 (env `mados`)**

| Nama Paket | Versi |
|---|---|
| Python | 3.8.20 |
| PyTorch (CPU) | 1.11.0 |
| Torchvision | 0.12.0 |
| MMCV-full | 1.6.0 |
| segmentation-models-pytorch | 0.3.3 |
| timm | 0.9.2 |
| Rasterio | 1.3.10 |
| GDAL | 3.9.2 |
| NumPy | 1.24.4 |
| SciPy | 1.10.1 |
| cv2 (OpenCV) | 4.10.0.84 |
| TQDM | 4.67.1 |

**Tabel X.5. Dependensi U-Net SAR Sentinel-1 (env `unet3`)**

| Nama Paket | Versi |
|---|---|
| Python | 3.12.16 |
| TensorFlow (CPU) | 2.21.0 |
| Keras | 3.15.1 |
| NumPy | 2.5.4 |
| cv2 (OpenCV) | 5.0.0.93 |
| h5py | 3.14.0 |

---

## 3. Fungsi tiap paket (bahan paragraf penjelasan)

### Frontend
- **Leaflet**: peta interaktif, layer tile citra, overlay hasil klasifikasi, menggambar kotak area analisis.
- **OpenStreetMap**: basemap; pencarian lokasi memakai OpenStreetMap Nominatim (dipanggil lewat backend).

### Server web (`.venv`)
- **FastAPI**: REST API (`/api/search`, `/api/tiles`, `/api/marinext`, `/api/sar-unet`, `/api/jobs`).
- **Uvicorn**: server ASGI yang menjalankan FastAPI.
- **Pydantic**: validasi data request/response API.
- **HTTPX**: klien HTTP ke STAC API Earth Search, bucket S3 AWS Open Data, dan Nominatim.
- **Rasterio / GDAL**: membaca dan menulis raster (COG, GeoTIFF), reproyeksi, *warp* citra.
- **rio-tiler**: membuat tile peta XYZ dinamis dari Cloud-Optimized GeoTIFF.
- **Morecantile**: sistem grid tile (TileMatrixSet Web Mercator).
- **PySTAC**: model data katalog STAC (dependensi rio-tiler).
- **NumPy**: operasi array dan raster.
- **SciPy**: filter median, morfologi, dan pelabelan petak (`ndimage`).
- **Shapely**: geometri poligon tumpahan, kotak analisis, dan perhitungan luas.
- **PyProj**: transformasi sistem koordinat (EPSG:3857 ↔ UTM).

### Koreksi atmosfer (`acolite`)
- **ACOLITE** (RBINS): koreksi atmosfer citra perairan, menghasilkan reflektansi ρ_rc.
- **GDAL** (driver JP2OpenJPEG, NetCDF): membaca band Sentinel-2 L1C (JPEG2000), menulis GeoTIFF.
- **NumPy, SciPy**: komputasi array, interpolasi.
- **PyProj, Pyresample**: proyeksi koordinat dan resampling data geospasial.
- **netCDF4, h5py, pyhdf, pygrib**: membaca dan menulis NetCDF, HDF5 (LUT), HDF4, GRIB (data meteorologi).
- **scikit-image**: pengolahan citra.
- **Matplotlib, Cartopy**: visualisasi dan pemetaan (*quicklook*).
- **Requests, aiohttp, Zarr, fsspec**: mengunduh LUT dan mengakses data pendukung berbasis cloud.

### MariNeXt dan masker awan (`mados`)
- **PyTorch (CPU), Torchvision**: framework *deep learning* untuk inferensi MariNeXt dan detektor awan.
- **MMCV-full**: fondasi arsitektur MMSegmentation (MariNeXt dibangun di atas `mmseg`).
- **segmentation-models-pytorch, timm**: U-Net MobileNetV2 untuk deteksi awan (CloudSEN12).
- **Rasterio / GDAL**: membaca band ρ_rc dan L2A, menulis hasil prediksi.
- **NumPy, SciPy**: komputasi array dan ilmiah.
- **OpenCV**: pengolahan citra.
- **TQDM**: indikator progres prediksi.

### U-Net SAR (`unet3`)
- **TensorFlow (CPU)**: backend *deep learning* untuk inferensi.
- **Keras**: memuat model `unet_oilspill.keras` dan menjalankan prediksi.
- **NumPy**: komputasi array.
- **OpenCV**: mengubah ukuran potongan citra ke 256 × 256 dan sebaliknya.
- **h5py**: membaca format model Keras/HDF5.

---

## 4. Lingkungan training (di luar laptop)

| Komponen | Versi | Keterangan |
|---|---|---|
| Kaggle Notebook (GPU) | – | Training U-Net SAR |
| Keras | 3.13.2 | Versi saat training (tercatat di README prototipe) |

Versi library lain di notebook training (mis. TensorFlow, Matplotlib, scikit-learn) **belum dicatat**.
Jangan mengisi versinya dengan perkiraan; biarkan kosong atau tulis "mengikuti lingkungan Kaggle".

---

## 5. Perangkat lunak pihak ketiga dan lisensinya

| Perangkat lunak | Lisensi | Keterangan |
|---|---|---|
| ACOLITE (RBINS) | GPL-3.0 | Disalin tanpa diubah ke `vendor/acolite` (tanpa LUT) |
| MADOS / MariNeXt (Kikaki dkk., 2024) | MIT | Kode `predict.py`, `mmseg`, `utils` disalin tanpa diubah ke `vendor/mados` |
| Smoothly-Blend-Image-Patches (Vooban) | MIT | Konsep penggabungan jendela prediksi spline |

---

## 6. Catatan tentang tabel dependensi kating (jangan ditiru)

Tabel dependensi U-Net kating ("Tabel 9. Dependensi U-Net, dimodifikasi dari Sherif (2025)") lebih panjang
karena memasukkan library training, evaluasi, dan visualisasi notebook (pandas, seaborn, sklearn, pydot,
IPython). Tabel itu **tidak konsisten** dan sebaiknya tidak dijadikan acuan:
- Ada entri dobel: Matplotlib (3.7.1 dan 3.7), sklearn/Scikit-learn (1.3.0 dan 1.3).
- Torchvision tercantum padahal U-Net kating memakai TensorFlow.
- Versinya tidak sesuai dengan model kating sebenarnya: SavedModel kating dibuat dengan **Keras 2.10**
  (env lama: Python 3.10, `tensorflow-cpu` 2.10.1, `numpy` 1.23.5, `opencv-python-headless` 4.7),
  bukan TensorFlow 2.2.0 / Keras 2.4.3.
- Beberapa kombinasi versi kemungkinan tidak bisa dipasang bersama (mis. pandas 2.2.2 dan skimage 0.22.0
  dengan Python 3.8; TensorFlow 2.2.0 dengan NumPy 1.24.4). Klaim ini **belum diverifikasi** ke PyPI;
  jangan dikutip di proposal tanpa dicek.

Tabel proyek ini sengaja lebih pendek: hanya paket yang terbukti terpasang dan dipakai kode.

---

## 7. Hal yang JANGAN ditulis di proposal

- Jangan tulis versi Python env `acolite` sebagai "3" saja; versi terpasang 3.14.10.
- Jangan tambahkan pandas, seaborn, scikit-learn, pydot, IPython ke tabel inferensi; paket itu tidak dipakai
  kode WebGIS.
- Jangan sebut GeoServer, WMS/WFS, atau OpenDrift/OpenOil sebagai dependensi terpasang; itu rencana
  pengembangan.
- Jangan sebut GPU untuk inferensi; semua inferensi berjalan di CPU laptop (training di GPU Kaggle).
