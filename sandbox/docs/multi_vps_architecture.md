# Multi-VPS Architecture Deep Dive

## Physical Infrastructure Setup

### Architecture Diagram

```
                         Internet
                            │
                            ▼
┌────────────────────────────────────────────────────────────┐
│                    VPS 1 (Central Hub)                     │
│        Location: US-East (New York)                        │
│        IP: 203.0.113.10                                    │
│                                                            │
│  ┌──────────────────────────────────────────────────┐     │
│  │  Nginx Reverse Proxy (Port 443 - HTTPS)          │     │
│  │  - SSL Termination                                │     │
│  │  - Rate limiting                                  │     │
│  │  - Request logging                                │     │
│  └────────────┬─────────────────────────────────────┘     │
│               │                                            │
│  ┌────────────▼────────────────┐                          │
│  │  Coordinator (Port 8000)     │                          │
│  │  - Load balancing logic      │                          │
│  │  - Health checking           │                          │
│  │  - Session routing           │                          │
│  └────────────┬─────────────────┘                          │
│               │                                            │
│  ┌────────────▼────────────────┐                          │
│  │  Redis (Port 6379)           │                          │
│  │  - Session → Worker mapping  │                          │
│  │  - Persistent storage        │                          │
│  └──────────────────────────────┘                          │
└────────────────┬───────────────────────────────────────────┘
                 │
                 │ Private Network / VPN Tunnel
                 │ (or Public Internet with auth)
                 │
        ┌────────┼─────────┬──────────────┐
        │        │         │              │
    ┌───▼────────▼───┐ ┌──▼──────────┐ ┌─▼────────────┐
    │   VPS 2        │ │  VPS 3      │ │  VPS 4       │
    │   US-East      │ │  US-West    │ │  EU-West     │
    │ 203.0.113.20   │ │203.0.113.30 │ │203.0.113.40  │
    │                │ │             │ │              │
    │ ┌────────────┐ │ │┌──────────┐ │ │┌───────────┐│
    │ │  Worker 1  │ │ ││ Worker 2 │ │ ││ Worker 3  ││
    │ │ Port 5000  │ │ ││Port 5000 │ │ ││Port 5000  ││
    │ │            │ │ ││          │ │ ││           ││
    │ │ Pool: 10   │ │ ││Pool: 10  │ │ ││Pool: 10   ││
    │ │ containers │ │ ││containers│ │ ││containers ││
    │ └────────────┘ │ │└──────────┘ │ │└───────────┘│
    └────────────────┘ └─────────────┘ └──────────────┘
```

## Request Flow - Step by Step

### Scenario: User Creates a Session and Executes Code

#### Step 1: Client Makes Request
```python
# User's laptop in California
client = SandboxClient("https://sandbox.yourapp.com")
client.create_session()
```

**Network Path:**
```
User's Laptop (California)
    │
    │ HTTPS Request (encrypted)
    │ ~40ms (California → New York)
    ▼
VPS 1 Nginx (New York) - 203.0.113.10:443
```

---

#### Step 2: Nginx → Coordinator
```
Nginx (VPS 1)
    │ Decrypts SSL
    │ Validates request
    │ Forwards to coordinator
    │ ~1ms (same machine)
    ▼
Coordinator (VPS 1) - localhost:8000
```

**What Coordinator Does:**
1. Receives POST to `/create_session`
2. Queries Redis: "Which workers are healthy?"
3. Selects a worker (round-robin or least-loaded)
4. In this example: Selects Worker 2 on VPS 3

**Code in coordinator.py (lines 48-56):**
```python
def select_worker():
    healthy_workers = get_healthy_workers()  # ← Checks all workers
    if not healthy_workers:
        return None
    return random.choice(healthy_workers)    # ← Picks one
```

---

#### Step 3: Coordinator → Worker (Cross-VPS Communication)
```
Coordinator (VPS 1, New York)
    │
    │ HTTP POST /create_session
    │ Over Internet or Private Network
    │ ~80ms (New York → California)
    ▼
Worker 2 (VPS 3, California) - 203.0.113.30:5000
```

**Network Options:**

**Option A: Public Internet**
- Coordinator connects to worker's public IP
- Secured with API tokens or VPN
- Latency: Variable (50-150ms depending on distance)

**Option B: Private Network (Better)**
- Use cloud provider's private networking (AWS VPC, DigitalOcean Private Network)
- Only accessible within your infrastructure
- Lower latency (~10-30ms)
- Free bandwidth (no egress charges)

**Option C: WireGuard VPN (Best for DIY)**
- All VPS servers connected via encrypted VPN
- Workers only listen on VPN interface
- Secure + fast

