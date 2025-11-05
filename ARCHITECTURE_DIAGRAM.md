# Enhanced Sandbox System V2 - Architecture Diagrams

## System Architecture

### High-Level Overview (SDK Approach)

```
┌─────────────────────────────────────────────────────────────────┐
│                        MyPA Backend                              │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │              AI Agent (Deep Agents V3)                    │  │
│  │  ┌────────────────────────────────────────────────────┐  │  │
│  │  │           Bash Tool (bash_tools.py)                │  │  │
│  │  │  - Validates commands (client-side)                │  │  │
│  │  │  - Extracts user_id, thread_id from context        │  │  │
│  │  │  - Uses SandboxClient SDK (import)                 │  │  │
│  │  └────────────────────────────────────────────────────┘  │  │
│  └──────────────────────────────────────────────────────────┘  │
│                              │                                   │
│                              │ SDK (Direct Python Import)        │
│                              │ mode="local" → In-Process         │
│                              │ mode="remote" → HTTP              │
│                              ▼                                   │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │           SandboxClient SDK (sandbox_client_v2.py)        │  │
│  │  - get_or_create_session(user_id, thread_id)             │  │
│  │  - execute(command, auto_retry=True)                     │  │
│  │  - upload_file() / download_file() / list_files()        │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ LOCAL MODE: Direct method calls
                              │ REMOTE MODE: HTTP to sandbox server
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Sandbox System V2                             │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │            API Server (FastAPI + Uvicorn)                 │  │
│  │  ┌────────────────────────────────────────────────────┐  │  │
│  │  │  Thread ID Mapping                                 │  │  │
│  │  │  thread_abc → session_123                          │  │  │
│  │  │  thread_xyz → session_456                          │  │  │
│  │  └────────────────────────────────────────────────────┘  │  │
│  │  ┌────────────────────────────────────────────────────┐  │  │
│  │  │  Command Validation (server-side)                  │  │  │
│  │  │  - Whitelist check                                 │  │  │
│  │  │  - Blacklist check                                 │  │  │
│  │  └────────────────────────────────────────────────────┘  │  │
│  │  ┌────────────────────────────────────────────────────┐  │  │
│  │  │  Resource Limits                                   │  │  │
│  │  │  - File size: 100MB                                │  │  │
│  │  │  - File count: 1000                                │  │  │
│  │  │  - Workspace: 500MB                                │  │  │
│  │  └────────────────────────────────────────────────────┘  │  │
│  └──────────────────────────────────────────────────────────┘  │
│                              │                                   │
│                              ▼                                   │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │              Container Pool (Pre-warmed)                  │  │
│  │  ┌──────┐  ┌──────┐  ┌──────┐  ┌──────┐  ┌──────┐      │  │
│  │  │ C1   │  │ C2   │  │ C3   │  │ C4   │  │ C5   │ ...  │  │
│  │  │ idle │  │ sess │  │ sess │  │ idle │  │ idle │      │  │
│  │  │      │  │ 123  │  │ 456  │  │      │  │      │      │  │
│  │  └──────┘  └──────┘  └──────┘  └──────┘  └──────┘      │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘

**Deployment Modes**:
- **Local Mode** (Development): SDK → Direct method calls → Container Pool
  - Zero HTTP overhead, faster execution
  - Simpler debugging (single process)
  - Ideal for development and single-server deployments

- **Remote Mode** (Production): SDK → HTTP → Remote Sandbox Server → Container Pool
  - Horizontal scaling across multiple sandbox servers
  - Resource isolation (sandbox crashes don't affect backend)
  - Load balancing and distributed session management
```

---

## Session Lifecycle

### 1. First Command in Conversation

```
Agent Tool Call
    │
    ├─ user_id: "user_123"
    ├─ thread_id: "thread_abc"
    └─ command: "echo 'hello' > greeting.txt"
    │
    ▼
Sandbox Client
    │
    ├─ get_or_create_session(user_123, thread_abc)
    │
    ▼
Sandbox Server
    │
    ├─ Check: thread_abc in mapping? → NO
    ├─ Create: session_123
    ├─ Store: thread_abc → session_123
    ├─ Assign: container from pool
    │
    ▼
Container (session_123)
    │
    ├─ Execute: echo 'hello' > greeting.txt
    ├─ File created: /workspace/greeting.txt
    │
    ▼
Response
    └─ exit_code: 0, stdout: "", stderr: ""
```

