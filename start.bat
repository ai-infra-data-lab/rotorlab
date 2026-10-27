@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Please run setup.ps1 first. See README.md.
  pause
  exit /b 1
)
set OPENBLAS_NUM_THREADS=1
set OMP_NUM_THREADS=1
".venv\Scripts\python.exe" server.py
if errorlevel 1 pause
