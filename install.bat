@echo off
setlocal
cd /d "%~dp0"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" %*
if errorlevel 1 (
    echo.
    echo BioShift installation failed. Review the message above, then run install.bat again.
    exit /b 1
)

echo.
echo Installation complete. Run start.bat to launch BioShift.
exit /b 0