---

#### Step 4: Worker Creates Container
```
Worker 2 (VPS 3)
    │
    │ Gets pre-warmed container from pool
    │ ~50ms (instant - already running!)
    │
    ▼
Returns: {
    "session_id": "abc123",
    "status": "created",
    "worker": "http://203.0.113.30:5000"
}
```

---

#### Step 5: Worker → Coordinator → Client
```
Worker 2 (VPS 3)
    │ Response
    │ ~80ms (California → New York)
    ▼
Coordinator (VPS 1)
    │ Stores mapping in Redis:
    │   session:abc123:worker → http://203.0.113.30:5000
    │ ~1ms
    ▼
Nginx
    │ Encrypts response
    │ ~40ms (New York → California)
    ▼
User's Laptop
```

**Total Latency for Session Creation:**
- Client → Nginx: 40ms
- Nginx → Coordinator: 1ms
- Coordinator → Worker: 80ms
- Worker creates session: 50ms
- Worker → Coordinator: 80ms
- Coordinator → Nginx: 1ms
- Nginx → Client: 40ms
- **TOTAL: ~292ms**

---

#### Step 6: User Executes Command
```python
# Same session - already knows which worker
result = client.execute("whoami")
```

**Flow:**
```
Client
  ↓ (40ms - California → New York)
Nginx (VPS 1)
  ↓ (1ms)
Coordinator
  │ Checks Redis: session:abc123:worker
  │ Found: http://203.0.113.30:5000
  │ (2ms - Redis query)
  ↓ (80ms - New York → California)
Worker 2 (VPS 3)
  │ Executes: docker exec ... whoami
  │ (20ms - command execution)
  ↓ (80ms - California → New York)
Coordinator
  ↓ (40ms - New York → California)
Client receives: "sandboxuser"
```

**Total Latency for Execute:**
- **~263ms**

---

## Latency Breakdown by Architecture

### Single VPS (Standalone Mode)
```
Client → Worker → Client
40ms + 1ms + 50ms + 1ms + 40ms = 132ms
```

### Multi-VPS (Distributed Mode)
```
Client → Nginx → Coordinator → Redis → Worker → Coordinator → Nginx → Client
40ms + 1ms + 2ms + 80ms + 50ms + 80ms + 1ms + 40ms = 294ms
```

**Latency Increase: ~162ms (122% slower)**

But wait! There's more to the story...

---

## Why Multi-VPS Despite Higher Latency?

### 1. **Horizontal Scalability**
```
Single VPS:  30 concurrent users max
Multi-VPS:   30 × N workers (90, 120, 300+)
```

### 2. **Geographic Distribution** (Reduces Latency!)

Instead of one coordinator in New York, you can have:

```
                    Global Traffic Manager
                    (Route53, Cloudflare)
                            │
              ┌─────────────┼─────────────┐
              │             │             │
        ┌─────▼──────┐ ┌────▼─────┐ ┌────▼─────┐
        │  US-East   │ │ US-West  │ │  EU      │
        │ Coordinator│ │Coordinator│ │Coordinator│
        │  + Redis   │ │ + Redis  │ │ + Redis  │
        └─────┬──────┘ └────┬─────┘ └────┬─────┘
              │             │             │
          Workers       Workers       Workers
```

**Result:**
- US-East user → 10ms to nearest coordinator
- US-West user → 10ms to nearest coordinator
- EU user → 10ms to nearest coordinator

**Now latency: ~100ms** (better than single VPS!)

### 3. **Fault Tolerance**

```
If VPS 2 (Worker 1) crashes:
  ├─ Coordinator detects via health check
  ├─ Routes new sessions to Worker 2 & 3
  └─ Existing sessions on Worker 1 fail gracefully
```

### 4. **Cost Efficiency**

**Single Big VPS:**
- 32GB RAM, 8 CPU cores = $160/month
- Single point of failure

**Multi-VPS:**
- 4 × 8GB VPS = $40 × 4 = $160/month
- Can remove/add servers as needed
- Distribute across regions

---

## Network Configuration Deep Dive

### Setup 1: Public Internet (Simplest)

**Coordinator config:**
```yaml
environment:
  - WORKERS=http://203.0.113.20:5000,http://203.0.113.30:5000
```

**Worker firewall:**
```bash
# Only allow coordinator IP
ufw allow from 203.0.113.10 to any port 5000
ufw deny 5000  # Block all others
```

**Pros:** Easy setup
**Cons:** Higher latency, uses bandwidth

---

### Setup 2: Private Network (Cloud Providers)

