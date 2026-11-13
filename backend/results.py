"""Penyusunan hasil segmentasi (MariNeXt, U-Net SAR) untuk WebGIS.

Masukan: raster kelas (uint8; 0 = tanpa data, 1..N = kelas) dan probabilitas kelas minyak
pada grid proyeksi metrik (UTM). Keluaran di folder `result/`:
classes.tif, oil_spill_prob.tif, oil_spill.geojson, classes.png (+ ringkasan untuk panel).
"""

import json
from pathlib import Path

import numpy as np
import rasterio
import rasterio.features
import rasterio.transform
import rasterio.warp
import shapely
from rasterio.enums import Resampling
from scipy import ndimage

from .jobs import files_url

MIN_OIL_PIXELS = 10


def summarise(classes: np.ndarray, prob: np.ndarray, profile: dict, out: Path, job_id: str,
              class_defs: list[tuple[str, str, str]], oil_value: int, transparent=(),
              min_oil_pixels: int = MIN_OIL_PIXELS) -> dict:
    """class_defs: (nama, nama Indonesia, warna hex) untuk kelas 1..N.

    `transparent`: nilai kelas yang tidak digambar di overlay peta (mis. laut pada SAR).
    """
    out.mkdir(parents=True, exist_ok=True)
    transform, crs = profile["transform"], profile["crs"]
    res = abs(transform.a)
    pixel_km2 = res * abs(transform.e) / 1e6

    profile = dict(profile, driver="GTiff", count=1, dtype="uint8", nodata=0, compress="deflate")
    with rasterio.open(out / "classes.tif", "w", **profile) as dst:
        dst.write(classes.astype("uint8"), 1)
    with rasterio.open(out / "oil_spill_prob.tif", "w", **dict(profile, dtype="float32", nodata=np.nan)) as dst:
        dst.write(prob.astype("float32"), 1)

    valid = int((classes > 0).sum())
    stats = []
    for value, (name, name_id, color) in enumerate(class_defs, start=1):
        n = int((classes == value).sum())
        stats.append({"id": value, "name": name, "name_id": name_id, "color": color,
                      "area_km2": round(n * pixel_km2, 4), "percent": round(100 * n / max(valid, 1), 2)})

    # Poligon tiap petak minyak, dengan luas dan probabilitas model.
    labels, _ = ndimage.label(classes == oil_value, structure=np.ones((3, 3), dtype=bool))
    features = []
    for index, sl in enumerate(ndimage.find_objects(labels), start=1):
        sub = labels[sl] == index
        if sub.sum() < min_oil_pixels:
            continue
        offset = transform * rasterio.Affine.translation(sl[1].start, sl[0].start)
        mask = sub.astype("uint8")
        parts = [shapely.geometry.shape(g) for g, _ in
                 rasterio.features.shapes(mask, mask=mask > 0, connectivity=8, transform=offset)]
        geom = shapely.union_all(parts).simplify(res * 0.75, preserve_topology=True)
        geom = rasterio.warp.transform_geom(crs, "EPSG:4326", shapely.geometry.mapping(geom))
        p = prob[sl][sub]
        features.append({"type": "Feature", "geometry": geom, "properties": {
            "area_km2": round(float(sub.sum()) * pixel_km2, 4),
            "prob_mean": round(float(np.nanmean(p)), 3),
            "prob_max": round(float(np.nanmax(p)), 3),
        }})
    features.sort(key=lambda f: -f["properties"]["area_km2"])
    for i, f in enumerate(features, start=1):
        f["id"] = f["properties"]["id"] = i
    oil = {"type": "FeatureCollection", "features": features}
    (out / "oil_spill.geojson").write_text(json.dumps(oil), encoding="utf-8")

    bounds = overlay_png(classes, profile, out / "classes.png", class_defs, transparent)
    base = files_url(job_id)
    return {
        "resolution_m": res,
        "valid_km2": round(valid * pixel_km2, 3),
        "classes": stats,
        "oil_class": oil_value,
        "oil_area_km2": round(sum(f["properties"]["area_km2"] for f in features), 4),
        "oil": oil,
        "overlay": {"url": f"{base}/classes.png", "bounds": bounds},
        "downloads": {name: f"{base}/{name}" for name in ("classes.tif", "oil_spill_prob.tif", "oil_spill.geojson")},
    }


def overlay_png(classes: np.ndarray, profile: dict, path: Path, class_defs, transparent=()) -> list[float]:
    """Peta kelas berwarna dalam Web Mercator, untuk L.imageOverlay. Kembalikan [[S, W], [N, E]]."""
    src_crs, src_transform = profile["crs"], profile["transform"]
    dst_transform, width, height = rasterio.warp.calculate_default_transform(
        src_crs, "EPSG:3857", classes.shape[1], classes.shape[0],
        *rasterio.transform.array_bounds(classes.shape[0], classes.shape[1], src_transform),
    )
    merc = np.zeros((height, width), dtype="uint8")
    rasterio.warp.reproject(classes.astype("uint8"), merc, src_transform=src_transform, src_crs=src_crs,
                            dst_transform=dst_transform, dst_crs="EPSG:3857",
                            resampling=Resampling.nearest, src_nodata=0, dst_nodata=0)
    palette = np.zeros((len(class_defs) + 1, 4), dtype="uint8")
    for value, (_, _, color) in enumerate(class_defs, start=1):
        alpha = 0 if value in transparent else 255
        palette[value] = [int(color[i:i + 2], 16) for i in (1, 3, 5)] + [alpha]
    rgba = palette[merc].transpose(2, 0, 1)
    with rasterio.open(path, "w", driver="PNG", width=width, height=height, count=4, dtype="uint8") as dst:
        dst.write(rgba)
    left, bottom, right, top = rasterio.transform.array_bounds(height, width, dst_transform)
    lons, lats = rasterio.warp.transform("EPSG:3857", "EPSG:4326", [left, right], [bottom, top])
    return [[lats[0], lons[0]], [lats[1], lons[1]]]
