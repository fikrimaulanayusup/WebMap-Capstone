"""Sentinel-1 GRD: sigma0 terkalibrasi untuk kotak analisis, dan pemetaan hasil ke grid UTM.

Kalibrasi: intensitas DN^2 dikurangi derau termal (LUT range x azimuth), lalu dibagi kuadrat
LUT `sigmaNought`. Semua LUT dibaca dari anotasi produk di bucket AWS yang sama.
GRD masih dalam geometri radar (georeferensi lewat GCP); hasil analisis dipetakan ke UTM.
"""

import xml.etree.ElementTree as ET
from dataclasses import dataclass

import numpy as np
import rasterio
import rasterio.crs
import rasterio.transform
import rasterio.warp
import rasterio.windows
from rasterio.control import GroundControlPoint
from rasterio.enums import Resampling

from .geo import DetectionError, Grid, utm_crs
from .sources import fetch, locate, open_raster

MAX_GRID_SIDE = 6000
MAX_GRID_PIXELS = 25_000_000


@dataclass
class SarScene:
    sigma0: np.ndarray  # linear, float32; NaN di luar data
    grid: Grid  # geometri radar pada resolusi analisis
    polarization: str


# ---------------------------------------------------------------- LUT anotasi
def _vectors(root: ET.Element, vector_tag: str, value_tag: str):
    lines, pixels, values = [], [], []
    for vec in root.iter(vector_tag):
        lines.append(float(vec.findtext("line")))
        pixels.append(np.array(vec.findtext("pixel").split(), dtype="float64"))
        values.append(np.array(vec.findtext(value_tag).split(), dtype="float64"))
    return np.array(lines), pixels, values


def _interp_vectors(lines, pixels, values, rows, cols) -> np.ndarray:
    """Interpolasi bilinear LUT Sentinel-1 (vektor per baris) ke grid rows x cols."""
    per_line = np.stack([np.interp(cols, p, v) for p, v in zip(pixels, values)])
    if len(lines) == 1:
        return np.repeat(per_line, len(rows), axis=0).astype("float32")
    i = np.clip(np.searchsorted(lines, rows, side="right") - 1, 0, len(lines) - 2)
    w = np.clip((rows - lines[i]) / (lines[i + 1] - lines[i]), 0, 1)[:, None]
    return (per_line[i] * (1 - w) + per_line[i + 1] * w).astype("float32")


def _noise(root: ET.Element, rows, cols) -> np.ndarray:
    if root.find(".//noiseRangeVector") is not None:  # IPF >= 2.9: range x azimuth
        noise = _interp_vectors(*_vectors(root, "noiseRangeVector", "noiseRangeLut"), rows, cols)
        for block in root.iter("noiseAzimuthVector"):
            r0, r1 = int(block.findtext("firstAzimuthLine")), int(block.findtext("lastAzimuthLine"))
            c0, c1 = int(block.findtext("firstRangeSample")), int(block.findtext("lastRangeSample"))
            rsel = (rows >= r0) & (rows <= r1)
            csel = (cols >= c0) & (cols <= c1)
            if not (rsel.any() and csel.any()):
                continue
            lines = np.array(block.findtext("line").split(), dtype="float64")
            lut = np.array(block.findtext("noiseAzimuthLut").split(), dtype="float64")
            az = np.interp(rows[rsel], lines, lut).astype("float32") if len(lines) > 1 else np.full(rsel.sum(), lut[0], "float32")
            noise[np.ix_(rsel, csel)] *= az[:, None]
        return noise
    return _interp_vectors(*_vectors(root, "noiseVector", "noiseLut"), rows, cols)  # IPF lama


