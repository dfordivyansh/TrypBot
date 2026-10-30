# Daily backup: database (safe online copy) + media folder. Scheduled by setup.ps1.
$App = "C:\app"
$Dest = "C:\backups"
& "$App\.venv\Scripts\python.exe" "$App\deploy\windows\backup_db.py" "$App\db.sqlite3" "$Dest\db" 4   # 4 days: each copy is ~300 MB and the disk is small
if ($LASTEXITCODE -ne 0) { Write-EventLog -LogName Application -Source convoapi -EventId 2 -EntryType Error -Message "DB backup FAILED" }
robocopy "$App\media" "$Dest\media" /E /NP /NFL /NDL /R:2 /W:5 | Out-Null   # adds/updates, never deletes
