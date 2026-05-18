@echo off
REM ============================================================
REM  Chạy WSL Port Forward Setup - tự xin quyền Admin
REM  Chỉ cần double-click file này là xong
REM ============================================================

REM Kiểm tra quyền admin, nếu chưa có thì tự xin
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo Đang xin quyền Administrator...
    powershell -Command "Start-Process cmd -ArgumentList '/c cd /d %~dp0 && \"%~f0\"' -Verb RunAs"
    exit /b
)

REM Chuyển vào thư mục chứa file bat
cd /d "%~dp0"

REM Chạy script PowerShell
powershell -ExecutionPolicy Bypass -File "%~dp0wsl-forward-voicecast.ps1"

pause
