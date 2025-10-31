# Sandbox Architecture Overview

## System Flow

```
┌─────────────────────────────────────────────────────────────┐
│                      Your LangGraph Agent                    │
│                                                              │
│  ┌────────────────────────────────────────────────────┐    │
│  │  Uses: sandbox_client.py                           │    │
│  │                                                     │    │
│  │  client = SandboxClient("http://vps-ip:5000")     │    │
│  │  client.create_session()                           │    │
│  │  result = client.execute("bash command")           │    │
│  │  client.cleanup()                                  │    │
│  └────────────────────────────────────────────────────┘    │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       │ HTTP REST API
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                    Your VPS (Ubuntu)                         │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  Flask Server (sandbox_server.py)                    │  │
│  │  Port: 5000                                          │  │
│  │                                                       │  │
│  │  Endpoints:                                          │  │
│  │  - POST /create_session  → Creates container        │  │
│  │  - POST /execute         → Runs bash command        │  │
│  │  - POST /cleanup         → Removes container        │  │
│  └──────────────────────────────────────────────────────┘  │
│                       │                                      │
│                       │ Docker API                          │
│                       │                                      │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              Docker Engine                            │  │
│  │                                                       │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌───────────┐ │  │
│  │  │ Container 1  │  │ Container 2  │  │ Container3│ │  │
│  │  │ User A       │  │ User B       │  │ User C    │ │  │
│  │  │              │  │              │  │           │ │  │
│  │  │ /workspace   │  │ /workspace   │  │ /workspace│ │  │
│  │  │ bash shell   │  │ bash shell   │  │ bash shell│ │  │
│  │  └──────────────┘  └──────────────┘  └───────────┘ │  │
│  │                                                       │  │
│  │  Each container:                                     │  │
│  │  - Isolated filesystem                               │  │
│  │  - Memory limit: 512MB                               │  │
│  │  - CPU limit: 50%                                    │  │
│  │  - No network access                                 │  │
│  │  - Auto-cleanup after 1 hour                         │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

## Request Flow Example

```
1. Agent sends: POST /create_session
   ↓
2. Server creates Docker container
   ↓
3. Server returns: {"session_id": "abc-123"}
   ↓
4. Agent sends: POST /execute 
              {"session_id": "abc-123", "command": "ls -la"}
   ↓
5. Server executes in container
   ↓
6. Server returns: {"exit_code": 0, "output": "...file list..."}
   ↓
7. Agent sends: POST /cleanup {"session_id": "abc-123"}
   ↓
8. Server stops and removes container
```

## Security Layers

```
┌─────────────────────────────────────────┐
│  Layer 1: Network Isolation             │
│  - Containers have no network access    │
│  - Can't reach external services        │
└─────────────────────────────────────────┘
              ▼
┌─────────────────────────────────────────┐
│  Layer 2: Resource Limits               │
│  - Memory: 512MB max                    │
│  - CPU: 50% of one core max             │
│  - Prevents resource exhaustion         │
└─────────────────────────────────────────┘
              ▼
┌─────────────────────────────────────────┐
│  Layer 3: Filesystem Isolation          │
│  - Each container has own filesystem    │
│  - Changes don't affect host            │
│  - Can't access other containers        │
└─────────────────────────────────────────┘
              ▼
┌─────────────────────────────────────────┐
│  Layer 4: Session Timeout               │
│  - Auto-cleanup after 1 hour            │
│  - Prevents container accumulation      │
│  - Frees up resources automatically     │
└─────────────────────────────────────────┘
```

## File Structure

```
sandbox-server/
│
├── Core Files
│   ├── sandbox_server.py      # Flask API server
│   ├── sandbox_client.py      # Python client library
│   └── requirements.txt       # Python dependencies
│
├── Examples
│   └── langgraph_example.py   # LangGraph integration examples
│
├── Docker
│   └── Dockerfile.sandbox     # Custom sandbox image
│
├── Setup
│   ├── quickstart.sh          # Automated setup script
│   └── SETUP_GUIDE.md        # Detailed setup instructions
│
└── Documentation
    ├── README.md              # Project overview
    └── ARCHITECTURE.md        # This file
```

## Production Deployment Architecture (Optional)

For production, add these components:

```
Internet
   │
   ▼
┌─────────────────────────┐
│  Nginx Reverse Proxy    │
│  - HTTPS/SSL            │
│  - Rate Limiting        │
│  - API Key Auth         │
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│  Flask App (Gunicorn)   │
│  - Multiple workers     │
│  - Load balancing       │
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│  Docker Engine          │
│  - Container pool       │
│  - Resource monitoring  │
└─────────────────────────┘
```

## Next Steps to Enhance

1. **Authentication**: Add API keys or JWT tokens
2. **Logging**: Implement comprehensive logging
3. **Monitoring**: Add Prometheus/Grafana metrics
4. **Rate Limiting**: Prevent abuse per user
5. **File Upload**: Allow users to upload files to containers
6. **Persistent Storage**: Add volume support for user data
7. **Webhooks**: Notify on command completion
8. **WebSocket**: Real-time command output streaming
