# Migration Guide: V1 → V2

Quick guide to upgrade from the basic sandbox to the enhanced version.

## What Changed?

### 🎯 Key Differences

1. **Non-root Execution**: Commands now run as `sandboxuser` (UID 1000) instead of root
2. **Container Pooling**: Pre-warmed containers for 40x faster session creation
3. **Distributed Support**: Optional multi-server setup with Redis
4. **File Uploads**: New endpoint for uploading files to sandbox
5. **Better Resource Management**: Automatic pool refilling

### 📦 Files Replaced

| V1 File | V2 File | Changes |
|---------|---------|---------|
| `sandbox_server.py` | `sandbox_server_v2.py` | + Pooling, + Redis, + Non-root |
| `sandbox_client.py` | `sandbox_client_v2.py` | + File upload, + Batch mode |
| `Dockerfile.sandbox` | `Dockerfile.secure` | + Non-root user |
| - | `coordinator.py` | NEW: Load balancer |
| - | `docker-compose.yml` | NEW: Distributed setup |

---

## 🚀 Migration Steps

### Step 1: Build New Secure Image

```bash
# Old V1 image (root user):
docker build -f Dockerfile.sandbox -t custom-sandbox:latest .

# New V2 image (non-root):
docker build -f Dockerfile.secure -t sandbox-secure:latest .
```

**Test the difference:**
```bash
# V1 - runs as root ❌
docker run --rm custom-sandbox:latest whoami
# Output: root

# V2 - runs as sandboxuser ✅
docker run --rm sandbox-secure:latest whoami
# Output: sandboxuser
```

### Step 2: Update Server

**Option A: Replace Existing Server**

```bash
# Stop V1 server
pkill -f sandbox_server.py

# Start V2 server
python sandbox_server_v2.py
```

**Option B: Run Both (Different Ports)**

```bash
# V1 on port 5000
python sandbox_server.py &

# V2 on port 5001
PORT=5001 python sandbox_server_v2.py &
```

### Step 3: Update Client Code

**Before (V1):**
```python
from sandbox_client import SandboxClient

client = SandboxClient("http://localhost:5000")
client.create_session()
result = client.execute("whoami")  # Returns: root
client.cleanup()
```

**After (V2):**
```python
from sandbox_client_v2 import SandboxClient

client = SandboxClient("http://localhost:5000")
client.create_session()
result = client.execute("whoami")  # Returns: sandboxuser
client.cleanup()
```

**No API changes!** Same methods, just different file name.

### Step 4: Verify Non-root Execution

```python
from sandbox_client_v2 import SandboxClient

with SandboxClient() as sandbox:
    # Check user
    result = sandbox.execute("id")
    print(result['output'])
    # Should show: uid=1000(sandboxuser)
    
    # Try root command (should fail)
    result = sandbox.execute("apt-get update")
    print(result['output'])
    # Should show permission error
```

---

## 🆕 New Features to Use

### 1. File Uploads (New!)

```python
# V2 only
with SandboxClient() as sandbox:
    # Upload a local file
    sandbox.upload_file("local_script.py", "script.py")
    
    # Execute it
    result = sandbox.execute("python3 script.py")
```

### 2. Batch Execution (New!)

```python
from sandbox_client_v2 import BatchSandboxClient

client = BatchSandboxClient()
results = client.execute_batch([
    "echo 'Step 1'",
    "echo 'Hello' > file.txt",
    "cat file.txt"
])
```

### 3. Container Pooling (Automatic)

V2 automatically maintains a pool of warm containers:

```python
# V1: ~2-5 seconds to create session
start = time.time()
client.create_session()
print(f"Took {time.time() - start}s")  # 2-5s

# V2: ~50-100ms to create session
start = time.time()
client.create_session()
print(f"Took {time.time() - start}s")  # 0.05-0.1s
```

---

## 🌐 Optional: Add Distribution

If you want to scale horizontally:

### Quick Setup with Docker Compose

```bash
# Build secure image
docker build -f Dockerfile.secure -t sandbox-secure:latest .

# Start distributed stack
docker-compose up -d

# Update client to use coordinator
client = SandboxClient("http://localhost:8000")  # Port 8000 for coordinator
```

### Manual Multi-VPS

See [SETUP_GUIDE_V2.md](SETUP_GUIDE_V2.md) for detailed instructions.

---

## 🔧 Configuration Changes

### V1 Configuration
```python
# sandbox_server.py
SESSION_TIMEOUT = timedelta(hours=1)
CONTAINER_IMAGE = "ubuntu:22.04"
MEMORY_LIMIT = "512m"
CPU_QUOTA = 50000
```

