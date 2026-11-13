@echo off
setlocal enabledelayedexpansion
title Instalasi WebGIS Pemetaan Tumpahan Minyak
cd /d "%~dp0"

:MENU
cls
echo ======================================================================
echo           PROGRAM INSTALASI WEBGIS PEMETAAN TUMPAHAN MINYAK
echo ======================================================================
echo.
echo Pilih opsi instalasi yang ingin dijalankan:
echo.
echo  [1] Instalasi Lengkap (WebGIS Server + U-Net SAR + MariNeXt Optik)
echo  [2] Instalasi Dasar WebGIS (Hanya .venv: Penampil Citra, Peta, dan AIS)
echo  [3] Pasang/Perbaiki Environment U-Net SAR (Conda 'unet3' - Sentinel-1)
echo  [4] Pasang/Perbaiki Environment MariNeXt (Conda 'mados' dan 'acolite' - Sentinel-2)
echo  [0] Keluar
echo.
echo ======================================================================
set "PILIHAN="
set /p PILIHAN="Masukkan pilihan Anda [1/2/3/4/0]: "

if "!PILIHAN!"=="1" goto DO_INSTALL_ALL
if "!PILIHAN!"=="2" goto DO_INSTALL_VENV
if "!PILIHAN!"=="3" goto DO_INSTALL_UNET
if "!PILIHAN!"=="4" goto DO_INSTALL_MARINEXT
if "!PILIHAN!"=="0" goto KELUAR

echo.
echo Pilihan tidak valid. Silakan coba lagi.
ping 127.0.0.1 -n 2 >nul 2>&1
goto MENU

:DO_INSTALL_ALL
goto RUN_ALL

:DO_INSTALL_VENV
goto RUN_VENV

:DO_INSTALL_UNET
goto RUN_UNET

:DO_INSTALL_MARINEXT
goto RUN_MARINEXT

:FIND_PYTHON
set "PYTHON_EXE="
set "PYTHON_ARGS="

REM 1. Cek Python Launcher (py -3.10)
py -3.10 --version >nul 2>&1
if not errorlevel 1 (
    set "PYTHON_EXE=py"
    set "PYTHON_ARGS=-3.10"
    exit /b 0
)

REM 2. Cek semua direktori user di C:\Users untuk Python 3.10, 3.11, 3.12
for /d %%U in ("C:\Users\*") do (
    if not defined PYTHON_EXE if exist "%%~U\AppData\Local\Programs\Python\Python310\python.exe" (
        set "PYTHON_EXE=%%~U\AppData\Local\Programs\Python\Python310\python.exe"
        exit /b 0
    )
    if not defined PYTHON_EXE if exist "%%~U\AppData\Local\Programs\Python\Python311\python.exe" (
        set "PYTHON_EXE=%%~U\AppData\Local\Programs\Python\Python311\python.exe"
        exit /b 0
    )
    if not defined PYTHON_EXE if exist "%%~U\AppData\Local\Programs\Python\Python312\python.exe" (
        set "PYTHON_EXE=%%~U\AppData\Local\Programs\Python\Python312\python.exe"
        exit /b 0
    )
)

REM 3. Cek folder Program Files dan root drive C:
for %%P in (
    "C:\Program Files\Python310\python.exe"
    "C:\Python310\python.exe"
    "C:\Program Files\Python311\python.exe"
    "C:\Python311\python.exe"
    "C:\Program Files\Python312\python.exe"
    "C:\Python312\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
) do (
    if not defined PYTHON_EXE if exist %%P (
        set "PYTHON_EXE=%%~P"
        exit /b 0
    )
)

REM 4. Cek python di PATH
python --version >nul 2>&1
if not errorlevel 1 (
    set "PYTHON_EXE=python"
    exit /b 0
)

REM 5. Cek py versi 3.11 / 3.12 / py default
py -3.11 --version >nul 2>&1
if not errorlevel 1 (
    set "PYTHON_EXE=py"
    set "PYTHON_ARGS=-3.11"
    exit /b 0
)
py -3.12 --version >nul 2>&1
if not errorlevel 1 (
    set "PYTHON_EXE=py"
    set "PYTHON_ARGS=-3.12"
    exit /b 0
)
py --version >nul 2>&1
if not errorlevel 1 (
    set "PYTHON_EXE=py"
    exit /b 0
)

