@echo off
setlocal EnableExtensions
rem Starts Fantastic HuggingFace Downloader from the venv in this folder.
rem Run install.bat once first. There is no second copy anywhere else.

set "VENV=%~dp0venv"
set "APP=%~dp0fantastic_huggingface_downloader.py"

if exist "%VENV%\Scripts\pythonw.exe" (
    start "" "%VENV%\Scripts\pythonw.exe" "%APP%" %*
    exit /b 0
)

python -c "import PySide6, huggingface_hub" >nul 2>&1
if not errorlevel 1 (
    start "" pythonw "%APP%" %*
    exit /b 0
)

echo Not set up yet - there is no venv folder here.
echo.
echo Run install.bat in this folder first. It only needs doing once,
echo and everything stays in this folder.
pause
exit /b 1
