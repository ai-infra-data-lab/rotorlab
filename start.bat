@echo off
pushd "%~dp0"
if errorlevel 1 exit /b 1
if not exist ".venv\Scripts\python.exe" (
  echo Please run setup.ps1 first. See README.md.
  pause
  popd
  exit /b 1
)
set OPENBLAS_NUM_THREADS=1
set OMP_NUM_THREADS=1
".venv\Scripts\python.exe" server.py
if errorlevel 1 pause
popd
