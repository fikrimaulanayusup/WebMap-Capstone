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
echo  [4] Pasang/Perbaiki Environment MariNeXt (Conda 'mados' ^& 'acolite' - Sentinel-2)
echo  [0] Keluar
echo.
echo ======================================================================
set /p PILIHAN="Masukkan pilihan Anda [1/2/3/4/0]: "

if "%PILIHAN%"=="1" goto INSTALL_ALL
if "%PILIHAN%"=="2" goto INSTALL_VENV
if "%PILIHAN%"=="3" goto INSTALL_UNET
if "%PILIHAN%"=="4" goto INSTALL_MARINEXT
if "%PILIHAN%"=="0" goto KELUAR

echo Pilihan tidak valid. Silakan coba lagi.
timeout /t 2 >nul
goto MENU

:FIND_CONDA
set CONDA_PATH=
if defined CONDA_EXE if exist "%CONDA_EXE%" set "CONDA_PATH=%CONDA_EXE%"
if not defined CONDA_PATH if exist "%USERPROFILE%\anaconda3\Scripts\conda.exe" set "CONDA_PATH=%USERPROFILE%\anaconda3\Scripts\conda.exe"
if not defined CONDA_PATH if exist "%USERPROFILE%\miniconda3\Scripts\conda.exe" set "CONDA_PATH=%USERPROFILE%\miniconda3\Scripts\conda.exe"
if not defined CONDA_PATH if exist "C:\anaconda3\Scripts\conda.exe" set "CONDA_PATH=C:\anaconda3\Scripts\conda.exe"
if not defined CONDA_PATH if exist "C:\miniconda3\Scripts\conda.exe" set "CONDA_PATH=C:\miniconda3\Scripts\conda.exe"
if not defined CONDA_PATH if exist "C:\ProgramData\anaconda3\Scripts\conda.exe" set "CONDA_PATH=C:\ProgramData\anaconda3\Scripts\conda.exe"
if not defined CONDA_PATH if exist "C:\ProgramData\miniconda3\Scripts\conda.exe" set "CONDA_PATH=C:\ProgramData\miniconda3\Scripts\conda.exe"
if not defined CONDA_PATH (
    where conda.exe >nul 2>&1
    if not errorlevel 1 for /f "delims=" %%I in ('where conda.exe') do set "CONDA_PATH=%%I"
)
exit /b 0

:INSTALL_VENV
cls
echo ======================================================================
echo [1/3] Menyiapkan Virtual Environment Server WebGIS [.venv]
echo ======================================================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo Mencari Python untuk membuat .venv ...
    set PYTHON_CMD=
    py -3.10 --version >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON_CMD=py -3.10"
    ) else (
        python --version >nul 2>&1
        if not errorlevel 1 (
            set "PYTHON_CMD=python"
        ) else (
            py --version >nul 2>&1
            if not errorlevel 1 set "PYTHON_CMD=py"
        )
    )

    if not defined PYTHON_CMD (
        echo [ERROR] Python tidak ditemukan di sistem!
        echo Pastikan Python 3.10 atau lebih baru sudah terpasang dan dicentang Add Python to PATH.
        pause
        goto MENU
    )

    echo Membuat virtual environment .venv menggunakan: !PYTHON_CMD! ...
    !PYTHON_CMD! -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Gagal membuat virtual environment .venv.
        pause
        goto MENU
    )
) else (
    echo Virtual environment [.venv] sudah ada. Melanjutkan pemasangan dependensi...
)

echo Memasang paket dependensi backend dari backend\requirements.txt ...
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
if errorlevel 1 (
    echo [ERROR] Gagal memasang requirements.txt ke .venv.
    pause
    goto MENU
)

echo.
echo [SUKSES] Virtual Environment WebGIS [.venv] berhasil disiapkan!
if "%PILIHAN%"=="2" (
    pause
    goto MENU
)
exit /b 0