**DigitalOcean Private Network:**
```
VPS 1: 10.0.0.1 (coordinator)
VPS 2: 10.0.0.2 (worker1)
VPS 3: 10.0.0.3 (worker2)

Coordinator config:
  - WORKERS=http://10.0.0.2:5000,http://10.0.0.3:5000

Workers bind to private IP:
  app.run(host='10.0.0.2', port=5000)
```

**Pros:**
- Free bandwidth
- Lower latency (~10-30ms)
- More secure

**Cons:**
- Must use same cloud provider
- Same region usually

---

### Setup 3: WireGuard VPN (Best for Multi-Cloud)

```bash
# Install on all VPS
apt install wireguard

# VPS 1 (Coordinator) - 10.8.0.1
# VPS 2 (Worker1)     - 10.8.0.2
# VPS 3 (Worker2)     - 10.8.0.3

# Coordinator config:
WORKERS=http://10.8.0.2:5000,http://10.8.0.3:5000
```

**Pros:**
- Works across any providers (DigitalOcean + AWS + Linode)
- Encrypted
- Fast (~20-40ms)

**Cons:**
- Requires VPN setup

---

## Redis Session Tracking

**Why Redis is Critical:**

When Worker 2 creates a session, the container lives on VPS 3. Future requests for that session MUST go to VPS 3.

**Redis stores:**
```
session:abc123:worker → http://10.8.0.3:5000
session:def456:worker → http://10.8.0.2:5000
session:ghi789:worker → http://10.8.0.3:5000
```

**Without Redis:**
```
1. User creates session on Worker 2
2. Next request randomly goes to Worker 1
3. Worker 1 doesn't have that container
4. ERROR: Session not found ❌
```

**With Redis:**
```
1. User creates session on Worker 2
2. Coordinator stores: session → Worker 2
3. Next request checks Redis
4. Routes to Worker 2 ✓
5. Command executes successfully ✓
```

---

## Latency Optimization Strategies

### 1. **Regional Coordinators**
Deploy coordinator + workers in same region:
```
US-East Coordinator → US-East Workers: 1-5ms ✓
```

### 2. **Connection Pooling**
Coordinator maintains persistent connections to workers:
```python
# Instead of new connection each request:
session = requests.Session()  # Reuse TCP connections
```
Saves: ~20ms per request

### 3. **Redis Pipelining**
Batch Redis operations:
```python
pipe = redis_client.pipeline()
pipe.get(f"session:{id}:worker")
pipe.setex(f"session:{id}:lastaccess", 3600, time.time())
results = pipe.execute()
```
Saves: ~5ms

### 4. **HTTP/2**
Enable HTTP/2 in Nginx:
```nginx
listen 443 ssl http2;
```
Multiplexes requests, reduces handshakes.

---

## Real-World Latency Example

**Setup:**
- Coordinator: AWS US-East-1
- Worker 1: AWS US-East-1
- Worker 2: AWS US-West-2
- Worker 3: AWS EU-West-1

**User in New York creates session:**
```
Route to Worker 1 (same region): 150ms total
Route to Worker 2 (cross-US):    290ms total
Route to Worker 3 (cross-ocean): 450ms total
```

**Smart routing:** Always prefer same-region workers!

```python
def select_worker():
    # Prefer workers in same region
    local_workers = [w for w in workers if is_same_region(w)]
    if local_workers:
        return random.choice(local_workers)
    return random.choice(all_workers)  # Fallback
```

---

## Summary

### Multi-VPS Request Flow:
1. **Client → Nginx** (SSL termination)
2. **Nginx → Coordinator** (routing logic)
3. **Coordinator → Redis** (session lookup)
4. **Coordinator → Worker** (execute command)
5. **Worker → Coordinator → Client** (return result)

### Latency Impact:
- **Single VPS:** ~130ms
- **Multi-VPS (same region):** ~180ms (+38%)
- **Multi-VPS (cross-region):** ~300ms (+131%)
- **Multi-VPS (geo-distributed):** ~100ms (-23%) ✓

### When to Use Multi-VPS:
✓ Need 50+ concurrent users
✓ Want fault tolerance
✓ Global user base (geo-distribution)
✓ Cost optimization (small VPS vs big VPS)

### When to Stick with Single VPS:
✓ < 30 concurrent users
✓ Regional user base
✓ Simplicity priority
✓ Development/testing

**Key Insight:** The coordinator adds ~2-5ms overhead. The real latency comes from network distance between VPS servers. Optimize by keeping coordinator and workers in the same data center, or use geo-distributed coordinators!
