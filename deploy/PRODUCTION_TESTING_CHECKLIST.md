# Production Testing Checklist for TrypBot

Complete checklist to verify your TrypBot application works correctly on EC2 after deployment.

## 🔧 Post-Deployment Verification

### Instance Status
- [ ] EC2 instance running (t3.small, Ubuntu 22.04)
- [ ] Instance public IP accessible
- [ ] SSH connection working
- [ ] Instance type confirmed: t3.small (2 vCPU, 2 GB RAM)
- [ ] Security group configured correctly
- [ ] EBS volume attached (20 GB)

### Service Status
- [ ] Daphne service running (`sudo systemctl status convoapi`)
- [ ] Redis service running (`sudo systemctl status redis-server`)
- [ ] Nginx service running (`sudo systemctl status nginx`)
- [ ] All services enabled for auto-start
- [ ] No service startup errors in logs

---

## 🌐 DNS & SSL Tests

### Domain Configuration
- [ ] Domain DNS points to EC2 public IP
- [ ] `trypbot.duckdns.org` resolves to correct IP
- [ ] `trypdeals.com` resolves to correct IP
- [ ] `www.trypdeals.com` resolves to correct IP

### SSL Certificate
- [ ] SSL certificate installed
- [ ] Certificate valid for all domains
- [ ] HTTPS works (test with curl -I)
- [ ] HTTP redirects to HTTPS
- [ ] Certificate not expired
- [ ] HSTS header present (check with curl -I)

---

## 🧪 Application Functionality Tests

### HTTP Response Tests
```bash
# Test homepage
curl -I https://trypbot.duckdns.org/

# Expected: HTTP/2 200
```
- [ ] Homepage loads at `https://trypbot.duckdns.org/`
- [ ] Returns HTTP 200 status
- [ ] Page renders correctly
- [ ] No 500 errors
- [ ] Redirects to HTTPS (if accessed via HTTP)

### Admin Panel
- [ ] Admin accessible at `https://trypbot.duckdns.org/admin/`
- [ ] Login page loads
- [ ] Can login with superuser credentials
- [ ] Admin panel loads without errors
- [ ] Can create/view database models
- [ ] Session management works

### CRM System
- [ ] CRM login accessible at `https://trypbot.duckdns.org/crm/login/`
- [ ] Can login as sales user
- [ ] Chat list loads
- [ ] Can view chat details
- [ ] Can send WhatsApp messages
- [ ] Can change conversation labels
- [ ] No CRM errors in logs

### API Endpoints
- [ ] API endpoint accessible at `https://trypbot.duckdns.org/api/T5Y8U2I9O3P1A6S4/`
- [ ] Can send POST request
- [ ] Returns valid JSON response
- [ ] No 500 errors
- [ ] CORS headers correct

### WebSocket Notifications
- [ ] WebSocket endpoint accessible at `/crm/notifications/`
- [ ] CRM users can connect
- [ ] Real-time notifications work
- [ ] New message notifications work
- [ ] Label change notifications work
- [ ] No WebSocket errors in logs

---

## 📊 Performance Tests

### Response Time Tests
- [ ] Homepage loads in < 500ms
- [ ] Admin panel loads in < 1s
- [ ] CRM chat list loads in < 1s
- [ ] CRM chat detail loads in < 500ms
- [ ] API response time < 1s
- [ ] No requests timeout (> 30s)

### Resource Usage Tests
```bash
# Check memory
free -h

# Check CPU
htop

# Check disk
df -h
```
- [ ] Memory usage < 80% (should be ~60-70%)
- [ ] CPU usage < 70% under normal load
- [ ] Disk usage < 80%
- [ ] Memory usage stable (not growing continuously)
- [ ] No memory leaks

### Worker Process Tests
```bash
# Check worker count
ps aux | grep daphne | wc -l

# Should be 1 (for t3.small)
```
- [ ] 1 worker process running (t3.small config)
- [ ] Worker process stable (not crashing)
- [ ] Worker CPU usage reasonable
- [ ] Worker memory usage reasonable

---

## 🗄️ Database Tests

