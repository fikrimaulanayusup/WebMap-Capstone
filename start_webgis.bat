@echo off
title WebGIS Pemetaan Tumpahan Minyak
cd /d "%~dp0"

echo ========================================================
echo          MEMULAI SERVER WEBGIS TUMPAHAN MINYAK
echo ========================================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment folder .venv belum ditemukan!
    echo Silakan jalankan file "install_webgis.bat" terlebih dahulu untuk memasang dependensi.
    echo.
    pause
    exit /b 1
)

echo Membuka browser ke http://127.0.0.1:8000 ...
start http://127.0.0.1:8000

echo Menjalankan server WebGIS...
echo.
echo - WebGIS dapat diakses di: http://127.0.0.1:8000
echo - Jangan tutup jendela ini selama WebGIS digunakan.
echo - Tekan Ctrl + C untuk mematikan server.
echo ========================================================
echo.

.\.venv\Scripts\python.exe -m uvicorn backend.main:app --port 8000

echo.
echo ========================================================
echo Server WebGIS telah dihentikan.
echo ========================================================
pause
