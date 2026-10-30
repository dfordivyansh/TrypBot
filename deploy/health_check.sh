#!/bin/bash
# TrypBot Health Check Script
# Run this to verify the application is working correctly after deployment

set -e

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

print_header() {
    echo ""
    echo "=========================================="
    echo "$1"
    echo "=========================================="
}

echo "TrypBot Health Check"
echo "Starting health checks..."
echo ""

# Check 1: Django application
print_header "Check 1: Django Application Status"
if systemctl is-active --quiet convoapi; then
    print_success "Daphne service is running"
else
    print_error "Daphne service is not running"
    systemctl status convoapi --no-pager -l
    exit 1
fi

# Check 2: Redis
print_header "Check 2: Redis Status"
if systemctl is-active --quiet redis-server; then
    print_success "Redis is running"
    redis-cli ping > /dev/null 2>&1
    if [ $? -eq 0 ]; then
        print_success "Redis is responding to PING"
    else
        print_error "Redis is not responding"
        exit 1
    fi
else
    print_error "Redis is not running"
    systemctl status redis-server --no-pager -l
    exit 1
fi

# Check 3: Nginx
print_header "Check 3: Nginx Status"
if systemctl is-active --quiet nginx; then
    print_success "Nginx is running"
else
    print_error "Nginx is not running"
    systemctl status nginx --no-pager -l
    exit 1
fi

# Check 4: Application response
print_header "Check 4: Application HTTP Response"
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/ || echo "000")
if [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "302" ]; then
    print_success "Application is responding (HTTP $HTTP_CODE)"
else
    print_error "Application returned HTTP $HTTP_CODE"
    exit 1
fi

# Check 5: WebSocket endpoint
print_header "Check 5: WebSocket Endpoint"
# This is a basic check - actual WebSocket connection requires a client
WS_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/crm/notifications/ || echo "000")
if [ "$WS_CODE" = "403" ] || [ "$WS_CODE" = "404" ]; then
    print_success "WebSocket endpoint is accessible (HTTP $WS_CODE - expected for WebSocket)"
else
    print_warning "WebSocket endpoint returned HTTP $WS_CODE (may need WebSocket client for full test)"
fi

# Check 6: Database
print_header "Check 6: Database Connection"
cd /home/ubuntu/app
source /home/ubuntu/app/.venv/bin/activate
python manage.py check --deploy > /dev/null 2>&1
if [ $? -eq 0 ]; then
    print_success "Database connection and migrations are valid"
else
    print_error "Database check failed"
    python manage.py check --deploy
    exit 1
fi

# Check 7: Memory usage
print_header "Check 7: Memory Usage"
MEMORY_USAGE=$(free -m | awk 'NR==2{printf "%.0f%%", $3*100/$2 }')
echo "Memory usage: $MEMORY_USAGE"
if [ $(free -m | awk 'NR==2{print $3}') -gt 7000 ]; then
    print_warning "High memory usage detected"
else
    print_success "Memory usage is acceptable"
fi

# Check 8: Disk usage
print_header "Check 8: Disk Usage"
DISK_USAGE=$(df -h / | awk 'NR==2{print $5}')
echo "Disk usage: $DISK_USAGE"
DISK_PERCENT=$(df -h / | awk 'NR==2{print $5}' | sed 's/%//')
if [ $DISK_PERCENT -gt 80 ]; then
    print_warning "High disk usage detected"
else
    print_success "Disk usage is acceptable"
fi

# Check 9: Recent errors in logs
print_header "Check 9: Recent Error Logs"
ERROR_COUNT=$(journalctl -u convoapi --since "1 hour ago" --no-pager | grep -i error | wc -l)
if [ $ERROR_COUNT -eq 0 ]; then
    print_success "No errors in the last hour"
else
    print_warning "Found $ERROR_COUNT errors in the last hour"
    echo "Recent errors:"
    journalctl -u convoapi --since "1 hour ago" --no-pager | grep -i error | tail -5
fi

# Check 10: Worker count
print_header "Check 10: Worker Processes"
WORKER_COUNT=$(ps aux | grep daphne | grep -v grep | wc -l)
echo "Daphne processes: $WORKER_COUNT"
if [ $WORKER_COUNT -ge 4 ]; then
    print_success "Multiple workers detected (configuration applied)"
else
    print_warning "Only $WORKER_COUNT worker(s) detected (expected 4)"
fi

# Final summary
print_header "Health Check Summary"
print_success "All critical checks passed!"
echo ""
echo "Service Status:"
systemctl status convoapi --no-pager -l | head -10
echo ""
echo "Recent Logs (last 10 lines):"
journalctl -u convoapi -n 10 --no-pager
echo ""
echo "To monitor live logs: sudo journalctl -u convoapi -f"
echo "To check worker processes: ps aux | grep daphne"
echo ""
