"""Klasifikasi optik Sentinel-2 dengan MariNeXt (MADOS), otomatis dari WebGIS.

Alur satu pekerjaan (job), dijalankan di thread latar belakang:

1. Cari produk Sentinel-2 L1C di AWS yang sama dengan scene L2A yang dipilih.
2. Bangun folder SAFE "tiruan" berisi metadata asli dari AWS dan 13 band L1C yang hanya
   memuat area analisis (band berupa VRT bernama .jp2 yang menunjuk potongan GeoTIFF lokal),
   sehingga tidak perlu mengunduh satu tile utuh.
3. Jalankan ACOLITE Python (env conda `acolite`) dengan setelan yang sama seperti
   pemrosesan data latih MADOS: L2R, s2_target_res=10, output_rhorc=True.
4. Jalankan MariNeXt (env conda `mados`, model 2, sama dengan WebGIS kating) pada 11 band
   rhorc lewat `marinext_runner.py`: `predict.py` MADOS diimpor apa adanya, hanya penggabungan
   jendelanya diganti: langkah 60, bobot spline + padding cermin, agar tidak muncul pola kisi.
5. Ubah `classes.tif` menjadi overlay peta, statistik luas per kelas, dan poligon Oil Spill.

Validasi (Karawang, 12 Sep 2019, T48MYU): rhorc identik rata-ratanya dengan ACOLITE
pengguna (bias 0,0000), luas Oil Spill 3,79 vs 3,84 km^2, IoU Oil Spill 88,7%. Selisihnya
berasal dari geolokasi produk AWS (baseline N0208) vs produk reprocessing (N0500).
"""

import json
import math
import os
import re
import shutil
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import numpy as np
import rasterio
import rasterio.warp
from rasterio.windows import Window

from . import jobs
from .geo import DetectionError, analysis_box, land_mask, lonlat_grid, raster_grid
from .results import summarise

# ---------------------------------------------------------------- Lokasi (bisa diubah lewat env var)
ACOLITE_DIR = Path(os.environ.get("MARINEXT_ACOLITE_DIR", r"C:\Akademik\Capstone\Acolite\acolite-main"))
MADOS_DIR = Path(os.environ.get("MARINEXT_MADOS_DIR", r"C:\Akademik\Capstone\Deep Learning\mados-master"))
ACOLITE_ENV = os.environ.get("MARINEXT_ACOLITE_ENV", "acolite")
MADOS_ENV = os.environ.get("MARINEXT_MADOS_ENV", "mados")
# Model 2 dari 5 hasil training MADOS, sama dengan pilihan WebGIS kating. Pada uji Karawang
# 12-09-2019 hasilnya lebih dekat ke rata-rata kelima model (IoU Oil Spill 89%) daripada model 1 (84%).
MODEL_PATH = MADOS_DIR / "marinext" / "trained_models" / "2"
# Prediksi lewat runner sendiri (repo MADOS tetap tidak diubah): penggabungan jendela berbobot
# spline. Uji 12-09-2019 T48MXU: rasio garis kisi 7,95 -> 1,09; validasi Karawang hampir sama
# (Oil Spill 4,09 -> 3,95 km2, kesesuaian kelas 91%).
RUNNER = Path(__file__).resolve().parent / "marinext_runner.py"
# Langkah 60 (bukan 120 bawaan predict.py): tiap piksel dirata-rata dari 16 jendela dengan posisi
# berbeda sehingga bias posisi model di dalam jendela (pola bercak/garis tiap 1,2 km) terhapus.
# Uji 15-10-2026 T48MYU: pola berulang 32,9 (langkah 120) -> 12,1; 12-09-2019 T48MXU: 2,1 -> 0,6.
# Tanpa TTA: rotasi/cermin tidak mengubah posisi di dalam jendela, jadi tidak membantu.
STRIDE = 60

STAC_API = "https://earth-search.aws.element84.com/v1"
L1C_BASE = "https://sentinel-s2-l1c.s3.eu-central-1.amazonaws.com/"
L1C_BANDS = ["B01", "B02", "B03", "B04", "B05", "B06", "B07", "B08", "B8A", "B09", "B10", "B11", "B12"]
# Sisi maksimum kotak analisis yang boleh dipilih pengguna (piksel 10 m):
# Dengan langkah 60 (CPU laptop): 10 km ~5 menit, 20 km ~15 menit, 40 km ~45 menit dan ~2 GB RAM.
AOI_SIZES_KM = (10, 20, 40)
CROP_MARGIN_M = 1200
OIL_SPILL = 6
STAGES = [
    "Mencari produk Sentinel-2 L1C di AWS",
    "Mengunduh 13 band L1C untuk area analisis",
    "ACOLITE: menghitung reflektansi rhorc",
    "MariNeXt: segmentasi 15 kelas MADOS",
    "Menyusun hasil",
]
GDAL_JP2 = dict(
    GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
    CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".jp2",
    GDAL_HTTP_MULTIRANGE="YES",
    GDAL_HTTP_MERGE_CONSECUTIVE_RANGES="YES",
)

