# NSE Dashboard Pro - Production Deployment Guide

## Overview
This guide covers deploying the NSE Dashboard for personal use, team use, or cloud deployment.

---

## Deployment Options

### Option 1: Local Development (Recommended for Personal Use)

**Pros**:
- ✅ Free
- ✅ Full control
- ✅ No data limits
- ✅ Private

**Cons**:
- ❌ Must keep computer running
- ❌ Not accessible remotely

**Setup**:
```bash
# 1. Clone/download files
cd nse-dashboard

# 2. Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run dashboard
streamlit run nse_dashboard_pro.py

# 5. Access at http://localhost:8501
```

---

### Option 2: Streamlit Cloud (Free Hosting)

**Pros**:
- ✅ Free tier available
- ✅ Auto-updates from Git
- ✅ Accessible anywhere
- ✅ HTTPS included

**Cons**:
- ❌ Resource limits
- ❌ Public by default
- ❌ May sleep when inactive

**Setup**:
```bash
# 1. Push code to GitHub
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/YOUR_USERNAME/nse-dashboard
git push -u origin main

# 2. Go to share.streamlit.io
# 3. Sign in with GitHub
# 4. Deploy from your repository
# 5. Choose: nse_dashboard_pro.py
```

**Resource Limits (Free Tier)**:
- 1 GB RAM
- 1 CPU core
- Sleeps after 7 days inactive

**Privacy Settings**:
```
Settings → Sharing → Make app private
(Requires authentication)
```

---

### Option 3: Docker Container (Team Deployment)

**Pros**:
- ✅ Consistent environment
- ✅ Easy to scale
- ✅ Can run on any cloud
- ✅ Isolated

**Dockerfile**:
```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY nse_dashboard_pro.py .
COPY USER_GUIDE.md .

# Create directories
RUN mkdir -p /app/logs /app/notes /app/exports

# Expose port
EXPOSE 8501

# Health check
HEALTHCHECK CMD curl --fail http://localhost:8501/_stcore/health

# Run app
CMD ["streamlit", "run", "nse_dashboard_pro.py", "--server.port=8501", "--server.address=0.0.0.0"]
```

**Build and Run**:
```bash
# Build image
docker build -t nse-dashboard .

# Run container
docker run -p 8501:8501 -v $(pwd)/logs:/app/logs nse-dashboard

# Access at http://localhost:8501
```

---

### Option 4: Cloud VM (AWS/GCP/Azure)

**Best for**: Team use, high reliability

**AWS EC2 Setup**:
```bash
# 1. Launch t3.micro instance (free tier eligible)
# 2. SSH into instance
ssh -i key.pem ubuntu@ec2-instance

# 3. Install Python and Git
sudo apt update
sudo apt install python3-pip git -y

# 4. Clone repository
git clone https://github.com/YOUR_USERNAME/nse-dashboard
cd nse-dashboard

# 5. Install dependencies
pip3 install -r requirements.txt

# 6. Run with systemd (persistent)
sudo nano /etc/systemd/system/nse-dashboard.service
```

**systemd Service File**:
```ini
[Unit]
Description=NSE Dashboard Pro
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/nse-dashboard
ExecStart=/usr/bin/python3 -m streamlit run nse_dashboard_pro.py
Restart=always

[Install]
WantedBy=multi-user.target
```

**Enable Service**:
```bash
sudo systemctl daemon-reload
sudo systemctl enable nse-dashboard
sudo systemctl start nse-dashboard
sudo systemctl status nse-dashboard
```

**Setup Nginx Reverse Proxy** (recommended):
```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://localhost:8501;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
    }
}
```

---

## Performance Optimization

### 1. System Requirements

**Minimum**:
- CPU: 2 cores
- RAM: 2 GB
- Storage: 1 GB
- Network: Stable internet

**Recommended**:
- CPU: 4 cores
- RAM: 4 GB
- Storage: 5 GB (for logs)
- Network: High-speed connection

### 2. Large Watchlist Optimization

**For 50+ stocks**:

```python
# Increase cache duration
@st.cache_data(ttl=600, show_spinner=False)  # 10 minutes

# Batch processing
# Already implemented in nse_dashboard_pro.py

# Async downloads (future enhancement)
import asyncio
async def fetch_all_stocks(symbols):
    # Parallel fetching
    pass
```

### 3. Database Integration (Optional)

**For historical tracking**:

```python
import sqlite3

# Create database
conn = sqlite3.connect('market_data.db')
cursor = conn.cursor()

cursor.execute('''
CREATE TABLE IF NOT EXISTS daily_data (
    date TEXT,
    symbol TEXT,
    close REAL,
    volume INTEGER,
    rsi REAL,
    PRIMARY KEY (date, symbol)
)
''')

# Store data
def save_daily_data(symbol, data):
    cursor.execute('''
        INSERT OR REPLACE INTO daily_data VALUES (?, ?, ?, ?, ?)
    ''', (date, symbol, close, volume, rsi))
    conn.commit()
```

---

## Security Considerations

### 1. Input Validation
✅ **Implemented** in v3.0:
- Symbol sanitization
- Dangerous character removal
- Watchlist validation

### 2. File Operations
✅ **Implemented**:
- Restricted to safe directories
- Path traversal prevention
- No user-controlled file paths

### 3. Environment Variables

**For sensitive configs**:
```python
import os
from dotenv import load_dotenv

load_dotenv()

# Example: Alternative data source API key
API_KEY = os.getenv('MARKET_DATA_API_KEY')
```

### 4. Authentication (For Cloud Deployment)

