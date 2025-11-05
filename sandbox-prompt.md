# Enhanced Sandbox System V2 - Implementation Prompt

## Overview

Build an enhanced Docker-based sandbox system for executing bash commands. The system must support **persistent, thread-scoped sessions** with file upload/download capabilities, automatic session management, and robust security controls.

**Key Architecture Decisions**:
- **API Framework**: FastAPI + Uvicorn (async, high performance, type-safe)
- **Client SDK**: Python SDK that supports both local (in-process) and remote (HTTP) modes
- **Deployment Modes**:
  - **Local Mode**: In-process SDK calls for development/single-server (zero HTTP overhead)
  - **Remote Mode**: HTTP calls to distributed sandbox servers for production scaling

**Note**: For integration with AI agents and other systems, see `INTEGRATION_GUIDE.md`.

## Core Architecture Principles

### 1. Session Scoping Strategy

**CRITICAL**: Sessions are mapped by `thread_id` (conversation ID), NOT `user_id`.

**Rationale**:
- A single user can have multiple concurrent conversations (different browser tabs, devices)
- Each conversation needs isolated filesystem state
- Prevents file collisions and cross-conversation pollution

**Session Lifecycle**:
```
User starts conversation → thread_id generated → sandbox session created
├─ Multiple bash commands execute in same session
├─ Files persist across commands within conversation
├─ Session auto-expires after idle timeout (default: 30 min)
└─ Explicit cleanup on conversation end (optional)
```

### 2. Technology Stack

**Base**: Enhance existing `sandbox-v2/` implementation
- **Container Runtime**: Docker with pre-warmed container pooling (keep existing)
- **Security**: Non-root execution as `sandboxuser` (keep existing)
- **State Management**: Redis for distributed mode, in-memory for standalone (keep existing)
- **API Framework**: FastAPI with Uvicorn (async support, better performance)
- **Client**: Python SDK (direct import, no HTTP overhead for local deployments)

### 3. Key Enhancements Over Current V2

| Feature | Current V2 | Enhanced V2 |
|---------|-----------|-------------|
| Session Mapping | `session_id` (UUID) | `thread_id` → `session_id` mapping |
| Session Reuse | Manual | Automatic via `get_or_create_session` |
| File Download | ❌ Missing | ✅ `/download_file` endpoint |
| File Listing | ❌ Missing | ✅ `/list_files` endpoint |
| Command Validation | Client-side only | ✅ Server-side + client-side |
| Resource Limits | Container limits only | ✅ File size + count limits |
| Auto-Retry | ❌ Missing | ✅ Client auto-recreates expired sessions |

## SDK Architecture

### Client-Server Model

The sandbox system provides a **SandboxClient SDK** that can operate in two modes:

```python
from sandbox_client_v2 import SandboxClient

# Local mode: Direct in-process calls (no HTTP)
client = SandboxClient(mode="local")

# Remote mode: HTTP calls to remote server
client = SandboxClient(mode="remote", server_url="http://sandbox-server:8000")

# Same API for both modes
result = client.execute("jq '.data' file.json")
```

**Deployment Modes**:
1. **Local Mode** (Development/Single Server): SDK calls server methods directly (in-process)
2. **Remote Mode** (Production/Distributed): SDK makes HTTP calls to remote sandbox servers

**Benefits**:
- **Local Mode**: Zero HTTP overhead, faster execution, simpler debugging
- **Remote Mode**: Horizontal scaling, isolation, resource management
- **Same API**: Client code doesn't change between modes

---

## API Specification

### Endpoint 1: Create Session

**Purpose**: Create a new sandbox session for a conversation thread.

**HTTP API** (Remote Mode):
```http
POST /create_session
Content-Type: application/json

{
  "user_id": "user_abc123",
  "thread_id": "thread_xyz789",
  "timeout_minutes": 30
}
```

**SDK API** (Local/Remote Mode):
```python
session = client.get_or_create_session(
    user_id="user_abc123",
    thread_id="thread_xyz789",
    timeout_minutes=30
)
```

**Response** (200 OK):
```json
{
  "session_id": "sess_uuid_here",
  "thread_id": "thread_xyz789",
  "status": "created",
  "workspace_dir": "/workspace",
  "user": "sandboxuser",
  "expires_at": "2025-11-05T15:30:00Z"
}
```

**Response** (409 Conflict - session already exists):
```json
{
  "session_id": "sess_existing_uuid",
  "thread_id": "thread_xyz789",
  "status": "existing",
  "workspace_dir": "/workspace",
  "created_at": "2025-11-05T14:00:00Z",
  "last_activity": "2025-11-05T14:45:00Z"
}
```

**Implementation Notes**:
- Check if session exists for `thread_id` before creating
- If exists and not expired, return existing session (409 status)
- If exists but expired, cleanup old session and create new one
- Store mapping: `thread_id` → `session_id` in Redis/memory
- Initialize container from pool (existing v2 logic)

---

### Endpoint 2: Get Session

**Purpose**: Check if an active session exists for a thread.

```http
GET /get_session?thread_id=thread_xyz789
```

**Response** (200 OK):
```json
{
  "session_id": "sess_uuid_here",
  "thread_id": "thread_xyz789",
  "status": "active",
  "created_at": "2025-11-05T14:00:00Z",
  "last_activity": "2025-11-05T14:45:00Z",
  "workspace_dir": "/workspace",
  "files_count": 5
}
```

**Response** (404 Not Found):
```json
{
  "error": "No active session found for thread_id",
  "thread_id": "thread_xyz789"
}
```

---

### Endpoint 3: Execute Command

**Purpose**: Execute bash command in session's container.

```http
POST /execute
Content-Type: application/json

{
  "session_id": "sess_uuid_here",
  "command": "jq '.[] | select(.amount > 100)' data.json",
  "timeout": 30
}
```

**Response** (200 OK):
```json
{
  "exit_code": 0,
  "stdout": "{\"id\": 1, \"amount\": 150}\n{\"id\": 3, \"amount\": 200}\n",
  "stderr": "",
  "execution_time_ms": 45
}
```

**Response** (404 Not Found):
```json
{
  "error": "Invalid or expired session",
  "session_id": "sess_uuid_here"
}
```

**Response** (400 Bad Request - validation failed):
```json
{
  "error": "Command contains forbidden pattern: \\brm\\b",
  "command": "rm -rf /workspace/*",
  "forbidden_pattern": "\\brm\\b"
}
```

**Implementation Notes**:
- **Server-side validation** (defense in depth):
  - Whitelist: `jq`, `awk`, `grep`, `sed`, `sort`, `uniq`, `head`, `tail`, `wc`, `cut`, `tr`, `cat`, `echo`, `date`, `find`, `ls`, `python3`, `python`
  - Blacklist patterns: `\brm\b`, `\bmv\b`, `\bdd\b`, `\bcurl\b`, `\bwget\b`, `\bssh\b`, `\bsudo\b`
