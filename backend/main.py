"""Backend prototipe Web-Map tumpahan minyak.

Tugas:
  1. /api/search   -> mencari scene Sentinel-1 GRD atau Sentinel-2 L2A di katalog STAC
                      Earth Search (AWS) berdasarkan rentang tanggal + bbox.
  2. /api/tiles    -> membaca COG langsung dari bucket S3 publik (akses anonim) dan
                      menyajikannya sebagai tile PNG untuk peta.
  3. /api/marinext -> klasifikasi optik 15 kelas MADOS dengan MariNeXt (Sentinel-2, marinext.py).
  4. /api/sar-unet -> klasifikasi SAR 5 kelas dengan U-Net kating (Sentinel-1, sar_unet.py).
  Keduanya berjalan di latar belakang (jobs.py); status & berkas hasil lewat /api/jobs/<id>.
"""

import importlib.util
import math
import os
import pathlib
import re
import threading
import time
from datetime import date

# Wheel rasterio membawa data PROJ/GDAL sendiri. Jika mesin punya PROJ_LIB dari instalasi
# lain (mis. PostGIS), rasterio gagal membaca proj.db, jadi arahkan ke data bawaannya
# sebelum rasterio di-import.
_rasterio_dir = pathlib.Path(importlib.util.find_spec("rasterio").origin).parent
if (_rasterio_dir / "proj_data").is_dir():
    os.environ["PROJ_LIB"] = os.environ["PROJ_DATA"] = str(_rasterio_dir / "proj_data")
if (_rasterio_dir / "gdal_data").is_dir():
    os.environ["GDAL_DATA"] = str(_rasterio_dir / "gdal_data")

import httpx  # noqa: E402
import morecantile  # noqa: E402
import numpy as np  # noqa: E402
import rasterio  # noqa: E402
import rasterio.warp  # noqa: E402
from fastapi import FastAPI, HTTPException, Query, Response  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from rio_tiler.errors import TileOutsideBounds  # noqa: E402
from rio_tiler.io import Reader  # noqa: E402
from rio_tiler.models import ImageData  # noqa: E402

from . import jobs, marinext, sar_unet  # noqa: E402
from .geo import DetectionError  # noqa: E402
from .remote_cache import prune_cache  # noqa: E402
from .sources import Location, locate, open_raster  # noqa: E402

STAC_API = "https://earth-search.aws.element84.com/v1"
MAX_SCENES = 300
PAGE_SIZE = 100

# Koleksi STAC tiap sensor dan aset (file COG) yang boleh diminta sebagai tile.
SENSORS = {
    "sentinel-1": {"collection": "sentinel-1-grd", "assets": ("vv", "vh", "hh", "hv")},
    # "visual" = komposit warna asli 10 m (TCI); "preview" = versi 320 m untuk zoom jauh.
    "sentinel-2": {"collection": "sentinel-2-c1-l2a", "assets": ("visual", "preview")},
}

GDAL_ENV = {"GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR"}
WEB_MERCATOR = morecantile.tms.get("WebMercatorQuad")
SCENE_ID_RE = re.compile(r"^S[12][A-Z]_[A-Za-z0-9_]{10,100}$")

app = FastAPI(title="Web-Map Tumpahan Minyak - Sentinel AWS")
stac = httpx.Client(base_url=STAC_API, timeout=30)

# (sensor, scene_id) -> {"vv": (bucket, key), ...}; diisi saat pencarian supaya permintaan
# tile tidak perlu bertanya ke STAC lagi.
_scene_assets: dict[tuple[str, str], dict[str, Location]] = {}
# lokasi -> (ukuran piksel asli dalam meter, faktor overview yang tersedia di file)
_pyramids: dict[Location, tuple[float, list[int]]] = {}

prune_cache()


def _data_assets(sensor: str, item: dict) -> dict[str, Location]:
    assets = item.get("assets", {})
    located = {}
    for name in SENSORS[sensor]["assets"]:
        location = locate(assets.get(name, {}).get("href", ""))
        if location:
            located[name] = location
    return located


def _slim_feature(sensor: str, item: dict) -> dict:
    """Ambil hanya atribut yang dipakai frontend dari sebuah STAC item."""
    props = item.get("properties", {})
    assets = _data_assets(sensor, item)
    _scene_assets[(sensor, item["id"])] = assets

    slim = {
        "datetime": props.get("datetime"),
        "platform": props.get("platform"),
        "assets": list(assets),
    }
    if sensor == "sentinel-1":
        slim["mode"] = props.get("sar:instrument_mode")
        slim["orbit_state"] = props.get("sat:orbit_state")
        slim["relative_orbit"] = props.get("sat:relative_orbit")
    else:
        slim["cloud_cover"] = props.get("eo:cloud_cover")
        slim["tile"] = (props.get("grid:code") or "").removeprefix("MGRS-")
        thumbnail = item.get("assets", {}).get("thumbnail", {}).get("href", "")
        slim["thumbnail"] = thumbnail if thumbnail.startswith("https://") else None

    return {
        "type": "Feature",
        "id": item["id"],
        "geometry": item["geometry"],
        "bbox": item.get("bbox"),
        "properties": slim,
    }