---

### 2. Second Command in Same Conversation

```
Agent Tool Call
    │
    ├─ user_id: "user_123"
    ├─ thread_id: "thread_abc"  ← SAME thread
    └─ command: "cat greeting.txt"
    │
    ▼
Sandbox Client
    │
    ├─ get_or_create_session(user_123, thread_abc)
    │
    ▼
Sandbox Server
    │
    ├─ Check: thread_abc in mapping? → YES
    ├─ Found: session_123
    ├─ Return: existing session (409 Conflict)
    │
    ▼
Container (session_123)  ← SAME container
    │
    ├─ Execute: cat greeting.txt
    ├─ File exists: /workspace/greeting.txt
    │
    ▼
Response
    └─ exit_code: 0, stdout: "hello", stderr: ""
```

---

### 3. Command in Different Conversation

```
Agent Tool Call
    │
    ├─ user_id: "user_123"  ← SAME user
    ├─ thread_id: "thread_xyz"  ← DIFFERENT thread
    └─ command: "cat greeting.txt"
    │
    ▼
Sandbox Client
    │
    ├─ get_or_create_session(user_123, thread_xyz)
    │
    ▼
Sandbox Server
    │
    ├─ Check: thread_xyz in mapping? → NO
    ├─ Create: session_456
    ├─ Store: thread_xyz → session_456
    ├─ Assign: different container from pool
    │
    ▼
Container (session_456)  ← DIFFERENT container
    │
    ├─ Execute: cat greeting.txt
    ├─ File NOT found: /workspace/greeting.txt
    │
    ▼
Response
    └─ exit_code: 1, stdout: "", stderr: "No such file"
```

---

## Session Expiry & Auto-Retry

```
Agent Tool Call (after 30 min idle)
    │
    ├─ thread_id: "thread_abc"
    └─ command: "cat greeting.txt"
    │
    ▼
Sandbox Client
    │
    ├─ execute(command, auto_retry=True)
    │
    ▼
Sandbox Server
    │
    ├─ Check: session_123 expired? → YES
    ├─ Return: 404 Not Found
    │
    ▼
Sandbox Client (auto-retry)
    │
    ├─ Detect: 404 error
    ├─ Recreate: get_or_create_session(user_123, thread_abc)
    │   ├─ Create: session_789 (new session)
    │   └─ Store: thread_abc → session_789
    ├─ Retry: execute(command)
    │
    ▼
Container (session_789)  ← NEW container
    │
    ├─ Execute: cat greeting.txt
    ├─ File NOT found (new container, files lost)
    │
    ▼
Response
    └─ exit_code: 1, stderr: "No such file"
```

**Note**: Files are lost on session expiry. Agent should handle this gracefully.

---

## File Upload/Download Flow

### Upload Flow

```
Agent
    │
    ├─ upload_file("local_data.json", "data.json")
    │
    ▼
Sandbox Client
    │
    ├─ Read: local_data.json (binary)
    ├─ POST /upload_file
    │   ├─ session_id: session_123
    │   ├─ file: <binary data>
    │   └─ filename: data.json
    │
    ▼
Sandbox Server
    │
    ├─ Validate: file size < 100MB? ✓
    ├─ Check: workspace size + file < 500MB? ✓
    ├─ Check: file count < 1000? ✓
    ├─ Create: tar archive
    ├─ Upload: to container
    ├─ Fix: permissions (chown sandboxuser)
    │
    ▼
Container
    │
    └─ File created: /workspace/data.json
```

---

### Download Flow

```
Agent
    │
    ├─ download_file("output.csv", "local_output.csv")
    │
    ▼
Sandbox Client
    │
    ├─ POST /download_file
    │   ├─ session_id: session_123
    │   └─ filename: output.csv
    │
    ▼
Sandbox Server
    │
    ├─ Validate: filename (no path traversal)
    ├─ Check: file exists in container? ✓
    ├─ Get: file as tar archive
    ├─ Extract: from tar
    ├─ Return: binary data
    │
    ▼
Sandbox Client
    │
    ├─ Receive: binary data
    ├─ Write: to local_output.csv
    │
    ▼
Agent
    └─ File saved: local_output.csv
```

---

## Command Validation Flow

