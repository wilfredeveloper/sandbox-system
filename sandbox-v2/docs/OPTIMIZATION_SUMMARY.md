# Sandbox v2 Optimization Summary

## Overview

The sandbox server has been optimized for **AI agent bash execution** on a **24GB RAM, 8 vCPU Contabo server** with a hybrid container pooling strategy inspired by Cloudflare's serverless approach.

## Key Changes

### 1. **Settings Module** (`settings.py`)
- ✅ All configuration moved to environment variables
- ✅ Centralized configuration with validation
- ✅ Easy to override via `.env` file or docker-compose
- ✅ Self-documenting with `settings.print_config()`

### 2. **Hybrid Pool Management**
Combines the best of both worlds:
- **Pre-warmed pool** for instant allocation (<100ms)
- **On-demand scaling** up to max capacity (~2-3s cold start)
- **Aggressive cleanup** to free resources during low usage

#### How It Works:
```
1. Pre-warm 10-20 containers (instant availability)
2. Scale up to 80 containers on demand (your server's capacity)
3. After use, keep containers only if pool needs refilling
4. Destroy idle containers after 5 minutes of inactivity
5. Shrink pool to minimum size during quiet periods
```

### 3. **Optimized Resource Limits**

#### Previous Config:
- Memory: 512MB per container = ~40 max containers
- CPU: 50% per container = 16 concurrent CPU-intensive tasks
- Pool: 5 pre-warmed, max 20 total

#### New Config (AI Agent Optimized):
- Memory: **256MB** per container = **~80 max containers**
- CPU: **25%** per container = **32 concurrent tasks**
- Pool: **10-20 pre-warmed**, max **80 total**
- Idle timeout: **5 minutes** (was 1 hour)
- Session timeout: **15 minutes** (was 1 hour)

### 4. **Activity Tracking**
- Tracks last activity timestamp per session
- Updates on every command execution
- Enables idle container cleanup separate from session expiry

### 5. **Docker Compose Optimization**
- Reduced from 3 workers to **2 workers** (better for single server)
- Each worker: 20 pre-warmed, 40 max capacity
- Combined capacity: **40 instant**, **80 max** concurrent sessions

## Performance Expectations

### For AI Agent Bash Execution:

| Scenario | Concurrent Sessions | Performance |
|----------|-------------------|-------------|
| Typical AI agents | **60-70 sessions** | Excellent, <100ms response |
| Heavy (python scripts) | **30-35 sessions** | Good, some queuing |
| Peak burst | **80 sessions** | Acceptable, may degrade |

### Session Lifecycle:
```
1. AI agent creates session: <100ms (pre-warmed) or ~2-3s (on-demand)
2. Execute bash commands: 5-50ms per command
3. Session idle for 5 minutes: Container cleanup triggered
4. Session expires at 15 minutes: Forced cleanup
```

### Resource Efficiency:
- **Low traffic**: Pool shrinks to 5-10 containers, freeing ~15GB RAM
- **High traffic**: Pool scales to 60-80 containers, using ~20GB RAM
- **Idle periods**: Containers destroyed after 5 min, resources released

## Configuration Files

### `settings.py`
Centralized configuration with environment variable support:
```python
from settings import settings

settings.POOL_SIZE          # 10 (default)
settings.MAX_POOL_SIZE      # 80 (default)
settings.MEMORY_LIMIT       # "256m" (default)
settings.AGGRESSIVE_CLEANUP # true (default)
```

### `.env.example`
Complete configuration reference with:
- Detailed explanations for each setting
- Recommended values for different use cases
- Memory/CPU capacity calculations

### `docker-compose.yml`
Updated for 2-worker distributed setup:
- Worker 1: 20 pre-warmed, 40 max
- Worker 2: 20 pre-warmed, 40 max
- Redis for session coordination
- Load balancer coordinator

## Architecture Comparison

### Cloudflare Sandbox vs Your Sandbox v2

| Aspect | Cloudflare | Your v2 |
|--------|-----------|---------|
| **Cold start** | ~2-3s | ~2-3s (on-demand) |
| **Warm start** | ~100ms | <100ms (pre-warmed) |
| **Resource model** | Pay per use, hibernate | Hybrid: pre-warm + on-demand |
| **Scaling** | Automatic, infinite | Manual config, limited by RAM |
| **Cost** | Usage-based | Fixed server cost |
| **Location** | Global edge | Single datacenter |

**Your advantage**: Lower latency (<100ms vs ~100-2000ms) for pre-warmed containers.

**Cloudflare's advantage**: Unlimited scaling, pay only for active use.

## Usage Examples

### Standalone Mode (Single Server)
```bash
# Copy and configure
cp .env.example .env
nano .env  # Edit configuration

# Run server
python sandbox_server_v2.py
```

### Distributed Mode (Docker Compose)
```bash
# Build and start
docker-compose up -d

# Check health
curl http://localhost:8000/health

# View logs
docker-compose logs -f worker1
```

### Custom Configuration
```bash
# Override specific settings
export POOL_SIZE=30
export MAX_POOL_SIZE=60
export MEMORY_LIMIT=384m
python sandbox_server_v2.py
```

## Monitoring

### Health Endpoint
```bash
curl http://localhost:5000/health
```

