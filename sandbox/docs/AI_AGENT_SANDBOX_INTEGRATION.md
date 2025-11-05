# AI Agent Sandbox Integration - Proposed Workflow

## Executive Summary

This document proposes a new workflow for integrating the MyPA sandbox system with the AI agent, replacing the current Cloudflare sandbox approach.

### Key Insight

**Single tool with auto-upload**: The bash tool should accept a command and optional file paths. Files are automatically uploaded from the virtual filesystem (PostgreSQL) to the sandbox before execution. No separate upload/download tools needed.

### Current vs. Proposed

| Aspect | Current (Cloudflare) | Proposed (MyPA Sandbox) |
|--------|---------------------|------------------------|
| **File handling** | Inline via heredocs | Auto-upload from virtual filesystem |
| **Session** | Ephemeral (destroyed after each command) | Persistent (thread-scoped) |
| **Workflow** | Read → Inline → Execute | Save → Execute (auto-upload) |
| **Code complexity** | 15 lines with heredocs | 8 lines, simple |
| **System prompt** | 100+ lines of heredoc instructions | Simple auto-upload explanation |
| **Tools needed** | 1 (execute_bash_command) | 1 (execute_bash_command with file_paths) |

### Benefits

- ✅ **50% less code** in agent workflows
- ✅ **100+ lines removed** from system prompt
- ✅ **Single tool** - No separate upload/download tools
- ✅ **Auto-upload** - Files automatically transferred before execution
- ✅ **Persistent workspace** - Files stay in sandbox for entire conversation
- ✅ **Simpler for agent** - Clear, obvious workflow

## Current Architecture Analysis

### Current State: Cloudflare Sandbox (Ephemeral)

**Location**: `mypa-backend/src/services/ai_agent_v3/tools/bash_tools.py`

**Current Workflow**:
1. Agent needs to process data → Must inline data via heredocs
2. Execute bash command with inlined data in Cloudflare sandbox
3. Get results back
4. Container destroyed (ephemeral)

**Problems**:
- No file persistence between commands
- Must inline all data via heredocs (verbose, error-prone)
- No file upload/download capabilities
- Limited to 30s execution time
- Agent prompt is complex with heredoc instructions

**Example from system prompt (lines 212-228)**:
```python
# Step 1: Get data from filesystem
data = read_file("/data-exports/my_data.json")

# Step 2: Inline data in bash command using heredoc
execute_bash_command(command=f'''
cat > /tmp/data.json << 'EOF'
{data}
EOF

jq '.[] | .amount' /tmp/data.json | awk "{{sum += $1}} END {{print sum}}"
''')
```

### New State: MyPA Sandbox (Persistent Sessions)

**Location**: `sandbox-system/sandbox/`

**Key Features**:
- **Thread-scoped sessions**: Persistent workspace per conversation
- **File upload/download**: Direct file transfer to/from sandbox
- **Local mode**: Direct in-process calls (no HTTP overhead)
- **Session reuse**: Same workspace across multiple commands in a conversation
- **Resource limits**: 100MB per file, 500MB workspace, 1000 files max

## Proposed Architecture

### Core Principle: Separation of Concerns