@app.get("/api/search")
def search(
    start: date = Query(..., description="Tanggal awal (YYYY-MM-DD, UTC)"),
    end: date = Query(..., description="Tanggal akhir (YYYY-MM-DD, UTC)"),
    bbox: str = Query(..., description="west,south,east,north (derajat)"),
    sensor: str = Query("sentinel-2", pattern="^sentinel-[12]$"),
    orbit: str | None = Query(None, pattern="^(ascending|descending)$", description="Hanya Sentinel-1"),
    cloud: float | None = Query(None, ge=0, le=100, description="Tutupan awan maks. (%), hanya Sentinel-2"),
):
    if start > end:
        raise HTTPException(400, "Tanggal awal harus sebelum atau sama dengan tanggal akhir.")
    try:
        west, south, east, north = (float(v) for v in bbox.split(","))
    except ValueError:
        raise HTTPException(400, "bbox harus berisi 4 angka: west,south,east,north.")
    west, east = max(west, -180.0), min(east, 180.0)
    south, north = max(south, -90.0), min(north, 90.0)
    if not (west < east and south < north):  # juga menolak NaN
        raise HTTPException(400, "bbox tidak valid.")

    body = {
        "collections": [SENSORS[sensor]["collection"]],
        "bbox": [west, south, east, north],
        "datetime": f"{start}T00:00:00Z/{end}T23:59:59Z",
        "limit": PAGE_SIZE,
        "sortby": [{"field": "properties.datetime", "direction": "desc"}],
    }
    if sensor == "sentinel-1" and orbit:
        body["query"] = {"sat:orbit_state": {"eq": orbit}}
    if sensor == "sentinel-2" and cloud is not None:
        body["query"] = {"eo:cloud_cover": {"lte": cloud}}

    features: list[dict] = []
    matched = None
    while body and len(features) < MAX_SCENES:
        try:
            resp = stac.post("/search", json=body)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise HTTPException(502, f"Gagal menghubungi katalog STAC Earth Search: {exc}")
        page = resp.json()
        if matched is None:
            matched = page.get("numberMatched")
        features.extend(_slim_feature(sensor, item) for item in page.get("features", []))
        # Halaman berikutnya: Earth Search mengirim body POST siap pakai di link rel=next.
        body = next((l.get("body") for l in page.get("links", []) if l.get("rel") == "next"), None)

    features = features[:MAX_SCENES]
    return {
        "type": "FeatureCollection",
        "features": features,
        "matched": matched if matched is not None else len(features),
        "returned": len(features),
    }


# ---------------------------------------------------------------- Pencarian lokasi
# Nominatim (OpenStreetMap): wajib User-Agent yang jelas dan maks. 1 permintaan per detik.
nominatim = httpx.Client(base_url="https://nominatim.openstreetmap.org", timeout=15,
                         headers={"User-Agent": "WebMapTumpahanMinyak/0.1 (prototipe capstone)"})
_geocode_cache: dict[str, list] = {}
_geocode_lock = threading.Lock()
_geocode_last = [0.0]


@app.get("/api/geocode")
def geocode(q: str = Query(..., min_length=2, max_length=200, description="nama tempat")):
    key = q.strip().lower()
    if key in _geocode_cache:
        return {"results": _geocode_cache[key]}
    with _geocode_lock:
        wait = 1.0 - (time.monotonic() - _geocode_last[0])
        if wait > 0:
            time.sleep(wait)
        try:
            resp = nominatim.get("/search", params={"q": q, "format": "jsonv2", "limit": 6, "accept-language": "id,en"})
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise HTTPException(502, f"Gagal menghubungi layanan pencarian lokasi (Nominatim): {exc}")
        finally:
            _geocode_last[0] = time.monotonic()
    results = []
    for r in resp.json():
        s, n, w, e = (float(v) for v in r["boundingbox"])
        results.append({"name": r["display_name"], "type": r.get("type", ""), "lat": float(r["lat"]),
                        "lon": float(r["lon"]), "bbox": [w, s, e, n]})
    if len(_geocode_cache) > 500:
        _geocode_cache.clear()
    _geocode_cache[key] = results
    return {"results": results}


