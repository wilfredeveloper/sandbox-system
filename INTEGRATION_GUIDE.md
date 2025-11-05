# Sandbox System V2 - Integration Guide

This document describes how to integrate the Enhanced Sandbox System V2 with the MyPA backend AI agent.

## Overview

The sandbox system is designed to be used by AI agents that need to execute bash commands in a secure, isolated environment. The integration uses an **SDK approach** where the AI agent imports the `SandboxClient` directly rather than making HTTP calls.

## Integration Architecture

```
┌─────────────────────────────────────────────────────┐
│  MyPA Backend - AI Agent V3                         │
│  ┌──────────────────────────────────────────────┐  │
│  │  Composite Backend (File Storage)            │  │
│  │  - Long-term file persistence                │  │
│  │  - Semantic search over files                │  │
│  │  - User's permanent file repository          │  │
│  └──────────────────────────────────────────────┘  │
│                      ↕                              │
│  ┌──────────────────────────────────────────────┐  │
│  │  Bash Tool + Sandbox Client SDK              │  │
│  │  - Ephemeral workspace (session-scoped)      │  │
│  │  - Temporary processing/analysis             │  │
│  │  - Files deleted on session expiry           │  │
│  └──────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────┘
```

**Workflow**:
1. User uploads file → Stored in **composite backend** (permanent)
2. Agent needs to process → Downloads to **sandbox workspace** (temporary)
3. Agent runs bash commands on temporary copy
4. Agent extracts results/insights → Stores back to **composite backend** if needed
5. Session expires → Sandbox workspace cleaned up, but original file safe in composite backend

**Key Principle**: The sandbox is a **compute environment**, not a storage layer.

---

## Bash Tool Integration (SDK Approach)

### File Location

`mypa-backend/src/services/ai_agent_v3/tools/bash_tools.py`

### Changes Required

1. Replace Cloudflare Worker HTTP call with Sandbox Client SDK
2. Use `thread_id` from runtime context
3. Leverage persistent sessions (no more heredoc workarounds)
4. Use **local mode** for in-process calls (no HTTP overhead)

### Implementation

```python
from typing import Dict, Any, Annotated
from langchain.tools import tool, ToolRuntime, InjectedToolArg
import logging

logger = logging.getLogger(__name__)

from src.services.ai_agent_v3.context import AgentContext
from src.config.settings import get_settings

# Import sandbox client SDK
import sys
sys.path.append('../../sandbox-system/sandbox-v2')
from sandbox_client_v2 import SandboxClient

settings = get_settings()

# Global client instance (reused across tool calls)
_sandbox_client: SandboxClient | None = None

def get_sandbox_client() -> SandboxClient:
    """Get or create sandbox client singleton"""
    global _sandbox_client
    if _sandbox_client is None:
        # Use LOCAL mode for in-process calls (no HTTP overhead)
        # For distributed deployment, use mode="remote" with server_url
        _sandbox_client = SandboxClient(
            mode="local"  # Direct SDK calls, no HTTP
        )
    return _sandbox_client


@tool
async def execute_bash_command(
    command: str,
    working_dir: str = "/workspace",
    runtime: Annotated[ToolRuntime[AgentContext] | None, InjectedToolArg] = None
) -> Dict[str, Any]:
    """
    Execute bash command in persistent sandbox session.

    Each conversation has its own isolated sandbox session where files persist
    across multiple command executions. This enables:
    - Creating files in one command and using them in subsequent commands
    - Building up complex data processing pipelines
    - Uploading/downloading files to/from the workspace

    The sandbox session is automatically created on first use and persists
    for the duration of the conversation (30 min idle timeout).

    Supported Commands: jq, awk, grep, sed, sort, uniq, head, tail, wc, cut, tr,
                       cat, echo, date, find, ls, python3

    Safety:
    - Only whitelisted commands allowed
    - NO destructive operations (rm, mv, dd, sudo)
    - NO external network calls (curl, wget, ssh)
    - 30 second timeout per command
    - Isolated execution as non-root user

    Args:
        command: Bash command to execute
        working_dir: Working directory (always /workspace)
        runtime: Injected ToolRuntime with user context

    Returns:
        Dict with status, stdout, stderr, return_code

    Example:
        # Create a file and process it
        result1 = await execute_bash_command(
            command="echo '[{\"amount\": 42}, {\"amount\": 100}]' > data.json"
        )

        # Process the file in a subsequent command
        result2 = await execute_bash_command(
            command="jq -r '.[].amount' data.json | awk '{sum += $1} END {print sum}'"
        )
        # Returns: {"status": "success", "stdout": "142", ...}
    """
    if not runtime:
        return {"status": "error", "error": "Runtime context not provided"}

    user_id = runtime.context.user_id
    thread_id = runtime.context.session_id  # This is the conversation thread ID

    if not thread_id:
        return {"status": "error", "error": "No thread_id in context"}

    logger.info(f"[BASH] user={user_id[:8]}... thread={thread_id[:12]}... cmd={command[:100]}")

    try:
        # Get sandbox client
        client = get_sandbox_client()

        # Get or create session for this thread
        # This automatically reuses existing session if available
        session_info = client.get_or_create_session(
            user_id=user_id,
            thread_id=thread_id,
            timeout_minutes=30
        )

        logger.info(f"[BASH] Using session {session_info['session_id'][:12]}... (status={session_info['status']})")

        # Execute command (with auto-retry on session expiry)
        result = client.execute(command, timeout=30, auto_retry=True)

        # Log results
        if result['exit_code'] == 0:
            logger.info(f"[BASH] Command completed successfully ({result['execution_time_ms']}ms)")
        else:
            logger.error(f"[BASH] Command failed (exit={result['exit_code']})")
            logger.error(f"[BASH] STDERR: {result.get('stderr', '')[:500]}")

        # Return in format expected by agent
        return {
            "status": "success" if result['exit_code'] == 0 else "error",
            "stdout": result.get('stdout', ''),
            "stderr": result.get('stderr', ''),
            "return_code": result['exit_code']
        }

    except Exception as e:
        logger.error(f"[BASH] Execution failed: {e}", exc_info=True)
        return {
            "status": "error",
            "error": str(e),
            "command": command[:200],
            "stdout": "",
            "stderr": "",
            "return_code": -1
        }


# Export tool for registration
BASH_TOOLS = [execute_bash_command]
```