REM 6. Cek python di conda envs unet3
for /d %%U in ("C:\Users\*") do (
    if not defined PYTHON_EXE if exist "%%~U\anaconda3\envs\unet3\python.exe" (
        set "PYTHON_EXE=%%~U\anaconda3\envs\unet3\python.exe"
        exit /b 0
    )
    if not defined PYTHON_EXE if exist "%%~U\miniconda3\envs\unet3\python.exe" (
        set "PYTHON_EXE=%%~U\miniconda3\envs\unet3\python.exe"
        exit /b 0
    )
)

exit /b 0

:FIND_CONDA
set "CONDA_PATH="

REM 1. Cek CONDA_EXE yang mungkin sudah di-set
if defined CONDA_EXE if exist "%CONDA_EXE%" (
    set "CONDA_PATH=%CONDA_EXE%"
    exit /b 0
)

REM 2. Cek semua direktori user di C:\Users
for /d %%U in ("C:\Users\*") do (
    if not defined CONDA_PATH if exist "%%~U\anaconda3\Scripts\conda.exe" set "CONDA_PATH=%%~U\anaconda3\Scripts\conda.exe"
    if not defined CONDA_PATH if exist "%%~U\miniconda3\Scripts\conda.exe" set "CONDA_PATH=%%~U\miniconda3\Scripts\conda.exe"
    if not defined CONDA_PATH if exist "%%~U\anaconda3\condabin\conda.bat" set "CONDA_PATH=%%~U\anaconda3\condabin\conda.bat"
    if not defined CONDA_PATH if exist "%%~U\miniconda3\condabin\conda.bat" set "CONDA_PATH=%%~U\miniconda3\condabin\conda.bat"
)
if defined CONDA_PATH exit /b 0

REM 3. Cek lokasi sistem / ProgramData / C:\
for %%C in (
    "C:\ProgramData\anaconda3\Scripts\conda.exe"
    "C:\ProgramData\miniconda3\Scripts\conda.exe"
    "C:\anaconda3\Scripts\conda.exe"
    "C:\miniconda3\Scripts\conda.exe"
    "C:\ProgramData\anaconda3\condabin\conda.bat"
    "C:\ProgramData\miniconda3\condabin\conda.bat"
    "C:\anaconda3\condabin\conda.bat"
    "C:\miniconda3\condabin\conda.bat"
) do (
    if not defined CONDA_PATH if exist %%C (
        set "CONDA_PATH=%%~C"
        exit /b 0
    )
)

REM 4. Cek conda di PATH
where conda.exe >nul 2>&1
if not errorlevel 1 (
    for /f "delims=" %%I in ('where conda.exe') do (
        if not defined CONDA_PATH set "CONDA_PATH=%%I"
    )
    if defined CONDA_PATH exit /b 0
)

where conda.bat >nul 2>&1
if not errorlevel 1 (
    for /f "delims=" %%I in ('where conda.bat') do (
        if not defined CONDA_PATH set "CONDA_PATH=%%I"
    )
    if defined CONDA_PATH exit /b 0
)

exit /b 0

:INSTALL_VENV
cls
echo ======================================================================
echo [1/3] Menyiapkan Virtual Environment Server WebGIS [.venv]
echo ======================================================================
echo.

if exist ".venv\Scripts\python.exe" goto VENV_EXISTS

echo Mencari instalasi Python di sistem ...
call :FIND_PYTHON

if not defined PYTHON_EXE goto PROMPT_INSTALL_PYTHON
goto DO_CREATE_VENV

:PROMPT_INSTALL_PYTHON
echo.
echo ======================================================================
echo [INFORMASI] Python belum terdeteksi di komputer ini.
echo ======================================================================
echo WebGIS membutuhkan Python versi 64-bit (disarankan Python 3.10) untuk berjalan.
echo Sistem dapat mengunduh dan memasang Python 3.10 resmi secara otomatis.
echo.
set PASANG_PY=Y
set /p PASANG_PY="Pasang Python 3.10 secara otomatis sekarang? [Y/T] (Default: Y): "
if /i "!PASANG_PY!"=="T" (
    echo.
    echo Silakan unduh dan pasang Python 3.10 secara manual dari https://python.org
    echo Pastikan Anda mencentang opsi "Add Python to PATH" saat memasang.
    pause
    goto MENU
)