```
┌─────────────────────────────────────────────────────────────┐
│                      AI Agent (DeepAgents)                   │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────────────┐      ┌─────────────────────────┐ │
│  │ Virtual Filesystem   │      │   Bash Tool             │ │
│  │ (deepagents)         │      │   (execute commands)    │ │
│  ├──────────────────────┤      ├─────────────────────────┤ │
│  │ - read_file()        │      │ - execute_bash_command()│ │
│  │ - write_file()       │      │   + auto file upload    │ │
│  │ - edit_file()        │      │ - NO file operations    │ │
│  │ - ls()               │      │ - Pure computation      │ │
│  └──────────┬───────────┘      └───────────┬─────────────┘ │
│             │                              │               │
│             │ Stores in                    │ Executes in   │
│             ▼                              ▼               │
│  ┌──────────────────────┐      ┌─────────────────────────┐ │
│  │ PostgreSQL Store     │      │   MyPA Sandbox          │ │
│  │ (/memories/,         │      │   (thread-scoped)       │ │
│  │  /data-exports/,     │      │                         │ │
│  │  /scripts/)          │      │   Workspace: /workspace │ │
│  └──────────────────────┘      └─────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### File Flow: Automatic Upload on Execute

**Simplified Workflow**:
1. **Agent saves data to virtual filesystem** (PostgreSQL) using `write_file()`
2. **Agent calls bash tool with command + file paths**
3. **Bash tool automatically uploads files** from virtual filesystem to sandbox
4. **Bash tool executes command** on files in `/workspace/`
5. **Agent optionally downloads results** back to virtual filesystem if needed

### Why This Design?

**Virtual Filesystem (PostgreSQL)**:
- ✅ Persistent across conversations
- ✅ User-scoped namespaces
- ✅ Integrated with agent memory
- ✅ No size limits for long-term storage
- ✅ Accessible from all agent tools

**Sandbox Workspace**:
- ✅ Isolated execution environment
- ✅ Fast file I/O for processing
- ✅ Thread-scoped (conversation-scoped)
- ✅ Automatic cleanup after conversation
- ✅ Resource limits prevent abuse

## Proposed Tool Design

### Single Bash Tool with Auto-Upload

**Key Insight**: The agent shouldn't need separate upload/download tools. The bash tool should handle file transfer automatically.

**New bash_tools.py**:
```python
@tool
async def execute_bash_command(
    command: str,
    file_paths: Optional[List[str]] = None,
    runtime: Annotated[ToolRuntime[AgentContext] | None, InjectedToolArg] = None
) -> Dict[str, Any]:
    """
    Execute bash command in persistent sandbox workspace.

    Files from virtual filesystem are automatically uploaded to sandbox before execution.
    Files in sandbox are accessible at /workspace/<filename>.

    Args:
        command: Bash command to execute
        file_paths: Optional list of file paths from virtual filesystem to upload
                   (e.g., ["/data-exports/receipts.json", "/scripts/process.py"])

    Returns:
        {
            "exit_code": 0,
            "stdout": "...",
            "stderr": "...",
            "execution_time_ms": 150,
            "uploaded_files": ["receipts.json", "process.py"]
        }

    Example:
        # Step 1: Save data to virtual filesystem
        write_file("/data-exports/receipts.json", json.dumps(receipts))

        # Step 2: Execute command (file auto-uploaded)
        result = execute_bash_command(
            command="jq '.[] | .amount' /workspace/receipts.json | awk '{sum += $1} END {print sum}'",
            file_paths=["/data-exports/receipts.json"]
        )

        # Step 3: If you need to save output, use write_file
        write_file("/data-exports/total.txt", result["stdout"])
    """
    # 1. Get or create sandbox session (thread-scoped)
    sandbox_client = get_sandbox_client()
    sandbox_client.get_or_create_session(
        user_id=runtime.context.user_id,
        thread_id=runtime.context.thread_id
    )

    # 2. Auto-upload files from virtual filesystem to sandbox
    uploaded_files = []
    if file_paths:
        for path in file_paths:
            # Read from virtual filesystem (PostgreSQL)
            file_content = await read_file(path)

            # Upload to sandbox workspace
            filename = os.path.basename(path)
            sandbox_client.upload_file_from_bytes(filename, file_content.encode())
            uploaded_files.append(filename)

            logger.info(f"Auto-uploaded {path} → /workspace/{filename}")

    # 3. Execute command in sandbox
    result = sandbox_client.execute(command)

    # 4. Add uploaded files to result
    result["uploaded_files"] = uploaded_files

    return result
```

**Key Features**:
- ✅ **Single tool** - No separate upload/download tools needed
- ✅ **Auto-upload** - Files automatically transferred before execution
- ✅ **Simple API** - Just command + file paths
- ✅ **No heredocs** - Files accessed at `/workspace/`
- ✅ **Session managed** - Thread-scoped, persistent across commands

### Optional: Download Helper (if needed)

Most of the time, the agent can just read stdout. But for large outputs, we can add a simple helper:

```python
@tool
async def download_sandbox_file(
    filename: str,
    save_path: str,
    runtime: Annotated[ToolRuntime[AgentContext] | None, InjectedToolArg] = None
) -> Dict[str, Any]:
    """
    Download file from sandbox workspace to virtual filesystem.

    Only needed for large outputs. For small outputs, just use stdout from execute_bash_command.

    Args:
        filename: Filename in sandbox (e.g., "results.csv")
        save_path: Path to save in virtual filesystem (e.g., "/data-exports/results.csv")

    Returns:
        {"status": "downloaded", "path": "/data-exports/results.csv", "size_bytes": 512}
    """
    sandbox_client = get_sandbox_client()
    file_data = sandbox_client.download_file(filename)

    await write_file(save_path, file_data.decode())

    return {"status": "downloaded", "path": save_path, "size_bytes": len(file_data)}