### SQLite Tests
- [ ] Database file exists (`db.sqlite3`)
- [ ] Database file size reasonable (< 500 MB)
- [ ] No "database is locked" errors in logs
- [ ] All migrations applied (0017 included)
- [ ] Database indexes created
- [ ] Query performance acceptable

### Database Query Tests
- [ ] No N+1 query errors
- [ ] Prefetch/select_related working
- [ ] Indexes being used (explain query if needed)
- [ ] No slow queries (> 1s)

---

## 🔄 Redis Tests

### Redis Connection
```bash
redis-cli ping

# Should return PONG
```
- [ ] Redis responding to PING
- [ ] Redis memory usage acceptable
- [ ] Redis connected clients reasonable
- [ ] No Redis connection errors in application logs
- [ ] Channel layer using Redis (check logs)

### Cache Tests
- [ ] Django cache backend configured
- [ ] Cache operations working
- [ ] Cache hits/misses reasonable
- [ ] No cache errors in logs

---

## 🌐 Nginx Tests

### Nginx Configuration
```bash
sudo nginx -t

# Should return "configuration file test is successful"
```
- [ ] Nginx configuration valid
- [ ] Nginx reloading successfully
- [ ] Static files served by Nginx
- [ ] Media files served by Nginx
- [ ] Gzip compression enabled
- [ ] Cache headers present

### Static Files
- [ ] Static files accessible at `/static/`
- [ ] Static files load quickly
- [ ] CSS/JS loads
- [ ] No 404 errors for static files
- [ ] Browser caching working

---

## 🔌 Integration Tests

### WhatsApp Integration
- [ ] WhatsApp webhook accessible
- [ ] Can receive WhatsApp messages
- [ ] Can send WhatsApp messages
- [ ] Media upload/download works
- [ ] No WhatsApp API errors in logs
- [ ] WhatsApp message IDs stored correctly

### DeepSeek AI
- [ ] DeepSeek API calls working
- [ ] AI responses generated
- [ ] No DeepSeek API errors
- [ ] Response time acceptable (< 10s)

### Website Integrations
- [ ] Website tours sync working
- [ ] Website booking webhook accessible
- [ ] Website enquiry webhook accessible
- [ ] No integration errors in logs

---

## 🛡️ Security Tests

### Security Headers
```bash
curl -I https://trypbot.duckdns.org/

# Check for:
# Strict-Transport-Security
# X-Frame-Options
# X-Content-Type-Options
```
- [ ] HSTS header present
- [ ] X-Frame-Options header present
- [ ] X-Content-Type-Options header present
- [ ] Cookies marked as Secure
- [ ] Cookies marked as HttpOnly

### Access Control
- [ ] Admin requires authentication
- [ ] CRM requires authentication
- [ ] API endpoints protected where needed
- [ ] No unauthorized access
- [ ] No exposed admin URLs

### Environment Variables
- [ ] .env file not in repository
- [ ] No secrets in code
- [ ] DEBUG=False in production
- [ ] SECRET_KEY is strong
- [ ] All API keys configured

---

## 📝 Logging Tests

### Application Logs
```bash
sudo journalctl -u convoapi -n 100
```
- [ ] No critical errors in logs
- [ ] No repeated error messages
- [ ] Log levels appropriate (INFO, not DEBUG)
- [ ] Logs not growing too fast
- [ ] Log rotation configured (if needed)

### Nginx Logs
```bash
sudo tail -f /var/log/nginx/error.log
```
- [ ] No Nginx errors
- [ ] Access logs being recorded
- [ ] No 4xx/5xx error spikes

---

## 🧹 Cleanup & Restart Tests

### Service Restart
```bash
sudo systemctl restart convoapi
```
- [ ] Service restarts successfully
- [ ] Application recovers gracefully
- [ ] Redis reconnects on restart
- [ ] No errors on restart
- [ ] Users can reconnect after restart

### System Reboot
- [ ] Services start automatically on boot
- [ ] No manual intervention needed
- [ ] Application accessible after reboot

---

## 📊 Health Check Script

### Run Health Check
```bash
bash deploy/health_check.sh
```
- [ ] All health checks pass
- [ ] Service status green
- [ ] Redis status green
- [ ] HTTP response test passes
- [ ] Database connection test passes
- [ ] Memory usage acceptable
- [ ] Disk usage acceptable

