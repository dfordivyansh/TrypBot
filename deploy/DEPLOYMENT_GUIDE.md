# TrypBot Deployment Guide - Phase 1 & Phase 2 Optimizations

This guide walks you through deploying the performance optimizations to your EC2 server.

## 📋 What's Been Changed

### Phase 1 (Critical Fixes)
1. ✅ **Daphne Workers**: Increased from 1 to 4 workers × 2 threads
2. ✅ **Redis Channels**: Switched from InMemoryChannelLayer to Redis
3. ✅ **Database Indexes**: Added 7 critical indexes for faster queries
4. ✅ **Nginx Optimization**: Added gzip, caching, buffering
5. ✅ **WhiteNoise Removal**: Nginx now serves static files directly

### Phase 2 (High Priority)
6. ✅ **Redis Caching**: Added Django cache backend
7. ✅ **Security Headers**: Added HSTS, SSL redirect, XSS filter
8. ✅ **N+1 Query Fixes**: Added prefetch/select_related to CRM views
9. ✅ **Debug Print Removal**: Cleaned up ASGI logs
10. ✅ **Dependencies**: Added django-redis to requirements

---

## 🚀 Deployment Steps

### Step 1: Upload Files to Server

Copy these files to your EC2 server (`/home/ubuntu/app/`):
- `deploy/deploy.sh`
- `deploy/rollback.sh`
- `deploy/health_check.sh`
- `deploy/nginx-convoapi.conf`
- `deploy/convoapi.service`
- `chatbot/migrations/0017_performance_indexes.py`
- `convoapi/settings.py`
- `convoapi/asgi.py`
- `chatbot/routing.py`
- `chatbot/crm_views.py`
- `requirements.txt`

### Step 2: SSH into EC2

```bash
ssh ubuntu@your-ec2-ip
cd /home/ubuntu/app
```

### Step 3: Make Scripts Executable

```bash
chmod +x deploy/deploy.sh
chmod +x deploy/rollback.sh
chmod +x deploy/health_check.sh
```

### Step 4: Run Deployment Script

```bash
sudo bash deploy/deploy.sh
```

The script will:
- ✅ Backup current configuration
- ✅ Install Redis if needed
- ✅ Install Python dependencies
- ✅ Run database migrations
- ✅ Collect static files
- ✅ Update systemd service
- ✅ Update Nginx configuration
- ✅ Restart application
- ✅ Run health check

### Step 5: Verify Deployment

```bash
# Run health check
bash deploy/health_check.sh

# Check service status
sudo systemctl status convoapi

# Check worker processes
ps aux | grep daphne

# Check Redis
redis-cli ping
```

---

## 🔄 Rollback Procedure

If anything goes wrong, rollback immediately:

```bash
# Find backup directory
ls -la /home/ubuntu/backups/

# Rollback (replace with actual backup path)
sudo bash deploy/rollback.sh /home/ubuntu/backups/YYYYMMDD_HHMMSS
```

---

## ✅ Testing Checklist

After deployment, go through `deploy/TESTING_CHECKLIST.md`:

### Critical Tests (Must Pass)
- [ ] Daphne service running with 4 workers
- [ ] Redis running and responding
- [ ] Application responds to HTTP requests
- [ ] CRM login works
- [ ] WebSocket notifications work
- [ ] No errors in logs

### Performance Tests
- [ ] Homepage loads in < 500ms
- [ ] CRM list loads in < 1s
- [ ] No "database is locked" errors
- [ ] Memory usage < 80%
- [ ] CPU usage < 70%

---

## 📊 Expected Performance Improvements

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| Request Capacity | 1 worker | 4 workers × 2 threads | **8x** |
| CRM Query Speed | No indexes | 7 indexes | **2-10x** |
| Static Files | No compression | Gzip + cache | **40-60% faster** |
| Database Queries | N+1 problem | Prefetch/Select | **80% fewer queries** |
| WebSocket Reliability | InMemory (broken) | Redis | **Fixed** |
| Overall Response Time | 2-5s avg | 0.5-1s avg | **50-75% faster** |

---

## ⚠️ Important Notes

### HTTPS Requirement
The security headers will force HTTPS redirect. Ensure SSL certificates are configured:

```bash
# If using Let's Encrypt
sudo certbot --nginx -d trypdeals.com -d www.trypdeals.com -d trypbot.duckdns.org
```

### Redis Dependency
The application requires Redis to be running:
```bash
sudo systemctl start redis-server
sudo systemctl enable redis-server
```

### Monitoring
After deployment, set up monitoring using `deploy/MONITORING_SETUP.md`:
- Install htop for resource monitoring
- Set up log rotation
- Configure alert scripts
- Monitor for 24-48 hours

---

## 🔍 Troubleshooting

### Application Won't Start

```bash
# Check logs
sudo journalctl -u convoapi -n 100

# Common issues:
# - Redis not running → sudo systemctl start redis-server
# - Port already in use → sudo netstat -tulpn | grep 8000
# - Migration failed → python manage.py migrate
```

### WebSocket Notifications Not Working

```bash
# Check Redis
redis-cli ping

# Check logs for channel layer errors
sudo journalctl -u convoapi | grep -i channel

# Verify Redis is configured in settings.py
grep -A 5 CHANNEL_LAYERS convoapi/settings.py
```

### Nginx Configuration Errors

```bash
# Test configuration
sudo nginx -t

# If test fails, rollback Nginx config
sudo cp /home/ubuntu/backups/LATEST/convoapi /etc/nginx/sites-available/convoapi
sudo systemctl reload nginx
```

### Database Migration Issues

```bash
# Check migration status
python manage.py showmigrations

# If migration 0017 fails, rollback
python manage.py migrate convoapi 0016

# Check for database locks
sudo journalctl -u convoapi | grep -i "database is locked"
```

### High Memory Usage

```bash
# Check memory
free -h

# Check per-worker memory
ps aux | grep daphne

# If memory > 80%, reduce workers:
# Edit deploy/convoapi.service: --workers 2 instead of 4
```

---

## 📈 Next Steps

### Immediate (Post-Deployment)
1. ✅ Run health check script
2. ✅ Complete testing checklist
3. ✅ Monitor for 24-48 hours
4. ✅ Check logs for errors
5. ✅ Verify performance improvements

### Short Term (1-2 Weeks)
1. Set up monitoring (MONITORING_SETUP.md)
2. Configure log rotation
3. Add alert scripts
4. Consider migrating to PostgreSQL
5. Implement async API calls

### Long Term (1-2 Months)
1. Migrate to PostgreSQL
2. Implement Celery for background tasks
3. Add load balancer + multiple instances
4. Implement circuit breakers
5. Add CDN for static files

---

## 📞 Support

If you encounter issues:

1. **Check logs first**: `sudo journalctl -u convoapi -n 100`
2. **Run health check**: `bash deploy/health_check.sh`
3. **Rollback if needed**: `sudo bash deploy/rollback.sh <backup-dir>`
4. **Review troubleshooting section** above

---

## 📝 Deployment Log

**Deployment Date**: _______________  
**Deployed By**: _______________  
**Changes Applied**: Phase 1 + Phase 2  
**Backup Location**: _______________  
**Rollback Point**: _______________  

**Status**: [ ] Success [ ] Failed  
**Issues Encountered**: _______________  
**Resolution**: _______________  

**Post-Deployment Tests**: [ ] All Passed [ ] Some Failed  
**Performance Baseline**: _______________  
**Monitoring Active**: [ ] Yes [ ] No  

**Signed Off By**: _______________