- Update `last_activity` timestamp
- Execute as `sandboxuser` in `/workspace`
- Capture stdout/stderr separately
- Return execution time for observability

---

### Endpoint 4: Upload File

**Purpose**: Upload a file to the session's workspace.

```http
POST /upload_file
Content-Type: multipart/form-data

session_id: sess_uuid_here
file: <binary data>
filename: data.json (optional, defaults to uploaded filename)
```

**Response** (200 OK):
```json
{
  "status": "uploaded",
  "filename": "data.json",
  "path": "/workspace/data.json",
  "size_bytes": 2048
}
```

**Response** (413 Payload Too Large):
```json
{
  "error": "File size exceeds maximum allowed size",
  "max_size_mb": 100,
  "uploaded_size_mb": 150
}
```

**Response** (507 Insufficient Storage):
```json
{
  "error": "Workspace size limit exceeded",
  "max_workspace_mb": 500,
  "current_workspace_mb": 480,
  "file_size_mb": 50
}
```

**Implementation Notes**:
- Validate file size: `MAX_FILE_SIZE = 100MB`
- Check total workspace size: `MAX_WORKSPACE_SIZE = 500MB`
- Check file count: `MAX_TOTAL_FILES = 1000`
- Use tarfile to upload to container (existing v2 logic)
- Fix permissions: `chown sandboxuser:sandboxuser`
- Update `last_activity` timestamp

---

### Endpoint 5: Download File (NEW)

**Purpose**: Download a file from the session's workspace.

```http
POST /download_file
Content-Type: application/json

{
  "session_id": "sess_uuid_here",
  "filename": "output.csv"
}
```

**Response** (200 OK):
```http
Content-Type: application/octet-stream
Content-Disposition: attachment; filename="output.csv"

<binary file data>
```

**Response** (404 Not Found):
```json
{
  "error": "File not found in workspace",
  "filename": "output.csv",
  "workspace_dir": "/workspace"
}
```

**Implementation Notes**:
- Use `container.get_archive()` to retrieve file as tar stream
- Extract file from tar and return as binary response
- Validate filename (no path traversal: `../`, absolute paths)
- Update `last_activity` timestamp
- Add file size to response headers

---

### Endpoint 6: List Files (NEW)

**Purpose**: List all files in the session's workspace.

```http
GET /list_files?session_id=sess_uuid_here
```

**Response** (200 OK):
```json
{
  "session_id": "sess_uuid_here",
  "workspace_dir": "/workspace",
  "files": [
    {
      "name": "data.json",
      "size_bytes": 2048,
      "modified": "2025-11-05T14:30:00Z",
      "permissions": "-rw-r--r--"
    },
    {
      "name": "output.csv",
      "size_bytes": 5120,
      "modified": "2025-11-05T14:35:00Z",
      "permissions": "-rw-r--r--"
    }
  ],
  "total_files": 2,
  "total_size_bytes": 7168
}
```

**Implementation Notes**:
- Execute `ls -la --time-style=iso /workspace` in container
- Parse output to extract file metadata
- Exclude `.` and `..` entries
- Return sorted by modification time (newest first)

---

### Endpoint 7: Cleanup Session

**Purpose**: Explicitly cleanup a session and release resources.

```http
POST /cleanup
Content-Type: application/json

{
  "session_id": "sess_uuid_here"
}
```

**Response** (200 OK):
```json
{
  "status": "cleaned_up",
  "session_id": "sess_uuid_here"
}
```

**Implementation Notes**:
- Remove session from active sessions map
- Remove thread_id → session_id mapping
- Return container to pool (existing v2 logic)
- If container is dirty, destroy and create fresh one

---

### Endpoint 8: Health Check

**Purpose**: System health and metrics.

```http
GET /health
```

**Response** (200 OK):
```json
{
  "status": "healthy",
  "worker_id": "worker1",
  "pool_size": 10,
  "pool_available": 7,
  "active_sessions": 3,
  "uptime_seconds": 86400,
  "redis_connected": true
}
```

---

## Client Implementation (SDK)

### Python Client Class

**File**: `sandbox-system/sandbox-v2/sandbox_client_v2.py` (enhance existing)

**Key Requirements**:

1. **Thread-based session management** (not user-based)
2. **Auto-retry on session expiry**
3. **Simple interface for bash tool integration**
4. **Context manager support**
5. **Support both local and remote modes**

**Interface**:

