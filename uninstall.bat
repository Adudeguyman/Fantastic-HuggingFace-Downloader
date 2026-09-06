@echo off
setlocal EnableExtensions
title Fantastic HuggingFace Downloader uninstaller

set "APPNAME=Fantastic HuggingFace Downloader"
set "VENV=%~dp0venv"
set "MENULNK=%APPDATA%\Microsoft\Windows\Start Menu\Programs\%APPNAME%.lnk"
set "DESKLNK=%USERPROFILE%\Desktop\%APPNAME%.lnk"

echo This will remove:
echo    %VENV%
echo    %~dp0xet-runtime
echo    the Start Menu and desktop shortcuts, if they exist
echo.
echo The app itself and your settings.ini stay in this folder.
echo Downloaded files are never touched.
echo.
set "ANS="
set /p ANS=Continue? [y/N] 
if /i not "%ANS%"=="y" goto canceled

if exist "%VENV%" rmdir /S /Q "%VENV%"
if exist "%~dp0xet-runtime" rmdir /S /Q "%~dp0xet-runtime"
if exist "%MENULNK%" del /Q "%MENULNK%"
if exist "%DESKLNK%" del /Q "%DESKLNK%"

echo.
echo Removed. Delete this folder to get rid of the rest.
pause
exit /b 0

:canceled
echo Canceled.
pause
exit /b 0