echo.
set "CLEAN_TEMP=%TEMP:"=%"
set "PY_INSTALLER=!CLEAN_TEMP!\python-3.10.11-amd64.exe"
echo Mengunduh installer resmi Python 3.10 ...
curl.exe -L -o "!PY_INSTALLER!" "https://www.python.org/ftp/python/3.10.11/python-3.10.11-amd64.exe"
if errorlevel 1 (
    echo [ERROR] Gagal mengunduh installer Python. Periksa koneksi internet Anda.
    pause
    goto MENU
)

echo Memasang Python 3.10 ke sistem...
echo (Jendela pemasangan Python akan muncul, mohon tunggu hingga selesai...)
"!PY_INSTALLER!" /passive PrependPath=1 Include_pip=1 SimpleInstall=1
del "!PY_INSTALLER!" >nul 2>&1

call :FIND_PYTHON
if not defined PYTHON_EXE (
    echo.
    echo [PERINGATAN] Pemasangan Python telah selesai.
    echo Silakan tutup jendela ini dan buka kembali install_webgis.bat
    echo agar sistem membaca jalur PATH Python yang baru.
    pause
    goto MENU
)
echo [SUKSES] Python 3.10 berhasil dipasang!

:DO_CREATE_VENV
echo.
if defined PYTHON_ARGS (
    echo Membuat virtual environment .venv menggunakan: "!PYTHON_EXE!" !PYTHON_ARGS! ...
    "!PYTHON_EXE!" !PYTHON_ARGS! -m venv .venv
) else (
    echo Membuat virtual environment .venv menggunakan: "!PYTHON_EXE!" ...
    "!PYTHON_EXE!" -m venv .venv
)
if errorlevel 1 (
    echo [ERROR] Gagal membuat virtual environment .venv.
    pause
    goto MENU
)

:VENV_EXISTS
echo.
echo Virtual environment [.venv] siap. Memeriksa dependensi backend...
echo Memasang / memperbarui paket dependensi backend dari backend\requirements.txt ...
call .\.venv\Scripts\python.exe -m pip install --upgrade pip
call .\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
if errorlevel 1 (
    echo [ERROR] Gagal memasang requirements.txt ke .venv.
    pause
    goto MENU
)

echo.
echo [SUKSES] Virtual Environment WebGIS [.venv] berhasil disiapkan!
exit /b 0

:INSTALL_UNET
cls
echo ======================================================================
echo [2/3] Menyiapkan Conda Environment U-Net SAR ['unet3']
echo ======================================================================
echo.

call :FIND_CONDA
if not defined CONDA_PATH goto PROMPT_INSTALL_CONDA_UNET
goto DO_SETUP_UNET

:PROMPT_INSTALL_CONDA_UNET
echo.
echo ======================================================================
echo [INFORMASI] Conda (Miniconda / Anaconda) belum terpasang di komputer ini.
echo ======================================================================
echo Model klasifikasi tumpahan minyak membutuhkan Conda untuk dijalankan.
echo Sistem dapat mengunduh dan memasang Miniconda resmi secara otomatis.
echo.
set PASANG_CONDA=Y
set /p PASANG_CONDA="Pasang Miniconda secara otomatis sekarang? [Y/T] (Default: Y): "
if /i "!PASANG_CONDA!"=="T" (
    echo.
    echo Silakan pasang Anaconda/Miniconda terlebih dahulu secara manual.
    pause
    goto MENU
)

echo.
set "CLEAN_TEMP=%TEMP:"=%"
set "CONDA_INSTALLER=!CLEAN_TEMP!\miniconda_installer.exe"
echo Mengunduh installer resmi Miniconda (sekitar 150 MB)...
curl.exe -L -o "!CONDA_INSTALLER!" "https://repo.anaconda.com/miniconda/Miniconda3-latest-Windows-x86_64.exe"
if errorlevel 1 (
    echo [ERROR] Gagal mengunduh installer Miniconda. Periksa koneksi internet Anda.
    pause
    goto MENU
)

echo Memasang Miniconda ke %USERPROFILE%\miniconda3 ...
echo (Mohon tunggu beberapa menit hingga proses pemasangan selesai...)
"!CONDA_INSTALLER!" /InstallationType=JustMe /RegisterPython=0 /S /D=%USERPROFILE%\miniconda3
del "!CONDA_INSTALLER!" >nul 2>&1

call :FIND_CONDA
if not defined CONDA_PATH (
    echo.
    echo [PERINGATAN] Instalasi Miniconda telah selesai.
    echo Silakan tutup jendela ini dan jalankan kembali install_webgis.bat.
    pause
    goto MENU
)
echo [SUKSES] Miniconda berhasil dipasang!

