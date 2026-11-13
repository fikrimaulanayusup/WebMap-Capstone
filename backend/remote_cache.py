"""Akses file COG jarak jauh lewat cache potongan (chunk) di disk lokal.

GDAL membaca COG dari S3 dengan satu koneksi HTTP berurutan. Dari Indonesia ke bucket
Sentinel-1 (Frankfurt) satu koneksi hanya ~0,2 MB/s, padahal satu tile butuh beberapa MB.
Modul ini menggantikan lapisan jaringan GDAL:

  * file dipecah jadi potongan 256 KB yang diunduh paralel (16 koneksi),
  * tiap potongan disimpan di folder `cache/`, jadi hanya diunduh sekali,
  * permintaan tile yang bersamaan dan butuh potongan sama menunggu satu unduhan saja.

Dipakai lewat `rasterio.open(key, opener=RemoteContainer(base_url))`, dengan `key` berupa
path file relatif terhadap `base_url`.
"""

import hashlib
import os
import threading
import time
from collections import OrderedDict
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

import httpx
from rasterio.abc import MultiByteRangeResourceContainer

CHUNK = 256 * 1024
CACHE_DIR = Path(__file__).resolve().parent.parent / "cache"
MAX_CACHE_BYTES = 5 * 1024**3
MEMORY_CHUNKS = 256  # ~64 MB potongan terakhir disimpan di RAM
WORKERS = 16

_http = httpx.Client(
    timeout=httpx.Timeout(60, connect=15),
    limits=httpx.Limits(max_connections=WORKERS, max_keepalive_connections=WORKERS),
)
_pool = ThreadPoolExecutor(WORKERS, thread_name_prefix="chunk")
_lock = threading.Lock()
_inflight: dict[tuple[str, int], Future] = {}
_memory: OrderedDict[tuple[str, int], bytes] = OrderedDict()
_sizes: dict[str, int] = {}


def _dir(url: str) -> Path:
    return CACHE_DIR / hashlib.sha1(url.encode()).hexdigest()[:20]


def _request(method: str, url: str, **kwargs) -> httpx.Response:
    for attempt in range(3):
        try:
            resp = _http.request(method, url, **kwargs)
            resp.raise_for_status()
            return resp
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code < 500 or attempt == 2:
                raise
        except httpx.TransportError:
            if attempt == 2:
                raise
        time.sleep(0.5 * (attempt + 1))
    raise AssertionError("unreachable")


def _size(url: str) -> int:
    size = _sizes.get(url)
    if size is None:
        meta = _dir(url) / "size"
        try:
            size = int(meta.read_text())
        except (FileNotFoundError, ValueError):
            size = int(_request("HEAD", url).headers["content-length"])
            meta.parent.mkdir(parents=True, exist_ok=True)
            meta.write_text(str(size))
        _sizes[url] = size
    return size


def _load_chunk(url: str, index: int) -> bytes:
    key = (url, index)
    try:
        path = _dir(url) / f"{index}.bin"
        try:
            data = path.read_bytes()
            # Tandai baru dipakai: prune_cache menghapus berdasarkan waktu ini, jadi data yang
            # sering dibaca tidak ikut terhapus hanya karena dulu diunduh lebih awal.
            try:
                os.utime(path)
            except OSError:
                pass
        except FileNotFoundError:
            start = index * CHUNK
            data = _request("GET", url, headers={"Range": f"bytes={start}-{start + CHUNK - 1}"}).content
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(data)
            os.replace(tmp, path)
        with _lock:
            _memory[key] = data
            while len(_memory) > MEMORY_CHUNKS:
                _memory.popitem(last=False)
        return data
    finally:
        with _lock:
            _inflight.pop(key, None)


def _read_ranges(url: str, ranges: list[tuple[int, int]]) -> list[bytes]:
    """Baca beberapa rentang (offset, panjang) sekaligus; potongan yang belum ada diunduh paralel."""
    needed = sorted({i for off, n in ranges if n > 0 for i in range(off // CHUNK, (off + n - 1) // CHUNK + 1)})
    chunks: dict[int, bytes] = {}
    pending: dict[int, Future] = {}
    with _lock:
        for i in needed:
            key = (url, i)
            if key in _memory:
                _memory.move_to_end(key)
                chunks[i] = _memory[key]
            else:
                if key not in _inflight:
                    _inflight[key] = _pool.submit(_load_chunk, url, i)
                pending[i] = _inflight[key]
    for i, future in pending.items():
        chunks[i] = future.result()

    out = []
    for off, n in ranges:
        if n <= 0:
            out.append(b"")
            continue
        first = off // CHUNK
        data = b"".join(chunks[i] for i in range(first, (off + n - 1) // CHUNK + 1))
        out.append(data[off - first * CHUNK : off - first * CHUNK + n])
    return out


class _RemoteFile:
    """Objek mirip-file (read/seek/tell) yang dilayani dari cache potongan."""

    def __init__(self, url: str):
        self.url = url
        self.size = _size(url)
        self.pos = 0

    def seek(self, offset: int, whence: int = 0) -> int:
        self.pos = offset + (0, self.pos, self.size)[whence]
        return self.pos

    def tell(self) -> int:
        return self.pos

    def read(self, n: int = -1) -> bytes:
        remaining = max(0, self.size - self.pos)
        n = remaining if n is None or n < 0 else min(n, remaining)
        (data,) = _read_ranges(self.url, [(self.pos, n)])
        self.pos += n
        return data

    def get_byte_ranges(self, offsets, sizes) -> list[bytes]:
        # Dipanggil GDAL saat satu tile butuh beberapa blok TIFF sekaligus.
        return _read_ranges(self.url, list(zip(offsets, sizes)))

    def close(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def read_file(url: str) -> bytes:
    """Isi lengkap sebuah file (untuk file kecil seperti XML), lewat cache potongan."""
    return _RemoteFile(url).read()


class RemoteContainer(MultiByteRangeResourceContainer):
    """'Sistem berkas' hanya-baca untuk rasterio: tiap path adalah key di bawah `base_url`.

    Path sengaja bukan URL utuh: rasterio.open jauh lebih lambat (~1,5 s) bila path yang
    diberikan ke opener berbentuk `https://...`.
    """

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/") + "/"

    def _url(self, path) -> str:
        return self.base_url + str(path).lstrip("/")

    def open(self, path, mode="rb", **kwds):
        if not self.isfile(path):
            raise FileNotFoundError(path)
        return _RemoteFile(self._url(path))

    def isfile(self, path):
        # GDAL juga mencoba file pendamping (.ovr, .aux.xml, ...); itu tidak ada di bucket.
        return str(path).endswith((".tiff", ".tif"))

    def isdir(self, path):
        return False

    def ls(self, path):
        return []

    def mtime(self, path):
        return 0

    def rm(self, path):
        raise PermissionError("cache hanya-baca")

    def size(self, path):
        return _size(self._url(path))


def prune_cache() -> None:
    """Jaga ukuran folder cache: jika melebihi batas, hapus potongan yang paling lama tidak dipakai."""
    if not CACHE_DIR.is_dir():
        return
    files = [(p.stat().st_mtime, p.stat().st_size, p) for p in CACHE_DIR.glob("*/*.bin")]
    total = sum(size for _, size, _ in files)
    for _, size, path in sorted(files, key=lambda f: f[0]):
        if total <= MAX_CACHE_BYTES:
            break
        path.unlink(missing_ok=True)
        total -= size