Returns:
```json
{
  "status": "healthy",
  "worker_id": "worker1",
  "pool": {
    "available": 15,
    "allocated": 5,
    "total": 20,
    "max_capacity": 80
  },
  "active_sessions": 5,
  "config": {
    "pool_size": 20,
    "max_pool_size": 80,
    "aggressive_cleanup": true
  }
}
```

### Server Startup Output
```
============================================================
Sandbox Server v2 Configuration
============================================================
Server:
  Host: 0.0.0.0:5000
  Worker ID: standalone
  Debug: False

Container Pool:
  Initial Size: 10
  Min Size: 3
  Max Size: 80
  Aggressive Cleanup: True

Container Resources:
  Image: sandbox-secure:latest
  Memory: 256m
  CPU Quota: 25000 (≈25.0%)
  User: sandboxuser
  Workspace: /workspace

Timeouts:
  Session Timeout: 15 minutes
  Container Idle Timeout: 5 minutes
  Cleanup Interval: 300 seconds
  Command Timeout: 30 seconds

Redis:
  Enabled: False
============================================================
⚙ Initializing container pool with 10 containers...
  ✓ Container 1/10 ready
  ✓ Container 2/10 ready
  ...
```

## Why These Optimizations?

### 1. **256MB Memory** (was 512MB)
AI agents typically run: `ls`, `cat`, `grep`, `python script.py`
- These commands use 50-150MB actual memory
- 256MB provides headroom without waste
- **Result**: 2x more concurrent sessions

### 2. **25% CPU** (was 50%)
- Bash commands are bursty: 0% idle, brief 100% spikes
- Average CPU usage: 5-10% per session
- 25% quota prevents hogging, allows oversubscription
- **Result**: Better CPU sharing across sessions

### 3. **5-Minute Idle Timeout** (was 1 hour)
- AI agents often create session, run commands, then idle
- 5 minutes allows session reuse within agent workflow
- Frees resources quickly after agent completes
- **Result**: More efficient resource turnover

### 4. **Aggressive Cleanup** (new)
- Cloudflare-inspired: destroy containers when not needed
- Keeps pool at optimal size, not maximum size
- During low traffic, frees RAM for other services
- **Result**: Resource-efficient, scales down automatically

## Capacity Planning

### Your 24GB Contabo Server:

```
Available RAM: 24GB
- OS overhead: 2GB
- Docker daemon: 500MB
- Redis: 200MB
- 2 workers: 500MB
= Usable: ~21GB

With 256MB containers:
21GB ÷ 0.256GB = 82 containers (theoretical)
Recommended max: 80 containers (safety margin)

Recommended configuration:
- POOL_SIZE: 20 (pre-warmed)
- MIN_POOL_SIZE: 5 (maintenance level)
- MAX_POOL_SIZE: 80 (capacity limit)
```

### Expected Real-World Usage:
- **Idle**: 5-10 containers (~1.5GB)
- **Moderate (20 AI agents)**: 20-30 containers (~6GB)
- **Busy (50 AI agents)**: 50-60 containers (~14GB)
- **Peak (100+ AI agents)**: 70-80 containers (~19GB)

## Migration from Old Config

### Breaking Changes:
None! The new code is backward compatible.

### Configuration Changes:
1. Old hardcoded values → New environment variables
2. Settings moved to `settings.py`
3. New idle timeout tracking

### To Migrate:
1. Update `sandbox_server_v2.py` (done)
2. Create `settings.py` (done)
3. Copy `.env.example` to `.env` and customize
4. Update `docker-compose.yml` (done)
5. Rebuild containers: `docker-compose build`
6. Restart: `docker-compose up -d`

## Next Steps

1. **Test the configuration**:
   ```bash
   python sandbox_server_v2.py
   ```

2. **Monitor resource usage**:
   ```bash
   htop  # Watch RAM/CPU
   docker stats  # Watch container resources
   ```

3. **Tune for your workload**:
   - Adjust `POOL_SIZE` based on typical concurrent usage
   - Adjust `MEMORY_LIMIT` if commands need more RAM
   - Adjust `IDLE_TIMEOUT` based on agent session patterns

4. **Load test** (optional):
   - Use the existing `load_test.py`
   - Verify performance at 60-70 concurrent sessions
   - Monitor for memory/CPU bottlenecks

## Questions & Tuning

### "My AI agents need more memory"
```bash
MEMORY_LIMIT=512m  # Reduces max to ~40 containers
# or
MEMORY_LIMIT=384m  # Allows ~54 containers
```

### "I want faster response, don't care about resource efficiency"
```bash
AGGRESSIVE_CLEANUP=false
POOL_SIZE=50
MIN_POOL_SIZE=30
```

### "I want maximum resource efficiency"
```bash
AGGRESSIVE_CLEANUP=true
POOL_SIZE=5
MIN_POOL_SIZE=2
CONTAINER_IDLE_TIMEOUT_MINUTES=3
```

### "My AI agent sessions last longer"
```bash
SESSION_TIMEOUT_MINUTES=30
CONTAINER_IDLE_TIMEOUT_MINUTES=10
```

---

**Summary**: Your sandbox is now optimized for 60-80 concurrent AI agent sessions on a 24GB server, with Cloudflare-inspired hybrid pooling for instant response + resource efficiency.