```python
from typing import Optional, Dict, Any, Literal
import requests

# Custom exception for local mode
class SessionExpiredError(Exception):
    """Raised when session is expired in local mode"""
    pass

class SandboxClient:
    """
    Enhanced SDK client with thread-scoped sessions and auto-retry.

    Supports two modes:
    - local: Direct in-process calls (no HTTP overhead)
    - remote: HTTP calls to remote sandbox server
    """

    def __init__(
        self,
        mode: Literal["local", "remote"] = "local",
        server_url: Optional[str] = None
    ):
        """
        Initialize sandbox client.

        Args:
            mode: "local" for in-process, "remote" for HTTP
            server_url: Required for remote mode (e.g., "http://localhost:8000")
        """
        self.mode = mode
        self.server_url = server_url.rstrip('/') if server_url else None
        self.session_id: Optional[str] = None
        self.thread_id: Optional[str] = None
        self.user_id: Optional[str] = None

        # For local mode, import server instance
        if mode == "local":
            from sandbox_v2.server import SandboxServer
            self._server = SandboxServer()
        else:
            if not server_url:
                raise ValueError("server_url required for remote mode")
            self._server = None

    def get_or_create_session(
        self,
        user_id: str,
        thread_id: str,
        timeout_minutes: int = 30
    ) -> Dict[str, Any]:
        """
        Get existing session for thread_id or create new one.

        This is the PRIMARY method for session initialization.
        Replaces the old create_session() method.

        Args:
            user_id: User identifier (for logging/metrics)
            thread_id: Conversation/thread identifier (PRIMARY KEY)
            timeout_minutes: Session idle timeout

        Returns:
            Session info dict with session_id, status, workspace_dir
        """
        # Step 1: Check if session exists
        if self.mode == "local":
            # Direct method call (no HTTP)
            session_info = self._server.get_session_by_thread(thread_id)
            if session_info:
                self.session_id = session_info['session_id']
                self.thread_id = thread_id
                self.user_id = user_id
                return session_info

            # Create new session
            session_info = self._server.create_session(user_id, thread_id, timeout_minutes)
            self.session_id = session_info['session_id']
            self.thread_id = thread_id
            self.user_id = user_id
            return session_info
        else:
            # Remote mode: HTTP calls
            try:
                response = requests.get(
                    f"{self.server_url}/get_session",
                params={"thread_id": thread_id},
                timeout=5
            )
            if response.status_code == 200:
                # Session exists, reuse it
                data = response.json()
                self.session_id = data['session_id']
                self.thread_id = thread_id
                self.user_id = user_id
                return data
            except requests.RequestException:
                pass  # Session doesn't exist, create new one

            # Step 2: Create new session
            response = requests.post(
                f"{self.server_url}/create_session",
                json={
                    "user_id": user_id,
                    "thread_id": thread_id,
                    "timeout_minutes": timeout_minutes
                },
                timeout=10
            )
            response.raise_for_status()

            data = response.json()
            self.session_id = data['session_id']
            self.thread_id = thread_id
            self.user_id = user_id

            return data

    def execute(
        self,
        command: str,
        timeout: int = 30,
        auto_retry: bool = True
    ) -> Dict[str, Any]:
        """
        Execute bash command with auto-retry on session expiry.

        Args:
            command: Bash command to execute
            timeout: Command timeout in seconds
            auto_retry: Auto-recreate session if expired

        Returns:
            Dict with exit_code, stdout, stderr, execution_time_ms
        """
        if not self.session_id:
            raise ValueError("No active session. Call get_or_create_session() first.")

        try:
            return self._execute_internal(command, timeout)
        except (requests.HTTPError, SessionExpiredError) as e:
            # Handle both HTTP 404 (remote) and SessionExpiredError (local)
            is_expired = (
                (isinstance(e, requests.HTTPError) and e.response.status_code == 404) or
                isinstance(e, SessionExpiredError)
            )
            if is_expired and auto_retry:
                # Session expired, recreate and retry
                logger.info(f"Session expired for thread {self.thread_id}, recreating...")
                self.get_or_create_session(
                    user_id=self.user_id,
                    thread_id=self.thread_id
                )
                return self._execute_internal(command, timeout)
            raise

    def _execute_internal(self, command: str, timeout: int) -> Dict[str, Any]:
        """Internal execute without retry logic"""
        if self.mode == "local":
            # Direct method call
            return self._server.execute_command(self.session_id, command, timeout)
        else:
            # Remote HTTP call
            response = requests.post(
                f"{self.server_url}/execute",
                json={
                    "session_id": self.session_id,
                    "command": command,
                    "timeout": timeout
                },
                timeout=timeout + 5
            )
            response.raise_for_status()
            return response.json()

    def upload_file(
        self,
        file_path: str,
        remote_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """Upload file to workspace"""
        if not self.session_id:
            raise ValueError("No active session.")

        import os
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        filename = remote_name or os.path.basename(file_path)

        if self.mode == "local":
            # Direct method call
            with open(file_path, 'rb') as f:
                file_data = f.read()
            return self._server.upload_file(self.session_id, filename, file_data)
        else:
            # Remote HTTP call
            with open(file_path, 'rb') as f:
                files = {'file': (filename, f)}
                response = requests.post(
                    f"{self.server_url}/upload_file",
                    files=files,
                    data={'session_id': self.session_id},
                    timeout=60
                )

            response.raise_for_status()
            return response.json()

    def download_file(
        self,
        remote_name: str,
        local_path: Optional[str] = None
    ) -> str:
        """
        Download file from workspace.

        Args:
            remote_name: Filename in workspace
            local_path: Local path to save (defaults to current dir)

        Returns:
            Path to downloaded file
        """
        if not self.session_id:
            raise ValueError("No active session.")

        if self.mode == "local":
            # Direct method call
            file_data = self._server.download_file(self.session_id, remote_name)
            import os
            save_path = local_path or os.path.join(os.getcwd(), remote_name)
            with open(save_path, 'wb') as f:
                f.write(file_data)
            return save_path
        else:
            # Remote HTTP call
            response = requests.post(
                f"{self.server_url}/download_file",
                json={
                    "session_id": self.session_id,
                    "filename": remote_name
                },
                timeout=60
            )
            response.raise_for_status()

            # Save to local path
            import os
            save_path = local_path or os.path.join(os.getcwd(), remote_name)
            with open(save_path, 'wb') as f:
                f.write(response.content)

            return save_path

    def list_files(self) -> Dict[str, Any]:
        """List all files in workspace"""
        if not self.session_id:
            raise ValueError("No active session.")

        if self.mode == "local":
            return self._server.list_files(self.session_id)
        else:
            response = requests.get(
                f"{self.server_url}/list_files",
                params={"session_id": self.session_id},
                timeout=5
            )
            response.raise_for_status()
            return response.json()

    def close_session(self):
        """Explicitly cleanup session"""
        if self.session_id:
            try:
                if self.mode == "local":
                    self._server.cleanup_session(self.session_id)
                else:
                    requests.post(
                        f"{self.server_url}/cleanup",
                        json={'session_id': self.session_id},
                        timeout=10
                    )
            except Exception as e:
                logger.warning(f"Cleanup failed: {e}")
            finally:
                self.session_id = None
                self.thread_id = None
                self.user_id = None

    def __enter__(self):
        """Context manager support"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Auto-cleanup on exit"""
        self.close_session()
```

---

## Server Implementation

### File Structure

```
sandbox-system/sandbox-v2/
├── server.py                    # ENHANCE: FastAPI + new endpoints + thread_id mapping
├── sandbox_client_v2.py         # ENHANCE: Add methods above
├── settings.py                  # ENHANCE: Add resource limits
├── coordinator.py               # ENHANCE: Update for FastAPI
├── Dockerfile.secure            # KEEP: Non-root image
├── docker-compose.yml           # KEEP: Distributed setup
└── requirements.txt             # UPDATE: FastAPI, uvicorn instead of Flask
```

### Technology: FastAPI + Uvicorn

**Why FastAPI over Flask**:
- **Async support**: Better concurrency for I/O-bound operations
- **Type safety**: Pydantic models for request/response validation
- **Performance**: 2-3x faster than Flask for typical workloads
- **Auto docs**: Built-in OpenAPI/Swagger documentation
- **Modern**: Better async/await support for Docker SDK operations

**Server Structure**:

```python
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import Response
from pydantic import BaseModel
import uvicorn

app = FastAPI(title="Sandbox System V2")

# Pydantic models for request/response validation
class CreateSessionRequest(BaseModel):
    user_id: str
    thread_id: str
    timeout_minutes: int = 30

class ExecuteRequest(BaseModel):
    session_id: str
    command: str
    timeout: int = 30

class DownloadRequest(BaseModel):
    session_id: str
    filename: str

class CleanupRequest(BaseModel):
    session_id: str

# ... endpoints below ...

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, workers=1)
```