# ---------------------------------------------------------------- Pembacaan
def read_sigma0(item: dict, bbox, target_res_m: float) -> SarScene:
    """sigma0 untuk `bbox` (lon/lat) pada resolusi terdekat >= target_res_m (overview GRD)."""
    assets = item["assets"]
    pol = next((p for p in ("vv", "hh") if p in assets), None)
    if pol is None:
        raise DetectionError("Scene ini tidak punya polarisasi VV/HH yang dibutuhkan.")
    measurement = locate(assets[pol]["href"])
    product, name = measurement[1].rsplit("/measurement/", 1)
    stem = name.rsplit(".", 1)[0]  # mis. iw-vv
    annotation = ET.fromstring(fetch((measurement[0], f"{product}/annotation/{stem}.xml")))
    calibration = ET.fromstring(fetch((measurement[0], f"{product}/annotation/calibration/calibration-{stem}.xml")))
    noise_xml = ET.fromstring(fetch((measurement[0], f"{product}/annotation/calibration/noise-{stem}.xml")))

    with open_raster(measurement) as ds:
        gcps, _ = ds.gcps
        height, width = ds.shape
        factors = [1] + list(ds.overviews(1))
    transformer = rasterio.transform.GCPTransformer(gcps)

    # Kotak analisis -> jendela piksel (resolusi penuh) di geometri radar.
    west, south, east, north = bbox
    t = np.linspace(0, 1, 21)
    xs = np.concatenate([west + (east - west) * t, np.full(21, east), east - (east - west) * t, np.full(21, west)])
    ys = np.concatenate([np.full(21, south), south + (north - south) * t, np.full(21, north), north - (north - south) * t])
    rows, cols = transformer.rowcol(xs, ys, op=lambda v: v)
    r0, r1 = max(0, int(np.floor(np.min(rows)))), min(height, int(np.ceil(np.max(rows))))
    c0, c1 = max(0, int(np.floor(np.min(cols)))), min(width, int(np.ceil(np.max(cols))))
    if r0 >= r1 or c0 >= c1:
        raise DetectionError("Kotak analisis tidak bertampalan dengan citra ini.")

    native = float(annotation.findtext(".//rangePixelSpacing") or 10.0)
    min_factor = max(1, int(round(target_res_m / native)))
    usable = [f for f in factors if f >= min_factor
              and max((r1 - r0) / f, (c1 - c0) / f) <= MAX_GRID_SIDE and (r1 - r0) * (c1 - c0) / f**2 <= MAX_GRID_PIXELS]
    if not usable:
        raise DetectionError("Kotak terlalu luas untuk dianalisis.")
    f = usable[0]
    level = factors.index(f) - 1  # -1 = resolusi penuh

    with open_raster(measurement, **({"overview_level": level} if level >= 0 else {})) as ds:
        win = rasterio.windows.Window.from_slices(
            (r0 // f, min(ds.height, -(-r1 // f))), (c0 // f, min(ds.width, -(-c1 // f)))
        )
        dn = ds.read(1, window=win).astype("float32")
    wr0, wc0 = int(win.row_off), int(win.col_off)
    h, w = dn.shape
    rows_full = (wr0 + np.arange(h) + 0.5) * f - 0.5
    cols_full = (wc0 + np.arange(w) + 0.5) * f - 0.5

    sigma_lut = _interp_vectors(*_vectors(calibration, "calibrationVector", "sigmaNought"), rows_full, cols_full)
    noise = _noise(noise_xml, rows_full, cols_full)
    sigma0 = np.maximum(dn * dn - noise, 1e-6) / (sigma_lut * sigma_lut)
    sigma0[dn <= 0] = np.nan

    def to_lonlat(r, c):  # koordinat tepi piksel grid analisis -> lon/lat
        lon, lat = transformer.xy((wr0 + np.asarray(r)) * f, (wc0 + np.asarray(c)) * f, offset="ul")
        return np.asarray(lon, dtype="float64"), np.asarray(lat, dtype="float64")

    return SarScene(sigma0.astype("float32"), Grid((h, w), native * f, to_lonlat), pol.upper())


# ---------------------------------------------------------------- Ke grid UTM
def utm_profile(bbox, res_m: float) -> dict:
    west, south, east, north = bbox
    crs = utm_crs((west + east) / 2, (south + north) / 2)
    left, bottom, right, top = rasterio.warp.transform_bounds("EPSG:4326", crs, west, south, east, north)
    width, height = int(np.ceil((right - left) / res_m)), int(np.ceil((top - bottom) / res_m))
    return {"crs": rasterio.crs.CRS.from_string(crs), "transform": rasterio.transform.from_origin(left, top, res_m, res_m),
            "width": width, "height": height}


def to_utm(array: np.ndarray, grid: Grid, profile: dict, resampling: Resampling, nodata) -> np.ndarray:
    """Petakan raster dalam geometri radar ke grid UTM `profile` memakai GCP grid analisis."""
    h, w = grid.shape
    step = max(16, max(h, w) // 30)
    rows = np.unique(np.r_[np.arange(0, h, step), h]).astype("float64")
    cols = np.unique(np.r_[np.arange(0, w, step), w]).astype("float64")
    rr, cc = np.meshgrid(rows, cols, indexing="ij")
    lon, lat = grid.to_lonlat(rr.ravel(), cc.ravel())
    gcps = [GroundControlPoint(row=r, col=c, x=x, y=y) for r, c, x, y in zip(rr.ravel(), cc.ravel(), lon, lat)]
    out = np.full((profile["height"], profile["width"]), nodata, dtype=array.dtype)
    rasterio.warp.reproject(array, out, gcps=gcps, src_crs="EPSG:4326", src_nodata=nodata,
                            dst_transform=profile["transform"], dst_crs=profile["crs"], dst_nodata=nodata,
                            resampling=resampling)
    return out
