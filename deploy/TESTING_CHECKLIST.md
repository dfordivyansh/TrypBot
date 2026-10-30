# TrypBot Deployment Testing Checklist

Use this checklist to verify the deployment is working correctly after running the deployment script.

## Pre-Deployment Checklist

- [ ] **Backup created** - Confirm backup directory exists
- [ ] **Redis installed** - Run `redis-cli ping` to verify
- [ ] **Dependencies updated** - Run `pip list | grep -E "redis|channels"`
- [ ] **Migration test** - Run `python manage.py migrate --plan` to preview
- [ ] **Nginx config test** - Run `nginx -t` to verify syntax
- [ ] **Service config test** - Review `deploy/convoapi.service` changes

## Post-Deployment Checklist

### 1. Service Status
- [ ] **Daphne running** - `sudo systemctl status convoapi` shows "active (running)"
- [ ] **Redis running** - `sudo systemctl status redis-server` shows "active (running)"
- [ ] **Nginx running** - `sudo systemctl status nginx` shows "active (running)"
- [ ] **4 worker processes** - `ps aux | grep daphne` shows 4+ processes
- [ ] **No startup errors** - `sudo journalctl -u convoapi -n 50` shows no errors

### 2. Application Functionality

#### Basic HTTP
- [ ] **Homepage loads** - `curl http://127.0.0.1:8000/` returns 200
- [ ] **Dashboard loads** - Access `/dashboard/` (requires auth)
- [ ] **API endpoint works** - Access `/api/T5Y8U2I9O3P1A6S4/` (requires POST)
- [ ] **Static files served** - Access `/static/` files via Nginx
- [ ] **Media files served** - Access `/media/` files via Nginx

#### WebSocket Notifications
- [ ] **WebSocket endpoint accessible** - `/crm/notifications/` returns 403 (expected without auth)
- [ ] **Redis channel layer working** - Check logs for "Redis" connection
- [ ] **No InMemoryChannelLayer warnings** - Check logs for channel layer errors

#### CRM Functionality
- [ ] **Login works** - Can log into CRM at `/crm/login/`
- [ ] **Chat list loads** - CRM conversation list loads without errors
- [ ] **Chat detail loads** - Individual chat messages load
- [ ] **Send message works** - Can send WhatsApp message from CRM
- [ ] **Labels work** - Can change conversation labels
- [ ] **No N+1 query errors** - Check logs for repeated queries

#### WhatsApp Integration
- [ ] **Webhook accessible** - `/whatsapp-webhook/` endpoint responds
- [ ] **WhatsApp message send** - Test sending a message (requires test phone)
- [ ] **Media upload works** - Test uploading an image
- [ ] **Template messages work** - Test template message send

#### Campaign System
- [ ] **Campaign list loads** - Can view campaigns
- [ ] **Campaign creation works** - Can create a draft campaign
- [ ] **Contact list upload works** - Can upload CSV
- [ ] **Campaign status updates** - Campaign status changes correctly

### 3. Performance Verification

#### Response Time
- [ ] **Homepage < 500ms** - `curl -w "@curl-format.txt" http://127.0.0.1:8000/`
- [ ] **CRM list < 1s** - Load conversation list
- [ ] **Chat detail < 500ms** - Load individual chat
- [ ] **API response < 1s** - Test API endpoint

#### Database Queries
- [ ] **No "database is locked" errors** - Check logs
- [ ] **Query count reasonable** - Enable Django debug toolbar to check
- [ ] **Indexes used** - Check query plans if needed

#### Memory Usage
- [ ] **Memory < 80%** - `free -h` shows acceptable usage
- [ ] **No memory leaks** - Monitor over 30 minutes
- [ ] **Worker memory stable** - Each worker uses stable amount

#### CPU Usage
- [ ] **CPU < 70%** - `htop` shows acceptable usage
- [ ] **No CPU spikes** - Monitor during typical load
- [ ] **Workers balanced** - Load distributed across workers

### 4. Security Verification

#### HTTPS
- [ ] **SSL certificate valid** - `certbot certificates` shows valid cert
- [ ] **HTTPS redirect works** - HTTP redirects to HTTPS
- [ ] **HSTS header present** - Check response headers

#### Security Headers
- [ ] **X-Frame-Options present** - Check response headers
- [ ] **X-Content-Type-Options present** - Check response headers
- [ ] **Secure cookies** - Check cookie flags
- [ ] **CORS configured** - Only allowed origins work

#### Access Control
- [ ] **Admin protected** - `/admin/` requires login
- [ ] **CRM protected** - `/crm/` requires login
- [ ] **API protected** - API endpoints require auth where needed

### 5. Cache Verification

