"""Lokasi data: bucket S3 publik yang dipakai, dan cara membuka/mengambil filenya.

Semua bucket dibaca anonim lewat HTTPS melalui cache potongan lokal (remote_cache.py).
Modul ini meng-import rasterio, jadi harus di-import setelah perbaikan PROJ_LIB di main.py.
"""

import re

import httpx
import rasterio

from .remote_cache import RemoteContainer, read_file

BUCKETS = {
    "sentinel-s1-l1c": RemoteContainer("https://sentinel-s1-l1c.s3.eu-central-1.amazonaws.com/"),
    "e84-earth-search-sentinel-data": RemoteContainer(
        "https://e84-earth-search-sentinel-data.s3.us-west-2.amazonaws.com/"
    ),
    "copernicus-dem-90m": RemoteContainer("https://copernicus-dem-90m.s3.eu-central-1.amazonaws.com/"),
}
# STAC menulis lokasi aset sebagai s3://bucket/key atau https://bucket.s3.<region>.amazonaws.com/key
HREF_RE = re.compile(r"^(?:s3://([a-z0-9.-]+)/|https://([a-z0-9-]+)\.s3\.[a-z0-9-]+\.amazonaws\.com/)(.+)$")

Location = tuple[str, str]  # (bucket, key di dalam bucket)


def locate(href: str) -> Location | None:
    """Ubah href aset STAC menjadi lokasi di salah satu bucket yang dikenal."""
    match = HREF_RE.match(href or "")
    if match and (match[1] or match[2]) in BUCKETS:
        return (match[1] or match[2], match[3])
    return None


def open_raster(location: Location, **options):
    bucket, key = location
    return rasterio.open(key, opener=BUCKETS[bucket], **options)


def fetch(location: Location) -> bytes:
    """Isi lengkap sebuah file kecil (mis. XML anotasi), lewat cache yang sama."""
    bucket, key = location
    return read_file(BUCKETS[bucket].base_url + key)


_missing: set[Location] = set()


def exists(location: Location) -> bool:
    """True jika file ada di bucket. Tile DEM untuk laut lepas memang tidak ada."""
    if location in _missing:
        return False
    bucket, key = location
    try:
        BUCKETS[bucket].size(key)
        return True
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (403, 404):  # S3 publik menjawab 403 untuk key yang tidak ada
            _missing.add(location)
            return False
        raise
