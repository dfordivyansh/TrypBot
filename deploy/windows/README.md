# Windows Server EC2 deployment

## 1. EC2
- AMI: Windows Server 2022/2025, t3.medium or bigger, 50 GB+ gp3 disk.
- Security group: 80 + 443 from anywhere, 3389 (RDP) from your IP only.
- Attach an Elastic IP. On duckdns.org, set the IP of "trypbot" to this Elastic IP (only on go-live day).
- AWS Console > EC2 > Lifecycle Manager: daily EBS snapshot policy for this volume, keep 7.

## 2. Software on the server (RDP in)
- Python 3.12 (python.org) - "Install for all users" (goes to C:\Program Files\Python312).
- nssm.exe (nssm.cc, win64 build)  -> C:\tools\nssm.exe
- caddy.exe (caddyserver.com/download, Windows amd64) -> C:\tools\caddy.exe

## 3. Copy the project to C:\app
Zip `src` WITHOUT `venv`, `.venv`, `db.local.sqlite3`, `*.orig`, and copy it over RDP.
`db.sqlite3`, `media\` and `.env` must be included.

## 4. Run setup (admin PowerShell)
    powershell -ExecutionPolicy Bypass -File C:\app\deploy\windows\setup.ps1

## 5. Go-live day (no data loss)
1. Stop the app wherever it is currently live (old server / PC).
2. Copy that machine's latest `db.sqlite3` and `media\` to C:\app (overwrite).
3. `Restart-Service convoapi`
4. On duckdns.org change "trypbot" to the new Elastic IP (wait 1-2 min). Webhook URLs stay the same.
   Caddy gets the HTTPS certificate automatically once the domain points here.
5. Check https://trypbot.duckdns.org/crm/ - latest chats must be visible.

## Daily operations
- Status:   `Get-Service convoapi, caddy`
- Restart:  `Restart-Service convoapi`
- Logs:     C:\app\logs\daphne.log, C:\app\logs\caddy.log
- Backups:  C:\backups\db (14 days), C:\backups\media
- Restore:  `Stop-Service convoapi`; copy a backup over C:\app\db.sqlite3; `Start-Service convoapi`
- Code update: `Stop-Service convoapi`; replace code files ONLY (never db.sqlite3/media/.env);
  `.venv\Scripts\pip install -r requirements.txt`; `.venv\Scripts\python manage.py migrate`;
  `.venv\Scripts\python manage.py collectstatic --noinput`; `Start-Service convoapi`

Never run `manage.py flush`, never delete db.sqlite3, and run only ONE live server at a time.