def _stac_item(sensor: str, scene_id: str) -> dict:
    if not SCENE_ID_RE.match(scene_id):
        raise HTTPException(400, "ID scene tidak valid.")
    try:
        resp = stac.get(f"/collections/{SENSORS[sensor]['collection']}/items/{scene_id}")
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Gagal menghubungi katalog STAC Earth Search: {exc}")
    if resp.status_code != 200:
        raise HTTPException(404, "Scene tidak ditemukan.")
    return resp.json()


def _scene_locations(sensor: str, scene_id: str) -> dict[str, Location]:
    if not SCENE_ID_RE.match(scene_id):
        raise HTTPException(400, "ID scene tidak valid.")
    assets = _scene_assets.get((sensor, scene_id))
    if assets is None:
        # Server baru di-restart atau tile diminta tanpa pencarian lebih dulu.
        assets = _scene_assets[(sensor, scene_id)] = _data_assets(sensor, _stac_item(sensor, scene_id))
    return assets


def _pyramid(location: Location) -> tuple[float, list[int]]:
    """Resolusi asli (meter/piksel) dan faktor overview sebuah COG; hanya membaca header."""
    info = _pyramids.get(location)
    if info is None:
        with open_raster(location) as ds:
            gcps, gcp_crs = ds.gcps
            if gcps:
                # Sentinel-1 GRD: jarak di permukaan bumi antara dua GCP terjauh dibagi
                # jaraknya dalam piksel.
                a, b = gcps[0], gcps[-1]
                xs, ys = rasterio.warp.transform(gcp_crs, "EPSG:3857", [a.x, b.x], [a.y, b.y])
                scale = math.cos(math.radians((a.y + b.y) / 2))  # distorsi skala Web Mercator
                metres = math.hypot(xs[1] - xs[0], ys[1] - ys[0]) * scale
                native = metres / math.hypot(b.col - a.col, b.row - a.row)
            else:
                native = abs(ds.res[0])  # Sentinel-2: proyeksi UTM, satuannya sudah meter
            info = _pyramids[location] = (native, ds.overviews(1))
    return info


def _tile_resolution(x: int, y: int, z: int) -> float:
    """Ukuran piksel tile Web Mercator di permukaan bumi (meter)."""
    bounds = WEB_MERCATOR.bounds(x, y, z)
    lat = (bounds.bottom + bounds.top) / 2
    return 156543.034 * math.cos(math.radians(lat)) / 2**z


def _sharp_enough(source_res: float, tile_res: float) -> bool:
    return source_res <= tile_res * 1.2


def _read_tile(location: Location, x: int, y: int, z: int) -> ImageData:
    """Baca satu tile 256 px dari COG, memakai overview paling kasar yang masih cukup tajam.

    Resolusi tile Web Mercator (mis. 76 m di z11) sedikit lebih halus daripada overview
    COG yang setara (80 m), sehingga GDAL sendiri akan mengambil overview satu tingkat
    lebih detail -- 4x lebih banyak data yang diunduh untuk hasil yang nyaris sama.
    """
    native, factors = _pyramid(location)
    tile_res = _tile_resolution(x, y, z)
    usable = [i for i, f in enumerate(factors) if _sharp_enough(native * f, tile_res)]
    options = {"overview_level": usable[-1]} if usable else {}
    with open_raster(location, **options) as ds:
        # Sentinel-1 GRD masih dalam geometri sensor (georeferensi lewat GCP) dan Sentinel-2
        # dalam UTM; rio-tiler me-warp keduanya ke Web Mercator.
        with Reader(None, dataset=ds, options={"nodata": 0}) as src:
            return src.tile(x, y, z, tilesize=256, resampling_method="bilinear", reproject_method="bilinear")


_EMPTY_TILE = ImageData(
    np.ma.MaskedArray(np.zeros((1, 256, 256), dtype="uint8"), mask=True)
).render(img_format="PNG")
_TILE_HEADERS = {"Cache-Control": "public, max-age=86400"}


