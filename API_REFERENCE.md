# Enhanced Sandbox System V2 - API Quick Reference

## Base URL
- **Standalone**: `http://localhost:5000`
- **Distributed**: `http://localhost:8000` (coordinator)

---

## Endpoints

### 1. Create Session
```http
POST /create_session
Content-Type: application/json

{
  "user_id": "user_abc123",
  "thread_id": "thread_xyz789",
  "timeout_minutes": 30
}
```
**Returns**: `session_id`, `status` (created/existing), `workspace_dir`

---

### 2. Get Session
```http
GET /get_session?thread_id=thread_xyz789
```
**Returns**: Session info or 404 if not found

---

### 3. Execute Command
```http
POST /execute
Content-Type: application/json

{
  "session_id": "sess_uuid",
  "command": "jq '.[] | select(.amount > 100)' data.json",
  "timeout": 30
}
```
**Returns**: `exit_code`, `stdout`, `stderr`, `execution_time_ms`

---

### 4. Upload File
```http
POST /upload_file
Content-Type: multipart/form-data

session_id: sess_uuid
file: <binary>
filename: data.json (optional)
```
**Returns**: `status`, `filename`, `path`, `size_bytes`

---

### 5. Download File (NEW)
```http
POST /download_file
Content-Type: application/json

{
  "session_id": "sess_uuid",
  "filename": "output.csv"
}
```
**Returns**: Binary file data

---

### 6. List Files (NEW)
```http
GET /list_files?session_id=sess_uuid
```
**Returns**: Array of files with metadata

---

### 7. Cleanup Session
```http
POST /cleanup
Content-Type: application/json

{
  "session_id": "sess_uuid"
}
```
**Returns**: `status: cleaned_up`

---

### 8. Health Check
```http
GET /health
```
**Returns**: System status and metrics

---

## Python Client Usage

```python
from sandbox_client_v2 import SandboxClient

# Initialize client
client = SandboxClient(server_url="http://localhost:5000")

# Get or create session (automatic reuse)
session = client.get_or_create_session(
    user_id="user_123",
    thread_id="thread_abc",
    timeout_minutes=30
)

# Execute commands
result = client.execute("echo 'Hello' > greeting.txt")
result = client.execute("cat greeting.txt")
print(result['stdout'])  # "Hello"

# Upload file
client.upload_file("local_data.json", "data.json")

# Download file
client.download_file("output.csv", "local_output.csv")

# List files
files = client.list_files()
print(files['files'])

# Cleanup (optional - auto-cleanup after timeout)
client.close_session()
```

---

## Context Manager Usage

```python
with SandboxClient() as sandbox:
    sandbox.get_or_create_session(user_id="user_123", thread_id="thread_abc")
    
    # Create and process file
    sandbox.execute("echo '[1,2,3]' > data.json")
    result = sandbox.execute("jq 'add' data.json")
    print(result['stdout'])  # "6"
    
# Auto-cleanup on exit
```

---

## Error Codes

| Code | Meaning | Common Cause |
|------|---------|--------------|
| 200 | Success | - |
| 400 | Bad Request | Missing parameters, invalid command |
| 404 | Not Found | Session expired, file not found |
| 409 | Conflict | Session already exists (reuse it) |
| 413 | Payload Too Large | File exceeds 100MB limit |
| 503 | Service Unavailable | Pool exhausted |
| 507 | Insufficient Storage | Workspace limit exceeded |

---

## Resource Limits

| Resource | Limit | Configurable |
|----------|-------|--------------|
| File Size | 100 MB | `MAX_FILE_SIZE_MB` |
| Total Files | 1000 | `MAX_TOTAL_FILES` |
| Workspace Size | 500 MB | `MAX_WORKSPACE_SIZE_MB` |
| Session Timeout | 30 min | `SESSION_TIMEOUT_MINUTES` |
| Command Timeout | 30 sec | `DEFAULT_COMMAND_TIMEOUT` |

---

## Allowed Commands

`jq`, `awk`, `grep`, `sed`, `sort`, `uniq`, `head`, `tail`, `wc`, `cut`, `tr`, `cat`, `echo`, `date`, `find`, `ls`, `python3`, `python`

## Forbidden Commands

`rm`, `mv`, `dd`, `curl`, `wget`, `ssh`, `sudo`