```

### Sandbox Client Integration

**Location**: `mypa-backend/src/services/ai_agent_v3/tools/sandbox_utils.py` (new file)

```python
from sandbox.client import SandboxClient

# Singleton client in local mode (direct in-process calls)
_sandbox_client = None

def get_sandbox_client() -> SandboxClient:
    """Get or create sandbox client in local mode."""
    global _sandbox_client
    if _sandbox_client is None:
        _sandbox_client = SandboxClient(mode="local")
    return _sandbox_client
```

## Workflow Examples

### Example 1: Calculate Uber Receipt Total (Simplified)

**Old Workflow (Cloudflare + Heredocs)** - 15 lines, complex:
```python
# Step 1: Search emails
emails = search_emails("from:uber.com receipt")

# Step 2: Extract amounts and save
receipts = [{"amount": extract_amount(e)} for e in emails]
write_file("/data-exports/uber_receipts.json", json.dumps(receipts))

# Step 3: Read back and inline in bash command
receipts_json = read_file("/data-exports/uber_receipts.json")
result = execute_bash_command(f'''
cat > /tmp/receipts.json << 'EOF'
{receipts_json}
EOF

jq -r ".[] | .amount" /tmp/receipts.json | awk "{{sum += $1}} END {{print sum}}"
''')
```

**New Workflow (MyPA Sandbox)** - 8 lines, simple:
```python
# Step 1: Search emails
emails = search_emails("from:uber.com receipt")

# Step 2: Extract amounts and save to virtual filesystem
receipts = [{"amount": extract_amount(e)} for e in emails]
write_file("/data-exports/uber_receipts.json", json.dumps(receipts))

# Step 3: Execute command (file auto-uploaded!)
result = execute_bash_command(
    command='jq -r ".[] | .amount" /workspace/uber_receipts.json | awk \'{sum += $1} END {print sum}\'',
    file_paths=["/data-exports/uber_receipts.json"]
)

# Result: {"exit_code": 0, "stdout": "142.50", "uploaded_files": ["uber_receipts.json"]}
```

**Benefits**:
- ✅ **50% less code** - No heredoc complexity
- ✅ **Auto-upload** - File automatically transferred to sandbox
- ✅ **Persistent** - File stays in sandbox for follow-up commands
- ✅ **Clear** - Obvious what's happening at each step

### Example 2: Multi-Step Data Processing

**Scenario**: Process calendar events, generate report, save results

```python
# Step 1: Get calendar events and save to virtual filesystem
events = list_calendar_events(start="2024-01-01", end="2024-12-31")
write_file("/data-exports/events_2024.json", json.dumps(events))

# Step 2: Process with Python in sandbox (file auto-uploaded)
result = execute_bash_command(
    command='''
python3 << 'EOF'
import json

with open("/workspace/events_2024.json") as f:
    events = json.load(f)

# Categorize meetings
categories = {}
for event in events:
    if "standup" in event["title"].lower():
        cat = "Standups"
    elif "1:1" in event["title"]:
        cat = "1-on-1s"
    else:
        cat = "Other"

    duration = event.get("duration_minutes", 30)
    categories[cat] = categories.get(cat, 0) + duration

# Print report to stdout
for cat, mins in categories.items():
    print(f"{cat}: {mins/60:.1f} hours")
EOF
''',
    file_paths=["/data-exports/events_2024.json"]
)

# Step 3: Save results to virtual filesystem
write_file("/data-exports/meeting_report_2024.txt", result["stdout"])

# Step 4: Present to user
# Report is in result["stdout"] or read from virtual filesystem
```

**Alternative: Large Output (Download from Sandbox)**:
```python
# If output is too large for stdout, save to file in sandbox and download
result = execute_bash_command(
    command='''
python3 << 'EOF'
import json

with open("/workspace/events_2024.json") as f:
    events = json.load(f)

# ... processing ...

# Save to file instead of stdout
with open("/workspace/meeting_report.txt", "w") as f:
    for cat, mins in categories.items():
        f.write(f"{cat}: {mins/60:.1f} hours\\n")
EOF
''',
    file_paths=["/data-exports/events_2024.json"]
)

