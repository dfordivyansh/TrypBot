# EC2 Ubuntu t3.small Launch & Deployment Guide

Complete step-by-step guide to launch Ubuntu t3.small and deploy TrypBot with optimizations.

## 🚀 Step 1: Launch EC2 Instance

### 1.1 Go to AWS Console
1. Login to AWS Console
2. Go to **EC2** → **Instances** → **Launch Instance**

### 1.2 Configure Instance

**Name & Tags:**
- Name: `trypbot-production`

**Application Image:**
- AMI: **Ubuntu Server 22.04 LTS (HVM)**
- Architecture: `64-bit (x86)`

**Instance Type:**
- **t3.small** (2 vCPU, 2 GB RAM)
- Click "Configure Instance Type" if not selected

**Key Pair:**
- Create new key pair OR use existing
- Name: `trypbot-key`
- Type: RSA
- Format: .pem
- **IMPORTANT**: Download and save key securely

**Network Settings:**
- VPC: Default
- Subnet: Default (any with public IP)
- Auto-assign Public IP: **Enable**
- Firewall (Security Group): Create security group

**Configure Security Group:**
- **Security Group Name**: `trypbot-sg`
- **Inbound Rules**:
  - SSH (Port 22): Source: Your IP (e.g., 203.0.113.0/32)
  - HTTP (Port 80): Source: 0.0.0.0/0
  - HTTPS (Port 443): Source: 0.0.0.0/0
  - Custom TCP (Port 8000): Source: 0.0.0.0/0 (for testing)

**Storage:**
- Volume Type: GP3
- Size: 20 GB (enough for logs + SQLite)
- Delete on termination: No (keep data)

**Launch:**
- Click "Launch Instance"

---

## 🔐 Step 2: Connect to EC2 Instance

### 2.1 Get Instance Public IP
1. Go to EC2 → Instances
2. Select your instance
3. Copy **Public IPv4 address**

### 2.2 Connect via SSH

**On Windows (PowerShell):**
```powershell
# Navigate to your key location
cd C:\Users\dford\.ssh

# Set key permissions (if using Git Bash or WSL)
chmod 400 trypbot-key.pem

# Connect
ssh -i trypbot-key.pem ubuntu@YOUR_PUBLIC_IP
```

**On WSL2 (after key is in Windows):**
```bash
# Access Windows drive
cd /mnt/c/Users/dford/.ssh

# Connect
ssh -i trypbot-key.pem ubuntu@YOUR_PUBLIC_IP
```

**First time:** Type "yes" to accept fingerprint

---

## 📦 Step 3: Initial Server Setup

Once connected to Ubuntu:

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Set timezone (optional)
sudo timedatectl set-timezone Asia/Kolkata

# Install essential packages
sudo apt install python3.11 python3.11-venv python3-pip git nginx redis-server htop net-tools -y

# Verify installations
python3.11 --version
redis-cli ping
nginx -v
```

---

## 📁 Step 4: Setup Project Directory

```bash
# Create app directory
sudo mkdir -p /home/ubuntu/app
sudo chown ubuntu:ubuntu /home/ubuntu/app

# Navigate to app directory
cd /home/ubuntu/app
```

### Upload Code (Choose Method)

**Method A: Git (Recommended)**
```bash
# Clone your repository
git clone YOUR_REPO_URL .
```

**Method B: SCP from Local**
```powershell
# On your local Windows PowerShell
scp -i C:\Users\dford\.ssh\trypbot-key.pem -r C:\Users\dford\Desktop\src ubuntu@YOUR_PUBLIC_IP:/home/ubuntu/app/
```

**Method C: SFTP (FileZilla)**
- Host: YOUR_PUBLIC_IP
- Username: ubuntu
- Private key: trypbot-key.pem
- Port: 22
- Upload files to `/home/ubuntu/app/`

---

## 🐍 Step 5: Setup Python Environment

```bash
cd /home/ubuntu/app

# Create virtual environment
python3.11 -m venv .venv

# Activate virtual environment
source .venv/bin/activate

# Upgrade pip
pip install --upgrade pip

# Install dependencies
pip install -r requirements.txt
```

---

## 🔑 Step 6: Setup Environment Variables

```bash
# Copy example to .env
cp .env.example .env

# Edit .env with your actual values
nano .env
```

**Required variables in .env:**
```bash
DJANGO_SECRET_KEY=your-secret-key-here
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=trypbot.duckdns.org,trypdeals.com,www.trypdeals.com,127.0.0.1,localhost
DEEPSEEK_API_KEY=your-deepseek-key
WHATSAPP_ACCESS_TOKEN=your-whatsapp-token
WHATSAPP_PHONE_NUMBER_ID=your-phone-id
# ... add all other required keys
```

Save with: `Ctrl+X`, then `Y`, then `Enter`

---

## 🗄️ Step 7: Setup Database

```bash
# Run migrations
python manage.py migrate

# Collect static files
python manage.py collectstatic --noinput

# Create superuser (optional)
python manage.py createsuperuser
```

---

## 🔄 Step 8: Setup Redis

```bash
# Redis should already be installed and running
sudo systemctl status redis-server

# If not running, start it
sudo systemctl start redis-server
sudo systemctl enable redis-server

# Test Redis
redis-cli ping  # Should return PONG
```

---

## 🌐 Step 9: Setup Nginx

```bash
# Copy Nginx config
sudo cp deploy/nginx-convoapi.conf /etc/nginx/sites-available/convoapi

# Enable site
sudo ln -s /etc/nginx/sites-available/convoapi /etc/nginx/sites-enabled/

