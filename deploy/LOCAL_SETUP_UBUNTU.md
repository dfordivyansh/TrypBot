# Local Ubuntu Setup Guide for TrypBot Testing

Complete guide to set up Ubuntu environment locally on Windows for testing before EC2 deployment.

## Option 1: WSL2 (Recommended) 🌟

**Why WSL2?**
- Runs Ubuntu directly on Windows
- Fast, lightweight, easy setup
- Perfect for Django development
- Uses Windows disk storage (easy file access)

### Step 1: Install WSL2 Ubuntu

```powershell
# Run in PowerShell as Administrator
wsl --install
```

This will:
- Enable WSL2
- Install Ubuntu (latest version)
- Restart your computer

### Step 2: Complete Ubuntu Setup

After restart, Ubuntu will open automatically. Then:

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Python 3.11
sudo apt install python3.11 python3.11-venv python3-pip git -y

# Install Redis
sudo apt install redis-server -y
sudo systemctl start redis-server
sudo systemctl enable redis-server

# Install Nginx (optional for local testing)
sudo apt install nginx -y
sudo systemctl start nginx
sudo systemctl enable nginx

# Verify installations
python3.11 --version
redis-cli ping
```

### Step 3: Setup Project

```bash
# Navigate to your project (Windows path accessible in WSL2)
cd /mnt/c/Users/dford/Desktop/src

# Create virtual environment
python3.11 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Setup environment
cp .env.example .env
nano .env  # Add your actual values
```

### Step 4: Run Migrations

```bash
python manage.py migrate
python manage.py collectstatic --noinput
```

### Step 5: Run Daphne Locally

```bash
# With 1 worker (t3.small config)
daphne -b 127.0.0.1 -p 8000 --workers 1 --threads 1 convoapi.asgi:application
```

### Step 6: Test Locally

Open browser: `http://localhost:8000/`

---

## Option 2: Docker (Alternative) 🐳

**Why Docker?**
- Complete isolation
- Reproducible environment
- Easy to match production

### Step 1: Install Docker Desktop

Download from: https://www.docker.com/products/docker-desktop/

Install with WSL2 backend enabled.

### Step 2: Create Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    make \
    libpq-dev \
    redis-server \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project
COPY . .

# Collect static
RUN python manage.py collectstatic --noinput

# Expose port
EXPOSE 8000

# Run Daphne
CMD ["daphne", "-b", "0.0.0.0", "-p", "8000", "--workers", "1", "--threads", "1", "convoapi.asgi:application"]
```

### Step 3: Create docker-compose.yml

```yaml
version: '3.8'

services:
  db:
    image: redis:alpine
    ports:
      - "6379:6379"

  web:
    build: .
    command: daphne -b 0.0.0.0 -p 8000 --workers 1 --threads 1 convoapi.asgi:application
    volumes:
      - .:/app
    ports:
      - "8000:8000"
    depends_on:
      - db
    environment:
      - DJANGO_SETTINGS_MODULE=convoapi.settings
```

### Step 4: Run Docker

```bash
docker-compose up --build
```

---

## Option 3: Virtual Machine (Alternative) 💻

**Why VM?**
- Complete Ubuntu isolation
- More like production environment

### Step 1: Install VirtualBox

Download from: https://www.virtualbox.org/

### Step 2: Download Ubuntu Server ISO

Download from: https://ubuntu.com/download/server

### Step 3: Create VM

1. Create new VM in VirtualBox
2. Mount Ubuntu ISO
3. Install Ubuntu Server
4. Install Guest Additions for shared folders

### Step 4: Setup Ubuntu (Same as WSL2 steps)

Follow the same steps as Option 1 above.

---

## 🧪 Local Testing Checklist

### Basic Tests
- [ ] Python environment created
- [ ] Dependencies installed successfully
- [ ] Redis running and responding (`redis-cli ping` returns PONG)
- [ ] Database migrations completed
- [ ] Static files collected
- [ ] Daphne starts without errors

### Application Tests
- [ ] Homepage loads at `http://localhost:8000/`
- [ ] Django admin accessible at `http://localhost:8000/admin/`
- [ ] API endpoint responds
- [ ] No errors in console logs
- [ ] WebSocket endpoint accessible

### Performance Tests
- [ ] Memory usage stable (check with `htop`)
- [ ] CPU usage reasonable (< 70%)
- [ ] Response time < 1s for homepage
- [ ] No memory leaks after 10 minutes

### Redis Tests
- [ ] Redis connects successfully
- [ ] Channel layer working (check logs)
- [ ] Cache backend working (test with cache commands)

---

## 🔧 Common Issues & Solutions

### Issue: WSL2 not found
```bash
# Enable WSL feature in PowerShell (Admin)
dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart
dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart
wsl --set-default-version 2
```

### Issue: Python not found
```bash
# Ensure python3.11 is installed
python3.11 --version

# If not, install:
sudo apt install python3.11 python3.11-venv -y
```

### Issue: Redis not starting
```bash
# Check status
sudo systemctl status redis-server

# Start manually
sudo redis-server

# Check if port is in use
sudo netstat -tulpn | grep 6379
```

### Issue: Port 8000 already in use
```bash
# Find process using port 8000
sudo lsof -i :8000

# Kill the process
sudo kill -9 <PID>
```

### Issue: Module not found
```bash
# Ensure you're in virtual environment
source .venv/bin/activate

# Reinstall dependencies
pip install -r requirements.txt
```

---

## 📊 Monitoring Locally

### Check System Resources
```bash
# Install htop
sudo apt install htop -y
htop
```

### Check Redis
```bash
redis-cli info memory
redis-cli info clients
```

### Check Django
```bash
# Enable Django debug toolbar temporarily
# (See monitoring guide for setup)
```

---

## ✅ Ready for Production?

Once local testing passes:

- [ ] All tests pass
- [ ] No errors in logs
- [ ] Performance acceptable
- [ ] Redis working correctly
- [ ] Application stable for 30+ minutes

Then proceed to EC2 deployment guide.

---

## 🎯 Recommended: WSL2

**I recommend WSL2 for local testing because:**
- Fastest setup
- Uses your Windows files directly
- Easy to switch between Windows and Linux
- No virtualization overhead
- Perfect match for Ubuntu EC2 environment

**Next Step:** Complete local testing, then follow EC2 deployment guide.
