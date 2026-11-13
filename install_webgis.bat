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

:FIND_PYTHON
set "PYTHON_EXE="
set "PYTHON_ARGS="

REM 1. Cek folder instalasi langsung (AppData / Program Files)
for %%P in (
    "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
    "C:\Program Files\Python310\python.exe"
    "C:\Python310\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    "C:\Program Files\Python311\python.exe"
    "C:\Python311\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    "C:\Program Files\Python312\python.exe"
    "C:\Python312\python.exe"
    "%USERPROFILE%\anaconda3\python.exe"
    "%USERPROFILE%\miniconda3\python.exe"
    "C:\anaconda3\python.exe"
    "C:\miniconda3\python.exe"
    "C:\ProgramData\anaconda3\python.exe"
    "C:\ProgramData\miniconda3\python.exe"
) do (
    if not defined PYTHON_EXE (
        if exist %%P (
            set "PYTHON_EXE=%%~P"
            set "PYTHON_ARGS="
            exit /b 0
        )
    )
)

REM 2. Cek Python Launcher (py)
py -3.10 --version >nul 2>&1
if not errorlevel 1 (
    set "PYTHON_EXE=py"
    set "PYTHON_ARGS=-3.10"
    exit /b 0
)

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
    set "PYTHON_ARGS="
    exit /b 0
)

REM 3. Cek python di PATH
python --version >nul 2>&1
if not errorlevel 1 (
    set "PYTHON_EXE=python"
    set "PYTHON_ARGS="
    exit /b 0
)

exit /b 0

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
    echo Mencari instalasi Python di sistem ...
    call :FIND_PYTHON

    if not defined PYTHON_EXE (
        echo.
        echo ======================================================================
        echo [INFORMASI] Python belum terdeteksi di komputer ini.
        echo ======================================================================
        echo WebGIS membutuhkan Python versi 64-bit untuk dapat berjalan.
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
        echo Mengunduh installer resmi Python 3.10 ...
        curl.exe -L -o "!CLEAN_TEMP!\python-3.10.11-amd64.exe" "https://www.python.org/ftp/python/3.10.11/python-3.10.11-amd64.exe"
        if errorlevel 1 (
            echo [ERROR] Gagal mengunduh installer Python. Periksa koneksi internet Anda.
            pause
            goto MENU
        )

        echo Memasang Python 3.10 ke sistem...
        echo (Jendela pemasangan Python akan muncul, mohon tunggu hingga selesai...)
        start /wait "" "!CLEAN_TEMP!\python-3.10.11-amd64.exe" /passive PrependPath=1 Include_pip=1 SimpleInstall=1
        del "!CLEAN_TEMP!\python-3.10.11-amd64.exe" >nul 2>&1

        call :FIND_PYTHON
        if not defined PYTHON_EXE (
            if exist "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" (
                set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
                set "PYTHON_ARGS="
            )
            if exist "C:\Program Files\Python310\python.exe" (
                set "PYTHON_EXE=C:\Program Files\Python310\python.exe"
                set "PYTHON_ARGS="
            )
        )
        if not defined PYTHON_EXE (
            echo.
            echo [PERINGATAN] Instalasi Python telah selesai.
            echo Silakan tutup jendela ini dan jalankan kembali install_webgis.bat
            echo agar Windows dapat memperbarui jalur PATH sistem yang baru.
            pause
            goto MENU
        )
        echo [SUKSES] Python 3.10 berhasil dipasang!
    )

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
) else (
    echo Virtual environment [.venv] sudah ada. Melanjutkan pemeriksaan dependensi...
)

echo.
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
    echo.
    echo ======================================================================
    echo [INFORMASI] Conda [Miniconda / Anaconda] belum terpasang di komputer ini.
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
    echo Mengunduh installer resmi Miniconda (sekitar 150 MB)...
    curl.exe -L -o "!CLEAN_TEMP!\miniconda_installer.exe" "https://repo.anaconda.com/miniconda/Miniconda3-latest-Windows-x86_64.exe"
    if errorlevel 1 (
        echo [ERROR] Gagal mengunduh installer Miniconda. Periksa koneksi internet Anda.
        pause
        goto MENU
    )

    echo Memasang Miniconda ke %USERPROFILE%\miniconda3 ...
    echo (Mohon tunggu beberapa menit hingga proses pemasangan selesai...)
    start /wait "" "!CLEAN_TEMP!\miniconda_installer.exe" /InstallationType=JustMe /RegisterPython=0 /S /D=%USERPROFILE%\miniconda3
    del "!CLEAN_TEMP!\miniconda_installer.exe" >nul 2>&1

    call :FIND_CONDA
    if not defined CONDA_PATH (
        echo.
        echo [PERINGATAN] Instalasi Miniconda telah selesai.
        echo Silakan tutup jendela ini dan jalankan kembali install_webgis.bat.
        pause
        goto MENU
    )
    echo [SUKSES] Miniconda berhasil dipasang!
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
    echo.
    echo ======================================================================
    echo [INFORMASI] Conda [Miniconda / Anaconda] belum terpasang di komputer ini.
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
    echo Mengunduh installer resmi Miniconda (sekitar 150 MB)...
    curl.exe -L -o "!CLEAN_TEMP!\miniconda_installer.exe" "https://repo.anaconda.com/miniconda/Miniconda3-latest-Windows-x86_64.exe"
    if errorlevel 1 (
        echo [ERROR] Gagal mengunduh installer Miniconda. Periksa koneksi internet Anda.
        pause
        goto MENU
    )

    echo Memasang Miniconda ke %USERPROFILE%\miniconda3 ...
    echo (Mohon tunggu beberapa menit hingga proses pemasangan selesai...)
    start /wait "" "!CLEAN_TEMP!\miniconda_installer.exe" /InstallationType=JustMe /RegisterPython=0 /S /D=%USERPROFILE%\miniconda3
    del "!CLEAN_TEMP!\miniconda_installer.exe" >nul 2>&1

    call :FIND_CONDA
    if not defined CONDA_PATH (
        echo.
        echo [PERINGATAN] Instalasi Miniconda telah selesai.
        echo Silakan tutup jendela ini dan jalankan kembali install_webgis.bat.
        pause
        goto MENU
    )
    echo [SUKSES] Miniconda berhasil dipasang!
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