:DO_SETUP_UNET
echo Ditemukan Conda: "%CONDA_PATH%"

REM Cek apakah environment unet3 sudah ada
call "%CONDA_PATH%" run -n unet3 python --version >nul 2>&1
if not errorlevel 1 goto UNET_ALREADY_EXISTS

echo Membuat environment Conda 'unet3' baru dengan Python 3.10...
call "%CONDA_PATH%" create -n unet3 python=3.10 -y
if errorlevel 1 (
    echo [ERROR] Gagal membuat conda environment unet3.
    pause
    goto MENU
)
goto UNET_INSTALL_PKGS

:UNET_ALREADY_EXISTS
echo Environment 'unet3' sudah terpasang. Memeriksa paket dependensi...

:UNET_INSTALL_PKGS
echo Memasang / memperbarui dependensi TensorFlow dan OpenCV pada 'unet3' ...
call "%CONDA_PATH%" run -n unet3 python -m pip install tensorflow opencv-python
if errorlevel 1 (
    echo [ERROR] Gagal memasang dependensi unet3.
    pause
    goto MENU
)

echo.
echo [SUKSES] Environment 'unet3' berhasil disiapkan!
exit /b 0

:INSTALL_MARINEXT
cls
echo ======================================================================
echo [3/3] Menyiapkan Conda Environment MariNeXt ['mados' dan 'acolite']
echo ======================================================================
echo.

call :FIND_CONDA
if not defined CONDA_PATH goto PROMPT_INSTALL_CONDA_MARINEXT
goto DO_SETUP_MARINEXT

:PROMPT_INSTALL_CONDA_MARINEXT
echo.
echo ======================================================================
echo [INFORMASI] Conda (Miniconda / Anaconda) belum terpasang di komputer ini.
echo ======================================================================
echo Model MariNeXt membutuhkan Conda untuk dijalankan.
echo Sistem dapat mengunduh dan memasang Miniconda resmi secara otomatis.
echo.
set PASANG_CONDA=Y
set /p PASANG_CONDA="Pasang Miniconda secara otomatis sekarang? [Y/T] (Default: Y): "
if /i "!PASANG_CONDA!"=="T" (
    echo.
    echo Silakan pasang Anaconda/Miniconda terlebih dahulu secara manual.
    pause
    goto MENU
)

echo.
set "CLEAN_TEMP=%TEMP:"=%"
set "CONDA_INSTALLER=!CLEAN_TEMP!\miniconda_installer.exe"
echo Mengunduh installer resmi Miniconda (sekitar 150 MB)...
curl.exe -L -o "!CONDA_INSTALLER!" "https://repo.anaconda.com/miniconda/Miniconda3-latest-Windows-x86_64.exe"
if errorlevel 1 (
    echo [ERROR] Gagal mengunduh installer Miniconda. Periksa koneksi internet Anda.
    pause
    goto MENU
)

echo Memasang Miniconda ke %USERPROFILE%\miniconda3 ...
echo (Mohon tunggu beberapa menit hingga proses pemasangan selesai...)
"!CONDA_INSTALLER!" /InstallationType=JustMe /RegisterPython=0 /S /D=%USERPROFILE%\miniconda3
del "!CONDA_INSTALLER!" >nul 2>&1

call :FIND_CONDA
if not defined CONDA_PATH (
    echo.
    echo [PERINGATAN] Instalasi Miniconda telah selesai.
    echo Silakan tutup jendela ini dan jalankan kembali install_webgis.bat.
    pause
    goto MENU
)
echo [SUKSES] Miniconda berhasil dipasang!

:DO_SETUP_MARINEXT
echo Ditemukan Conda: "%CONDA_PATH%"
echo.

REM --- [A] Environment MADOS ---
echo [A] Menyiapkan environment Conda 'mados' ...
call "%CONDA_PATH%" run -n mados python --version >nul 2>&1
if not errorlevel 1 goto MADOS_ALREADY_EXISTS

echo Membuat environment Conda 'mados' baru...
call "%CONDA_PATH%" create -n mados -c conda-forge --override-channels python=3.8 numpy=1.23 pandas=1.4 scikit-learn=1.0 gdal rasterio pytables tqdm -y
if errorlevel 1 (
    echo [ERROR] Gagal membuat environment mados.
    pause
    goto MENU
)
goto MADOS_INSTALL_PKGS