#### Redis Cache
- [ ] **Redis connected** - `redis-cli ping` returns PONG
- [ ] **Cache working** - Check Django cache usage
- [ ] **Channel layer using Redis** - Check logs for Redis channel

#### Static File Cache
- [ ] **Cache headers present** - Check `/static/` response headers
- [ ] **Browser caching works** - Repeated requests use cache
- [ ] **Cache invalidation** - Changes reflect after deployment

### 6. Error Checking

#### Logs
- [ ] **No critical errors** - `sudo journalctl -u convoapi -p err`
- [ ] **No warnings** - `sudo journalctl -u convoapi -p warning`
- [ ] **No database errors** - Check for SQLite errors
- [ ] **No API errors** - Check for WhatsApp/Meta API errors

#### Application Logs
- [ ] **Debug prints removed** - No `[ASGI] Request path:` spam
- [ ] **Structured logging** - Logs are readable
- [ ] **Log levels appropriate** - INFO in production

### 7. Integration Testing

#### External APIs
- [ ] **WhatsApp API working** - Test message send
- [ ] **DeepSeek API working** - Test AI response (if enabled)
- [ ] **Website API working** - Test tour sync
- [ ] **Firebase working** - Test booking webhook (if enabled)

#### Database
- [ ] **Migrations applied** - `python manage.py showmigrations` shows all applied
- [ ] **Data intact** - Check CRM data
- [ ] **No corruption** - Run `python manage.py check`

### 8. Monitoring Setup

#### Alerts
- [ ] **Health check script runs** - Test `bash deploy/health_check.sh`
- [ ] **Log rotation configured** - Check `/etc/logrotate.d/`
- [ ] **Monitoring tools installed** - htop, net-tools if desired

#### Metrics
- [ ] **Baseline established** - Record normal response times
- [ ] **Alert thresholds set** - Configure if using monitoring tools
- [ ] **Dashboard configured** - If using Grafana/etc.

### 9. Rollback Preparation

- [ ] **Backup verified** - Can restore from backup directory
- [ ] **Rollback script tested** - Run `bash deploy/rollback.sh --help`
- [ ] **Rollback procedure documented** - Team knows how to rollback
- [ ] **Rollback < 5 minutes** - Practice rollback

### 10. User Acceptance Testing

#### CRM Users
- [ ] **Can log in** - Test with actual user account
- [ ] **Can view chats** - Check conversation list
- [ ] **Can send messages** - Test WhatsApp send
- [ ] **Can change labels** - Test label changes
- [ ] **WebSocket notifications work** - Test real-time updates

#### End Users
- [ ] **WhatsApp bot responds** - Test with actual WhatsApp
- [ ] **Website widget works** - Test web widget if applicable
- [ ] **Booking flow works** - Test booking process

---

## Quick Smoke Test

Run this after deployment:

```bash
# 1. Check services
sudo systemctl status convoapi redis-server nginx --no-pager

# 2. Check workers
ps aux | grep daphne | wc -l  # Should be 4+

# 3. Check Redis
redis-cli ping  # Should return PONG

# 4. Check HTTP
curl -I http://127.0.0.1:8000/  # Should return 200

# 5. Check logs for errors
sudo journalctl -u convoapi -p err --since "5 minutes ago"

# 6. Run health check
bash deploy/health_check.sh
```

## Performance Test

```bash
# Install Apache Bench
sudo apt install apache2-utils -y

# Test homepage (100 requests, 10 concurrent)
ab -n 100 -c 10 http://127.0.0.1:8000/

# Expected: All requests successful, avg response time < 500ms
```

## Failure Recovery Test

```bash
# Test Redis failure
sudo systemctl stop redis-server
# Wait 30 seconds
sudo systemctl start redis-server
# Check if app recovers

# Test Daphne restart
sudo systemctl restart convoapi
# Check if it comes back up

# Test Nginx restart
sudo systemctl restart nginx
# Check if proxy works
```

## Known Issues to Watch For

1. **Redis connection failure** - WebSocket notifications won't work
2. **SSL certificate issues** - Security headers may cause redirect loops
3. **Database locks** - May still occur with SQLite under heavy load
4. **Memory exhaustion** - 4 workers × 2 threads may need more RAM
5. **Worker not starting** - Check if ports are already in use

## Sign-Off

**Deployed by**: _______________  
**Date**: _______________  
**Deployment ID**: _______________  
**Rollback point**: _______________  

**All critical checks passed**: [ ] Yes [ ] No  
**Performance baseline established**: [ ] Yes [ ] No  
**Monitoring active**: [ ] Yes [ ] No  

**Approved for production**: [ ] Yes [ ] No  
**Approved by**: _______________