### Key Server Changes

**File**: `sandbox-system/sandbox-v2/server.py`

**Note**: The server can be used in two ways:
1. **HTTP Mode**: Run with `uvicorn server:app` for remote access (production)
2. **Direct Mode**: Import `SandboxServer` class for in-process SDK calls (development)

#### 0. Add SandboxServer Class (for Local Mode)

For local mode SDK usage, create a `SandboxServer` class that provides direct method access:

```python
class SandboxServer:
    """
    Server class for direct (non-HTTP) usage in local mode.
    Provides the same functionality as HTTP endpoints but as direct method calls.
    """

    def __init__(self):
        """Initialize server components"""
        self.pool = ContainerPool()  # Initialize container pool
        self.sessions: Dict[str, Dict] = {}  # In-memory session storage
        self.thread_to_session: Dict[str, str] = {}  # thread_id → session_id

    def get_session_by_thread(self, thread_id: str) -> Optional[Dict]:
        """Get session info by thread_id (direct method call)"""
        session_id = self.thread_to_session.get(thread_id)
        if not session_id:
            return None

        session_data = self.sessions.get(session_id)
        if not session_data:
            # Stale mapping, cleanup
            del self.thread_to_session[thread_id]
            return None

        return {
            'session_id': session_id,
            'thread_id': thread_id,
            'status': 'active',
            'created_at': session_data.get('created_at'),
            'last_activity': session_data.get('last_activity'),
            'workspace_dir': settings.WORKSPACE_DIR
        }

    def create_session(self, user_id: str, thread_id: str, timeout_minutes: int = 30) -> Dict:
        """Create new session (direct method call)"""
        # Check if session already exists
        existing_session_id = self.thread_to_session.get(thread_id)
        if existing_session_id and existing_session_id in self.sessions:
            session_data = self.sessions[existing_session_id]
            return {
                'session_id': existing_session_id,
                'thread_id': thread_id,
                'status': 'existing',
                'workspace_dir': settings.WORKSPACE_DIR,
                'user': settings.SANDBOX_USER,
                'created_at': session_data.get('created_at'),
                'last_activity': session_data.get('last_activity')
            }

        # Create new session
        session_id = str(uuid.uuid4())
        container = self.pool.get_container()
        if not container:
            raise Exception("Pool at max capacity")

        # Store session
        self.sessions[session_id] = {
            'container_id': container.id,
            'user_id': user_id,
            'thread_id': thread_id,
            'created_at': datetime.now().isoformat(),
            'last_activity': datetime.now().isoformat()
        }

        # Store thread mapping
        self.thread_to_session[thread_id] = session_id

        return {
            'session_id': session_id,
            'thread_id': thread_id,
            'status': 'created',
            'workspace_dir': settings.WORKSPACE_DIR,
            'user': settings.SANDBOX_USER,
            'expires_at': (datetime.now() + timedelta(minutes=timeout_minutes)).isoformat()
        }

    def execute_command(self, session_id: str, command: str, timeout: int = 30) -> Dict:
        """Execute command in session (direct method call)"""
        session_data = self.sessions.get(session_id)
        if not session_data:
            raise SessionExpiredError(f"Session {session_id} not found or expired")

        # Validate command
        validation_result = validate_command(command)
        if not validation_result["valid"]:
            raise ValueError(validation_result['error'])

        # Execute in container
        container = docker_client.containers.get(session_data['container_id'])
        result = container.exec_run(
            f'bash -c {shlex.quote(command)}',
            user=settings.SANDBOX_USER,
            workdir=settings.WORKSPACE_DIR,
            demux=True
        )

        # Update last activity
        session_data['last_activity'] = datetime.now().isoformat()

        return {
            'exit_code': result.exit_code,
            'stdout': result.output[0].decode('utf-8') if result.output[0] else '',
            'stderr': result.output[1].decode('utf-8') if result.output[1] else '',
            'session_id': session_id
        }

    # Add similar methods for upload_file, download_file, list_files, cleanup_session
    # ... (implementation similar to HTTP endpoints but return data directly)

# Global server instance for local mode
_server_instance: Optional[SandboxServer] = None

def get_server_instance() -> SandboxServer:
    """Get or create server instance for local mode"""
    global _server_instance
    if _server_instance is None:
        _server_instance = SandboxServer()
    return _server_instance
```

#### 1. Add Thread ID Mapping

```python
# Global state (in-memory or Redis)
thread_to_session: Dict[str, str] = {}  # thread_id → session_id

def store_thread_mapping(thread_id: str, session_id: str):
    """Store thread_id → session_id mapping"""
    if settings.REDIS_ENABLED:
        redis_client.setex(
            f"thread:{thread_id}",
            int(settings.SESSION_TIMEOUT.total_seconds()),
            session_id
        )
    else:
        thread_to_session[thread_id] = session_id

def get_session_by_thread(thread_id: str) -> Optional[str]:
    """Get session_id for a thread_id"""
    if settings.REDIS_ENABLED:
        session_id = redis_client.get(f"thread:{thread_id}")
        return session_id.decode() if session_id else None
    else:
        return thread_to_session.get(thread_id)

def remove_thread_mapping(thread_id: str):
    """Remove thread_id mapping on cleanup"""
    if settings.REDIS_ENABLED:
        redis_client.delete(f"thread:{thread_id}")
    else:
        thread_to_session.pop(thread_id, None)
```

#### 2. Add Command Validation (Server-Side)

```python
import re
import shlex

# Same whitelist/blacklist as bash_tools.py
ALLOWED_COMMANDS = {
    'jq', 'awk', 'grep', 'sed', 'sort', 'uniq', 'head',
    'tail', 'wc', 'cut', 'tr', 'cat', 'echo', 'date', 'find', 'ls', 'python3', 'python'
}

FORBIDDEN_PATTERNS = [
    r'\brm\b', r'\bmv\b', r'\bdd\b', r'\bcurl\b', r'\bwget\b',
    r'\bssh\b', r'\bsudo\b'
]

def validate_command(command: str) -> Dict[str, Any]:
    """
    Validate command against whitelist and blacklist.
    Returns: {"valid": bool, "error": str, "pattern": str}
    """
    if not command or not command.strip():
        return {"valid": False, "error": "Empty command"}

    # Check blacklist
    for pattern in FORBIDDEN_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            return {
                "valid": False,
                "error": f"Command contains forbidden pattern: {pattern}",
                "pattern": pattern
            }

    # Parse and validate commands in pipeline
    # (Use same logic as bash_tools.py - split on |, &&, ||)
    parts = split_on_operators(command)

    for part in parts:
        try:
            tokens = shlex.split(part)
            if tokens and tokens[0] not in ALLOWED_COMMANDS:
                return {
                    "valid": False,
                    "error": f"Command '{tokens[0]}' not in whitelist. Allowed: {', '.join(sorted(ALLOWED_COMMANDS))}"
                }
        except ValueError as e:
            return {"valid": False, "error": f"Invalid command syntax: {str(e)}"}

    return {"valid": True}
```

