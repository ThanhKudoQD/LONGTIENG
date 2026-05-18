@echo off
REM ============================================================
REM  DubEditor Launcher (Windows -> WSL)
REM
REM  Cau hinh: sua 3 bien duoi neu khac may
REM ============================================================

setlocal

set CONDA_ENV=flash
set APP_DIR=~/nano
set APP_PORT=8809
set APP_URL=http://localhost:%APP_PORT%/app
set WAIT_SECONDS=8

title DubEditor Launcher

echo.
echo ============================================================
echo  DubEditor Launcher
echo ============================================================
echo  Conda env : %CONDA_ENV%
echo  App dir   : %APP_DIR%
echo  URL       : %APP_URL%
echo ============================================================
echo.

echo [1/3] Khoi dong server trong WSL...
start "DubEditor Server (WSL)" wsl.exe -- bash -ic "source ~/miniconda3/etc/profile.d/conda.sh 2>/dev/null || source ~/anaconda3/etc/profile.d/conda.sh 2>/dev/null; conda activate %CONDA_ENV% && cd %APP_DIR% && python app.py; echo; echo [Server da dung. Bam Enter de dong cua so.]; read"

echo [2/3] Doi server start (%WAIT_SECONDS% giay)...
timeout /t %WAIT_SECONDS% /nobreak >nul

echo [3/3] Mo trinh duyet: %APP_URL%
start "" "%APP_URL%"

echo.
echo Da khoi dong xong. Cua so WSL hien thi log o ben canh.
echo Dong cua so do se TAT server.
echo.
timeout /t 3 /nobreak >nul

endlocal
