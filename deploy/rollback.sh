#!/bin/bash
# TrypBot Rollback Script
# Usage: sudo bash deploy/rollback.sh /path/to/backup/directory

set -e

BACKUP_DIR=$1

if [ -z "$BACKUP_DIR" ]; then
    echo "Usage: sudo bash deploy/rollback.sh /path/to/backup/directory"
    echo ""
    echo "Available backups:"
    ls -la /home/ubuntu/backups/ 2>/dev/null || echo "No backups found"
    exit 1
fi

if [ ! -d "$BACKUP_DIR" ]; then
    echo "Error: Backup directory not found: $BACKUP_DIR"
    exit 1
fi

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

echo "=========================================="
echo "TrypBot Rollback Script"
echo "=========================================="
echo ""
echo "Rolling back from: $BACKUP_DIR"
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    print_warning "This script should be run with sudo privileges"
    echo "Please run: sudo bash deploy/rollback.sh $BACKUP_DIR"
    exit 1
fi

# Stop the application
echo "Step 1: Stopping application..."
systemctl stop convoapi
print_success "Application stopped"

# Restore systemd service
if [ -f "$BACKUP_DIR/convoapi.service" ]; then
    echo "Step 2: Restoring systemd service..."
    cp "$BACKUP_DIR/convoapi.service" /etc/systemd/system/convoapi.service
    systemctl daemon-reload
    print_success "Systemd service restored"
else
    print_warning "No systemd service backup found, skipping..."
fi

# Restore Nginx configuration
if [ -f "$BACKUP_DIR/convoapi" ]; then
    echo "Step 3: Restoring Nginx configuration..."
    cp "$BACKUP_DIR/convoapi" /etc/nginx/sites-available/convoapi
    nginx -t
    if [ $? -eq 0 ]; then
        systemctl reload nginx
        print_success "Nginx configuration restored"
    else
        print_error "Nginx configuration test failed"
        exit 1
    fi
else
    print_warning "No Nginx config backup found, skipping..."
fi

# Restore settings.py
if [ -f "$BACKUP_DIR/settings.py" ]; then
    echo "Step 4: Restoring settings.py..."
    cp "$BACKUP_DIR/settings.py" convoapi/settings.py
    print_success "settings.py restored"
else
    print_warning "No settings.py backup found, skipping..."
fi

# Rollback database migrations (optional - requires manual confirmation)
echo ""
echo "Step 5: Database migrations"
echo "WARNING: Rolling back migrations may cause data loss."
read -p "Do you want to rollback migrations? (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    python manage.py migrate convoapi 0016
    print_success "Migrations rolled back to 0016"
else
    print_warning "Skipping migration rollback"
fi

# Restart the application
echo ""
echo "Step 6: Restarting application..."
systemctl start convoapi
sleep 5

# Check service status
if systemctl is-active --quiet convoapi; then
    print_success "Application restarted successfully"
else
    print_error "Application failed to start. Checking logs..."
    journalctl -u convoapi -n 50 --no-pager
    exit 1
fi

echo ""
echo "=========================================="
echo "Rollback Summary"
echo "=========================================="
echo ""
print_success "Rollback completed successfully!"
echo ""
echo "To monitor logs: sudo journalctl -u convoapi -f"
echo ""
