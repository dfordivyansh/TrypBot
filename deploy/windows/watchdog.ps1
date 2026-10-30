# Runs every minute (scheduled task "convoapi-watchdog"). If the app stops
# answering (hung, not just crashed: nssm already restarts crashes), restart
# its service. Two quick tries so a single slow request does not trigger it.
$ok = $false
for ($i = 0; $i -lt 2 -and -not $ok; $i++) {
    try {
        $r = Invoke-WebRequest "http://127.0.0.1:8000/crm/login/" -UseBasicParsing -TimeoutSec 15
        $ok = ($r.StatusCode -eq 200)
    } catch { Start-Sleep 5 }
}
if (-not $ok) {
    Write-EventLog -LogName Application -Source convoapi -EventId 1 -EntryType Warning -Message "convoapi not responding - restarting"
    Restart-Service convoapi -Force
}
