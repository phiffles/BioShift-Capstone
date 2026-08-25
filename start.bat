@echo off
setlocal
cd /d "%~dp0"

if not exist "%~dp0.venv\Scripts\python.exe" (
    echo BioShift is not installed yet. Run install.bat first.
    exit /b 1
)

echo Starting BioShift...
echo When startup is complete, open http://127.0.0.1:5000
echo Press Ctrl+C to stop the server.
echo.

"%~dp0.venv\Scripts\python.exe" "%~dp0server.py"
exit /b %errorlevel%
