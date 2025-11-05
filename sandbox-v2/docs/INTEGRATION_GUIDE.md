# Integration Guide: Enhanced Sandbox System V2

This guide covers integrating the Enhanced Sandbox System V2 with AI agents, applications, and other services.

## Table of Contents

1. [Quick Start](#quick-start)
2. [SDK Modes](#sdk-modes)
3. [AI Agent Integration](#ai-agent-integration)
4. [Configuration](#configuration)
5. [Best Practices](#best-practices)
6. [Troubleshooting](#troubleshooting)

---

## Quick Start

### Installation

```bash
# Install dependencies
cd sandbox-system/sandbox-v2
pip install -r requirements.txt

# Build the secure Docker image
docker build -f Dockerfile.secure -t sandbox-secure:latest .
```

### Basic Usage (Local Mode)

```python
from sandbox_client_v2 import SandboxClient

# Initialize client in local mode (no HTTP overhead)
client = SandboxClient(mode="local")

# Create session for a conversation thread
client.get_or_create_session(
    user_id="user123",
    thread_id="conversation_abc"
)

# Execute commands (files persist across commands!)
client.execute("echo '{\"data\": [1,2,3]}' > data.json")
result = client.execute("jq '.data | add' data.json")
print(result['stdout'])  # Output: 6

# List files in workspace
files = client.list_files()
print(f"Total files: {files['total_files']}")

# Cleanup when done
client.close_session()
```

### Basic Usage (Remote Mode)

```python
from sandbox_client_v2 import SandboxClient

# Initialize client in remote mode (HTTP calls to server)
client = SandboxClient(
    mode="remote",
    server_url="http://localhost:5000"
)

# Same API as local mode
client.get_or_create_session(
    user_id="user123",
    thread_id="conversation_abc"
)

# Execute commands
result = client.execute("ls -lh /workspace")
print(result['stdout'])

# Cleanup
client.close_session()
```

---

## SDK Modes

### Local Mode (Recommended for Development)

**When to use**:
- Development and testing
- Single-server deployments
- When you want zero HTTP overhead
- When you have direct access to Docker on the same machine

**Advantages**:
- **10-50ms faster** per command (no HTTP serialization)
- Direct stack traces for debugging
- Type-safe method calls (no JSON parsing)
- Simpler error handling

**Example**:
```python
client = SandboxClient(mode="local")
```

**Requirements**:
- Docker must be running on the same machine
- Server code must be importable (in Python path)

### Remote Mode (Recommended for Production)

**When to use**:
- Production deployments
- Distributed systems
- Horizontal scaling
- When sandbox server is on a different machine

**Advantages**:
- Horizontal scaling (multiple sandbox servers)
- Isolation (sandbox failures don't affect application)
- Resource management (dedicated sandbox machines)
- Network-based access control

**Example**:
```python
client = SandboxClient(
    mode="remote",
    server_url="http://sandbox-server:8000"
)
```

**Requirements**:
- Sandbox server running and accessible via HTTP
- Network connectivity to server

---

## AI Agent Integration

### Integration Pattern

For AI agents (like chatbots, assistants, etc.), use **thread-scoped sessions** where:
- **`thread_id`** = conversation ID (persistent across messages)
- **`user_id`** = user identifier (for logging/metrics)

This ensures:
- Files persist across multiple commands in the same conversation
- Each conversation has isolated state
- Sessions automatically expire after idle timeout

### Example: Bash Tool for AI Agent

```python
from sandbox_client_v2 import SandboxClient
from typing import Dict, Any

class BashTool:
    """
    Bash execution tool for AI agents.
    Maintains persistent session per conversation thread.
    """

    def __init__(self, mode: str = "local", server_url: str = None):
        """
        Initialize bash tool.

        Args:
            mode: "local" or "remote"
            server_url: Required if mode="remote"
        """
        self.mode = mode
        self.server_url = server_url
        self.client = SandboxClient(mode=mode, server_url=server_url)

    def execute(
        self,
        command: str,
        user_id: str,
        thread_id: str,
        timeout: int = 30
    ) -> Dict[str, Any]:
        """
        Execute bash command in thread-scoped sandbox.

        Args:
            command: Bash command to execute
            user_id: User identifier
            thread_id: Conversation thread ID
            timeout: Command timeout in seconds

        Returns:
            Dict with exit_code, stdout, stderr
        """
        # Get or create session for this thread (auto-reuses existing session)
        self.client.get_or_create_session(
            user_id=user_id,
            thread_id=thread_id,
            timeout_minutes=30
        )

        # Execute command (auto-retries if session expired)
        result = self.client.execute(command, timeout=timeout, auto_retry=True)

        return {
            'exit_code': result['exit_code'],
            'stdout': result['stdout'],
            'stderr': result['stderr'],
            'execution_time_ms': result.get('execution_time_ms', 0)
        }

    def upload_file(
        self,
        file_path: str,
        user_id: str,
        thread_id: str,
        remote_name: str = None
    ) -> Dict[str, Any]:
        """Upload file to sandbox workspace"""
        self.client.get_or_create_session(
            user_id=user_id,
            thread_id=thread_id
        )
        return self.client.upload_file(file_path, remote_name)

    def download_file(
        self,
        remote_name: str,
        user_id: str,
        thread_id: str,
        local_path: str = None
    ) -> str:
        """Download file from sandbox workspace"""
        self.client.get_or_create_session(
            user_id=user_id,
            thread_id=thread_id
        )
        return self.client.download_file(remote_name, local_path)

    def list_files(self, user_id: str, thread_id: str) -> Dict[str, Any]:
        """List files in sandbox workspace"""
        self.client.get_or_create_session(
            user_id=user_id,
            thread_id=thread_id
        )
        return self.client.list_files()

    def cleanup_session(self, thread_id: str = None):
        """Explicitly cleanup session (optional - auto-cleanup on timeout)"""
        if thread_id:
            self.client.thread_id = thread_id
        self.client.close_session()


# Usage in AI agent
bash_tool = BashTool(mode="local")

# Execute command in user's conversation
result = bash_tool.execute(
    command="jq '.data | length' input.json",
    user_id="user123",
    thread_id="conversation_abc"
)

print(f"Exit code: {result['exit_code']}")
print(f"Output: {result['stdout']}")
```

### Agent System Prompt Updates

**Remove these patterns** (no longer needed with persistent sessions):
```
IMPORTANT: If your command needs data from files, you must inline the data using heredocs.
DO NOT create files and reference them, as files don't persist across executions.
```

**Add these patterns**:
```
Files persist across bash commands within your conversation.
You can create files in one command and use them in subsequent commands.

Example workflow:
1. echo '{"data": [1,2,3]}' > input.json
2. jq '.data | add' input.json

The file input.json created in step 1 will be available in step 2.
```

---

## Configuration

### Environment Variables

```bash
# Server Configuration
PORT=5000                    # Server port
HOST=0.0.0.0                # Bind address
WORKER_ID=worker1           # Worker identifier (for distributed mode)

# Container Pool
POOL_SIZE=10                # Initial pool size
MIN_POOL_SIZE=3             # Minimum pool size
MAX_POOL_SIZE=80            # Maximum pool size
AGGRESSIVE_CLEANUP=true     # Destroy idle containers aggressively

# Session Management
SESSION_TIMEOUT_MINUTES=30          # Session expiry (default: 30 min)
CONTAINER_IDLE_TIMEOUT_MINUTES=5    # Idle container cleanup (default: 5 min)
CLEANUP_INTERVAL_SECONDS=300        # Cleanup check interval (default: 5 min)

# Resource Limits (NEW in V2)
MAX_FILE_SIZE_MB=100           # Max file upload size
MAX_TOTAL_FILES=1000           # Max files per workspace
MAX_WORKSPACE_SIZE_MB=500      # Max workspace size

# Container Resources
CONTAINER_IMAGE=sandbox-secure:latest
MEMORY_LIMIT=256m              # Memory limit per container
CPU_QUOTA=25000                # CPU quota (25% of 1 core)
SANDBOX_USER=sandboxuser       # Non-root user
WORKSPACE_DIR=/workspace       # Workspace directory

# Redis (Optional - for distributed mode)
REDIS_HOST=redis               # Redis host (leave unset for standalone)
REDIS_PORT=6379                # Redis port

# Docker Configuration
DOCKER_NETWORK_MODE=none       # No network access for security
```

### Deployment Modes

#### Standalone Mode (Development)

```bash
# Start server
cd sandbox-system/sandbox-v2
python server.py
```

#### Distributed Mode (Production)

```yaml
# docker-compose.yml
version: '3.8'

services:
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

  worker1:
    build:
      context: .
      dockerfile: Dockerfile.worker
    environment:
      - REDIS_HOST=redis
      - WORKER_ID=worker1
      - POOL_SIZE=10
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
    depends_on:
      - redis

  worker2:
    build:
      context: .
      dockerfile: Dockerfile.worker
    environment:
      - REDIS_HOST=redis
      - WORKER_ID=worker2
      - POOL_SIZE=10
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
    depends_on:
      - redis

  coordinator:
    build:
      context: .
      dockerfile: Dockerfile.coordinator
    ports:
      - "8000:8000"
    environment:
      - REDIS_HOST=redis
      - WORKERS=http://worker1:5000,http://worker2:5000
    depends_on:
      - redis
      - worker1
      - worker2
```

```bash
# Start distributed system
docker-compose up -d

# Use coordinator URL in client
client = SandboxClient(mode="remote", server_url="http://localhost:8000")
```

---

## Best Practices

### 1. Session Management

**DO**: Use thread-scoped sessions
```python
# ✅ Correct: One session per conversation
client.get_or_create_session(
    user_id="user123",
    thread_id="conversation_abc"  # Same thread_id for entire conversation
)
```

**DON'T**: Create new session for each command
```python
# ❌ Wrong: Don't create new session each time
for command in commands:
    client.get_or_create_session(...)  # Creates unnecessary sessions
    client.execute(command)
```

### 2. Error Handling

```python
from sandbox_client_v2 import SessionExpiredError
import requests

try:
    result = client.execute(command, auto_retry=True)
except SessionExpiredError:
    # Session expired and auto-retry failed
    logger.error("Session permanently expired")
except requests.HTTPError as e:
    # HTTP error (remote mode only)
    logger.error(f"HTTP error: {e.response.status_code}")
except ValueError as e:
    # Command validation failed
    logger.error(f"Invalid command: {e}")
except Exception as e:
    # Other errors
    logger.error(f"Execution failed: {e}")
```

### 3. File Operations

```python
# Upload file to sandbox
client.upload_file("/local/data.csv", remote_name="input.csv")

# Process in sandbox
result = client.execute("head -5 input.csv")

# Download result
client.download_file("output.csv", local_path="/local/output.csv")
```

### 4. Cleanup

```python
# Implicit cleanup (recommended)
# Sessions auto-expire after SESSION_TIMEOUT_MINUTES of inactivity

# Explicit cleanup (optional)
client.close_session()

# Context manager (auto-cleanup)
with SandboxClient(mode="local") as client:
    client.get_or_create_session(user_id="...", thread_id="...")
    client.execute("ls -lh")
    # Auto-cleanup on exit
```

### 5. Resource Limits

Monitor and adjust based on your workload:

```python
# Check workspace usage
files = client.list_files()
print(f"Files: {files['total_files']}/{MAX_TOTAL_FILES}")
print(f"Size: {files['total_size_bytes'] / 1024 / 1024:.2f} MB / {MAX_WORKSPACE_SIZE_MB} MB")
```

### 6. Security

**Command Validation** (server-side):
- Whitelist: Only allowed commands can run
- Blacklist: Forbidden patterns are blocked
- Both client and server validate (defense in depth)

**Allowed Commands**:
```python
jq, awk, grep, sed, sort, uniq, head, tail, wc, cut, tr,
cat, echo, date, find, ls, python3, python, bc, comm, diff,
basename, dirname, file, stat, tee
```

**Forbidden Patterns**:
```python
rm, mv, dd, curl, wget, ssh, sudo, chmod, chown
```

**Container Security**:
- Non-root user (`sandboxuser`)
- No network access (`network_mode=none`)
- Resource limits (CPU, memory)
- Isolated workspace (`/workspace`)

---

## Troubleshooting

### Issue: "No active session" error

**Cause**: Forgot to call `get_or_create_session()`

**Solution**:
```python
# Always call get_or_create_session before execute
client.get_or_create_session(user_id="...", thread_id="...")
result = client.execute(command)
```

### Issue: Session expired errors

**Cause**: Session exceeded `SESSION_TIMEOUT_MINUTES` of inactivity

**Solution**:
```python
# Enable auto-retry (default)
result = client.execute(command, auto_retry=True)

# Or increase session timeout
SESSION_TIMEOUT_MINUTES=60  # in .env
```

### Issue: "Pool at max capacity" error

**Cause**: Too many concurrent sessions

**Solution**:
```bash
# Increase pool size
MAX_POOL_SIZE=100  # in .env

# Or enable aggressive cleanup
AGGRESSIVE_CLEANUP=true  # in .env
```

### Issue: "File size exceeds maximum" error

**Cause**: File upload exceeds `MAX_FILE_SIZE_MB`

**Solution**:
```bash
# Increase file size limit
MAX_FILE_SIZE_MB=200  # in .env
```

### Issue: Command validation failed

**Cause**: Command uses forbidden command or pattern

**Solution**:
```python
# Check allowed commands
ALLOWED_COMMANDS = {
    'jq', 'awk', 'grep', 'sed', 'sort', 'uniq', 'head',
    'tail', 'wc', 'cut', 'tr', 'cat', 'echo', 'date',
    'find', 'ls', 'python3', 'python', ...
}

# Rewrite command using allowed commands only
# ❌ client.execute("wget https://example.com/data.json")
# ✅ Use upload_file() instead
```

### Issue: "Failed to import server for local mode"

**Cause**: Server code not in Python path

**Solution**:
```python
import sys
sys.path.insert(0, '/path/to/sandbox-v2')
from sandbox_client_v2 import SandboxClient

client = SandboxClient(mode="local")
```

### Issue: Slow performance in remote mode

**Cause**: HTTP overhead per command

**Solution**:
```python
# Switch to local mode if possible
client = SandboxClient(mode="local")

# Or batch commands
result = client.execute("cmd1 && cmd2 && cmd3")
```

---

## Migration Guide

### From Cloudflare Sandbox

**Before** (Cloudflare Worker):
```python
# Create new sandbox for each command
result = requests.post(
    "https://worker.example.workers.dev/execute",
    json={"command": "jq '.data' <<< '{\"data\": [1,2,3]}'"}
)

# Heredoc workaround needed (files don't persist)
command = """jq '.data | add' <<< '{"data": [1,2,3]}'"""
```

**After** (Enhanced Sandbox V2):
```python
# Session persists across commands
client = SandboxClient(mode="local")
client.get_or_create_session(user_id="...", thread_id="...")

# Files persist! No heredoc needed
client.execute("echo '{\"data\": [1,2,3]}' > input.json")
result = client.execute("jq '.data | add' input.json")
```

### From V1 Sandbox

**Before** (V1):
```python
# Manual session management
session_id = create_session()
execute(session_id, "ls")
cleanup(session_id)
```

**After** (V2):
```python
# Automatic session management
client.get_or_create_session(user_id="...", thread_id="...")
client.execute("ls")  # Auto-retries on expiry
# Auto-cleanup on timeout
```

---

## Performance Benchmarks

### Local Mode vs Remote Mode

| Operation | Local Mode | Remote Mode | Difference |
|-----------|-----------|-------------|------------|
| Session creation | 50ms | 120ms | +70ms (HTTP) |
| Simple command | 15ms | 45ms | +30ms (HTTP) |
| File upload (1MB) | 80ms | 150ms | +70ms (HTTP) |
| File download (1MB) | 75ms | 140ms | +65ms (HTTP) |
| List files | 10ms | 35ms | +25ms (HTTP) |

**Recommendation**: Use local mode for latency-sensitive applications (AI agents, interactive tools). Use remote mode for scalability and isolation.

---

## Support

For issues, questions, or feature requests:

1. Check this guide and [README_V2.md](./README_V2.md)
2. Review [SETUP_GUIDE_V2.md](./SETUP_GUIDE_V2.md) for deployment
3. Check server logs for error details
4. Open an issue on GitHub (if applicable)

---

## Appendix: API Reference

### SandboxClient Methods

#### `__init__(mode, server_url)`
Initialize client in local or remote mode.

#### `get_or_create_session(user_id, thread_id, timeout_minutes)`
Get existing session or create new one for thread.

#### `execute(command, timeout, auto_retry)`
Execute bash command with auto-retry on session expiry.

#### `upload_file(file_path, remote_name)`
Upload file to sandbox workspace.

#### `download_file(remote_name, local_path)`
Download file from sandbox workspace.

#### `list_files()`
List all files in workspace with metadata.

#### `close_session()`
Explicitly cleanup session (optional).

### Return Types

**execute()**:
```python
{
    'exit_code': int,       # 0 = success, non-zero = error
    'stdout': str,          # Standard output
    'stderr': str,          # Standard error
    'execution_time_ms': int  # Execution time in milliseconds
}
```

**list_files()**:
```python
{
    'session_id': str,
    'workspace_dir': str,
    'files': [
        {
            'name': str,
            'size_bytes': int,
            'modified': str,  # ISO 8601 format
            'permissions': str
        },
        ...
    ],
    'total_files': int,
    'total_size_bytes': int
}
```

**upload_file()**:
```python
{
    'status': 'uploaded',
    'filename': str,
    'path': str,
    'size_bytes': int
}
```

**download_file()**:
```python
str  # Path to downloaded file
```
