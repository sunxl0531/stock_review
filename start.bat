@echo off
cd /d "%~dp0"
if exist "runtime\python.exe" (
  "runtime\python.exe" launcher.py
) else if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" launcher.py
) else (
  echo Python environment not found. Use the portable release or run setup.bat.
)
pause
