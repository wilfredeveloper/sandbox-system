# Sandbox System V2 - Documentation Index

## Overview

The Enhanced Sandbox System V2 is a Docker-based sandbox for executing bash commands in a secure, isolated environment with persistent, thread-scoped sessions.

**Key Features**:
- ✅ Thread-scoped persistent sessions (files persist across commands)
- ✅ FastAPI + Uvicorn server (async, high performance)
- ✅ Python SDK with local/remote modes
- ✅ File upload/download/list capabilities
- ✅ Automatic session management and cleanup
- ✅ Command validation and resource limits
- ✅ Container pooling for fast session creation

---

## Documentation Structure

### 1. **sandbox-prompt.md** (Main Implementation Guide)
**Purpose**: Complete implementation specification for building the sandbox system

**Audience**: Developers/AI agents implementing the sandbox

**Contents**:
- Core architecture principles
- API specification (8 endpoints)
- Client SDK implementation
- Server implementation (FastAPI)
- Command validation logic
- Resource limits and security
- Container pool management
- Observability and logging
- Testing and deployment
- Technology migration guide (Flask→FastAPI, HTTP→SDK)

**Start here if**: You're building or modifying the sandbox system itself

---

### 2. **INTEGRATION_GUIDE.md** (Client Integration Guide)
**Purpose**: How to integrate the sandbox with AI agents and applications

**Audience**: Developers integrating the sandbox into their applications

**Contents**:
- Integration architecture overview
- Bash tool implementation example
- Configuration and environment variables
- Agent system prompt updates
- Deployment modes (local vs remote)
- Migration from Cloudflare Workers
- Best practices and troubleshooting
- Security considerations

**Start here if**: You're integrating the sandbox into an AI agent or application

---

### 3. **ARCHITECTURE_DIAGRAM.md** (Visual Architecture)
**Purpose**: Visual diagrams of system architecture and data flows

**Audience**: Anyone wanting to understand the system visually

**Contents**:
- High-level system architecture
- SDK approach (local vs remote modes)
- Data flow diagrams
- Session lifecycle
- Thread mapping visualization
- Container pool structure

**Start here if**: You want a visual overview of how the system works

---

### 4. **API_REFERENCE.md** (Quick API Reference)
**Purpose**: Quick reference for API endpoints and SDK methods

**Audience**: Developers using the sandbox

**Contents**:
- Endpoint summaries
- Request/response examples
- SDK method signatures
- Error codes and handling

**Start here if**: You need a quick API lookup

---

## Quick Start

### For Implementers (Building the Sandbox)

1. Read **sandbox-prompt.md** sections 1-3 (Overview, Architecture, API Spec)
2. Review **ARCHITECTURE_DIAGRAM.md** for visual understanding
3. Implement following **sandbox-prompt.md** step-by-step
4. Test using examples in **API_REFERENCE.md**

### For Integrators (Using the Sandbox)

1. Read **INTEGRATION_GUIDE.md** overview
2. Review **ARCHITECTURE_DIAGRAM.md** for deployment modes
3. Implement bash tool following **INTEGRATION_GUIDE.md** examples
4. Configure deployment mode (local vs remote)
5. Test and monitor

---

## Technology Stack

- **Server**: FastAPI + Uvicorn (Python 3.10+)
- **Client**: Python SDK (supports local/remote modes)
- **Runtime**: Docker (container pooling)
- **State**: Redis (optional, for distributed mode)
- **Security**: Non-root execution, command whitelisting, resource limits

---

## Key Concepts

### Thread-Scoped Sessions
Sessions are mapped by `thread_id` (conversation ID), not `user_id`. This allows:
- Multiple concurrent conversations per user
- Isolated filesystem state per conversation
- No file collisions between conversations

### Deployment Modes

**Local Mode** (Development):
- SDK calls server methods directly (in-process)
- Zero HTTP overhead
- Simpler debugging

**Remote Mode** (Production):
- SDK makes HTTP calls to remote server
- Horizontal scaling
- Resource isolation

### Session Lifecycle

```
Conversation starts → thread_id generated → session created
├─ Commands execute in same session
├─ Files persist across commands
├─ Auto-expires after idle timeout (30 min)
└─ Explicit cleanup on conversation end
```

---

## Support

For questions or issues:
1. Check **INTEGRATION_GUIDE.md** troubleshooting section
2. Review **sandbox-prompt.md** for implementation details
3. Consult **ARCHITECTURE_DIAGRAM.md** for system understanding

---

## Version

**Current Version**: Enhanced V2 (FastAPI + SDK)

**Previous Version**: V2 (Flask + HTTP-only)

**Migration Guide**: See **sandbox-prompt.md** section "Technology Migration Summary"

