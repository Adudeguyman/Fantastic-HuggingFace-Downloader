@echo off
setlocal EnableExtensions
title Fantastic HuggingFace Downloader installer

set "APPNAME=Fantastic HuggingFace Downloader"
set "HERE=%~dp0"
set "VENV=%~dp0venv"
set "APPPY=%~dp0fantastic_huggingface_downloader.py"
set "MENUDIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs"

echo ============================================================
echo  %APPNAME% - installer
echo ============================================================
echo.
echo Everything is installed INSIDE this folder:
echo    %HERE%
echo The virtual environment goes in .\venv, roughly 1 GB once
echo PySide6 is in. To remove it all, delete this folder.
echo.
echo Only a Start Menu or desktop shortcut can land outside it,
echo and each is asked about separately.
echo.

if not exist "%APPPY%" goto nosrc
if not exist "%~dp0theme.py" goto notheme

rem ---- update from git first, so a new install.bat is the one that runs ---
if defined FHD_PULLED goto skipgit
if not exist "%~dp0.git" goto skipgit
where git >nul 2>&1
if errorlevel 1 goto skipgit
for /f %%i in ('git -C "%~dp0." status --porcelain 2^>nul') do goto dirtytree
set "PULLANS="
set /p PULLANS=Check for updates first (git pull)? [Y/n] 
if /i "%PULLANS%"=="n" goto skipgit
for /f %%i in ('git -C "%~dp0." rev-parse HEAD 2^>nul') do set "BEFORE=%%i"
git -C "%~dp0." pull --ff-only
if errorlevel 1 (
    echo Could not pull. Carrying on with the version you have.
    goto skipgit
)
for /f %%i in ('git -C "%~dp0." rev-parse HEAD 2^>nul') do set "AFTER=%%i"
if not "%BEFORE%"=="%AFTER%" (
    echo.
    echo Updated. Restarting the installer with the new version...
    set "FHD_PULLED=1"
    call "%~dp0install.bat"
    exit /b %ERRORLEVEL%
)
echo Already up to date.
goto skipgit
:dirtytree
echo You have local changes here, so skipping the update check.
echo Run "git pull" yourself when you are ready.
:skipgit
echo.

rem ---- locate a usable Python -------------------------------------------
set "PY="
py -3 --version >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if not defined PY (
    python --version >nul 2>&1
    if not errorlevel 1 set "PY=python"
)
if not defined PY goto nopython
echo Using Python: %PY%

rem ---- virtual environment ----------------------------------------------
if exist "%VENV%\Scripts\python.exe" goto haveenv
echo Creating .\venv ...
%PY% -m venv "%VENV%"
if errorlevel 1 goto venvfail
:haveenv

rem ---- only touch pip when requirements.txt actually changed -------------
set "REQ=%~dp0requirements.txt"
if not exist "%REQ%" goto noreq
set "STAMP=%VENV%\.installed-requirements"
set "WANT="
for /f "skip=1 tokens=* delims=" %%h in ('certutil -hashfile "%REQ%" SHA256') do if not defined WANT set "WANT=%%h"
set "HAVE="
if exist "%STAMP%" set /p HAVE=<"%STAMP%"
if "%WANT%"=="%HAVE%" (
    "%VENV%\Scripts\python.exe" -c "import PySide6, huggingface_hub" >nul 2>&1
    if not errorlevel 1 (
        echo Dependencies are already up to date - nothing to install.
        goto depsdone
    )
)
echo Installing dependencies (a few hundred MB the first time, please wait)...
"%VENV%\Scripts\python.exe" -m pip install --upgrade pip >nul
"%VENV%\Scripts\python.exe" -m pip install --upgrade -r "%REQ%"
if errorlevel 1 goto pipfail
> "%STAMP%" echo %WANT%
echo Dependencies installed.
:depsdone

echo.
echo Installed. Everything lives in %HERE%
echo   start it:   run.bat in this folder
echo   update it:  run install.bat again. If this is a git clone it pulls
echo               the latest version; either way it only reinstalls
echo               dependencies if they actually changed.
echo   remove it:  delete this folder
echo.

rem ---- optional shortcuts, both off unless you say yes -------------------
set "MENUANS="
set /p MENUANS=Show it in your Start Menu, so you can launch it like any other app? [y/N] 
if /i not "%MENUANS%"=="y" goto skipmenu
call :makeshortcut "%MENUDIR%\%APPNAME%.lnk"
if errorlevel 1 (echo Could not create the Start Menu shortcut.) else (echo Start Menu shortcut created.)
:skipmenu

set "DESKANS="
set /p DESKANS=Also put an icon on your desktop? [y/N] 
if /i not "%DESKANS%"=="y" goto skipdesk
call :makeshortcut "%USERPROFILE%\Desktop\%APPNAME%.lnk"
if errorlevel 1 (echo Could not create the desktop shortcut.) else (echo Desktop shortcut created.)
:skipdesk

set "RUNANS="
set /p RUNANS=Start it now? [y/N] 
if /i not "%RUNANS%"=="y" goto done
call "%~dp0run.bat"

:done
echo.
echo Finished. Shortcuts point back at this folder, so moving it breaks them.
pause
exit /b 0

rem ---- helper: build a .lnk via a temp PowerShell script -----------------
rem Batch-to-PowerShell quoting is fragile, so the script goes to a file.
:makeshortcut
set "PS1=%TEMP%\fhd_shortcut_%RANDOM%.ps1"
> "%PS1%" echo $ErrorActionPreference = 'Stop'
>>"%PS1%" echo $shell = New-Object -ComObject WScript.Shell
>>"%PS1%" echo $lnk = $shell.CreateShortcut($env:FHD_LNK)
>>"%PS1%" echo $lnk.TargetPath = $env:FHD_TARGET
>>"%PS1%" echo $lnk.Arguments = '"' + $env:FHD_SCRIPT + '"'
>>"%PS1%" echo $lnk.WorkingDirectory = $env:FHD_PREFIX
>>"%PS1%" echo $lnk.Description = 'Paste a Hugging Face link and download the file'
>>"%PS1%" echo $lnk.Save()
set "FHD_LNK=%~1"
set "FHD_TARGET=%VENV%\Scripts\pythonw.exe"
set "FHD_SCRIPT=%APPPY%"
set "FHD_PREFIX=%HERE%"
powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%" >nul 2>&1
set "RC=%ERRORLEVEL%"
del "%PS1%" >nul 2>&1
exit /b %RC%

rem ---- failure paths -----------------------------------------------------
:nosrc
echo ERROR: fantastic_huggingface_downloader.py is not next to this installer.
echo Clone the whole repository and run install.bat from inside that folder.
pause
exit /b 1

:noreq
echo ERROR: requirements.txt is missing from %~dp0
pause
exit /b 1

:notheme
echo ERROR: theme.py is missing from %~dp0
echo The app imports it for its look. Clone the whole repository.
pause
exit /b 1

:nopython
echo ERROR: No Python found.
echo Install Python 3.9 or newer from https://www.python.org/downloads/
echo and tick "Add python.exe to PATH" during setup, then run this again.
pause
exit /b 1

:venvfail
echo ERROR: Could not create a virtual environment in %VENV%.
echo If this folder is inside Program Files or another protected location,
echo move it somewhere you own, such as your Desktop, and try again.
pause
exit /b 1

:pipfail
echo ERROR: Installing the dependencies failed. Scroll up for pip's output.
pause
exit /b 1
