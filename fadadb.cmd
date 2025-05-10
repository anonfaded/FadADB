@echo off
REM Add FadADB install directory to user PATH if not already present, then launch the app
set SCRIPT_DIR=%~dp0
setx PATH "%PATH%;%SCRIPT_DIR%" >nul 2>&1
start "" "%SCRIPT_DIR%FadADB.exe" --gui
