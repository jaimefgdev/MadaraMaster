# build.ps1 — MadaraMaster release builder (Windows)
# ─────────────────────────────────────────────────────────────────────────────
# Run from the project root in a normal (non-elevated) PowerShell session:
#
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#   .\build.ps1
#
# What it does:
#   1. Creates (or reuses) a virtual environment in .venv\
#   2. Installs the package with its build extra (PyInstaller)
#   3. Runs PyInstaller with MadaraMaster.spec
#   4. Smoke-tests the executable and copies it to the project root
#
# Output: MadaraMaster.exe in the project root
# ─────────────────────────────────────────────────────────────────────────────

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ProjectRoot = $PSScriptRoot
$VenvDir     = Join-Path $ProjectRoot '.venv'
$Python      = 'python'          # must be Python 3.10+ on PATH
$DistExe     = Join-Path $ProjectRoot 'dist\MadaraMaster.exe'
$ReleaseExe  = Join-Path $ProjectRoot 'MadaraMaster.exe'

function Invoke-Checked {
    param([string]$Exe, [string[]]$Arguments)
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Command failed ($LASTEXITCODE): $Exe $Arguments" }
}

Write-Host ''
Write-Host '══════════════════════════════════════════════════════' -ForegroundColor Cyan
Write-Host '  MadaraMaster — Release Builder' -ForegroundColor Cyan
Write-Host '══════════════════════════════════════════════════════' -ForegroundColor Cyan
Write-Host ''

# ── 1. Virtual environment ─────────────────────────────────────────────────
if (-Not (Test-Path $VenvDir)) {
    Write-Host '[1/4] Creating virtual environment...' -ForegroundColor Yellow
    Invoke-Checked $Python @('-m', 'venv', $VenvDir)
} else {
    Write-Host '[1/4] Virtual environment already exists, reusing.' -ForegroundColor Green
}

$PyExe = Join-Path $VenvDir 'Scripts\python.exe'

# ── 2. Dependencies ───────────────────────────────────────────────────────
Write-Host '[2/4] Installing the package and PyInstaller...' -ForegroundColor Yellow
Invoke-Checked $PyExe @('-m', 'pip', 'install', '--upgrade', 'pip', '--quiet')
Invoke-Checked $PyExe @('-m', 'pip', 'install', "$ProjectRoot[build]", '--quiet')

# ── 3. PyInstaller ────────────────────────────────────────────────────────
Write-Host '[3/4] Running PyInstaller...' -ForegroundColor Yellow
Set-Location $ProjectRoot
Invoke-Checked $PyExe @('-m', 'PyInstaller', 'MadaraMaster.spec', '--clean', '--noconfirm')

if (-Not (Test-Path $DistExe)) {
    Write-Host ''
    Write-Host '  ERROR: Build failed — dist\MadaraMaster.exe not found.' -ForegroundColor Red
    exit 1
}

# ── 4. Smoke test + copy to project root ───────────────────────────────────
Write-Host '[4/4] Smoke-testing and copying the executable...' -ForegroundColor Yellow
Invoke-Checked $DistExe @('version')
Copy-Item $DistExe $ReleaseExe -Force

$Version = & $PyExe -c 'import madaramaster; print(madaramaster.__version__)'
$SizeKB  = [math]::Round((Get-Item $ReleaseExe).Length / 1KB)
Write-Host ''
Write-Host '══════════════════════════════════════════════════════' -ForegroundColor Green
Write-Host "  BUILD SUCCESSFUL — v$Version" -ForegroundColor Green
Write-Host "  Output : $ReleaseExe" -ForegroundColor Green
Write-Host "  Size   : $SizeKB KB" -ForegroundColor Green
Write-Host '══════════════════════════════════════════════════════' -ForegroundColor Green
Write-Host ''
Write-Host '  Next steps:'
Write-Host '    1. Test: .\MadaraMaster.exe --help'
Write-Host "    2. Tag : git tag v$Version && git push origin v$Version"
Write-Host '    3. Upload MadaraMaster.exe to the GitHub Release'
Write-Host ''
