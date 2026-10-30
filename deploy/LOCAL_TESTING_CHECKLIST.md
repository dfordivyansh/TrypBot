# Local Testing Checklist for TrypBot

Complete checklist to verify your application works correctly before deploying to EC2.

## 🔧 Pre-Testing Setup

### Environment Setup
- [ ] WSL2 Ubuntu installed and running
- [ ] Python 3.11 installed (`python3.11 --version`)
- [ ] Virtual environment created (`.venv`)
- [ ] Dependencies installed (`pip install -r requirements.txt`)
- [ ] Redis installed and running (`redis-cli ping` returns PONG)
- [ ] `.env` file created with actual values
- [ ] `.env` file contains all required keys

### Code Verification
- [ ] Latest code pulled from repository
- [ ] All changes applied (settings.py, asgi.py, etc.)
- [ ] Migration file created (0017_performance_indexes.py)
- [ ] Nginx config updated (nginx-convoapi.conf)
- [ ] Systemd service config updated (convoapi.service)

---

## 🧪 Basic Functionality Tests

### Database Tests
- [ ] Run `python manage.py check` (no errors)
- [ ] Run `python manage.py migrate` (all migrations applied)
- [ ] Run `python manage.py showmigrations` (all applied)
- [ ] Run `python manage.py collectstatic --noinput` (static files collected)
- [ ] SQLite database file created (db.sqlite3)
- [ ] No database lock errors

### Redis Tests
- [ ] Redis server running (`sudo systemctl status redis-server`)
- [ ] Redis responding to PING (`redis-cli ping`)
- [ ] Redis memory usage acceptable (`redis-cli info memory`)
- [ ] No Redis connection errors in logs

---

## 🌐 Application Tests

### Start Application
```bash
source .venv/bin/activate
daphne -b 127.0.0.1 -p 8000 --workers 1 --threads 1 convoapi.asgi:application
```

- [ ] Daphne starts without errors
- [ ] Worker process created (check with `ps aux | grep daphne`)
- [ ] Console shows "ASGI application loaded successfully"
- [ ] WebSocket routes loaded (check console logs)
- [ ] Campaign worker thread started (check console logs)

### HTTP Tests
- [ ] Homepage loads at `http://localhost:8000/`
- [ ] Returns HTTP 200 status
- [ ] Page renders correctly
- [ ] No console errors on page load

### Admin Panel
- [ ] Admin accessible at `http://localhost:8000/admin/`
- [ ] Login page loads
- [ ] Can create superuser (`python manage.py createsuperuser`)
- [ ] Can login with superuser credentials
- [ ] Admin panel loads without errors

### API Endpoints
- [ ] API endpoint accessible at `http://localhost:8000/api/T5Y8U2I9O3P1A6S4/`
- [ ] Can send POST request (test with curl or Postman)
- [ ] Returns valid JSON response
- [ ] No 500 errors

### WebSocket Tests
- [ ] WebSocket endpoint accessible at `http://localhost:8000/crm/notifications/`
- [ ] Returns 403 (expected without auth)
- [ ] No WebSocket connection errors in logs
- [ ] Redis channel layer working (check logs for Redis)

---

## 📊 Performance Tests

### Response Time
- [ ] Homepage loads in < 500ms
- [ ] Admin panel loads in < 1s
- [ ] API response time < 1s
- [ ] No long delays (> 3s)

