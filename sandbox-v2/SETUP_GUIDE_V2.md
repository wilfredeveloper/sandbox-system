# Enhanced Sandbox Setup Guide v2

This guide covers setting up the enhanced sandbox system with:
- 🚀 Container pooling for instant sessions
- 🔒 Non-root user execution
- 🌐 Distributed architecture with load balancing
- ⚡ 10x faster session creation

## Quick Start - Choose Your Mode

### Mode 1: Standalone (Single Server)
Best for: Development, small workloads, single VPS

### Mode 2: Distributed (Multiple Workers)
Best for: Production, high traffic, multiple VPS servers or Docker Swarm

---

## 🏃 Mode 1: Standalone Setup

### Step 1: Build Secure Image

```bash
# Build the secure non-root image
docker build -f Dockerfile.secure -t sandbox-secure:latest .

# Verify it's non-root
docker run --rm sandbox-secure:latest whoami
# Should output: sandboxuser (NOT root!)
```

### Step 2: Install Dependencies

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install requirements
pip install -r requirements-worker.txt
```

### Step 3: Start Standalone Server

```bash
# Start the enhanced server
python sandbox_server_v2.py
```

You should see:
```
🚀 Starting Enhanced Sandbox Server
   Pool size: 5
   Container image: sandbox-secure:latest
   User: sandboxuser
🔄 Initializing container pool with 5 containers...
  ✅ Container 1/5 ready
  ✅ Container 2/5 ready
  ...
✨ Pool initialized with 5 containers
```

### Step 4: Test It

```bash
# In another terminal
python sandbox_client_v2.py --test
```

Expected output:
```
🧪 Testing sandbox client...

✅ Session created: abc-123-...
📝 Test 1: whoami
   User: sandboxuser  ← NOT ROOT!
   Exit code: 0
...
```

---

## 🌐 Mode 2: Distributed Setup

### Architecture

```
          Client
            ↓
      Coordinator (Port 8000)
            ↓
    Redis (Session State)
            ↓
    ┌───────┼───────┐
    ↓       ↓       ↓
 Worker1 Worker2 Worker3
 (Port   (Port   (Port
  5000)   5000)   5000)
```

### Option A: Docker Compose (Easiest)

Perfect for single VPS with multiple workers:

```bash
# Build the secure sandbox image first
docker build -f Dockerfile.secure -t sandbox-secure:latest .

# Start the entire stack
docker-compose up -d

# Check status
docker-compose ps

# View coordinator logs
docker-compose logs -f coordinator

# Scale workers (add more)
docker-compose up -d --scale worker1=1 --scale worker2=1 --scale worker3=1
```

Test it:
```bash
# The coordinator is on port 8000
python sandbox_client_v2.py --test

# Or direct curl
curl http://localhost:8000/health
```

### Option B: Manual Multi-VPS Setup

For multiple servers, follow these steps on each machine:

#### On Redis Server (one machine):

```bash
# Install Redis
sudo apt-get update
sudo apt-get install -y redis-server

# Configure Redis to listen on all interfaces
sudo nano /etc/redis/redis.conf
# Change: bind 127.0.0.1 → bind 0.0.0.0
# Change: protected-mode yes → protected-mode no

# Restart Redis
sudo systemctl restart redis

# Verify
redis-cli ping  # Should return PONG
```

#### On Each Worker Server:

```bash
# 1. Build secure image
docker build -f Dockerfile.secure -t sandbox-secure:latest .

# 2. Install dependencies
python3 -m venv venv
source venv/bin/activate
pip install -r requirements-worker.txt

# 3. Set environment variables
export REDIS_HOST=<redis-server-ip>
export REDIS_PORT=6379
export WORKER_ID=worker1  # Change for each worker
export POOL_SIZE=5

# 4. Start worker
python sandbox_server_v2.py
```

#### On Coordinator Server:

```bash
# 1. Install dependencies
python3 -m venv venv
source venv/bin/activate
pip install -r requirements-coordinator.txt

# 2. Set environment variables
export REDIS_HOST=<redis-server-ip>
export REDIS_PORT=6379
export WORKERS=http://worker1-ip:5000,http://worker2-ip:5000,http://worker3-ip:5000

