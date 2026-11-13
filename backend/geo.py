"""Utilitas geospasial bersama: grid analisis, masker darat (Copernicus DEM), kotak analisis."""

import math
from dataclasses import dataclass
from typing import Callable

import numpy as np
import rasterio
import rasterio.transform
import rasterio.warp
from scipy import ndimage

from .sources import exists, open_raster


class DetectionError(ValueError):
    """Kesalahan yang pesannya layak ditampilkan ke pengguna."""


@dataclass
class Grid:
    """Grid analisis dan cara mengubah koordinat piksel (tepi piksel, float) ke lon/lat."""

    shape: tuple[int, int]
    res_m: float
    to_lonlat: Callable[[np.ndarray, np.ndarray], tuple[np.ndarray, np.ndarray]]


def lonlat_grid(grid: Grid, step: int = 16) -> tuple[np.ndarray, np.ndarray]:
    """lon/lat di pusat setiap piksel; dihitung tiap `step` piksel lalu diinterpolasi."""
    h, w = grid.shape
    rows = np.arange(0, h + step, step, dtype="float64")
    cols = np.arange(0, w + step, step, dtype="float64")
    rr, cc = np.meshgrid(rows + 0.5, cols + 0.5, indexing="ij")
    lon, lat = grid.to_lonlat(rr.ravel(), cc.ravel())
    lon = np.asarray(lon).reshape(rr.shape)
    lat = np.asarray(lat).reshape(rr.shape)
    ri, ci = np.meshgrid(np.arange(h) / step, np.arange(w) / step, indexing="ij")
    coords = [ri.ravel(), ci.ravel()]
    lon_full = ndimage.map_coordinates(lon, coords, order=1).reshape(h, w)
    lat_full = ndimage.map_coordinates(lat, coords, order=1).reshape(h, w)
    return lon_full, lat_full


def raster_grid(shape, transform, crs) -> Grid:
    """Grid untuk raster biasa (bukan geometri radar)."""

    def to_lonlat(r, c):
        x, y = rasterio.transform.xy(transform, np.asarray(r), np.asarray(c), offset="ul")
        lon, lat = rasterio.warp.transform(crs, "EPSG:4326", np.ravel(x), np.ravel(y))
        return np.asarray(lon), np.asarray(lat)

    return Grid(tuple(shape), abs(transform.a), to_lonlat)


# ---------------------------------------------------------------- Masker darat (DEM)
_dem_cache: dict[tuple[int, int], tuple[np.ndarray, rasterio.Affine] | None] = {}


def _dem_tile(lat0: int, lon0: int):
    key = (lat0, lon0)
    if key not in _dem_cache:
        ns = f"N{lat0:02d}" if lat0 >= 0 else f"S{-lat0:02d}"
        ew = f"E{lon0:03d}" if lon0 >= 0 else f"W{-lon0:03d}"
        name = f"Copernicus_DSM_COG_30_{ns}_00_{ew}_00_DEM"
        location = ("copernicus-dem-90m", f"{name}/{name}.tif")
        if not exists(location):
            _dem_cache[key] = None  # tile laut lepas tidak diterbitkan
        else:
            with open_raster(location) as ds:
                _dem_cache[key] = (ds.read(1), ds.transform)
    return _dem_cache[key]


def land_mask(lon: np.ndarray, lat: np.ndarray) -> np.ndarray:
    """True untuk darat menurut Copernicus DEM GLO-90 (laut bernilai tepat 0)."""
    land = np.zeros(lon.shape, dtype=bool)
    lat_idx, lon_idx = np.floor(lat).astype(int), np.floor(lon).astype(int)
    for lat0 in np.unique(lat_idx):
        for lon0 in np.unique(lon_idx[lat_idx == lat0]):
            tile = _dem_tile(int(lat0), int(lon0))
            if tile is None:
                continue
            dem, transform = tile
            sel = (lat_idx == lat0) & (lon_idx == lon0)
            cols, rows = ~transform * (lon[sel], lat[sel])
            rows = np.clip(rows.astype(int), 0, dem.shape[0] - 1)
            cols = np.clip(cols.astype(int), 0, dem.shape[1] - 1)
            land[sel] = dem[rows, cols] != 0
    return land


# ---------------------------------------------------------------- Kotak analisis
def analysis_box(box, scene_bbox, max_km: float):
    """Kotak pengguna dipotong dengan jejak scene; bila sisinya lebih dari max_km, ambil bagian tengahnya.

    Frontend sudah membatasi ukuran kotak; pemotongan di sini hanya pengaman.
    """
    west, south = max(box[0], scene_bbox[0]), max(box[1], scene_bbox[1])
    east, north = min(box[2], scene_bbox[2]), min(box[3], scene_bbox[3])
    if west >= east or south >= north:
        raise DetectionError("Kotak analisis tidak bertampalan dengan citra ini. Gambar kotak di atas citra tersebut.")
    lat = (south + north) / 2
    half_lon = max_km / 2 / (111.32 * math.cos(math.radians(lat)))
    half_lat = max_km / 2 / 110.57
    cx, cy = (west + east) / 2, (south + north) / 2
    return (max(west, cx - half_lon), max(south, cy - half_lat), min(east, cx + half_lon), min(north, cy + half_lat))


def utm_crs(lon: float, lat: float) -> str:
    zone = int((lon + 180) // 6) + 1
    return f"EPSG:{32600 + zone if lat >= 0 else 32700 + zone}"
