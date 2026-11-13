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

echo Menyiapkan server WebGIS...
echo Browser akan otomatis terbuka begitu server selesai dimuat.
echo.
echo - Alamat WebGIS : http://127.0.0.1:8000
echo - Jangan tutup jendela ini selama WebGIS digunakan.
echo - Tekan Ctrl + C untuk mematikan server.
echo ========================================================
echo.

REM Buka browser otomatis tepat saat port 8000 sudah siap menerima koneksi (tanpa perlu refresh)
start "" /b powershell -WindowStyle Hidden -NoProfile -Command "for ($i=0; $i -lt 50; $i++) { try { $c = New-Object System.Net.Sockets.TcpClient('127.0.0.1', 8000); $c.Close(); Start-Process 'http://127.0.0.1:8000'; break } catch { Start-Sleep -Milliseconds 300 } }"

.\.venv\Scripts\python.exe -m uvicorn backend.main:app --port 8000

echo.
echo ========================================================
echo Server WebGIS telah dihentikan.
echo ========================================================
pause