# 3. Start coordinator
python coordinator.py
```

---

## 🔧 Configuration

### Worker Configuration (sandbox_server_v2.py)

Edit at top of file:

```python
POOL_SIZE = 5          # Pre-warmed containers
MIN_POOL_SIZE = 2      # Minimum to maintain
MAX_POOL_SIZE = 20     # Maximum pool size
SESSION_TIMEOUT = timedelta(hours=1)
MEMORY_LIMIT = "512m"
CPU_QUOTA = 50000      # 50% of one core
```

### Coordinator Configuration (coordinator.py)

Via environment variables:
```bash
export WORKERS="http://ip1:5000,http://ip2:5000,http://ip3:5000"
export REDIS_HOST="redis-ip"
export PORT=8000
```

---

## 🔍 Monitoring

### Health Checks

```bash
# Coordinator health
curl http://localhost:8000/health

# Worker health (standalone)
curl http://localhost:5000/health
```

Example output:
```json
{
  "status": "healthy",
  "pool_size": 5,
  "active_sessions": 3,
  "worker_id": "worker1"
}
```

### View Docker Containers

```bash
# List all sandbox containers
docker ps | grep sandbox-secure

# View container resource usage
docker stats
```

### Redis Monitoring

```bash
# Connect to Redis CLI
redis-cli

# View all sessions
KEYS session:*

# View session data
GET session:abc-123

# Monitor commands in real-time
MONITOR
```

---

## ⚡ Performance Comparison

### V1 (Original) vs V2 (Enhanced)

| Metric | V1 | V2 |
|--------|----|----|
| Session Creation | ~2-5s | ~50-100ms (40x faster!) |
| User | root ❌ | sandboxuser ✅ |
| Scaling | Manual | Distributed |
| Pool | None | Yes (5-20 containers) |

### Load Test

```bash
# Install hey (HTTP load testing)
go install github.com/rakyll/hey@latest

# Test session creation
hey -n 100 -c 10 -m POST http://localhost:8000/create_session

# Results should show:
# - ~100ms average response time
# - 0 failures with proper pool size
```

---

## 🐛 Troubleshooting

### Issue: "User is still root"

```bash
# Rebuild the secure image
docker build -f Dockerfile.secure -t sandbox-secure:latest .

# Verify the image
docker run --rm sandbox-secure:latest id
# Should show: uid=1000(sandboxuser) gid=1000(sandboxuser)

# Make sure sandbox_server_v2.py uses the right image
# Check: CONTAINER_IMAGE = "sandbox-secure:latest"
```

### Issue: "Pool empty, creating container on demand"

This means pool size is too small. Increase it:

```python
# In sandbox_server_v2.py
POOL_SIZE = 10  # Increase from 5
```

### Issue: Workers not responding

```bash
# Check worker logs
docker-compose logs worker1

# Check if Docker socket is accessible
docker ps

# Verify network connectivity
ping worker1-ip
curl http://worker1-ip:5000/health
```

### Issue: Redis connection failed

```bash
# Test Redis connection
redis-cli -h redis-ip ping

# Check Redis is listening on correct interface
netstat -an | grep 6379

# Check firewall
sudo ufw allow 6379/tcp
```

---

## 🔒 Production Checklist

Before going to production:

- [ ] Change `network_mode="none"` to allow controlled network if needed
- [ ] Set up nginx reverse proxy with SSL
- [ ] Implement API key authentication
- [ ] Add rate limiting per user
- [ ] Set up logging aggregation (ELK stack)
- [ ] Configure alerts for high resource usage
- [ ] Set up backup for Redis
- [ ] Implement proper secrets management
- [ ] Use read-only root filesystem in containers
- [ ] Enable Docker security scanning
- [ ] Set up monitoring (Prometheus + Grafana)

---

## 📊 Resource Planning

### Single Worker Capacity

- Pool of 5 containers: ~500MB RAM idle
- Each active session: +50-100MB RAM
- Recommended: 4GB RAM per worker for ~30 concurrent sessions

### Multi-Worker Setup

Example for 100 concurrent sessions:
- 4 workers × 4GB RAM = 16GB total
- 1 Redis server: 2GB RAM
- 1 Coordinator: 1GB RAM
- **Total: ~19GB RAM**

---

## 🚀 Next Steps

1. Test in standalone mode first
2. Verify non-root execution
3. Deploy distributed setup if needed
4. Add monitoring and alerting
5. Integrate with your LangGraph agent
6. Load test before production
7. Implement production security

---

## 📚 Additional Files

- `sandbox_server_v2.py` - Enhanced worker with pooling
- `coordinator.py` - Load balancer for distributed setup  
- `sandbox_client_v2.py` - Updated client
- `docker-compose.yml` - Easy distributed deployment
- `Dockerfile.secure` - Non-root sandbox image

Need help? Check the examples or reach out!