# Download large file from sandbox
download_sandbox_file("meeting_report.txt", "/data-exports/meeting_report_2024.txt")
```

**Benefits**:
- ✅ **Auto-upload** - File automatically transferred to sandbox
- ✅ **Persistent session** - Multiple commands in same workspace
- ✅ **Flexible output** - Use stdout for small results, file download for large results
- ✅ **Clean code** - No manual upload/download steps

## System Prompt Changes

### Current Bash Tool Section (Lines 198-334)

**Remove**:
- All heredoc instructions (100+ lines)
- Data inlining examples
- Complex multi-step heredoc patterns

**Replace with** (much simpler):

```markdown
### Bash Tools for Data Analysis

You have access to powerful Bash command execution in a persistent sandbox workspace.

**Tool: `execute_bash_command(command, file_paths=None)`**

Execute bash commands in a thread-scoped sandbox. Files from the virtual filesystem are automatically uploaded before execution.

**Parameters:**
- `command`: Bash command to execute
- `file_paths`: Optional list of file paths from virtual filesystem to auto-upload
  (e.g., `["/data-exports/data.json", "/scripts/process.py"]`)

**When to Use Bash:**
1. **Calculate totals/averages** from data files (exact arithmetic required)
2. **Filter large datasets** efficiently with jq, awk, grep
3. **Complex data transformations** with pipes and standard Unix tools
4. **Python scripts** for advanced processing

**Simple Workflow:**
1. Save data to virtual filesystem: `write_file("/data-exports/data.json", ...)`
2. Execute command with auto-upload: `execute_bash_command(command="...", file_paths=["/data-exports/data.json"])`
3. Results in stdout, or save to virtual filesystem if needed

**Sandbox Workspace:**
- Files auto-uploaded to `/workspace/<filename>`
- Workspace persists for entire conversation (thread-scoped)
- Automatically cleaned up when conversation ends
- Limits: 100MB per file, 500MB total, 1000 files max

**Example - Calculate Receipt Total:**
```python
# Step 1: Save data to virtual filesystem
receipts = [{"amount": 45.50}, {"amount": 67.00}, {"amount": 30.00}]
write_file("/data-exports/receipts.json", json.dumps(receipts))

# Step 2: Execute command (file auto-uploaded to /workspace/receipts.json)
result = execute_bash_command(
    command="jq '.[] | .amount' /workspace/receipts.json | awk '{sum += $1} END {print sum}'",
    file_paths=["/data-exports/receipts.json"]
)

# Result: {"exit_code": 0, "stdout": "142.50", "uploaded_files": ["receipts.json"]}
```

**Example - Multi-File Processing:**
```python
# Save multiple files
write_file("/data-exports/data.json", json.dumps(data))
write_file("/scripts/process.py", python_script)

# Execute with multiple files auto-uploaded
result = execute_bash_command(
    command="python3 /workspace/process.py /workspace/data.json",
    file_paths=["/data-exports/data.json", "/scripts/process.py"]
)
```

**Available Commands:**
- **jq**: JSON processing
- **awk**: Text processing, math, aggregation
- **grep, sed**: Pattern matching and text transformation
- **sort, uniq, head, tail, wc**: Data manipulation
- **python3**: Advanced scripting
- **cat, echo, ls**: File operations

**Safety:**
- Sandboxed execution (isolated containers)
- 30-second timeout per command
- Whitelisted commands only
- No network access (curl, wget blocked)
- No destructive operations (rm, sudo blocked)

**Optional: Download Large Files**

For large outputs, save to file in sandbox and download:

