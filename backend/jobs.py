"""Pekerjaan analisis yang berjalan di latar belakang (MariNeXt, U-Net SAR).

Satu pekerjaan dijalankan sekaligus (CPU penuh). Status disimpan di memori; berkas hasil di
`cache/jobs/<id>/result/` dan tetap ada setelah server di-restart.
"""

import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

from .geo import DetectionError

WORK_DIR = Path(__file__).resolve().parent.parent / "cache" / "jobs"
KEEP_JOBS = 20
CONDA = os.environ.get("MARINEXT_CONDA", r"C:\miniconda3\Scripts\conda.exe")
RESULT_FILES = {
    "classes.png": "image/png",
    "classes.tif": "image/tiff",
    "oil_spill_prob.tif": "image/tiff",
    "oil_spill.geojson": "application/geo+json",
}

_jobs: dict[str, dict] = {}
_lock = threading.Lock()
_runner = ThreadPoolExecutor(1, thread_name_prefix="job")


class Job:
    def __init__(self, job_id: str, stages: list[str]):
        self.id = job_id
        self.stages = stages
        self.dir = WORK_DIR / job_id

    def stage(self, index: int):
        """Tandai tahap ke-`index` (dari `stages`) sedang berjalan."""
        with _lock:
            _jobs[self.id].update(status="running", stage=self.stages[index], stage_index=index)


def start(kind: str, stages: list[str], aoi, run: Callable[[Job], dict]) -> str:
    """Jalankan `run(job)` di latar belakang; hasilnya (dict) disimpan sebagai `result`."""
    _remove_old_jobs()
    job = Job(uuid.uuid4().hex[:8], stages)
    with _lock:
        _jobs[job.id] = {"kind": kind, "status": "queued", "stage": "Menunggu giliran", "stage_index": -1,
                         "stages": stages, "started": time.time(), "aoi": [round(v, 5) for v in aoi]}
    _runner.submit(_execute, job, run)
    return job.id


def _execute(job: Job, run):
    try:
        job.dir.mkdir(parents=True, exist_ok=True)
        result = run(job)
        with _lock:
            _jobs[job.id].update(status="done", stage="Selesai", stage_index=len(job.stages), result=result)
    except Exception as exc:  # pesan ditampilkan ke pengguna
        message = str(exc) if isinstance(exc, (DetectionError, RuntimeError)) else f"{type(exc).__name__}: {exc}"
        with _lock:
            _jobs[job.id].update(status="error", error=message)


def status(job_id: str) -> dict | None:
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            return None
        out = {k: v for k, v in job.items() if k != "started"}
    out["elapsed_s"] = round(time.time() - job["started"], 1)
    return out


def result_file(job_id: str, name: str) -> Path | None:
    if name not in RESULT_FILES or not re.fullmatch(r"[0-9a-f]{8}", job_id):
        return None
    path = WORK_DIR / job_id / "result" / name
    return path if path.is_file() else None


def files_url(job_id: str) -> str:
    return f"/api/jobs/{job_id}/files"


def _remove_old_jobs():
    """Folder hasil disimpan untuk KEEP_JOBS pekerjaan terakhir saja."""
    if not WORK_DIR.is_dir():
        return
    folders = sorted((p for p in WORK_DIR.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime)
    for folder in folders[:-KEEP_JOBS]:
        shutil.rmtree(folder, ignore_errors=True)


def _env_python(env: str) -> str:
    """Path lengkap python.exe milik env conda (C:\\miniconda3\\envs\\<env>\\python.exe)."""
    return str(Path(CONDA).resolve().parents[1] / "envs" / env / "python.exe")


def conda_run(env: str, args: list[str], cwd: Path, log: Path, timeout: int):
    """Jalankan python env conda `env` dengan argumen `args`; keluaran ke berkas `log`."""
    # Python ditulis lengkap: bila server dijalankan dari terminal yang mengaktifkan .venv,
    # `conda run ... python` ternyata memakai python .venv, bukan python env conda.
    # `conda run` tetap dipakai agar variabel lingkungan env (PROJ, GDAL) ikut aktif.
    cmd = [CONDA, "run", "-n", env, "--no-capture-output", _env_python(env), *args]
    with open(log, "w", encoding="utf-8", errors="replace") as out:
        proc = subprocess.run(cmd, cwd=cwd, stdout=out, stderr=subprocess.STDOUT, timeout=timeout,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if proc.returncode != 0:
        tail = log.read_text(encoding="utf-8", errors="replace").strip().splitlines()[-5:]
        raise RuntimeError(f"{env} gagal (kode {proc.returncode}): " + " | ".join(tail))