**Streamlit Cloud**:
```python
# Use built-in authentication
# Settings → Sharing → Require email authentication
```

**Custom Auth** (if needed):
```python
import streamlit_authenticator as stauth

# In your app
authenticator = stauth.Authenticate(
    credentials,
    'dashboard_auth',
    'auth_key',
    cookie_expiry_days=30
)

name, authentication_status, username = authenticator.login('Login', 'main')

if authentication_status:
    # Show dashboard
    pass
elif authentication_status == False:
    st.error('Username/password is incorrect')
```

---

## Monitoring & Logging

### 1. Application Logs
✅ **Implemented** in v3.0:

```bash
# Check logs
tail -f logs/dashboard_YYYYMMDD.log

# Monitor errors
grep ERROR logs/dashboard_YYYYMMDD.log

# API failures
grep "Download attempt" logs/dashboard_YYYYMMDD.log
```

### 2. Health Monitoring

**Create health check endpoint**:
```python
# Add to dashboard
def health_check():
    try:
        # Test data fetch
        test = yf.Ticker("^NSEI").history(period="1d")
        if not test.empty:
            return "healthy"
    except:
        return "unhealthy"
```

**Monitor with cron**:
```bash
# Check every 5 minutes
*/5 * * * * curl http://localhost:8501/health || echo "Dashboard down" | mail -s "Alert" admin@example.com
```

### 3. Usage Analytics

```python
# Track page views
if 'page_views' not in st.session_state:
    st.session_state.page_views = 0
st.session_state.page_views += 1

# Log user actions
logger.info(f"Mode selected: {dashboard_mode}")
logger.info(f"Stocks in watchlist: {len(watchlist)}")
```

---

## Backup & Disaster Recovery

### 1. Code Backup
```bash
# Use Git
git add .
git commit -m "Daily backup"
git push

# Or automated backup
0 0 * * * cd /path/to/dashboard && git add . && git commit -m "Auto backup $(date)" && git push
```

### 2. Data Backup
```bash
# Backup logs and notes
tar -czf backup_$(date +%Y%m%d).tar.gz logs/ notes/ exports/

# Move to cloud storage
aws s3 cp backup_*.tar.gz s3://my-backups/dashboard/
```

### 3. Configuration Backup
```bash
# Store watchlist
cat watchlist.txt > backup/watchlist_$(date +%Y%m%d).txt
```

---

## Scaling Considerations

### For Team of 10+ Users

**Option A: Multiple Instances**
```bash
# Load balancer distributes traffic
User 1-5 → Instance 1 (port 8501)
User 6-10 → Instance 2 (port 8502)
```

**Option B: Shared Database**
```python
# Central database for all users
# Each user has personal watchlist stored in DB
# Shared market data cache
```

### For High-Frequency Updates

**Use Redis Cache**:
```python
import redis

r = redis.Redis(host='localhost', port=6379)

def get_cached_data(symbol):
    cached = r.get(f"stock:{symbol}")
    if cached:
        return json.loads(cached)
    
    # Fetch fresh data
    data = yf.Ticker(symbol).history()
    r.setex(f"stock:{symbol}", 300, json.dumps(data))
    return data
```

---

## Troubleshooting Deployment

### Problem: Port Already in Use

```bash
# Find process using port 8501
lsof -i :8501

# Kill process
kill -9 PID

# Or use different port
streamlit run app.py --server.port=8502
```

### Problem: Permission Denied (Logs)

```bash
# Fix permissions
chmod 755 logs/
chown -R $USER:$USER logs/
```

### Problem: Out of Memory

```bash
# Check memory
free -h

# Increase swap (temporary)
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
```

### Problem: Slow Data Fetching

```bash
# Check network
ping finance.yahoo.com

# Test download speed
time python3 -c "import yfinance as yf; yf.download('RELIANCE.NS', period='1mo')"

# Use faster DNS
# Add to /etc/resolv.conf:
nameserver 8.8.8.8
nameserver 8.8.4.4
```

---

## Cost Estimates

### Free Options
- **Local**: $0/month (just electricity)
- **Streamlit Cloud**: $0/month (free tier)

### Paid Options
- **AWS t3.micro**: ~$8/month
- **DigitalOcean Droplet**: ~$6/month
- **Heroku**: ~$7/month

### Team (10 users)
- **AWS t3.small**: ~$15/month
- **Shared database**: +$5/month
- **Total**: ~$20/month

---

## Maintenance Schedule

### Daily
- Check logs for errors
- Verify data is updating

### Weekly
- Review performance metrics
- Check disk space
- Test backups

### Monthly
- Update dependencies: `pip install --upgrade -r requirements.txt`
- Review and clean old logs
- Security patches

### Quarterly
- Code review
- Feature additions
- User feedback integration

---

## Support & Updates

### Getting Updates
```bash
# If using Git
git pull origin main

# If downloaded directly
# Re-download latest version
```

### Version Compatibility
- v3.0+: Production ready
- v2.0: Optimized version
- v1.0: Basic version

### Migration Guide
See CHANGELOG.md for version-specific changes

---

## Production Checklist

Before deploying to production:

- [ ] All tests passing (`python test_indicators.py`)
- [ ] Logs directory created
- [ ] Notes directory created
- [ ] Exports directory created
- [ ] Watchlist configured
- [ ] Cache duration appropriate (300-600s)
- [ ] Backup strategy in place
- [ ] Monitoring configured
- [ ] Documentation accessible
- [ ] Team trained on usage

---

**Document Version**: 3.0  
**Last Updated**: February 2024  
**For**: NSE Dashboard Pro v3.0
