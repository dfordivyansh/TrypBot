#!/bin/bash
# TrypBot Deployment Script
# Run this on the EC2 server to deploy Phase 1 + Phase 2 optimizations

set -e  # Exit on error

echo "=========================================="
echo "TrypBot Deployment Script"
echo "=========================================="
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored output
print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    print_warning "This script should be run with sudo privileges"
    echo "Please run: sudo bash deploy/deploy.sh"
    exit 1
fi

# Check if in the correct directory
if [ ! -f "manage.py" ]; then
    print_error "manage.py not found. Please run this script from the project root."
    exit 1
fi

# Backup current configuration
echo ""
echo "Step 1: Backing up current configuration..."
BACKUP_DIR="/home/ubuntu/backups/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"

if [ -f "/etc/systemd/system/convoapi.service" ]; then
    cp /etc/systemd/system/convoapi.service "$BACKUP_DIR/"
    print_success "Backed up systemd service"
fi

if [ -f "/etc/nginx/sites-available/convoapi" ]; then
    cp /etc/nginx/sites-available/convoapi "$BACKUP_DIR/"
    print_success "Backed up Nginx config"
fi

if [ -f "convoapi/settings.py" ]; then
    cp convoapi/settings.py "$BACKUP_DIR/"
    print_success "Backed up settings.py"
fi

print_success "Backups saved to: $BACKUP_DIR"

# Check if Redis is installed
echo ""
echo "Step 2: Checking Redis installation..."
if ! command -v redis-server &> /dev/null; then
    print_warning "Redis not found. Installing..."
    apt update
    apt install redis-server -y
    print_success "Redis installed"
else
    print_success "Redis already installed"
fi

# Start Redis if not running
if ! systemctl is-active --quiet redis-server; then
    print_warning "Redis not running. Starting..."
    systemctl start redis-server
    systemctl enable redis-server
    print_success "Redis started"
else
    print_success "Redis is running"
fi

# Install/update Python dependencies
echo ""
echo "Step 3: Installing Python dependencies..."
source /home/ubuntu/app/.venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
print_success "Python dependencies installed"

# Run database migrations
echo ""
echo "Step 4: Running database migrations..."
python manage.py migrate
print_success "Database migrations completed"

# Collect static files
echo ""
echo "Step 5: Collecting static files..."
python manage.py collectstatic --noinput
print_success "Static files collected"

# Update systemd service
echo ""
echo "Step 6: Updating systemd service..."
cp deploy/convoapi.service /etc/systemd/system/convoapi.service
systemctl daemon-reload
print_success "Systemd service updated"

# Update Nginx configuration
echo ""
echo "Step 7: Updating Nginx configuration..."
cp deploy/nginx-convoapi.conf /etc/nginx/sites-available/convoapi
nginx -t
if [ $? -eq 0 ]; then
    systemctl reload nginx
    print_success "Nginx configuration updated and reloaded"
else
    print_error "Nginx configuration test failed. Rolling back..."
    cp "$BACKUP_DIR/convoapi" /etc/nginx/sites-available/convoapi
    systemctl reload nginx
    exit 1
fi

# Restart the application
echo ""
echo "Step 8: Restarting application..."
systemctl restart convoapi
sleep 5

# Check service status
if systemctl is-active --quiet convoapi; then
    print_success "Application restarted successfully"
else
    print_error "Application failed to start. Checking logs..."
    journalctl -u convoapi -n 50 --no-pager
    exit 1
fi

# Run health check
echo ""
echo "Step 9: Running health check..."
curl -f http://127.0.0.1:8000/ > /dev/null 2>&1
if [ $? -eq 0 ]; then
    print_success "Application is responding"
else
    print_warning "Application health check failed. May still be starting up..."
fi

# Display status
echo ""
echo "=========================================="
echo "Deployment Summary"
echo "=========================================="
echo ""
echo "Service Status:"
systemctl status convoapi --no-pager -l
echo ""
echo "Redis Status:"
systemctl status redis-server --no-pager -l
echo ""
echo "Backup Location: $BACKUP_DIR"
echo ""
print_success "Deployment completed successfully!"
echo ""
echo "To rollback if needed, run: sudo bash deploy/rollback.sh $BACKUP_DIR"
echo ""
echo "To monitor logs: sudo journalctl -u convoapi -f"
echo ""