### Resource Usage
- [ ] Memory usage stable after 5 minutes
- [ ] Memory usage < 80% of available RAM
- [ ] CPU usage < 70% under normal load
- [ ] No memory leaks (memory doesn't grow continuously)
- [ ] CPU doesn't spike unexpectedly

### Database Queries
- [ ] No "database is locked" errors
- [ ] Query count reasonable (enable Django Debug Toolbar to check)
- [ ] No N+1 query errors in logs
- [ ] Database indexes working (check query plans if needed)

---

## 🔌 External Integration Tests

### WhatsApp Integration
- [ ] WhatsApp webhook endpoint accessible
- [ ] Can send test message (if test phone available)
- [ ] No WhatsApp API errors in logs
- [ ] Media upload works (if tested)

### DeepSeek AI
- [ ] DeepSeek API key configured in .env
- [ ] AI response works (if testing a message)
- [ ] No DeepSeek API errors in logs
- [ ] Response time acceptable

### Other APIs
- [ ] Google Maps API working (if used)
- [ ] Website tours API working (if tested)
- [ ] Firebase working (if used)

---

## 🛡️ Security Tests

### Environment Variables
- [ ] .env file is NOT committed to git
- [ ] .env is in .gitignore
- [ ] No secrets in code files
- [ ] DEBUG=False in .env
- [ ] SECRET_KEY is set to strong value

### Headers
- [ ] CORS headers configured correctly
- [ ] CSRF tokens working
- [ ] Security headers will be enabled in production (check settings.py)

---

## 📝 Configuration Tests

### Settings Verification
- [ ] Channel layer uses Redis (check settings.py)
- [ ] Cache backend uses Redis (check settings.py)
- [ ] Security headers will be enabled (check settings.py)
- [ ] ALLOWED_HOSTS includes your domains
- [ ] Database path configured correctly

### Nginx Configuration (if testing locally)
- [ ] Nginx config file syntax valid (`nginx -t`)
- [ ] Nginx can proxy to port 8000
- [ ] Static files accessible via Nginx
- [ ] Gzip compression working (test with curl -I)

---

## 🧹 Cleanup Tests

### Stop Application
- [ ] Application stops gracefully (Ctrl+C)
- [ ] No zombie processes remain
- [ ] Redis can be stopped cleanly
- [ ] Ports released (check with `netstat -tulpn | grep 8000`)

### Restart Application
- [ ] Application restarts successfully
- [ ] Redis reconnects on restart
- [ ] No errors on restart
- [ ] Database accessible after restart

---

## 🚨 Error Handling Tests

### Invalid Requests
- [ ] 404 page works for invalid URLs
- [ ] 500 errors handled gracefully
- [ ] No stack traces exposed to users
- [ ] Error logging works

### Database Errors
- [ ] Handles connection errors gracefully
- [ ] Recovers from temporary failures
- [ ] No data corruption on errors

---

## 📋 Final Checklist Before EC2 Deployment

### Code Ready
- [ ] All Phase 1 & Phase 2 changes applied
- [ ] Database migration file created
- [ ] Nginx config updated
- [ ] Systemd service config updated
- [ ] Dependencies updated in requirements.txt

### Testing Complete
- [ ] All basic tests pass
- [ ] All application tests pass
- [ ] All performance tests pass
- [ ] All integration tests pass
- [ ] No critical errors in logs

### Files Ready for Upload
- [ ] `convoapi/settings.py` (with Redis + security headers)
- [ ] `convoapi/asgi.py` (debug prints removed)
- [ ] `chatbot/routing.py` (debug prints removed)
- [ ] `chatbot/crm_views.py` (N+1 fixes)
- [ ] `chatbot/migrations/0017_performance_indexes.py`
- [ ] `deploy/nginx-convoapi.conf`
- [ ] `deploy/convoapi.service`
- [ ] `deploy/health_check.sh`
- [ ] `requirements.txt` (with django-redis)
- [ ] `.env.example` (for reference)

---

## ✅ Sign-Off

**Local Testing Completed By**: _______________  
**Date**: _______________  
**WSL2/Docker Used**: _______________  
**All Tests Passed**: [ ] Yes [ ] No  

**Issues Found**: _______________  
**Resolution**: _______________  

**Ready for EC2 Deployment**: [ ] Yes [ ] No

---

## 🚀 Next Step

If all tests pass:
1. Follow EC2_DEPLOYMENT_GUIDE.md
2. Launch Ubuntu t3.small instance
3. Deploy code using scripts
4. Run production testing checklist

If tests fail:
1. Fix issues locally first
2. Re-test until all pass
3. Then proceed to EC2 deployment