```python
# Execute and save output to file
execute_bash_command(
    command="jq '...' /workspace/data.json > /workspace/results.csv",
    file_paths=["/data-exports/data.json"]
)

# Download large file
download_sandbox_file("results.csv", "/data-exports/results.csv")
```
```

## Implementation Checklist

### Phase 1: Sandbox Client Enhancement
- [ ] Add `upload_file_from_bytes()` method to SandboxClient (if not exists)
  - Should accept filename and bytes data
  - Should work in both local and remote modes
- [ ] Verify session management works with thread_id
- [ ] Test auto-retry on session expiry

### Phase 2: Bash Tool Refactor
- [ ] Create `sandbox_utils.py` with singleton client
- [ ] Update `execute_bash_command()` signature:
  - Add `file_paths: Optional[List[str]] = None` parameter
  - Add auto-upload logic before command execution
  - Add session management (get_or_create_session)
  - Return uploaded_files in result
- [ ] Remove heredoc validation logic (no longer needed)
- [ ] Remove data inlining instructions from docstring
- [ ] Update error handling for session expiry

### Phase 3: Optional Download Tool
- [ ] Implement `download_sandbox_file()` tool (optional)
  - Only needed for large outputs
  - Most results can use stdout

### Phase 4: System Prompt Update
- [ ] Remove heredoc instructions (lines 212-228, ~100 lines)
- [ ] Add new bash tool documentation with auto-upload
- [ ] Update examples to use new pattern
- [ ] Simplify workflow description

### Phase 5: Testing
- [ ] Test auto-upload from virtual filesystem
- [ ] Test bash command execution on uploaded files
- [ ] Test multiple file uploads in single command
- [ ] Test session persistence across multiple commands
- [ ] Test session cleanup on conversation end
- [ ] Test resource limits (file size, count, workspace size)
- [ ] Test error handling (file not found, session expired, etc.)

## Current Implementation Status

### ✅ Already Implemented in Sandbox
- Thread-scoped session management (`get_or_create_session()`)
- Session persistence across commands
- File upload/download APIs
- Local mode (in-process) support
- Auto-retry on session expiry
- Resource limits enforcement

### ⚠️ Needs Enhancement in Sandbox
- **Add `upload_file_from_bytes()` method** to SandboxClient
  - Current `upload_file()` expects file path on disk
  - Need method that accepts filename + bytes data
  - Should work in both local and remote modes

**Proposed Addition to `client.py`**:
```python
def upload_file_from_bytes(
    self,
    filename: str,
    file_data: bytes
) -> Dict[str, Any]:
    """
    Upload file from bytes data to workspace.

    Args:
        filename: Name to save file as in workspace
        file_data: File content as bytes

    Returns:
        Upload result dict
    """
    if not self.session_id:
        raise ValueError("No active session. Call get_or_create_session() first.")

    if self.mode == "local":
        # Direct method call
        return self._server.upload_file(self.session_id, filename, file_data)
    else:
        # Remote HTTP call
        files = {'file': (filename, file_data)}
        response = requests.post(
            f"{self.server_url}/upload_file",
            files=files,
            data={'session_id': self.session_id},
            timeout=60
        )
        response.raise_for_status()
        return response.json()
```

### 🔨 Needs Implementation in AI Agent
- Bash tool refactor with auto-upload
- Sandbox client singleton
- System prompt update
- Remove Cloudflare sandbox dependency

## Benefits Summary

### For the Agent
- ✅ **Simpler prompts**: No heredoc complexity (remove 100+ lines)
- ✅ **Clearer workflow**: Save → Execute (auto-upload) → Results
- ✅ **Better error handling**: File operations separate from execution
- ✅ **Persistent workspace**: Files available across commands in conversation

### For Users
- ✅ **Faster execution**: No data inlining overhead
- ✅ **Larger datasets**: Upload files instead of inlining
- ✅ **Better reliability**: Session persistence prevents data loss
- ✅ **Transparent**: Clear file flow (PostgreSQL ↔ Sandbox)

### For Developers
- ✅ **Separation of concerns**: Filesystem vs. execution
- ✅ **Easier debugging**: Clear boundaries between components
- ✅ **Better testing**: Mock sandbox client easily
- ✅ **Scalable**: Local mode for dev, remote mode for production
- ✅ **Single tool**: No separate upload/download tools needed

## Migration Path

1. **Enhance sandbox client** - Add `upload_file_from_bytes()` method
2. **Refactor bash tool** - Add auto-upload with `file_paths` parameter
3. **Update system prompt** - Remove heredocs, add new workflow
4. **Test thoroughly** - Verify auto-upload, session persistence, error handling
5. **Deploy gradually** - Monitor usage, validate behavior
6. **Remove Cloudflare sandbox** - Clean up old code

## Conclusion

This design leverages the strengths of both systems:
- **DeepAgents virtual filesystem**: Long-term storage, user-scoped, integrated with agent memory
- **MyPA sandbox**: Fast execution, isolated environment, thread-scoped workspace

The result is a **simpler, more powerful, and more maintainable** system:
- **50% less code** in agent workflows
- **100+ lines removed** from system prompt
- **Single tool** instead of multiple upload/download tools
- **Auto-upload** makes file handling transparent
- **Easier for agent to use** and easier for developers to understand


