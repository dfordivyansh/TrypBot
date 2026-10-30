# Run the app on http://127.0.0.1:8000
#   .\run_local.ps1         TEST mode: uses a copy (db.local.sqlite3), WhatsApp campaigns OFF
#   .\run_local.ps1 -Live   LIVE mode: uses the real db.sqlite3, WhatsApp campaigns ON
#                           (only run LIVE on ONE machine at a time - PC or EC2, never both)
# Start with: powershell -ExecutionPolicy Bypass -File .\run_local.ps1 [-Live]
param([switch]$Live)
Set-Location $PSScriptRoot
if (-not (Test-Path .venv)) {
    & "C:\Program Files\Python312\python.exe" -m venv .venv
    .\.venv\Scripts\python -m pip install -r requirements.txt
}
if ($Live) {
    Write-Host "LIVE MODE: real database, campaign messages WILL be sent." -ForegroundColor Yellow
    $env:CAMPAIGN_INLINE_WORKER = "1"
    $env:DJANGO_DEBUG = "True"   # local only; needed so /media/ files show on this PC
} else {
    if (-not (Test-Path db.local.sqlite3)) { Copy-Item db.sqlite3 db.local.sqlite3 }
    $env:DJANGO_DB_PATH = "$PSScriptRoot\db.local.sqlite3"
    $env:CAMPAIGN_INLINE_WORKER = "0"
    $env:DJANGO_DEBUG = "True"
}
.\.venv\Scripts\daphne -b 127.0.0.1 -p 8000 convoapi.asgi:application