:MADOS_ALREADY_EXISTS
echo Environment 'mados' sudah terpasang. Memeriksa paket dependensi...

:MADOS_INSTALL_PKGS
echo Memeriksa PyTorch CPU dan pustaka MADOS ...
call "%CONDA_PATH%" run -n mados python -m pip install torch==1.11.0+cpu torchvision==0.12.0+cpu --extra-index-url https://download.pytorch.org/whl/cpu
call "%CONDA_PATH%" run -n mados python -m pip install mmcv==1.6.0 yapf==0.40.1 timm==0.4.12 opencv-python==4.7.0.72

REM --- [B] Environment ACOLITE ---
echo.
echo [B] Menyiapkan environment Conda 'acolite' ...
call "%CONDA_PATH%" run -n acolite python --version >nul 2>&1
if not errorlevel 1 goto ACOLITE_ALREADY_EXISTS

echo Membuat environment Conda 'acolite' baru...
call "%CONDA_PATH%" create -n acolite --override-channels -c conda-forge python=3.10 pyresample cartopy scipy pyhdf gdal libgdal-jp2openjpeg libgdal-netcdf netcdf4 h5py pygrib requests matplotlib scikit-image pyproj zarr fsspec aiohttp -y
if errorlevel 1 (
    echo [ERROR] Gagal membuat environment acolite.
    pause
    goto MENU
)
goto ACOLITE_INSTALL_PKGS

:ACOLITE_ALREADY_EXISTS
echo Environment 'acolite' sudah terpasang. Memeriksa paket dependensi...

:ACOLITE_INSTALL_PKGS
call "%CONDA_PATH%" run -n acolite python -m pip install "numpy<2"

echo Memeriksa file dependensi GDAL liblz4.dll pada acolite ...
for /d %%U in ("C:\Users\*") do (
    if exist "%%~U\anaconda3\envs\acolite\Library\bin\lz4.dll" (
        if not exist "%%~U\anaconda3\envs\acolite\Library\bin\liblz4.dll" (
            copy /y "%%~U\anaconda3\envs\acolite\Library\bin\lz4.dll" "%%~U\anaconda3\envs\acolite\Library\bin\liblz4.dll" >nul 2>&1
            echo [INFO] Berhasil menyalin lz4.dll ke liblz4.dll.
        )
    )
    if exist "%%~U\miniconda3\envs\acolite\Library\bin\lz4.dll" (
        if not exist "%%~U\miniconda3\envs\acolite\Library\bin\liblz4.dll" (
            copy /y "%%~U\miniconda3\envs\acolite\Library\bin\lz4.dll" "%%~U\miniconda3\envs\acolite\Library\bin\liblz4.dll" >nul 2>&1
            echo [INFO] Berhasil menyalin lz4.dll ke liblz4.dll.
        )
    )
)
for %%D in ("C:\anaconda3" "C:\miniconda3" "C:\ProgramData\anaconda3" "C:\ProgramData\miniconda3") do (
    if exist "%%~D\envs\acolite\Library\bin\lz4.dll" (
        if not exist "%%~D\envs\acolite\Library\bin\liblz4.dll" (
            copy /y "%%~D\envs\acolite\Library\bin\lz4.dll" "%%~D\envs\acolite\Library\bin\liblz4.dll" >nul 2>&1
            echo [INFO] Berhasil menyalin lz4.dll ke liblz4.dll.
        )
    )
)

echo.
echo [SUKSES] Environment 'mados' dan 'acolite' berhasil disiapkan!
exit /b 0

:RUN_VENV
call :INSTALL_VENV
pause
goto MENU

:RUN_UNET
call :INSTALL_UNET
pause
goto MENU

:RUN_MARINEXT
call :INSTALL_MARINEXT
pause
goto MENU

:RUN_ALL
call :INSTALL_VENV
call :INSTALL_UNET
call :INSTALL_MARINEXT
cls
echo ======================================================================
echo                 SEMUA INSTALASI TELAH SELESAI!
echo ======================================================================
echo.
echo Anda kini dapat langsung menjalankan WebGIS dengan klik dua kali berkas:
echo   --^> start_webgis.bat
echo.
echo Server akan otomatis terbuka di browser Anda (http://127.0.0.1:8000).
echo ======================================================================
pause
goto MENU

:KELUAR
exit /b 0