# Remove default site
sudo rm /etc/nginx/sites-enabled/default

# Test Nginx configuration
sudo nginx -t

# Reload Nginx
sudo systemctl reload nginx
```

---

## 🛠️ Step 10: Setup Systemd Service

```bash
# Copy systemd service file
sudo cp deploy/convoapi.service /etc/systemd/system/convoapi.service

# Reload systemd
sudo systemctl daemon-reload

# Start service
sudo systemctl start convoapi

# Enable service (auto-start on boot)
sudo systemctl enable convoapi

# Check status
sudo systemctl status convoapi
```

---

## 🔒 Step 11: Setup SSL Certificate

```bash
# Install Certbot
sudo apt install certbot python3-certbot-nginx -y

# Get SSL certificate
sudo certbot --nginx -d trypbot.duckdns.org -d trypdeals.com -d www.trypdeals.com

# Follow prompts:
# - Enter email
# - Agree to terms
# - Choose option 2 (Redirect HTTP to HTTPS)
```

---

## ✅ Step 12: Verify Deployment

```bash
# Make health check script executable
chmod +x deploy/health_check.sh

# Run health check
bash deploy/health_check.sh
```

**Expected Output:**
- ✅ Daphne service running
- ✅ Redis running
- ✅ Nginx running
- ✅ Application responding
- ✅ 1 worker process detected

---

## 🧪 Step 13: Production Testing

### Test in Browser

1. **Homepage**: `https://trypbot.duckdns.org/`
2. **Admin**: `https://trypbot.duckdns.org/admin/`
3. **CRM**: `https://trypbot.duckdns.org/crm/`

### Test API
```bash
curl https://trypbot.duckdns.org/
```

### Check Logs
```bash
# Application logs
sudo journalctl -u convoapi -f

# Nginx logs
sudo tail -f /var/log/nginx/access.log
sudo tail -f /var/log/nginx/error.log
```

---

## 📊 Step 14: Monitor Resources

```bash
# Check memory and CPU
htop

# Check disk usage
df -h

# Check Redis memory
redis-cli info memory
```

---

## 🔄 Step 15: Update Configuration Files

Make sure these files match your local changes:

**deploy/convoapi.service** should have:
```ini
ExecStart=/home/ubuntu/app/.venv/bin/daphne -b 127.0.0.1 -p 8000 --workers 1 --threads 1 --timeout 300 --max-requests 1000 --max-requests-jitter 100 convoapi.asgi:application
```

**convoapi/settings.py** should have:
- Redis channel layer
- Redis cache
- Security headers
- N+1 query fixes

---

## 🚨 Troubleshooting

### Service won't start
```bash
# Check logs
sudo journalctl -u convoapi -n 100

# Common issues:
# - Redis not running → sudo systemctl start redis-server
# - Port already in use → sudo netstat -tulpn | grep 8000
# - Python error → Check logs for missing dependencies
```

### Redis connection failed
```bash
# Check Redis status
sudo systemctl status redis-server

# Test Redis
redis-cli ping

# Check if Redis is listening
sudo netstat -tulpn | grep 6379
```

### Nginx 502 Bad Gateway
```bash
# Check if Daphne is running
sudo systemctl status convoapi

# Check Nginx error log
sudo tail -f /var/log/nginx/error.log

# Verify port 8000 is accessible
curl http://127.0.0.1:8000/
```

### SSL Certificate Issues
```bash
# Renew certificate
sudo certbot renew

# Force renewal
sudo certbot renew --force-renewal

# Check certificate status
sudo certbot certificates
```

---

## 📋 Deployment Checklist

Before going live:

- [ ] Instance launched (t3.small, Ubuntu 22.04)
- [ ] SSH connection working
- [ ] Python 3.11 installed
- [ ] Virtual environment created
- [ ] Dependencies installed
- [ ] Environment variables configured
- [ ] Database migrations completed
- [ ] Static files collected
- [ ] Redis running and responding
- [ ] Nginx configured and running
- [ ] Systemd service created and running
- [ ] SSL certificate installed
- [ ] Health check passes
- [ ] Homepage loads in browser
- [ ] Admin panel accessible
- [ ] No errors in logs
- [ ] Memory usage < 80%
- [ ] CPU usage < 70%

---

## 💰 Cost Verification

Check your AWS billing dashboard to ensure:
- Instance: t3.small
- Cost: ~$0.0216/hour
- Monthly estimate: ~$15.72
- Within $200 budget for 6 months ($93.31 total)

---

## 🎯 Next Steps After Deployment

1. **Monitor for 24-48 hours**
2. **Check performance metrics**
3. **Verify WhatsApp integration**
4. **Test CRM functionality**
5. **Monitor resource usage**
6. **Set up alerts** (optional)

---

## 🔄 Update Code in Future

```bash
# SSH into server
ssh -i trypbot-key.pem ubuntu@YOUR_PUBLIC_IP

# Navigate to app
cd /home/ubuntu/app

# Activate venv
source .venv/bin/activate

# Pull latest code (if using git)
git pull

# Or upload new files (scp)

# Install new dependencies
pip install -r requirements.txt

# Run migrations
python manage.py migrate

# Collect static files
python manage.py collectstatic --noinput

# Restart service
sudo systemctl restart convoapi
```

---

## 📞 Support

If issues occur:
1. Check logs: `sudo journalctl -u convoapi -n 100`
2. Run health check: `bash deploy/health_check.sh`
3. Review troubleshooting section above
4. Check AWS EC2 console for instance status

---

**Deployment Complete!** 🎉

Your TrypBot is now running on Ubuntu t3.small with all optimizations applied.
