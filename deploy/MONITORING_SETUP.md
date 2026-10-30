# TrypBot Monitoring Setup Guide

This guide helps you set up monitoring for your TrypBot deployment to track performance and detect issues early.

## 1. Basic System Monitoring (Already Available)

### Check Service Status
```bash
# Check Daphne service
sudo systemctl status convoapi

# Check Redis
sudo systemctl status redis-server

# Check Nginx
sudo systemctl status nginx
```

### View Logs
```bash
# Real-time logs
sudo journalctl -u convoapi -f

# Last 100 lines
sudo journalctl -u convoapi -n 100

# Logs from last hour
sudo journalctl -u convoapi --since "1 hour ago"

# Logs with errors only
sudo journalctl -u convoapi -p err
```

### System Resources
```bash
# CPU and Memory
htop
# or
top

# Disk usage
df -h

# Memory usage
free -h

# Network connections
netstat -tulpn
```

## 2. Advanced Monitoring (Recommended)

### Install htop for Better Resource Monitoring
```bash
sudo apt install htop -y
```

### Install net-tools for Network Monitoring
```bash
sudo apt install net-tools -y
```

### Install iotop for Disk I/O Monitoring
```bash
sudo apt install iotop -y
sudo iotop
```

## 3. Django Debug Toolbar (Development Only)

Add to `convoapi/settings.py` in DEBUG mode:

```python
if DEBUG:
    INSTALLED_APPS += ['debug_toolbar']
    MIDDLEWARE += ['debug_toolbar.middleware.DebugToolbarMiddleware']
    INTERNAL_IPS = ['127.0.0.1']
```

## 4. Simple Performance Logging

Create `chatbot/middleware.py`:

```python
import time
import logging

logger = logging.getLogger(__name__)

class PerformanceLoggingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        start_time = time.time()
        response = self.get_response(request)
        duration = time.time() - start_time
        
        if duration > 1.0:  # Log slow requests (> 1 second)
            logger.warning(f"Slow request: {request.path} took {duration:.2f}s")
        
        return response
```

Add to `convoapi/settings.py` MIDDLEWARE:
```python
'chatbot.middleware.PerformanceLoggingMiddleware',
```

## 5. Redis Monitoring

```bash
# Redis info
redis-cli info

# Redis memory usage
redis-cli info memory

# Redis connected clients
redis-cli info clients

# Redis slow log
redis-cli slowlog get 10
```

## 6. Database Monitoring

```bash
# SQLite database size
ls -lh db.sqlite3

# Check for database locks (SQLite)
# Monitor for "database is locked" errors in logs
sudo journalctl -u convoapi | grep -i "database is locked"
```

## 7. Log Rotation (Prevent Disk Full)

Create `/etc/logrotate.d/convoapi`:

```
/var/log/convoapi/*.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    create 0640 ubuntu ubuntu
}
```

## 8. Custom Monitoring Script

Create `monitor.sh`:

```bash
#!/bin/bash
# Simple monitoring script - run every 5 minutes via cron

# Check if services are running
if ! systemctl is-active --quiet convoapi; then
    echo "ALERT: convoapi is down!" | mail -s "TrypBot Down" admin@trypdeals.com
    systemctl restart convoapi
fi

if ! systemctl is-active --quiet redis-server; then
    echo "ALERT: Redis is down!" | mail -s "Redis Down" admin@trypdeals.com
    systemctl restart redis-server
fi

# Check disk space
DISK_USAGE=$(df / | awk 'NR==2{print $5}' | sed 's/%//')
if [ $DISK_USAGE -gt 80 ]; then
    echo "ALERT: Disk usage is ${DISK_USAGE}%" | mail -s "Disk Space Warning" admin@trypdeals.com
fi
```

Add to crontab:
```bash
sudo crontab -e
# Add this line:
*/5 * * * * /home/ubuntu/app/monitor.sh
```

## 9. Performance Metrics to Track

### Key Metrics:
- **Response Time**: Average time per request
- **Error Rate**: Percentage of failed requests
- **Worker CPU Usage**: CPU usage per Daphne worker
- **Memory Usage**: Total RAM consumption
- **Database Query Time**: Average query duration
- **Redis Hit Rate**: Cache effectiveness
- **Disk I/O**: Read/write operations

### Commands to Check Metrics:

```bash
# Average response time (from logs)
sudo journalctl -u convoapi --since "1 hour ago" | grep "GET" | awk '{print $NF}' | grep -o '[0-9]*' | awk '{sum+=$1; count++} END {print sum/count "ms"}'

# Error rate
sudo journalctl -u convoapi --since "1 hour ago" | grep -i error | wc -l

# Worker CPU
ps aux | grep daphne | awk '{print $3}'

# Memory per worker
ps aux | grep daphne | awk '{print $4}'
```

## 10. Alert Thresholds

Set up alerts for:
- Response time > 5 seconds
- Error rate > 5%
- Memory usage > 80%
- Disk usage > 80%
- Redis not responding
- Daphne not running

## 11. External Monitoring Tools (Optional)

### Prometheus + Grafana (Advanced)
```bash
# Install Prometheus
sudo apt install prometheus -y

# Install Grafana
sudo apt install grafana -y

# Configure prometheus.yml to scrape Django metrics
```

### New Relic / Datadog (Cloud-based)
- Sign up for account
- Install agent
- Configure Django integration

### Uptime Robot (Free)
- Monitor https://trypbot.duckdns.org
- Get alerts when site is down
- Free tier available

## 12. Log Analysis

### Count requests by endpoint:
```bash
sudo journalctl -u convoapi --since "1 hour ago" | grep "GET" | awk '{print $NF}' | sort | uniq -c | sort -rn
```

### Find slow requests:
```bash
sudo journalctl -u convoapi --since "1 hour ago" | grep -i "slow"
```

### Database queries:
```bash
# Enable Django query logging temporarily
# Add to settings.py:
LOGGING = {
    'version': 1,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'loggers': {
        'django.db.backends': {
            'handlers': ['console'],
            'level': 'DEBUG',
        },
    },
}
```

## 13. Health Check Automation

Run health check every minute via cron:
```bash
sudo crontab -e
# Add:
* * * * * /home/ubuntu/app/deploy/health_check.sh > /tmp/health_check.log 2>&1
```

## 14. Quick Monitoring Commands

```bash
# All-in-one status check
bash deploy/health_check.sh

# Quick service status
sudo systemctl status convoapi redis-server nginx --no-pager

# Recent errors
sudo journalctl -u convoapi -p err --since "1 hour ago"

# Worker processes
ps aux | grep daphne

# Redis memory
redis-cli info memory | grep used_memory_human

# Disk space
df -h /home/ubuntu
```

## 15. Performance Baseline

After deployment, establish baseline metrics:
- Normal response time: ___ ms
- Normal CPU usage: ___%
- Normal memory usage: ___%
- Normal disk usage: ___%

Alert when metrics deviate > 50% from baseline.
