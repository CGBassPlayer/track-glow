# Run ON Windows (a VM is fine), from a checkout, in PowerShell: packaging\build-windows.ps1
# Builds dist\track-glow\, smoke-tests it, and zips it to dist\track-glow-windows.zip.
# Wine can't do this build: Qt needs the system icuuc.dll, which Wine lacks.
$ErrorActionPreference = "Stop"

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "Install uv first: winget install --id=astral-sh.uv  (or https://docs.astral.sh/uv/)"
}

Set-Location (Split-Path -Parent $PSScriptRoot)
uv sync --frozen --extra desktop
uv run pyinstaller packaging/track-glow.spec --noconfirm
if ($LASTEXITCODE -ne 0) { throw "pyinstaller failed" }

$exe = "dist\track-glow\track-glow.exe"
& $exe --version
if ($LASTEXITCODE -ne 0) { throw "--version failed" }

function Test-Health($port) {
    for ($i = 0; $i -lt 30; $i++) {
        try {
            Invoke-WebRequest "http://127.0.0.1:$port/api/health" -UseBasicParsing | Out-Null
            return $true
        } catch { Start-Sleep 1 }
    }
    return $false
}

$env:TRACK_GLOW_CONFIG = Join-Path ([IO.Path]::GetTempPath()) "track-glow-smoke-settings.json"

$p = Start-Process $exe -ArgumentList "--headless", "--port", "18790" -PassThru -WindowStyle Hidden
try { if (-not (Test-Health 18790)) { throw "headless health check failed" } } finally { Stop-Process $p -Force }

# Desktop mode proves Qt was bundled; the launcher binds 127.0.0.1:8780.
$env:QT_QPA_PLATFORM = "offscreen"
$p = Start-Process $exe -PassThru -WindowStyle Hidden
try { if (-not (Test-Health 8780)) { throw "desktop mode failed: is Qt bundled?" } } finally { Stop-Process $p -Force }
Remove-Item Env:QT_QPA_PLATFORM, Env:TRACK_GLOW_CONFIG

Compress-Archive -Path dist\track-glow -DestinationPath dist\track-glow-windows.zip -Force
Write-Host "built: $(Resolve-Path dist\track-glow-windows.zip)"