---

## 🚨 Error Scenarios

### High Load Test
- [ ] Application handles 10 concurrent requests
- [ ] No 502 errors under load
- [ ] No memory exhaustion
- [ ] No database locks under load

### Error Recovery
- [ ] Application recovers from temporary failures
- [ ] Redis reconnection works
- [ ] Database reconnects after temporary issues
- [ ] No zombie processes

---

## 📋 Final Production Checklist

### Configuration
- [ ] t3.small instance running
- [ ] Ubuntu 22.04 LTS
- [ ] 2 GB RAM, 2 vCPU
- [ ] $93.31 for 6 months (within $200 budget)
- [ ] 1 worker, 1 thread configured
- [ ] Redis running
- [ ] Nginx running
- [ ] SSL configured

### Functionality
- [ ] Homepage accessible
- [ ] Admin panel working
- [ ] CRM system working
- [ ] WhatsApp integration working
- [ ] All APIs working
- [ ] WebSocket notifications working

### Performance
- [ ] Response times acceptable
- [ ] Resource usage acceptable
- [ ] No memory leaks
- [ ] No database locks
- [ ] Stable operation

### Security
- [ ] HTTPS working
- [ ] Security headers present
- [ ] Authentication working
- [ ] No exposed secrets
- [ ] DEBUG=False

### Monitoring
- [ ] Health check script passing
- [ ] Logs being recorded
- [ ] Resource monitoring possible
- [ ] Alert configuration (if desired)

---

## ✅ Sign-Off

**Production Deployment Completed By**: _______________  
**Date**: _______________  
**Instance**: t3.small (Ubuntu 22.04)  
**Public IP**: _______________  
**Domain**: trypbot.duckdns.org  

**All Tests Passed**: [ ] Yes [ ] No  

**Issues Found**: _______________  
**Resolution**: _______________  

**Ready for Production Use**: [ ] Yes [ ] No  

**Monitoring Active**: [ ] Yes [ ] No  

---

## 🚀 Post-Deployment Monitoring

### First 24 Hours
- [ ] Monitor resource usage every 2 hours
- [ ] Check logs for errors every 2 hours
- [ ] Test key user flows
- [ ] Verify WhatsApp integration
- [ ] Monitor response times

### First Week
- [ ] Daily health check
- [ ] Review logs daily
- [ ] Monitor cost in AWS billing
- [ ] Check for any errors
- [ ] Verify all integrations

### Ongoing
- [ ] Weekly health check
- [ ] Monthly cost review
- [ ] Quarterly optimization review
- [ ] Log rotation check
- [ ] Backup verification

---

## 🔄 Update Process

### Future Code Updates
```bash
# SSH into server
ssh -i trypbot-key.pem ubuntu@YOUR_PUBLIC_IP

# Navigate to app
cd /home/ubuntu/app

# Activate venv
source .venv/bin/activate

# Pull latest code
git pull

# Install new dependencies
pip install -r requirements.txt

# Run migrations
python manage.py migrate

# Collect static files
python manage.py collectstatic --noinput

# Restart service
sudo systemctl restart convoapi

# Run health check
bash deploy/health_check.sh
```

---

## 📞 Support & Troubleshooting

### Common Issues

**Application not responding:**
```bash
sudo systemctl status convoapi
sudo journalctl -u convoapi -n 50
```

**Redis not working:**
```bash
sudo systemctl status redis-server
sudo systemctl restart redis-server
```

**Nginx errors:**
```bash
sudo nginx -t
sudo systemctl reload nginx
sudo tail -f /var/log/nginx/error.log
```

**SSL issues:**
```bash
sudo certbot renew
sudo certbot certificates
```

---

## 🎯 Success Criteria

Deployment is successful when:
- ✅ All tests in this checklist pass
- ✅ Application stable for 24 hours
- ✅ No critical errors in logs
- ✅ Performance metrics acceptable
- ✅ All integrations working
- ✅ Resource usage within limits
- ✅ Users can use all features

---

**Production Deployment Complete!** 🎉

Your TrypBot is now live on Ubuntu t3.small with all optimizations applied and tested.