```
Agent
    │
    └─ command: "jq '.data' input.json | grep 'value'"
    │
    ▼
Bash Tool (client-side validation)
    │
    ├─ Split: ["jq '.data' input.json", "grep 'value'"]
    ├─ Check whitelist: jq ✓, grep ✓
    ├─ Check blacklist: no forbidden patterns ✓
    ├─ Pass: validation
    │
    ▼
Sandbox Server (server-side validation)
    │
    ├─ Split: ["jq '.data' input.json", "grep 'value'"]
    ├─ Check whitelist: jq ✓, grep ✓
    ├─ Check blacklist: no forbidden patterns ✓
    ├─ Pass: validation
    │
    ▼
Container
    └─ Execute: command
```

---

### Validation Failure Example

```
Agent
    │
    └─ command: "rm -rf /workspace/*"
    │
    ▼
Bash Tool (client-side validation)
    │
    ├─ Check blacklist: \brm\b → MATCH!
    ├─ Fail: validation
    │
    ▼
Response (400 Bad Request)
    └─ error: "Command contains forbidden pattern: \brm\b"
```

**Note**: Even if client validation is bypassed, server validation catches it.

---

## Distributed Mode Architecture

```
                    ┌─────────────────┐
                    │  Load Balancer  │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │  Coordinator    │
                    │  (Port 8000)    │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │     Redis       │
                    │  (State Store)  │
                    └────────┬────────┘
                             │
         ┌───────────────────┼───────────────────┐
         │                   │                   │
    ┌────▼────┐         ┌────▼────┐         ┌────▼────┐
    │ Worker1 │         │ Worker2 │         │ Worker3 │
    │ Pool: 5 │         │ Pool: 5 │         │ Pool: 5 │
    └────┬────┘         └────┬────┘         └────┬────┘
         │                   │                   │
    ┌────▼────┐         ┌────▼────┐         ┌────▼────┐
    │ Docker  │         │ Docker  │         │ Docker  │
    │Containers│        │Containers│        │Containers│
    └─────────┘         └─────────┘         └─────────┘
```

**Session Affinity**: Once a thread is assigned to a worker, all subsequent requests for that thread go to the same worker (via Redis mapping).

---

## Data Flow Summary

### Local Mode (SDK Direct Calls)

```
┌──────────┐
│  Agent   │
└────┬─────┘
     │ 1. Tool call (user_id, thread_id, command)
     ▼
┌──────────────┐
│  Bash Tool   │
└────┬─────────┘
     │ 2. Client-side validation
     ▼
┌──────────────┐
│Sandbox Client│ (mode="local")
│     SDK      │
└────┬─────────┘
     │ 3. Direct method call: client._server.get_session_by_thread()
     │    (NO HTTP overhead)
     ▼
┌──────────────┐
│Sandbox Server│ (in-process)
│   Instance   │
└────┬─────────┘
     │ 4. Thread mapping lookup
     │ 5. Server-side validation
     │ 6. Resource limit checks
     ▼
┌──────────────┐
│  Container   │
└────┬─────────┘
     │ 7. Execute command
     ▼
┌──────────────┐
│   Response   │
└──────────────┘
```

### Remote Mode (HTTP Calls)

```
┌──────────┐
│  Agent   │
└────┬─────┘
     │ 1. Tool call (user_id, thread_id, command)
     ▼
┌──────────────┐
│  Bash Tool   │
└────┬─────────┘
     │ 2. Client-side validation
     ▼
┌──────────────┐
│Sandbox Client│ (mode="remote")
│     SDK      │
└────┬─────────┘
     │ 3. HTTP POST to /get_session
     │    (Network overhead)
     ▼
┌──────────────┐
│Sandbox Server│ (remote process)
│  (FastAPI)   │
└────┬─────────┘
     │ 4. Thread mapping lookup
     │ 5. Server-side validation
     │ 6. Resource limit checks
     ▼
┌──────────────┐
│  Container   │
└────┬─────────┘
     │ 7. Execute command
     ▼
┌──────────────┐
│   Response   │
└──────────────┘
```

---

## Key Takeaways

1. **Thread-scoped sessions** prevent file collisions across conversations
2. **Automatic session reuse** reduces overhead and enables file persistence
3. **Auto-retry logic** handles session expiry gracefully
4. **Defense-in-depth** validation (client + server) ensures security
5. **Resource limits** prevent abuse and ensure stability
6. **Container pooling** provides fast session creation (40x faster)
7. **Distributed mode** enables horizontal scaling for high load