@app.get("/api/tiles/{sensor}/{scene_id}/{asset}/{z}/{x}/{y}.png")
def tile(
    sensor: str,
    scene_id: str,
    asset: str,
    z: int,
    x: int,
    y: int,
    vmin: float = Query(30.0, ge=0, le=100),
    vmax: float = Query(50.0, ge=0, le=100),
):
    """Tile PNG sebuah scene.

    Sentinel-1: skala abu-abu dari amplitudo GRD dalam desibel, 20*log10(DN), direntang
    antara vmin dan vmax. Belum dikalibrasi ke sigma0, cukup untuk visualisasi: permukaan
    laut berminyak tampak lebih gelap dari sekitarnya.
    Sentinel-2: komposit warna asli (TCI) apa adanya.
    """
    if sensor not in SENSORS:
        raise HTTPException(404, "Sensor tidak dikenal.")
    if asset not in SENSORS[sensor]["assets"]:
        raise HTTPException(400, "Aset tidak dikenal untuk sensor ini.")
    if vmax <= vmin:
        raise HTTPException(400, "vmax harus lebih besar dari vmin.")
    if not 0 <= z <= 18 or not (0 <= x < 2**z and 0 <= y < 2**z):
        raise HTTPException(400, "Koordinat tile tidak valid.")
    locations = _scene_locations(sensor, scene_id)
    if asset not in locations:
        raise HTTPException(404, f"Scene ini tidak punya aset {asset.upper()}.")
    location = locations[asset]

    try:
        with rasterio.Env(**GDAL_ENV):
            # Pada zoom jauh, pratinjau 320 m Sentinel-2 sudah cukup tajam dan jauh lebih
            # kecil daripada overview terkasar TCI (160 m).
            preview = locations.get("preview")
            if asset == "visual" and preview and _sharp_enough(_pyramid(preview)[0], _tile_resolution(x, y, z)):
                location = preview
            img = _read_tile(location, x, y, z)
    except TileOutsideBounds:
        return Response(_EMPTY_TILE, media_type="image/png", headers=_TILE_HEADERS)
    except (rasterio.errors.RasterioIOError, httpx.HTTPError) as exc:
        raise HTTPException(502, f"Gagal membaca citra dari S3: {exc}")

    if sensor == "sentinel-1":
        dn = img.array[0]
        db = 20.0 * np.log10(np.maximum(dn.filled(1).astype("float32"), 1.0))
        gray = (np.clip((db - vmin) / (vmax - vmin), 0.0, 1.0) * 255).astype("uint8")
        img = ImageData(np.ma.MaskedArray(gray[np.newaxis], mask=np.ma.getmaskarray(dn)[np.newaxis]))
    return Response(img.render(img_format="PNG"), media_type="image/png", headers=_TILE_HEADERS)


def _check_bbox(bbox):
    west, south, east, north = bbox
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise HTTPException(400, "bbox tidak valid.")


class JobRequest(BaseModel):
    scene_id: str
    bbox: tuple[float, float, float, float] = Field(description="kotak analisis: west, south, east, north")
    max_km: int = Field(20, description="sisi maksimum kotak (km); pilihan bergantung model")
    mode: str = Field("standar", description="hanya U-Net SAR: 'akurat' (multi-skala + flip) atau 'standar' (flip)")


def _start(start_job, sensor: str, req: JobRequest):
    _check_bbox(req.bbox)
    item = _stac_item(sensor, req.scene_id)
    try:
        job_id = start_job(item, req.bbox, req.max_km)
    except DetectionError as exc:
        raise HTTPException(422, str(exc))
    return {"job_id": job_id, **jobs.status(job_id)}


@app.post("/api/marinext")
def marinext_start(req: JobRequest):
    """Klasifikasi MariNeXt (15 kelas MADOS) untuk scene Sentinel-2; hasil lewat /api/jobs.

    Scene dipilih dari katalog L2A (tampilan warna asli 10 m); model memakai produk L1C dari
    akuisisi yang sama (dicari di marinext._find_l1c).
    """
    return _start(marinext.start_job, "sentinel-2", req)


@app.post("/api/sar-unet")
def sar_unet_start(req: JobRequest):
    """Klasifikasi U-Net kating (5 kelas) untuk scene Sentinel-1; hasil lewat /api/jobs."""
    return _start(lambda item, bbox, km: sar_unet.start_job(item, bbox, km, req.mode), "sentinel-1", req)


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    status = jobs.status(job_id)
    if status is None:
        raise HTTPException(404, "Pekerjaan tidak ditemukan (server mungkin sudah di-restart).")
    return status


@app.get("/api/jobs/{job_id}/files/{name}")
def job_file(job_id: str, name: str):
    path = jobs.result_file(job_id, name)
    if path is None:
        raise HTTPException(404, "File hasil tidak ditemukan.")
    return FileResponse(path, media_type=jobs.RESULT_FILES[name], filename=f"hasil_{job_id}_{name}")


class _FrontendFiles(StaticFiles):
    """File frontend dengan `Cache-Control: no-cache`.

    Tanpa header ini browser menebak sendiri berapa lama CSS/JS boleh disimpan, sehingga
    setelah file diubah halaman bisa tampil dengan HTML baru tetapi gaya/skrip lama.
    Dengan no-cache browser selalu bertanya dulu ke server (dijawab 304 bila tidak berubah).
    """

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


# Frontend statis; dipasang terakhir supaya tidak menutupi rute /api.
_frontend = pathlib.Path(__file__).resolve().parent.parent / "frontend"
app.mount("/", _FrontendFiles(directory=_frontend, html=True), name="frontend")