### V2 Configuration
```python
# sandbox_server_v2.py
SESSION_TIMEOUT = timedelta(hours=1)
CONTAINER_IMAGE = "sandbox-secure:latest"  # ← Changed
MEMORY_LIMIT = "512m"
CPU_QUOTA = 50000
POOL_SIZE = 5  # ← New
MIN_POOL_SIZE = 2  # ← New
MAX_POOL_SIZE = 20  # ← New
SANDBOX_USER = "sandboxuser"  # ← New
```

---

## 🐛 Common Issues

### Issue 1: Commands Still Run as Root

**Cause**: Using old image or wrong image name

**Fix**:
```bash
# Rebuild secure image
docker build -f Dockerfile.secure -t sandbox-secure:latest .

# Update server config
# In sandbox_server_v2.py:
CONTAINER_IMAGE = "sandbox-secure:latest"

# Restart server
```

### Issue 2: "Permission denied" Errors

**Cause**: Non-root user can't do root operations

**Expected behavior**: This is correct! V2 is more secure.

**Solution**: If you need specific capabilities, modify Dockerfile.secure to install them:
```dockerfile
# In Dockerfile.secure, BEFORE switching to sandboxuser:
RUN apt-get install -y some-package

# Then switch user:
USER sandboxuser
```

### Issue 3: Slower Than Advertised

**Cause**: Pool not initialized or too small

**Check**:
```bash
curl http://localhost:5000/health
```

Should show:
```json
{"pool_size": 5, ...}
```

If pool_size is 0 or low, increase:
```python
POOL_SIZE = 10
```

### Issue 4: Workers Not Found (Distributed Mode)

**Cause**: Workers not running or coordinator can't reach them

**Debug**:
```bash
# Test worker directly
curl http://worker-ip:5000/health

# Test coordinator
curl http://localhost:8000/health

# Check Redis
redis-cli -h redis-ip ping
```

---

## 📊 Performance Comparison

### Session Creation Speed

```python
import time
from sandbox_client import SandboxClient as V1Client
from sandbox_client_v2 import SandboxClient as V2Client

# Test V1
start = time.time()
v1 = V1Client("http://localhost:5000")
v1.create_session()
v1_time = time.time() - start
v1.cleanup()
print(f"V1: {v1_time:.3f}s")  # ~2-5s

# Test V2
start = time.time()
v2 = V2Client("http://localhost:5001")
v2.create_session()
v2_time = time.time() - start
v2.cleanup()
print(f"V2: {v2_time:.3f}s")  # ~0.05-0.1s

print(f"Speedup: {v1_time/v2_time:.1f}x faster!")
```

### User Verification

```python
# V1
with V1Client("http://localhost:5000") as client:
    result = client.execute("whoami")
    print(f"V1 user: {result['output'].strip()}")  # root

# V2
with V2Client("http://localhost:5001") as client:
    result = client.execute("whoami")
    print(f"V2 user: {result['output'].strip()}")  # sandboxuser
```

---

## ✅ Migration Checklist

- [ ] Build sandbox-secure:latest image
- [ ] Verify image runs as non-root (docker run ... whoami)
- [ ] Update to sandbox_server_v2.py
- [ ] Update client imports (sandbox_client_v2)
- [ ] Test session creation speed (~100ms)
- [ ] Verify commands run as sandboxuser
- [ ] Test file upload feature (optional)
- [ ] Set up distributed mode (optional)
- [ ] Update documentation for your team
- [ ] Monitor pool_size in health checks

---

## 🎯 Recommended Approach

### For Development
1. Start with standalone V2
2. Test non-root execution
3. Verify performance improvements
4. Add distributed mode if needed

### For Production
1. Deploy standalone V2 first
2. Monitor for 1-2 weeks
3. Add distributed mode for scaling
4. Set up Redis cluster for HA
5. Add monitoring and alerts

---

## 🆘 Rollback Plan

If you need to rollback to V1:

```bash
# Stop V2
pkill -f sandbox_server_v2.py

# Start V1
python sandbox_server.py

# Revert client code
# Change: from sandbox_client_v2 → from sandbox_client
```

---

## 📚 Additional Help

- **Setup Issues**: See [SETUP_GUIDE_V2.md](SETUP_GUIDE_V2.md)
- **Features**: See [README_V2.md](README_V2.md)
- **Architecture**: See docker-compose.yml

Questions? The V2 system is backward compatible at the API level, so migration should be smooth!