#### 3. Add Resource Limits

**File**: `sandbox-system/sandbox-v2/settings.py`

```python
class Settings:
    # ... existing settings ...

    # File and workspace limits (NEW)
    MAX_FILE_SIZE_MB = int(os.getenv('MAX_FILE_SIZE_MB', 100))
    MAX_FILE_SIZE = MAX_FILE_SIZE_MB * 1024 * 1024  # 100MB

    MAX_TOTAL_FILES = int(os.getenv('MAX_TOTAL_FILES', 1000))

    MAX_WORKSPACE_SIZE_MB = int(os.getenv('MAX_WORKSPACE_SIZE_MB', 500))
    MAX_WORKSPACE_SIZE = MAX_WORKSPACE_SIZE_MB * 1024 * 1024  # 500MB
```

#### 4. Implement New Endpoints

**GET /get_session**:

```python
@app.route('/get_session', methods=['GET'])
def get_session_endpoint():
    """Get session info by thread_id"""
    thread_id = request.args.get('thread_id')

    if not thread_id:
        return jsonify({'error': 'thread_id required'}), 400

    session_id = get_session_by_thread(thread_id)
    if not session_id:
        return jsonify({
            'error': 'No active session found for thread_id',
            'thread_id': thread_id
        }), 404

    session_data = get_session(session_id)
    if not session_data:
        # Stale mapping, cleanup
        remove_thread_mapping(thread_id)
        return jsonify({
            'error': 'Session expired',
            'thread_id': thread_id
        }), 404

    return jsonify({
        'session_id': session_id,
        'thread_id': thread_id,
        'status': 'active',
        'created_at': session_data.get('created_at'),
        'last_activity': session_data.get('last_activity'),
        'workspace_dir': settings.WORKSPACE_DIR
    })
```

**POST /create_session** (MODIFIED - FastAPI):