---

## Configuration

### Backend Settings

Add to `mypa-backend/src/config/settings.py`:

```python
class Settings(BaseSettings):
    # ... existing settings ...

    # Sandbox System (replaces cloudflare_sandbox_url)
    sandbox_mode: Literal["local", "remote"] = Field(
        'local',
        env='SANDBOX_MODE',
        description='Sandbox deployment mode: local (in-process) or remote (HTTP)'
    )

    sandbox_url: str = Field(
        'http://localhost:8000',
        env='SANDBOX_URL',
        description='Sandbox system URL (only used in remote mode)'
    )
```

### Environment Variables

Add to `mypa-backend/.env`:

```bash
# Sandbox System (replaces CLOUDFLARE_SANDBOX_URL)
SANDBOX_MODE=local  # or "remote" for distributed deployment
SANDBOX_URL=http://localhost:8000  # only used if SANDBOX_MODE=remote
```

---

## Agent System Prompt Updates

After implementing the sandbox system, update the agent system prompt to reflect the new capabilities:

### Remove References To:
- Heredoc workarounds for inlining data
- Ephemeral execution environments
- Cloudflare worker limitations

### Add References To:
- Persistent session model
- File-based workflows as the preferred approach
- Session persistence across commands within a conversation
- Automatic session management

### Example System Prompt Update:

**OLD**:
```
The bash tool executes commands in an ephemeral environment. Each command runs in a fresh container,
so you cannot create files in one command and use them in another. To work with data, use heredoc
syntax to inline the data directly in the command:

cat << 'EOF' | jq '.data'
{"data": [1, 2, 3]}
EOF
```

**NEW**:
```
The bash tool executes commands in a persistent sandbox session. Files created in one command
are available in subsequent commands within the same conversation. This enables natural workflows:

# Create a file
echo '{"data": [1, 2, 3]}' > data.json

# Use it in later commands
jq '.data' data.json

The session persists for 30 minutes of inactivity and is automatically cleaned up.
```

---

## Deployment Modes

### Local Mode (Development/Single Server)

**When to use**:
- Development environment
- Single-server deployments
- When backend and sandbox run on the same machine

**Configuration**:
```python
client = SandboxClient(mode="local")
```

**Benefits**:
- Zero HTTP overhead (10-50ms faster per command)
- Simpler debugging (single process, direct stack traces)
- No network configuration needed

**Limitations**:
- Backend and sandbox must run on same machine
- No horizontal scaling
- Sandbox crashes can affect backend

### Remote Mode (Production/Distributed)

