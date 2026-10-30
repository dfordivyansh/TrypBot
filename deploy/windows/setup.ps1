# One-time setup on the Windows EC2. Run in an ADMIN PowerShell:
#   powershell -ExecutionPolicy Bypass -File C:\app\deploy\windows\setup.ps1
# Needs: Python 3.12 (found automatically), nssm.exe at C:\tools\nssm.exe,
#        caddy.exe at C:\tools\caddy.exe, project at C:\app (with db.sqlite3, media, .env).
$ErrorActionPreference = "Stop"
$App = "C:\app"; $Nssm = "C:\tools\nssm.exe"; $Caddy = "C:\tools\caddy.exe"
Set-Location $App
foreach ($f in "db.sqlite3", ".env", $Nssm, $Caddy) { if (-not (Test-Path $f)) { throw "Missing: $f" } }

# 1. Safety copy of the database before anything else
New-Item -ItemType Directory -Force C:\backups, "$App\logs" | Out-Null
Copy-Item db.sqlite3 "C:\backups\db-before-setup-$(Get-Date -Format yyyyMMdd-HHmm).sqlite3"

# 2. Python environment (find Python 3.12 wherever it was installed)
$Python = @(
    "C:\Program Files\Python312\python.exe",
    "C:\Python312\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
    "C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Python -and (Get-Command py -ErrorAction SilentlyContinue)) {
    $Python = (& py -3.12 -c "import sys; print(sys.executable)" 2>$null)
}
if (-not $Python) { throw "Python 3.12 not found. Install it from python.org (tick 'Add to PATH' and 'Install for all users') and run again." }
Write-Host "Using Python: $Python"
if (-not (Test-Path .venv)) { & $Python -m venv .venv }
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python manage.py check
$plan = .\.venv\Scripts\python manage.py migrate --plan | Out-String
if ($plan -notmatch "No planned migration operations") { throw "Unexpected pending migrations - stop and check:`n$plan" }
.\.venv\Scripts\python manage.py collectstatic --noinput

# nssm/sc write normal messages to stderr; don't let PowerShell treat them as fatal
$ErrorActionPreference = "Continue"
function Reset-Service($Name) {
    if (Get-Service $Name -ErrorAction SilentlyContinue) {
        & $Nssm stop $Name 2>&1 | Out-Null
        & $Nssm remove $Name confirm 2>&1 | Out-Null
    }
}
function Set-Svc($Name) { foreach ($a in $args) { & $Nssm set $Name @a 2>&1 | Out-Null } }

# 3. App service (auto start on boot, auto restart on crash)
if (-not [System.Diagnostics.EventLog]::SourceExists("convoapi")) { New-EventLog -LogName Application -Source convoapi }
Reset-Service convoapi
& $Nssm install convoapi "$App\.venv\Scripts\daphne.exe" "-b 127.0.0.1 -p 8000 convoapi.asgi:application" 2>&1 | Out-Null
if (-not (Get-Service convoapi -ErrorAction SilentlyContinue)) { throw "Could not create convoapi service" }
Set-Svc convoapi @("AppDirectory", $App) @("Start", "SERVICE_AUTO_START") @("AppExit", "Default", "Restart") `
    @("AppRestartDelay", "5000") @("AppStdout", "$App\logs\daphne.log") @("AppStderr", "$App\logs\daphne.log") `
    @("AppRotateFiles", "1") @("AppRotateOnline", "1") @("AppRotateBytes", "10485760")
sc.exe failure convoapi reset= 86400 actions= restart/5000/restart/10000/restart/30000 | Out-Null
Start-Service convoapi

# 4. Caddy service (HTTPS reverse proxy)
Reset-Service caddy
& $Nssm install caddy $Caddy "run --config $App\deploy\windows\Caddyfile" 2>&1 | Out-Null
if (-not (Get-Service caddy -ErrorAction SilentlyContinue)) { throw "Could not create caddy service" }
Set-Svc caddy @("AppDirectory", "C:\tools") @("Start", "SERVICE_AUTO_START") @("AppExit", "Default", "Restart") `
    @("AppRestartDelay", "5000") @("AppStdout", "$App\logs\caddy.log") @("AppStderr", "$App\logs\caddy.log") `
    @("AppRotateFiles", "1") @("AppRotateBytes", "10485760")
Start-Service caddy

# 5. Firewall
foreach ($port in 80, 443) {
    if (-not (Get-NetFirewallRule -DisplayName "convoapi $port" -ErrorAction SilentlyContinue)) {
        New-NetFirewallRule -DisplayName "convoapi $port" -Direction Inbound -Protocol TCP -LocalPort $port -Action Allow | Out-Null
    }
}

# 6. Scheduled tasks: watchdog every minute, backup daily 03:00 (both as SYSTEM)
$ps = "powershell.exe"
$wd = New-ScheduledTaskAction -Execute $ps -Argument "-NoProfile -ExecutionPolicy Bypass -File $App\deploy\windows\watchdog.ps1"
$wdT = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) -RepetitionInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName "convoapi-watchdog" -Action $wd -Trigger $wdT -User SYSTEM -RunLevel Highest -Force | Out-Null
$bk = New-ScheduledTaskAction -Execute $ps -Argument "-NoProfile -ExecutionPolicy Bypass -File $App\deploy\windows\backup.ps1"
Register-ScheduledTask -TaskName "convoapi-backup" -Action $bk -Trigger (New-ScheduledTaskTrigger -Daily -At 3am) -User SYSTEM -RunLevel Highest -Force | Out-Null

Start-Sleep 10
Get-Service convoapi, caddy | Format-Table Name, Status, StartType
try { (Invoke-WebRequest http://127.0.0.1:8000/admin/login/ -UseBasicParsing).StatusCode } catch { "App not answering yet - check $App\logs\daphne.log" }
