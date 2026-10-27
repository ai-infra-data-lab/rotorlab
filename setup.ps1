param([string]$Python = "python")
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
& $Python -m venv --without-pip .venv
if ($LASTEXITCODE -ne 0) { throw "venv creation failed" }
& $Python -m pip --python .venv/Scripts/python.exe install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed" }
Write-Host "Ready: start.bat"
