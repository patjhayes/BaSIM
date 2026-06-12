param(
  [switch]$Recreate,
  [switch]$Dev,
  [string]$PythonExecutable = 'python'
)

$ErrorActionPreference = 'Stop'
Write-Host "[build_env] Starting environment bootstrap" -ForegroundColor Cyan

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$proj = Split-Path -Parent $root
$envDir = Join-Path $proj '.build_env'

if ($Recreate -and (Test-Path $envDir)) {
  Write-Host "[build_env] Removing existing env $envDir" -ForegroundColor Yellow
  Remove-Item -Recurse -Force $envDir
}

if (-not (Test-Path $envDir)) {
  Write-Host "[build_env] Creating venv" -ForegroundColor Cyan
  & $PythonExecutable -m venv $envDir
}

$py = Join-Path $envDir 'Scripts/python.exe'
if (-not (Test-Path $py)) { throw "Virtual environment python missing at $py" }

Write-Host "[build_env] Upgrading pip/setuptools/wheel" -ForegroundColor DarkGray
& $py -m pip install --upgrade pip setuptools wheel | Out-Null

$reqIn = Join-Path $proj 'requirements.in'
if (-not (Test-Path $reqIn)) { throw "requirements.in not found" }

$reqToInstall = @($reqIn)
if ($Dev) {
  $reqDevIn = Join-Path $proj 'requirements-dev.in'
  if (-not (Test-Path $reqDevIn)) { throw "requirements-dev.in not found (Dev mode requested)" }
  $reqToInstall = @($reqDevIn)
}

foreach ($f in $reqToInstall) {
  Write-Host "[build_env] Installing spec: $([IO.Path]::GetFileName($f))" -ForegroundColor Cyan
  & $py -m pip install -r $f
}

Write-Host "[build_env] Freezing pinned versions -> requirements.txt" -ForegroundColor Cyan
$lockFile = Join-Path $proj 'requirements.txt'
& $py -m pip freeze --exclude-editable | Sort-Object | Out-File -Encoding UTF8 $lockFile
Write-Host "[build_env] Lock file updated." -ForegroundColor Green

Write-Host "[build_env] Done." -ForegroundColor Green