```python
@app.post("/create_session", status_code=201)
async def create_session(request: CreateSessionRequest):
    """Create session with thread_id mapping"""
    user_id = request.user_id
    thread_id = request.thread_id
    timeout_minutes = request.timeout_minutes

    # Check if session already exists for this thread
    existing_session_id = get_session_by_thread(thread_id)
    if existing_session_id:
        session_data = get_session(existing_session_id)
        if session_data:
            # Return existing session with 409 status
            return Response(
                content=json.dumps({
                    'session_id': existing_session_id,
                    'thread_id': thread_id,
                    'status': 'existing',
                    'workspace_dir': settings.WORKSPACE_DIR,
                    'user': settings.SANDBOX_USER,
                    'created_at': session_data.get('created_at'),
                    'last_activity': session_data.get('last_activity')
                }),
                status_code=409,
                media_type="application/json"
            )

    # Create new session
    session_id = str(uuid.uuid4())

    try:
        container = pool.get_container()
        if not container:
            raise HTTPException(status_code=503, detail="Pool at max capacity")

        # Store session
        store_session(session_id, container.id, user_id, thread_id)

        # Store thread mapping
        store_thread_mapping(thread_id, session_id)

        return {
            'session_id': session_id,
            'thread_id': thread_id,
            'status': 'created',
            'workspace_dir': settings.WORKSPACE_DIR,
            'user': settings.SANDBOX_USER,
            'expires_at': (datetime.now() + timedelta(minutes=timeout_minutes)).isoformat()
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

**POST /execute** (MODIFIED - FastAPI + validation):

```python
@app.post("/execute")
async def execute_command(request: ExecuteRequest):
    """Execute command with server-side validation"""
    session_id = request.session_id
    command = request.command
    timeout = request.timeout

    # SERVER-SIDE VALIDATION (defense in depth)
    validation_result = validate_command(command)
    if not validation_result["valid"]:
        raise HTTPException(
            status_code=400,
            detail={
                'error': validation_result['error'],
                'command': command[:200],
                'forbidden_pattern': validation_result.get('pattern')
            }
        )

    session_data = get_session(session_id)
    if not session_data:
        return jsonify({'error': 'Invalid or expired session'}), 404

    try:
        container = client.containers.get(session_data['container_id'])

        # Execute with timing
        import time
        start_time = time.time()

        exec_instance = container.exec_run(
            ['bash', '-c', command],
            workdir=settings.WORKSPACE_DIR,
            user=settings.SANDBOX_USER,
            demux=True
        )

        execution_time_ms = int((time.time() - start_time) * 1000)

        # Update activity
        update_session_activity(session_id)

        # Parse output
        output_stdout = ""
        output_stderr = ""
        if exec_instance.output:
            stdout, stderr = exec_instance.output
            if stdout:
                output_stdout = stdout.decode('utf-8', errors='replace')
            if stderr:
                output_stderr = stderr.decode('utf-8', errors='replace')

        return jsonify({
            'exit_code': exec_instance.exit_code,
            'stdout': output_stdout,
            'stderr': output_stderr,
            'execution_time_ms': execution_time_ms
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500
```

**POST /upload_file** (MODIFIED - add limits):

```python
@app.route('/upload_file', methods=['POST'])
def upload_file():
    """Upload file with size and count limits"""
    session_id = request.form.get('session_id')

    if not session_id:
        return jsonify({'error': 'session_id required'}), 400

    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    session_data = get_session(session_id)
    if not session_data:
        return jsonify({'error': 'Invalid or expired session'}), 404

    try:
        file = request.files['file']
        filename = request.form.get('filename', file.filename)

        # Read file data
        file_data = file.read()
        file_size = len(file_data)

        # Check file size limit
        if file_size > settings.MAX_FILE_SIZE:
            return jsonify({
                'error': 'File size exceeds maximum allowed size',
                'max_size_mb': settings.MAX_FILE_SIZE_MB,
                'uploaded_size_mb': round(file_size / (1024 * 1024), 2)
            }), 413

        container = client.containers.get(session_data['container_id'])

        # Check workspace size and file count
        workspace_info = get_workspace_info(container)

        if workspace_info['total_files'] >= settings.MAX_TOTAL_FILES:
            return jsonify({
                'error': 'Maximum file count exceeded',
                'max_files': settings.MAX_TOTAL_FILES,
                'current_files': workspace_info['total_files']
            }), 507

        if workspace_info['total_size'] + file_size > settings.MAX_WORKSPACE_SIZE:
            return jsonify({
                'error': 'Workspace size limit exceeded',
                'max_workspace_mb': settings.MAX_WORKSPACE_SIZE_MB,
                'current_workspace_mb': round(workspace_info['total_size'] / (1024 * 1024), 2),
                'file_size_mb': round(file_size / (1024 * 1024), 2)
            }), 507

        # Upload file (existing v2 logic)
        import tarfile
        import io

        tar_stream = io.BytesIO()
        tar = tarfile.TarFile(fileobj=tar_stream, mode='w')

        tarinfo = tarfile.TarInfo(name=filename)
        tarinfo.size = file_size
        tar.addfile(tarinfo, io.BytesIO(file_data))
        tar.close()

        tar_stream.seek(0)
        container.put_archive(settings.WORKSPACE_DIR, tar_stream)

        # Fix permissions
        container.exec_run(
            f'chown {settings.SANDBOX_USER}:{settings.SANDBOX_USER} {settings.WORKSPACE_DIR}/{filename}',
            user='root'
        )

        update_session_activity(session_id)

        return jsonify({
            'status': 'uploaded',
            'filename': filename,
            'path': f'{settings.WORKSPACE_DIR}/{filename}',
            'size_bytes': file_size
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500

def get_workspace_info(container) -> Dict[str, Any]:
    """Get workspace file count and total size"""
    result = container.exec_run(
        f'du -sb {settings.WORKSPACE_DIR} && find {settings.WORKSPACE_DIR} -type f | wc -l',
        user=settings.SANDBOX_USER
    )

    if result.exit_code != 0:
        return {'total_size': 0, 'total_files': 0}

    output = result.output.decode('utf-8').strip().split('\n')
    total_size = int(output[0].split()[0]) if output else 0
    total_files = int(output[1]) if len(output) > 1 else 0

    return {'total_size': total_size, 'total_files': total_files}
```

**POST /download_file** (NEW):

```python
@app.route('/download_file', methods=['POST'])
def download_file():
    """Download file from workspace"""
    data = request.json
    session_id = data.get('session_id')
    filename = data.get('filename')

    if not session_id or not filename:
        return jsonify({'error': 'session_id and filename required'}), 400

    # Validate filename (prevent path traversal)
    if '..' in filename or filename.startswith('/'):
        return jsonify({'error': 'Invalid filename'}), 400

    session_data = get_session(session_id)
    if not session_data:
        return jsonify({'error': 'Invalid or expired session'}), 404

    try:
        container = client.containers.get(session_data['container_id'])

        # Check if file exists
        check_result = container.exec_run(
            f'test -f {settings.WORKSPACE_DIR}/{filename}',
            user=settings.SANDBOX_USER
        )

        if check_result.exit_code != 0:
            return jsonify({
                'error': 'File not found in workspace',
                'filename': filename,
                'workspace_dir': settings.WORKSPACE_DIR
            }), 404

        # Get file as tar archive
        import tarfile
        import io

        bits, stat = container.get_archive(f'{settings.WORKSPACE_DIR}/{filename}')

        # Extract file from tar
        tar_stream = io.BytesIO()
        for chunk in bits:
            tar_stream.write(chunk)
        tar_stream.seek(0)

        tar = tarfile.open(fileobj=tar_stream)
        file_member = tar.getmembers()[0]
        file_data = tar.extractfile(file_member).read()
        tar.close()

        update_session_activity(session_id)

        # Return as binary response
        from flask import send_file
        return send_file(
            io.BytesIO(file_data),
            mimetype='application/octet-stream',
            as_attachment=True,
            download_name=filename
        )

    except Exception as e:
        return jsonify({'error': str(e)}), 500
```

**GET /list_files** (NEW):

```python
@app.route('/list_files', methods=['GET'])
def list_files():
    """List all files in workspace"""
    session_id = request.args.get('session_id')

    if not session_id:
        return jsonify({'error': 'session_id required'}), 400

    session_data = get_session(session_id)
    if not session_data:
        return jsonify({'error': 'Invalid or expired session'}), 404

    try:
        container = client.containers.get(session_data['container_id'])

        # List files with metadata
        result = container.exec_run(
            f'ls -la --time-style=iso {settings.WORKSPACE_DIR}',
            user=settings.SANDBOX_USER
        )

        if result.exit_code != 0:
            return jsonify({'error': 'Failed to list files'}), 500

        # Parse ls output
        lines = result.output.decode('utf-8').strip().split('\n')[1:]  # Skip 'total' line
        files = []
        total_size = 0

        for line in lines:
            parts = line.split()
            if len(parts) < 9:
                continue

            filename = parts[8]
            if filename in ['.', '..']:
                continue

            file_info = {
                'name': filename,
                'size_bytes': int(parts[4]),
                'modified': f"{parts[5]}T{parts[6]}Z",
                'permissions': parts[0]
            }
            files.append(file_info)
            total_size += file_info['size_bytes']

        # Sort by modification time (newest first)
        files.sort(key=lambda x: x['modified'], reverse=True)

        return jsonify({
            'session_id': session_id,
            'workspace_dir': settings.WORKSPACE_DIR,
            'files': files,
            'total_files': len(files),
            'total_size_bytes': total_size
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500
```

**POST /cleanup** (MODIFIED - remove thread mapping):

```python
@app.route('/cleanup', methods=['POST'])
def cleanup():
    """Cleanup session and thread mapping"""
    data = request.json
    session_id = data.get('session_id')

    if not session_id:
        return jsonify({'error': 'session_id required'}), 400

    # Get session data to find thread_id
    session_data = get_session(session_id)
    if session_data:
        thread_id = session_data.get('thread_id')
        if thread_id:
            remove_thread_mapping(thread_id)

    cleanup_session(session_id)
    return jsonify({'status': 'cleaned_up', 'session_id': session_id})
```

---

## Client Integration

For details on how to integrate this sandbox system with AI agents or other applications, see **`INTEGRATION_GUIDE.md`**.

The integration guide covers:
- SDK usage patterns (local vs remote mode)
- AI agent bash tool implementation
- Configuration and environment variables
- Migration from other sandbox systems
- Best practices and troubleshooting

---

## Observability & Logging

### Structured Logging Format

All log messages should follow this format:

```python
logger.info(
    f"[SANDBOX] event={event} user={user_id[:8]} thread={thread_id[:12]} "
    f"session={session_id[:12]} command={command[:50]} exit_code={exit_code} "
    f"duration_ms={duration_ms}"
)
```

**Events to Log**:
- `session_created` - New session created
- `session_reused` - Existing session returned
- `session_expired` - Session cleanup due to timeout
- `command_executed` - Command execution completed
- `command_failed` - Command execution failed
- `file_uploaded` - File uploaded to workspace
- `file_downloaded` - File downloaded from workspace
- `validation_failed` - Command validation failed
- `resource_limit_exceeded` - File size/count limit hit

### Metrics to Track

**Session Metrics**:
- Active sessions count
- Session creation rate (sessions/min)
- Session reuse rate (%)
- Average session lifetime

**Command Metrics**:
- Command execution rate (commands/min)
- Average execution time
- Command failure rate (%)
- Validation failure rate (%)

**Resource Metrics**:
- Pool utilization (%)
- Average workspace size per session
- File upload/download volume
- Resource limit violations

### Example Logging Implementation

```python
import logging
import time
from functools import wraps

logger = logging.getLogger(__name__)

def log_execution(event_type: str):
    """Decorator for logging execution metrics"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                duration_ms = int((time.time() - start_time) * 1000)

                logger.info(
                    f"[SANDBOX] event={event_type}_success "
                    f"duration_ms={duration_ms}"
                )
                return result
            except Exception as e:
                duration_ms = int((time.time() - start_time) * 1000)
                logger.error(
                    f"[SANDBOX] event={event_type}_failed "
                    f"duration_ms={duration_ms} error={str(e)}"
                )
                raise
        return wrapper
    return decorator

# Usage
@log_execution('command_execute')
def execute_command_internal(session_id, command):
    # ... implementation ...
    pass
```

---

## Testing Strategy

### Unit Tests

**File**: `sandbox-system/sandbox-v2/test_server.py`

Test cases to implement:

1. **Session Management**:
   - Create session with thread_id
   - Get existing session by thread_id
   - Session reuse (same thread_id returns same session)
   - Session isolation (different thread_ids get different sessions)
   - Session expiry and cleanup

2. **Command Execution**:
   - Valid command execution
   - Command validation (whitelist/blacklist)
   - Timeout handling
   - Auto-retry on session expiry

3. **File Operations**:
   - Upload file within size limit
   - Upload file exceeding size limit (413 error)
   - Download existing file
   - Download non-existent file (404 error)
   - List files in workspace
   - Workspace size limit enforcement

4. **Resource Limits**:
   - File count limit
   - Workspace size limit
   - File size limit

5. **Error Handling**:
   - Invalid session_id
   - Expired session
   - Missing required parameters
   - Path traversal attempts

### Integration Tests

**File**: `mypa-backend/tests/integration/test_bash_tools_sandbox.py`

Test cases:

1. **Agent Integration**:
   - Execute command from agent tool
   - Session persistence across multiple commands
   - File creation and reuse
   - Thread isolation (concurrent conversations)

2. **End-to-End Workflows**:
   - Upload file → process with bash → download result
   - Multi-step data pipeline
   - Error recovery (session expiry)

### Load Tests

**File**: `sandbox-system/sandbox-v2/load_test.py`

Scenarios:

1. **Concurrent Sessions**: 100 concurrent threads creating sessions
2. **Command Throughput**: 1000 commands/min across 50 sessions
3. **File Upload/Download**: 100 concurrent file operations
4. **Session Churn**: Rapid create/cleanup cycles

---

## Deployment Checklist

### Standalone Mode (Development)

```bash
# 1. Build secure Docker image
cd sandbox-system/sandbox-v2
docker build -f Dockerfile.secure -t sandbox-secure:latest .

# 2. Start server
python server.py

# 3. Test health
curl http://localhost:5000/health

# 4. Update mypa-backend config
# Add SANDBOX_URL=http://localhost:5000 to .env

# 5. Restart backend
cd mypa-backend
uvicorn src.main:app --reload
```

### Distributed Mode (Production)

```bash
# 1. Build images
docker build -f Dockerfile.secure -t sandbox-secure:latest .
docker build -f Dockerfile.worker -t sandbox-worker:latest .
docker build -f Dockerfile.coordinator -t sandbox-coordinator:latest .

# 2. Start stack
docker-compose up -d

# 3. Verify health
curl http://localhost:8000/health

# 4. Update mypa-backend config
# Add SANDBOX_URL=http://localhost:8000 to .env (coordinator URL)

# 5. Monitor logs
docker-compose logs -f
```

### Environment Variables (Production)

```bash
# Worker
REDIS_HOST=redis
REDIS_PORT=6379
WORKER_ID=worker1
POOL_SIZE=10
PORT=5000
SESSION_TIMEOUT_MINUTES=30
MAX_FILE_SIZE_MB=100
MAX_TOTAL_FILES=1000
MAX_WORKSPACE_SIZE_MB=500

# Coordinator
REDIS_HOST=redis
REDIS_PORT=6379
PORT=8000
WORKERS=http://worker1:5000,http://worker2:5000,http://worker3:5000
```

---

## Migration from Cloudflare Sandbox

### Phase 1: Parallel Deployment

1. Deploy sandbox-v2 alongside existing Cloudflare Worker
2. Add feature flag to bash_tools.py:
   ```python
   USE_SANDBOX_V2 = os.getenv('USE_SANDBOX_V2', 'false').lower() == 'true'
   ```
3. Test with subset of users

### Phase 2: Update Agent Prompts

Remove heredoc references from:
- `bash_tools.py` docstring
- Agent system prompt
- Tool descriptions

New guidance:
```
Files persist across commands in your sandbox session.
You can create files in one command and use them in subsequent commands.
Example:
  1. echo '{"data": [1,2,3]}' > input.json
  2. jq '.data | add' input.json
```

### Phase 3: Full Migration

1. Set `USE_SANDBOX_V2=true` for all users
2. Monitor error rates and performance
3. Deprecate Cloudflare Worker
4. Remove feature flag code

---

## Security Considerations

### Container Isolation

- ✅ Non-root execution (sandboxuser)
- ✅ No network access (network_mode="none")
- ✅ Resource limits (CPU, memory)
- ✅ Command whitelist/blacklist
- ✅ File size limits

### Additional Hardening (Optional)

1. **AppArmor/SELinux profiles** for containers
2. **Seccomp filters** to restrict syscalls
3. **Read-only root filesystem** (except /workspace)
4. **Capability dropping** (drop all Linux capabilities)
5. **User namespace remapping** (additional UID isolation)

### Monitoring & Alerts

Set up alerts for:
- High session creation rate (potential abuse)
- Resource limit violations
- Command validation failures
- Unusual command patterns
- Container escape attempts (monitor Docker logs)

---

## Performance Optimization

### Container Pooling (Already Implemented)

- Pre-warm containers for instant session creation
- Pool size: 10 (standalone), 5 per worker (distributed)
- Aggressive cleanup to recycle containers

### Caching Strategies

1. **Session metadata caching**: Cache session lookups in memory (1 min TTL)
2. **Thread mapping caching**: Cache thread_id → session_id (Redis or local)
3. **Workspace info caching**: Cache file counts/sizes (invalidate on upload)

### Scaling Guidelines

| Load Level | Configuration | Expected Performance |
|------------|---------------|---------------------|
| Low (< 10 concurrent users) | Standalone, pool=5 | < 100ms session creation |
| Medium (10-50 users) | Standalone, pool=20 | < 100ms session creation |
| High (50-200 users) | Distributed, 3 workers, pool=10 each | < 150ms session creation |
| Very High (200+ users) | Distributed, 5+ workers, pool=20 each | < 200ms session creation |

---

## Troubleshooting Guide

### Common Issues

**Issue**: Session not found after creation
- **Cause**: Redis connection lost, session expired
- **Fix**: Check Redis connectivity, increase timeout

**Issue**: Command validation fails unexpectedly
- **Cause**: Whitelist too restrictive
- **Fix**: Add command to ALLOWED_COMMANDS, test thoroughly

**Issue**: File upload fails with 507 error
- **Cause**: Workspace size limit exceeded
- **Fix**: Cleanup old files, increase MAX_WORKSPACE_SIZE

**Issue**: Container pool exhausted (503 error)
- **Cause**: High load, slow session cleanup
- **Fix**: Increase POOL_SIZE, enable aggressive cleanup

**Issue**: Auto-retry not working
- **Cause**: Client not detecting 404 correctly
- **Fix**: Check error handling in client.execute()

### Debug Commands

```bash
# Check active sessions
curl http://localhost:5000/health

# Check specific session
curl "http://localhost:5000/get_session?thread_id=thread_xyz"

# List files in session
curl "http://localhost:5000/list_files?session_id=sess_abc"

# Check container pool
docker ps | grep sandbox-secure

# Check Redis keys (distributed mode)
redis-cli KEYS "session:*"
redis-cli KEYS "thread:*"
```

---

## Success Criteria

Implementation is complete when:

- ✅ All 8 API endpoints implemented and tested
- ✅ Thread-based session management working
- ✅ File upload/download functional
- ✅ Server-side command validation enforced
- ✅ Resource limits enforced (file size, count, workspace)
- ✅ Auto-retry logic in client working
- ✅ Integration with bash_tools.py complete
- ✅ Unit tests passing (>80% coverage)
- ✅ Integration tests passing
- ✅ Load tests showing acceptable performance
- ✅ Structured logging implemented
- ✅ Documentation updated

---

## Post-Implementation Tasks

After implementing the enhanced sandbox system:

1. **Update Agent System Prompt**:
   - Remove references to heredoc workarounds
   - Add guidance on file-based workflows
   - Update examples to show file persistence

2. **Update Tool Docstrings**:
   - Remove "IMPORTANT: If your command needs data from files, you must inline the data using heredocs"
   - Add "Files persist across commands in your session"
   - Update examples to show multi-command workflows

3. **Update Documentation**:
   - `mypa-backend/docs/bash_tool_design.md`
   - `mypa-backend/docs/bash_implementation_summary.md`
   - `sandbox-system/README.md`

4. **Monitor Production**:
   - Track session reuse rate (should be >50%)
   - Monitor resource limit violations
   - Watch for command validation failures
   - Check auto-retry success rate

---

## Technology Migration Summary

### Flask → FastAPI + Uvicorn

**Key Changes**:

| Aspect | Flask (Old) | FastAPI (New) |
|--------|-------------|---------------|
| **Decorators** | `@app.route('/path', methods=['POST'])` | `@app.post('/path')` |
| **Request Data** | `request.json`, `request.args` | Pydantic models (`CreateSessionRequest`) |
| **Responses** | `return jsonify({...}), 400` | `raise HTTPException(status_code=400, detail={...})` |
| **Success Response** | `return jsonify({...})` | `return {...}` (auto-serialized) |
| **File Upload** | `request.files['file']` | `file: UploadFile = File(...)` |
| **Async Support** | Limited (via threads) | Native `async def` |
| **Type Safety** | Manual validation | Automatic via Pydantic |
| **Performance** | Baseline | 2-3x faster |

**Example Conversion**:

```python
# Flask (OLD)
@app.route('/execute', methods=['POST'])
def execute_command():
    data = request.json
    session_id = data.get('session_id')
    if not session_id:
        return jsonify({'error': 'session_id required'}), 400
    # ... logic ...
    return jsonify({'result': 'success'})

# FastAPI (NEW)
@app.post('/execute')
async def execute_command(request: ExecuteRequest):
    # session_id automatically validated by Pydantic
    # ... logic ...
    return {'result': 'success'}
```

### HTTP-Only → SDK Approach

**Key Changes**:

| Aspect | HTTP-Only (Old) | SDK Approach (New) |
|--------|-----------------|---------------------|
| **Integration** | `requests.post(url, json={...})` | `client.execute(command)` |
| **Overhead** | HTTP serialization/network | Zero (local mode) |
| **Error Handling** | HTTP status codes | Python exceptions |
| **Type Safety** | Manual JSON parsing | Type-safe method calls |
| **Deployment** | Always remote | Local or remote |
| **Debugging** | Network logs | Direct stack traces |

**Example Conversion**:

```python
# HTTP-Only (OLD)
response = requests.post(
    f"{SANDBOX_URL}/execute",
    json={'session_id': session_id, 'command': command}
)
if response.status_code == 404:
    # Session expired, recreate
    ...
result = response.json()

# SDK Approach (NEW)
try:
    result = client.execute(command, auto_retry=True)
except SessionExpiredError:
    # Automatically handled by auto_retry
    pass
```

**Benefits**:
- **Local Mode**: 10-50ms faster per command (no HTTP overhead)
- **Remote Mode**: Same as before, but with cleaner API
- **Unified Interface**: Same code works for both modes
- **Better DX**: Type hints, auto-complete, direct debugging

---

## Final Notes

### Implementation Checklist

After implementing this sandbox system:

1. ✅ Verify all endpoints work correctly (create, execute, upload, download, list, cleanup)
2. ✅ Test both local and remote modes
3. ✅ Validate command whitelisting and blacklisting
4. ✅ Test resource limits (file size, count, workspace size)
5. ✅ Verify session expiry and auto-cleanup
6. ✅ Test container pool management
7. ✅ Validate thread-scoped session isolation
8. ✅ Test auto-retry logic on session expiry

### Integration

For client integration (AI agents, applications, etc.), refer to **`INTEGRATION_GUIDE.md`** which covers:
- SDK usage patterns
- Configuration and deployment
- Migration strategies
- Best practices and troubleshooting

### Key Benefits

The persistent session model enables:
- **File-based workflows**: Create files in one command, use in subsequent commands
- **Natural command chaining**: Build complex pipelines across multiple executions
- **Better performance**: Session reuse eliminates container startup overhead
- **Cleaner code**: No need for heredoc workarounds or data inlining