# Urutan kelas MADOS (utils/assets.py) dan warnanya (CLASS_COLORS di marinext/predict.py).
CLASSES = [
    ("Marine Debris", "Sampah laut", "#ff0000"),
    ("Dense Sargassum", "Sargassum rapat", "#008000"),
    ("Sparse Floating Algae", "Alga apung jarang", "#32cd32"),
    ("Natural Organic Material", "Material organik alami", "#a52a2a"),
    ("Ship", "Kapal", "#ffa500"),
    ("Oil Spill", "Tumpahan minyak", "#d8bfd8"),
    ("Marine Water", "Air laut", "#000080"),
    ("Sediment-Laden Water", "Air bersedimen", "#ffd700"),
    ("Foam", "Buih", "#800080"),
    ("Turbid Water", "Air keruh", "#bdb76b"),
    ("Shallow Water", "Perairan dangkal", "#00ced1"),
    ("Waves & Wakes", "Ombak & jejak kapal", "#ffe4c4"),
    ("Oil Platform", "Anjungan minyak", "#696969"),
    ("Jellyfish", "Ubur-ubur", "#ff69b4"),
    ("Sea snot", "Sea snot", "#ffff00"),
]

http = httpx.Client(timeout=120)


# ---------------------------------------------------------------- Job
def start_job(item_l2a: dict, bbox, max_km: int = 20) -> str:
    """Mulai klasifikasi untuk scene L2A `item_l2a` pada kotak `bbox` (lon/lat) pilihan pengguna."""
    if max_km not in AOI_SIZES_KM:
        raise DetectionError(f"Ukuran kotak harus salah satu dari {AOI_SIZES_KM} km.")
    aoi = analysis_box(bbox, item_l2a["bbox"], max_km)
    return jobs.start("marinext", STAGES, aoi, lambda job: _run(job, item_l2a, aoi))


def _run(job: jobs.Job, item_l2a: dict, aoi) -> dict:
    work = job.dir
    job.stage(0)
    tile_prefix, product = _find_l1c(item_l2a)
    job.stage(1)
    safe = _build_safe(tile_prefix, aoi, work / "l1c")
    job.stage(2)
    acolite_out = _run_acolite(safe, aoi, work)
    job.stage(3)
    pred = _run_predict(acolite_out, work)
    job.stage(4)
    result = _summarise(pred, job)
    result.update(model="MariNeXt (model 2)", scene_id=item_l2a["id"], product=product,
                  aoi=[round(v, 5) for v in aoi])
    # Simpan hanya rhorc (input model) dan hasil; potongan L1C dan produk ACOLITE lain besar.
    shutil.rmtree(work / "l1c", ignore_errors=True)
    shutil.rmtree(work / "predict", ignore_errors=True)
    for path in acolite_out.iterdir():
        if "_rhorc_" not in path.name:
            path.unlink(missing_ok=True)
    return result


# ---------------------------------------------------------------- 1. Produk L1C
def _find_l1c(item_l2a: dict) -> tuple[str, str]:
    """Prefix tile L1C di bucket AWS dan nama produknya.

    Panel deteksi memilih item L1C langsung (koleksi sentinel-2-l1c); item L2A masih diterima
    dan dicarikan produk L1C dari akuisisi yang sama.
    """
    href = item_l2a.get("assets", {}).get("tileinfo_metadata", {}).get("href", "")
    if item_l2a.get("collection") == "sentinel-2-l1c" and href.startswith("s3://sentinel-s2-l1c/"):
        prefix = href[len("s3://sentinel-s2-l1c/"):].rsplit("/", 1)[0]
        info = json.loads(http.get(L1C_BASE + prefix + "/productInfo.json").content)
        return prefix, info["name"]
    tile = re.search(r"_T?(\d{2}[A-Z]{3})_", item_l2a["id"]).group(1)
    when = item_l2a["properties"]["datetime"][:10]
    resp = http.post(f"{STAC_API}/search", json={
        "collections": ["sentinel-2-l1c"],
        "bbox": item_l2a["bbox"],
        "datetime": f"{when}T00:00:00Z/{when}T23:59:59Z",
        "limit": 50,
    })
    resp.raise_for_status()
    for item in resp.json().get("features", []):
        href = item["assets"].get("tileinfo_metadata", {}).get("href", "")
        if f"_{tile}_" in item["id"] and href.startswith("s3://sentinel-s2-l1c/"):
            prefix = href[len("s3://sentinel-s2-l1c/"):].rsplit("/", 1)[0]
            info = json.loads(http.get(L1C_BASE + prefix + "/productInfo.json").content)
            return prefix, info["name"]
    raise DetectionError(f"Produk L1C untuk tile {tile} tanggal {when} tidak ditemukan di AWS.")