:INSTALL_UNET
cls
echo ======================================================================
echo [2/3] Menyiapkan Conda Environment U-Net SAR ['unet3']
echo ======================================================================
echo.

call :FIND_CONDA
if not defined CONDA_PATH (
    echo [ERROR] Conda [Anaconda / Miniconda] tidak ditemukan!
    echo Silakan pasang Anaconda/Miniconda terlebih dahulu untuk menjalankan klasifikasi SAR.
    pause
    goto MENU
)

echo Ditemukan Conda: "%CONDA_PATH%"
echo Membuat / memperbarui environment Conda 'unet3' ...
"%CONDA_PATH%" create -n unet3 python=3.10 -y
if errorlevel 1 (
    echo [ERROR] Gagal membuat conda environment unet3.
    pause
    goto MENU
)

echo Memasang dependensi TensorFlow dan OpenCV ke 'unet3' ...
"%CONDA_PATH%" run -n unet3 python -m pip install tensorflow opencv-python
if errorlevel 1 (
    echo [ERROR] Gagal memasang dependensi unet3.
    pause
    goto MENU
)

echo.
echo [SUKSES] Environment 'unet3' berhasil disiapkan!
if "%PILIHAN%"=="3" (
    pause
    goto MENU
)
exit /b 0

:INSTALL_MARINEXT
cls
echo ======================================================================
echo [3/3] Menyiapkan Conda Environment MariNeXt ['mados' ^& 'acolite']
echo ======================================================================
echo.

call :FIND_CONDA
if not defined CONDA_PATH (
    echo [ERROR] Conda [Anaconda / Miniconda] tidak ditemukan!
    echo Silakan pasang Anaconda/Miniconda terlebih dahulu untuk menjalankan klasifikasi MariNeXt.
    pause
    goto MENU
)

echo Ditemukan Conda: "%CONDA_PATH%"
echo.
echo [A] Membuat conda environment 'mados' ...
"%CONDA_PATH%" create -n mados -c conda-forge --override-channels python=3.8 numpy=1.23 pandas=1.4 scikit-learn=1.0 gdal rasterio pytables tqdm -y
echo Memasang PyTorch CPU dan pustaka MADOS ...
"%CONDA_PATH%" run -n mados python -m pip install torch==1.11.0+cpu torchvision==0.12.0+cpu --extra-index-url https://download.pytorch.org/whl/cpu
"%CONDA_PATH%" run -n mados python -m pip install mmcv==1.6.0 yapf==0.40.1 timm==0.4.12 opencv-python==4.7.0.72

echo.
echo [B] Membuat conda environment 'acolite' ...
"%CONDA_PATH%" create -n acolite --override-channels -c conda-forge python=3.10 pyresample cartopy scipy pyhdf gdal libgdal-jp2openjpeg libgdal-netcdf netcdf4 h5py pygrib requests matplotlib scikit-image pyproj zarr fsspec aiohttp -y
"%CONDA_PATH%" run -n acolite python -m pip install "numpy<2"

echo Memeriksa file dependensi GDAL liblz4.dll pada acolite ...
for /f "delims=" %%I in ('"%CONDA_PATH%" run -n acolite python -c "import sys, pathlib; print(pathlib.Path(sys.prefix) / 'Library' / 'bin')"' 2^>nul) do set "ACOLITE_BIN=%%I"
if defined ACOLITE_BIN (
    if not exist "%ACOLITE_BIN%\liblz4.dll" (
        if exist "%ACOLITE_BIN%\lz4.dll" (
            copy "%ACOLITE_BIN%\lz4.dll" "%ACOLITE_BIN%\liblz4.dll" >nul 2>&1
        )
    )
)

echo.
echo [SUKSES] Environment 'mados' dan 'acolite' berhasil disiapkan!
if "%PILIHAN%"=="4" (
    pause
    goto MENU
)
exit /b 0

:INSTALL_ALL
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