**When to use**:
- Production deployments
- Multi-server architectures
- When you need horizontal scaling
- When you want resource isolation

**Configuration**:
```python
client = SandboxClient(
    mode="remote",
    server_url="http://sandbox-server:8000"
)
```

**Benefits**:
- Horizontal scaling (multiple sandbox servers)
- Resource isolation (sandbox crashes don't affect backend)
- Load balancing across sandbox servers
- Distributed session management with Redis

**Requirements**:
- Sandbox server running separately
- Network connectivity between backend and sandbox
- Optional: Redis for distributed session state

---

## Migration from Cloudflare Workers

### Step 1: Deploy Sandbox System

1. Build and deploy the sandbox system (see main `sandbox-prompt.md`)
2. Verify it's running: `curl http://localhost:8000/health`

### Step 2: Update Bash Tool

1. Replace the bash tool implementation with the code above
2. Update imports to use `SandboxClient`
3. Remove Cloudflare worker HTTP calls

### Step 3: Update Configuration

1. Add `SANDBOX_MODE` and `SANDBOX_URL` to `.env`
2. Update settings.py with new configuration fields
3. Remove `CLOUDFLARE_SANDBOX_URL` references

### Step 4: Update Agent Prompts

1. Update system prompt to remove heredoc workarounds
2. Update tool docstrings to reflect persistent sessions
3. Add examples of file-based workflows

### Step 5: Test

1. Test basic command execution
2. Test file persistence across commands
3. Test session reuse within a conversation
4. Test session expiry and auto-retry
5. Test file upload/download (if used)

### Step 6: Monitor

Track these metrics after deployment:
- Session reuse rate (should be >50%)
- Command execution time (should be faster than Cloudflare)
- Resource limit violations
- Auto-retry success rate

---

## Troubleshooting

### Issue: "No thread_id in context"

**Cause**: Runtime context not properly injected

**Solution**: Ensure the tool is registered with `InjectedToolArg` for runtime parameter

### Issue: "Session expired" errors

**Cause**: Session timeout too short for long conversations

**Solution**: Increase `timeout_minutes` in `get_or_create_session()` call

### Issue: Commands slower than expected

**Cause**: Using remote mode when local mode would suffice

**Solution**: Switch to `mode="local"` for single-server deployments

### Issue: "Pool at max capacity"

**Cause**: Too many concurrent sessions

**Solution**:
- Increase `MAX_POOL_SIZE` in sandbox settings
- Implement more aggressive session cleanup
- Use distributed mode with multiple sandbox servers

---

## Best Practices

### 1. File Management

**DO**:
- Use the composite backend for long-term file storage
- Download files to sandbox only when needed for processing
- Clean up large files after processing

**DON'T**:
- Rely on sandbox for permanent file storage
- Upload large files unnecessarily
- Keep files in sandbox after processing is complete

### 2. Session Management

**DO**:
- Let the client handle session creation automatically
- Use `auto_retry=True` for resilient execution
- Log session IDs for debugging

**DON'T**:
- Manually manage session lifecycle
- Create multiple sessions per conversation
- Ignore session expiry errors

### 3. Command Design

**DO**:
- Use file-based workflows for complex processing
- Chain commands with pipes when appropriate
- Validate command output before using in subsequent commands

**DON'T**:
- Use heredoc syntax (no longer needed)
- Execute destructive commands
- Rely on external network access

---

## Security Considerations

### Sandbox Isolation

The sandbox provides:
- ✅ Non-root execution (commands run as `sandboxuser`)
- ✅ Command whitelisting (only approved commands allowed)
- ✅ No network access (curl, wget, ssh blocked)
- ✅ Resource limits (file size, count, workspace size)
- ✅ Timeout enforcement (30 seconds per command)

### What the Sandbox Does NOT Protect Against

- ❌ Malicious data in files (e.g., CSV injection)
- ❌ Resource exhaustion via allowed commands (e.g., infinite loops in awk)
- ❌ Information leakage between sessions (mitigated by thread-scoped sessions)

### Additional Recommendations

1. **Validate user input** before passing to bash commands
2. **Sanitize file contents** before processing
3. **Monitor resource usage** and set appropriate limits
4. **Audit command logs** for suspicious patterns
5. **Rotate container images** regularly for security patches

---

## Final Note

After implementing this integration, the agent will have access to a powerful, persistent sandbox environment that enables natural file-based workflows while maintaining security and isolation. The SDK approach provides better performance and developer experience compared to the previous Cloudflare worker implementation.