# ---------------------------------------------------------------- 2. SAFE tiruan
def _get(path: str) -> bytes:
    resp = http.get(L1C_BASE + path)
    resp.raise_for_status()
    return resp.content


def _vrt_full_tile(width, height, wkt, transform, crop_name, window) -> str:
    """VRT seukuran tile penuh yang hanya berisi potongan `crop_name` pada posisinya."""
    srs = wkt.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    t = transform
    return f"""<VRTDataset rasterXSize="{width}" rasterYSize="{height}">
  <SRS>{srs}</SRS>
  <GeoTransform>{t.c!r}, {t.a!r}, 0, {t.f!r}, 0, {t.e!r}</GeoTransform>
  <VRTRasterBand dataType="UInt16" band="1">
    <NoDataValue>0</NoDataValue>
    <SimpleSource>
      <SourceFilename relativeToVRT="1">_crops/{crop_name}</SourceFilename>
      <SourceBand>1</SourceBand>
      <SrcRect xOff="0" yOff="0" xSize="{window.width}" ySize="{window.height}"/>
      <DstRect xOff="{window.col_off}" yOff="{window.row_off}" xSize="{window.width}" ySize="{window.height}"/>
    </SimpleSource>
  </VRTRasterBand>
</VRTDataset>
"""


def _build_safe(tile_prefix: str, aoi, out_dir: Path) -> Path:
    """Folder SAFE yang bisa dibaca ACOLITE, dengan band L1C hanya untuk `aoi`.

    ACOLITE membaca band lewat GDAL, yang mengenali VRT dari isinya walau berekstensi .jp2.
    """
    info = json.loads(_get(f"{tile_prefix}/productInfo.json"))
    product = info["name"]
    mtd_tl = _get(f"{tile_prefix}/metadata.xml")
    root = ET.fromstring(mtd_tl)
    tile_id = root.findtext(".//TILE_ID")
    orbit = re.search(r"_(A\d{6})_", tile_id).group(1)
    tile = re.search(r"_(T\d{2}[A-Z]{3})_", tile_id).group(1)
    sensing = re.sub(r"[-:]", "", root.findtext(".//SENSING_TIME"))[:15]
    datatake = product.split("_")[2]

    safe = out_dir / f"{product}.SAFE"
    granule = safe / "GRANULE" / f"L1C_{tile}_{orbit}_{sensing}"
    (granule / "IMG_DATA" / "_crops").mkdir(parents=True, exist_ok=True)
    (granule / "QI_DATA").mkdir(parents=True, exist_ok=True)
    (safe / "MTD_MSIL1C.xml").write_bytes(_get(f"{info['path']}/metadata.xml"))
    (granule / "MTD_TL.xml").write_bytes(mtd_tl)

    # Footprint detektor: dipakai ACOLITE untuk sudut pandang per piksel (geometry_type=grids_footprint).
    listing = http.get(L1C_BASE, params={"list-type": "2", "prefix": f"{tile_prefix}/qi/"}).text
    for key in re.findall(r"<Key>([^<]+)</Key>", listing):
        match = re.match(r"(?:MSK_)?DETFOO_(B\w\w)\.(gml|jp2)$", key.rsplit("/", 1)[-1])
        if not match:
            continue
        band, ext = match.groups()
        target = granule / "QI_DATA" / f"MSK_DETFOO_{band}.{ext}"
        if ext == "gml":
            target.write_bytes(_get(key))
        else:  # disimpan sebagai GeoTIFF; env ACOLITE tidak wajib punya driver JP2
            with rasterio.Env(**GDAL_JP2), rasterio.open("/vsicurl/" + L1C_BASE + key) as src:
                data, profile = src.read(), src.profile
            profile.update(driver="GTiff", compress="deflate")
            with rasterio.open(target, "w", **profile) as dst:
                dst.write(data)

    west, south, east, north = aoi

    def crop(band):
        with rasterio.Env(**GDAL_JP2), rasterio.open(f"/vsicurl/{L1C_BASE}{tile_prefix}/{band}.jp2") as src:
            left, bottom, right, top = rasterio.warp.transform_bounds("EPSG:4326", src.crs, west, south, east, north)
            res = src.res[0]
            # Batas dibulatkan ke kelipatan 60 m agar semua resolusi (10/20/60 m) sejajar.
            col0 = max(0, math.floor((left - CROP_MARGIN_M - src.bounds.left) / 60) * 60 // int(res))
            row0 = max(0, math.floor((src.bounds.top - top - CROP_MARGIN_M) / 60) * 60 // int(res))
            col1 = min(src.width, math.ceil((right + CROP_MARGIN_M - src.bounds.left) / 60) * 60 // int(res))
            row1 = min(src.height, math.ceil((src.bounds.top - bottom + CROP_MARGIN_M) / 60) * 60 // int(res))
            window = Window(col0, row0, col1 - col0, row1 - row0)
            data = src.read(1, window=window)
            profile = dict(driver="GTiff", width=window.width, height=window.height, count=1, dtype=data.dtype,
                           crs=src.crs, transform=src.window_transform(window), nodata=0, compress="deflate")
            vrt = _vrt_full_tile(src.width, src.height, src.crs.to_wkt(), src.transform, f"{band}.tif", window)
        with rasterio.open(granule / "IMG_DATA" / "_crops" / f"{band}.tif", "w", **profile) as dst:
            dst.write(data, 1)
        (granule / "IMG_DATA" / f"{tile}_{datatake}_{band}.jp2").write_text(vrt, encoding="utf-8")

    with ThreadPoolExecutor(7) as pool:
        list(pool.map(crop, L1C_BANDS))
    return safe


# ---------------------------------------------------------------- 3-4. ACOLITE & MariNeXt
def _run_acolite(safe: Path, aoi, work: Path) -> Path:
    out = work / "acolite"
    out.mkdir(parents=True, exist_ok=True)
    west, south, east, north = aoi
    settings = work / "acolite_settings.txt"
    # Sama dengan pemrosesan data latih MADOS; peta RGB/L2W dimatikan karena tidak dipakai.
    settings.write_text("\n".join([
        f"inputfile={safe}",
        f"output={out}",
        f"limit={south:.6f},{west:.6f},{north:.6f},{east:.6f}",
        "s2_target_res=10",
        "output_rhorc=True",
        "l2r_export_geotiff=True",
        "rgb_rhot=False",
        "rgb_rhos=False",
        "map_l2w=False",
    ]) + "\n", encoding="utf-8")
    jobs.conda_run(ACOLITE_ENV, ["launch_acolite.py", "--cli", "--nogfx", f"--settings={settings}"],
               ACOLITE_DIR, work / "acolite.log", timeout=30 * 60)
    if len(list(out.glob("*_L2R_rhorc_*.tif"))) < 11:
        raise RuntimeError("ACOLITE tidak menghasilkan 11 band rhorc; lihat acolite.log di " + str(work))
    return out


def _run_predict(acolite_out: Path, work: Path) -> Path:
    """predict.py MADOS lewat marinext_runner.py: jendela 240 dengan langkah 60, digabung dengan
    bobot spline + padding cermin (tanpa pola kisi/bercak di batas jendela), tanpa TTA."""
    pred = work / "predict"
    jobs.conda_run(MADOS_ENV, [str(RUNNER), "--mados_dir", str(MADOS_DIR), "--input", str(acolite_out),
                               "--model_path", str(MODEL_PATH), "--output", str(pred),
                               "--stride", str(STRIDE), "--tta", "False"],
                   MADOS_DIR / "marinext", work / "predict.log", timeout=180 * 60)
    return pred


# ---------------------------------------------------------------- 5. Hasil
def _summarise(pred: Path, job: jobs.Job) -> dict:
    with rasterio.open(pred / "classes.tif") as ds:
        classes = ds.read(1)
        profile = {"crs": ds.crs, "transform": ds.transform, "width": ds.width, "height": ds.height}
    with rasterio.open(pred / "oil_spill_prob.tif") as ds:
        prob = ds.read(1)
    # MariNeXt hanya dilatih di permukaan laut; daratan (Copernicus DEM) tidak ditampilkan.
    lon, lat = lonlat_grid(raster_grid(classes.shape, profile["transform"], profile["crs"]))
    land = land_mask(lon, lat)
    classes[land] = 0
    prob[land] = np.nan
    return summarise(classes, prob, profile, job.dir / "result", job.id, CLASSES, OIL_SPILL)
