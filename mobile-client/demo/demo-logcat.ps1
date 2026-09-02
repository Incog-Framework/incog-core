# Incog mobile-client — demo log stream
# Streams the Sentinel Engine + Ghost State logs live so you can show covert activation
# and sensor/audio/GPS capture on a laptop screen during a demo.
#
# Usage (PowerShell):  .\demo-logcat.ps1
# Stop with Ctrl+C.

$ErrorActionPreference = "Stop"

function Resolve-Adb {
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "Android\Sdk\platform-tools\adb.exe"),
        (Join-Path $env:ANDROID_HOME "platform-tools\adb.exe"),
        (Join-Path $env:ANDROID_SDK_ROOT "platform-tools\adb.exe")
    )
    foreach ($c in $candidates) {
        if ($c -and (Test-Path $c)) { return $c }
    }
    $cmd = Get-Command adb -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    throw "adb not found. Set ANDROID_HOME or add platform-tools to PATH."
}

$adb = Resolve-Adb
Write-Host "Using adb: $adb" -ForegroundColor DarkGray

$connected = & $adb devices | Select-String -Pattern "\tdevice$"
if (-not $connected) {
    Write-Host "No authorized device found." -ForegroundColor Yellow
    Write-Host "  - Plug the phone in with a DATA USB cable" -ForegroundColor Yellow
    Write-Host "  - Unlock the screen and tap 'Allow' on the USB debugging prompt" -ForegroundColor Yellow
    exit 1
}

Write-Host "Device connected. Starting live log (Ctrl+C to stop)..." -ForegroundColor Green
Write-Host "Watch for: 'Ghost State ACTIVATED' then 'snapshot ...' lines with live sensor data." -ForegroundColor Cyan
Write-Host ""

& $adb logcat -c
& $adb logcat -s SentinelEngine:* GhostState:*
