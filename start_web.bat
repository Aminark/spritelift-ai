@echo off
setlocal

cd /d "%~dp0"

for /f "tokens=2 delims== " %%P in ('wmic process where "name='python.exe' and commandline like '%%web_app.py%%'" get ProcessId /value ^| find "="') do (
  echo Stopping existing web_app.py process %%P...
  taskkill /PID %%P /F >nul 2>nul
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment...
  python -m venv .venv
  if errorlevel 1 (
    echo Failed to create .venv. Please install Python 3.10+ and try again.
    pause
    exit /b 1
  )
)

echo Installing or checking dependencies...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo Failed to install dependencies.
  pause
  exit /b 1
)

start "" http://127.0.0.1:7860
".venv\Scripts\python.exe" web_app.py

pause
