# Deploying to a new EC2 instance (Ubuntu 24.04)

1. Launch EC2 (Ubuntu), open ports 22, 80, 443 in the security group. Attach an Elastic IP
   and point trypdeals.com / www / trypbot.duckdns.org at it.

2. Copy the project (from this PC, in the folder above `src`):
       scp -i key.pem -r src ubuntu@<IP>:/home/ubuntu/app
   Skip `venv`, `.venv`, `db.local.sqlite3` and `*.orig` (zip without them is easiest).
   `db.sqlite3`, `media/` and `.env` MUST be copied — they are the data and the secrets.

3. On the server:
       sudo apt update && sudo apt install -y python3-venv python3-pip nginx sqlite3 certbot python3-certbot-nginx
       cd /home/ubuntu/app
       python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
       .venv/bin/python manage.py migrate --plan      # must say "No planned migration operations"
       .venv/bin/python manage.py collectstatic --noinput
       sudo chown -R ubuntu:www-data /home/ubuntu/app && chmod 750 /home/ubuntu/app && chmod 600 .env
       sudo chmod o+x /home/ubuntu          # lets nginx reach static/media files
       sudo cp deploy/convoapi.service /etc/systemd/system/
       sudo systemctl daemon-reload && sudo systemctl enable --now convoapi
       sudo cp deploy/nginx-convoapi.conf /etc/nginx/sites-available/convoapi
       sudo ln -s /etc/nginx/sites-available/convoapi /etc/nginx/sites-enabled/ && sudo rm -f /etc/nginx/sites-enabled/default
       sudo nginx -t && sudo systemctl reload nginx
       sudo certbot --nginx -d trypdeals.com -d www.trypdeals.com -d trypbot.duckdns.org
       chmod +x deploy/backup_db.sh && (crontab -l; echo "0 3 * * * /home/ubuntu/app/deploy/backup_db.sh") | crontab -

4. Update webhook URLs (WhatsApp / Meta / Google Ads) only if the domain changes.

Notes
- Run ONE daphne process only: the campaign sender runs inside it and SQLite + the
  in-memory channel layer assume a single process.
- Never run `flush`, `migrate --run-syncdb`, or delete db.sqlite3. Logs: `journalctl -u convoapi -f`.
