"""
Enhanced Sandbox Server V2 with FastAPI
- Thread-scoped persistent sessions
- Dual mode: Local (in-process) and Remote (HTTP)
- File upload/download capabilities
- Server-side command validation
- Resource limits enforcement
- Pre-warmed container pooling
- Non-root user execution
"""

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import docker
import uuid
import redis
import json
import logging
import re
import shlex
import tarfile
import io
import os
from datetime import datetime, timedelta
from threading import Thread, Lock
from typing import Optional, Dict, Any, List, Literal
import time
import signal
import sys
import atexit

from settings import settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize Docker client
client = docker.from_env()

# Redis configuration
if settings.REDIS_ENABLED:
    redis_client = redis.Redis(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        password=settings.REDIS_PASSWORD,
        decode_responses=True
    )
    logger.info(f"✓ Redis enabled - distributed mode ({settings.REDIS_HOST}:{settings.REDIS_PORT})")
else:
    redis_client = None
    logger.info("✓ Redis disabled - standalone mode")

# ============================================================================
# Command Validation (Server-Side)
# ============================================================================

ALLOWED_COMMANDS = {
    # Text processing
    'jq', 'awk', 'grep', 'sed', 'sort', 'uniq', 'head',
    'tail', 'wc', 'cut', 'tr', 'cat', 'echo', 'date',
    'comm', 'diff', 'tee',
    # File operations
    'find', 'ls', 'basename', 'dirname', 'file', 'stat',
    'mkdir', 'touch', 'rm', 'cp', 'mv',
    # Navigation
    'cd', 'pwd', 'whoami',
    # Programming
    'python3', 'python', 'bc'
}

FORBIDDEN_PATTERNS = [
    r'\brm\b', r'\bmv\b', r'\bdd\b', r'\bcurl\b', r'\bwget\b',
    r'\bssh\b', r'\bsudo\b', r'\bchmod\b', r'\bchown\b'
]


def split_on_operators(command: str) -> List[str]:
    """Split command on pipe and logical operators"""
    parts = []
    current = []
    tokens = shlex.split(command, posix=True)

    for token in tokens:
        if token in ('|', '&&', '||', ';'):
            if current:
                parts.append(' '.join(current))
                current = []
        else:
            current.append(token)

    if current:
        parts.append(' '.join(current))

    return parts


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


# ============================================================================
# Container Pool Management
# ============================================================================

class ContainerPool:
    """Hybrid pool manager with aggressive cleanup for resource efficiency"""

    def __init__(self, size=settings.POOL_SIZE):
        self.size = size
        self.containers = []  # Available containers ready for use
        self.allocated_containers = {}  # {container_id: allocation_time}
        self.lock = Lock()

    def initialize(self):
        """Create initial pool of containers"""
        logger.info(f"⚙ Initializing container pool with {self.size} containers...")
        for i in range(self.size):
            container = self._create_container()
            if container:
                self.containers.append(container)
                logger.info(f"  ✓ Container {i+1}/{self.size} ready")
        logger.info(f"✓ Pool initialized with {len(self.containers)} containers")

    def _create_container(self):
        """Create a single container"""
        try:
            container = client.containers.run(
                settings.CONTAINER_IMAGE,
                command="sleep infinity",
                detach=True,
                mem_limit=settings.MEMORY_LIMIT,
                cpu_quota=settings.CPU_QUOTA,
                network_mode=settings.DOCKER_NETWORK_MODE,
                remove=False,
                user=settings.SANDBOX_USER,
                working_dir=settings.WORKSPACE_DIR
            )
            return container
        except Exception as e:
            logger.error(f"✗ Error creating container: {e}")
            return None

    def get_container(self):
        """Get a container from the pool (instant if available, create if needed)"""
        with self.lock:
            if self.containers:
                # Fast path: get from pre-warmed pool
                container = self.containers.pop()
                self.allocated_containers[container.id] = time.time()
                # Async refill to maintain minimum pool size
                Thread(target=self._refill_pool, daemon=True).start()
                return container
            else:
                # Slow path: create on demand
                total_containers = len(self.allocated_containers)
                if total_containers >= settings.MAX_POOL_SIZE:
                    logger.warning(f"⚠ Pool at max capacity ({settings.MAX_POOL_SIZE})")
                    return None

                logger.info("⚙ Pool empty, creating container on demand...")
                container = self._create_container()
                if container:
                    self.allocated_containers[container.id] = time.time()
                return container

    def return_container(self, container):
        """Return a container to the pool after cleanup"""
        try:
            # Remove from allocated tracking
            with self.lock:
                self.allocated_containers.pop(container.id, None)

            # Reset the container state
            container.exec_run(
                f"sh -c 'rm -rf {settings.WORKSPACE_DIR}/* {settings.WORKSPACE_DIR}/.*' 2>/dev/null || true",
                user=settings.SANDBOX_USER
            )

            with self.lock:
                current_pool_size = len(self.containers)
                total_containers = current_pool_size + len(self.allocated_containers)

                # Aggressive cleanup: only keep containers if below max and pool needs refilling
                if settings.AGGRESSIVE_CLEANUP:
                    if current_pool_size < settings.MIN_POOL_SIZE:
                        # Pool needs refilling
                        self.containers.append(container)
                    elif current_pool_size < settings.POOL_SIZE and total_containers < settings.MAX_POOL_SIZE:
                        # Pool could use more containers
                        self.containers.append(container)
                    else:
                        # Pool is full enough, destroy to free resources
                        logger.info(f"⚙ Destroying idle container (pool size: {current_pool_size})")
                        container.stop(timeout=2)
                        container.remove()
                else:
                    # Non-aggressive: keep up to max pool size
                    if current_pool_size < settings.MAX_POOL_SIZE:
                        self.containers.append(container)
                    else:
                        container.stop(timeout=2)
                        container.remove()

        except Exception as e:
            logger.error(f"✗ Error returning container: {e}")
            try:
                container.stop(timeout=2)
                container.remove()
            except:
                pass

    def _refill_pool(self):
        """Refill the pool to minimum size (with delay to avoid thrashing)"""
        time.sleep(settings.POOL_REFILL_DELAY_SECONDS)

        with self.lock:
            current_size = len(self.containers)
            if current_size < settings.MIN_POOL_SIZE:
                needed = settings.MIN_POOL_SIZE - current_size
                logger.info(f"⚙ Refilling pool: {current_size} -> {settings.MIN_POOL_SIZE}")
                for _ in range(needed):
                    container = self._create_container()
                    if container:
                        self.containers.append(container)

    def get_stats(self):
        """Get current pool statistics"""
        with self.lock:
            return {
                'available': len(self.containers),
                'allocated': len(self.allocated_containers),
                'total': len(self.containers) + len(self.allocated_containers),
                'max_capacity': settings.MAX_POOL_SIZE
            }

    def cleanup_all(self):
        """Clean up all containers in the pool"""
        with self.lock:
            # Clean up available containers
            for container in self.containers:
                try:
                    container.stop(timeout=2)
                    container.remove()
                except:
                    pass
            self.containers = []

            # Clean up allocated containers
            for container_id in list(self.allocated_containers.keys()):
                try:
                    container = client.containers.get(container_id)
                    container.stop(timeout=2)
                    container.remove()
                except:
                    pass
            self.allocated_containers = {}


# Initialize the pool
pool = ContainerPool(size=settings.POOL_SIZE)


# ============================================================================
# Session Management
# ============================================================================

# Global state (in-memory or Redis)
active_sessions = {}  # {session_id: session_data}
session_last_activity = {}  # {session_id: last_activity_timestamp}
thread_to_session = {}  # thread_id → session_id mapping


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
        # Redis client has decode_responses=True, so session_id is already a str
        return session_id if session_id else None
    else:
        return thread_to_session.get(thread_id)


def remove_thread_mapping(thread_id: str):
    """Remove thread_id mapping on cleanup"""
    if settings.REDIS_ENABLED:
        redis_client.delete(f"thread:{thread_id}")
    else:
        thread_to_session.pop(thread_id, None)


def store_session(session_id, container_id, user_id, thread_id):
    """Store session info (Redis or local)"""
    session_data = {
        'container_id': container_id,
        'user_id': user_id,
        'thread_id': thread_id,
        'created_at': datetime.now().isoformat(),
        'last_activity': datetime.now().isoformat(),
        'worker': settings.WORKER_ID
    }

    if settings.REDIS_ENABLED:
        redis_client.setex(
            f"session:{session_id}",
            int(settings.SESSION_TIMEOUT.total_seconds()),
            json.dumps(session_data)
        )
    else:
        active_sessions[session_id] = session_data
        session_last_activity[session_id] = datetime.now()


def get_session(session_id):
    """Get session info (Redis or local)"""
    if settings.REDIS_ENABLED:
        data = redis_client.get(f"session:{session_id}")
        return json.loads(data) if data else None
    else:
        return active_sessions.get(session_id)


def update_session_activity(session_id):
    """Update last activity timestamp for a session"""
    if settings.REDIS_ENABLED:
        session_data = get_session(session_id)
        if session_data:
            session_data['last_activity'] = datetime.now().isoformat()
            redis_client.setex(
                f"session:{session_id}",
                int(settings.SESSION_TIMEOUT.total_seconds()),
                json.dumps(session_data)
            )
    else:
        if session_id in active_sessions:
            active_sessions[session_id]['last_activity'] = datetime.now().isoformat()
            session_last_activity[session_id] = datetime.now()


def delete_session(session_id):
    """Delete session info (Redis or local)"""
    if settings.REDIS_ENABLED:
        redis_client.delete(f"session:{session_id}")
    else:
        active_sessions.pop(session_id, None)
        session_last_activity.pop(session_id, None)


def cleanup_session_internal(session_id):
    """Stop and remove a container, return to pool if possible"""
    session_data = get_session(session_id)
    if session_data:
        try:
            # Remove thread mapping
            thread_id = session_data.get('thread_id')
            if thread_id:
                remove_thread_mapping(thread_id)

            container = client.containers.get(session_data['container_id'])
            pool.return_container(container)
        except Exception as e:
            logger.error(f"✗ Error cleaning up {session_id}: {e}")
        finally:
            delete_session(session_id)


def get_workspace_info(container) -> Dict[str, Any]:
    """Get workspace file count and total size"""
    try:
        result = container.exec_run(
            f'bash -c "du -sb {settings.WORKSPACE_DIR} && find {settings.WORKSPACE_DIR} -type f | wc -l"',
            user=settings.SANDBOX_USER
        )

        if result.exit_code != 0:
            return {'total_size': 0, 'total_files': 0}

        output = result.output.decode('utf-8').strip().split('\n')
        total_size = int(output[0].split()[0]) if output else 0
        total_files = int(output[1]) if len(output) > 1 else 0

        return {'total_size': total_size, 'total_files': total_files}
    except:
        return {'total_size': 0, 'total_files': 0}


# ============================================================================
# Background Cleanup
# ============================================================================

def init_pool():
    """Initialize pool in background"""
    pool.initialize()
    # Start background cleanup thread
    Thread(target=cleanup_loop, daemon=True).start()


def cleanup_loop():
    """Background thread to cleanup expired and idle sessions"""
    while True:
        time.sleep(settings.CLEANUP_INTERVAL_SECONDS)
        cleanup_expired_sessions()
        if settings.AGGRESSIVE_CLEANUP:
            cleanup_idle_containers()


def cleanup_expired_sessions():
    """Remove sessions that have exceeded SESSION_TIMEOUT"""
    if not settings.REDIS_ENABLED:
        now = datetime.now()
        expired = []

        for sid, data in list(active_sessions.items()):
            created = datetime.fromisoformat(data['created_at'])
            if now - created > settings.SESSION_TIMEOUT:
                expired.append(sid)
                logger.info(f"⚙ Cleaning up expired session: {sid}")

        for sid in expired:
            cleanup_session_internal(sid)


def cleanup_idle_containers():
    """Remove containers that have been idle for CONTAINER_IDLE_TIMEOUT"""
    if not settings.REDIS_ENABLED:
        now = datetime.now()
        idle = []

        for sid, last_activity in list(session_last_activity.items()):
            if now - last_activity > settings.CONTAINER_IDLE_TIMEOUT:
                idle.append(sid)
                logger.info(f"⚙ Cleaning up idle container: {sid}")

        for sid in idle:
            cleanup_session_internal(sid)


# ============================================================================
# SandboxServer Class (for Local Mode)
# ============================================================================

class SessionExpiredError(Exception):
    """Raised when session is expired in local mode"""
    pass


class SandboxServer:
    """
    Server class for direct (non-HTTP) usage in local mode.
    Provides the same functionality as HTTP endpoints but as direct method calls.
    """

    def __init__(self):
        """Initialize server components"""
        self.pool = pool
        self.sessions = active_sessions
        self.thread_to_session_map = thread_to_session

    def get_session_by_thread(self, thread_id: str) -> Optional[Dict]:
        """Get session info by thread_id (direct method call)"""
        session_id = get_session_by_thread(thread_id)
        if not session_id:
            return None

        session_data = get_session(session_id)
        if not session_data:
            # Stale mapping, cleanup
            remove_thread_mapping(thread_id)
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
        existing_session_id = get_session_by_thread(thread_id)
        if existing_session_id and existing_session_id in active_sessions:
            session_data = active_sessions[existing_session_id]
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
        store_session(session_id, container.id, user_id, thread_id)
        store_thread_mapping(thread_id, session_id)

        logger.info(f"[SANDBOX] event=session_created user={user_id[:8]} thread={thread_id[:12]} session={session_id[:12]}")

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
        session_data = get_session(session_id)
        if not session_data:
            raise SessionExpiredError(f"Session {session_id} not found or expired")

        # Validate command
        validation_result = validate_command(command)
        if not validation_result["valid"]:
            raise ValueError(validation_result['error'])

        # Execute in container
        start_time = time.time()
        try:
            container = client.containers.get(session_data['container_id'])
            result = container.exec_run(
                ['bash', '-c', command],
                user=settings.SANDBOX_USER,
                workdir=settings.WORKSPACE_DIR,
                demux=True
            )

            execution_time_ms = int((time.time() - start_time) * 1000)

            # Update last activity
            update_session_activity(session_id)

            # Parse output
            output_stdout = ""
            output_stderr = ""
            if result.output:
                stdout, stderr = result.output
                if stdout:
                    output_stdout = stdout.decode('utf-8', errors='replace')
                if stderr:
                    output_stderr = stderr.decode('utf-8', errors='replace')

            logger.info(
                f"[SANDBOX] event=command_executed session={session_id[:12]} "
                f"exit_code={result.exit_code} duration_ms={execution_time_ms}"
            )

            return {
                'exit_code': result.exit_code,
                'stdout': output_stdout,
                'stderr': output_stderr,
                'execution_time_ms': execution_time_ms
            }

        except Exception as e:
            logger.error(f"[SANDBOX] event=command_failed session={session_id[:12]} error={str(e)}")
            raise

    def upload_file(self, session_id: str, filename: str, file_data: bytes) -> Dict:
        """Upload file to workspace (direct method call)"""
        session_data = get_session(session_id)
        if not session_data:
            raise SessionExpiredError(f"Session {session_id} not found or expired")

        file_size = len(file_data)

        # Check file size limit
        if file_size > settings.MAX_FILE_SIZE:
            raise ValueError(
                f"File size exceeds maximum allowed size: "
                f"{settings.MAX_FILE_SIZE_MB} MB"
            )

        try:
            container = client.containers.get(session_data['container_id'])

            # Check workspace size and file count
            workspace_info = get_workspace_info(container)

            if workspace_info['total_files'] >= settings.MAX_TOTAL_FILES:
                raise ValueError(
                    f"Maximum file count exceeded: {settings.MAX_TOTAL_FILES}"
                )

            if workspace_info['total_size'] + file_size > settings.MAX_WORKSPACE_SIZE:
                raise ValueError(
                    f"Workspace size limit exceeded: {settings.MAX_WORKSPACE_SIZE_MB} MB"
                )

            # Upload file
            tar_stream = io.BytesIO()
            tar = tarfile.TarFile(fileobj=tar_stream, mode='w')
            tarinfo = tarfile.TarInfo(name=filename)
            tarinfo.size = file_size
            tarinfo.mtime = int(time.time())
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

            logger.info(f"[SANDBOX] event=file_uploaded session={session_id[:12]} filename={filename} size_bytes={file_size}")

            return {
                'status': 'uploaded',
                'filename': filename,
                'path': f'{settings.WORKSPACE_DIR}/{filename}',
                'size_bytes': file_size
            }

        except Exception as e:
            logger.error(f"[SANDBOX] event=file_upload_failed session={session_id[:12]} error={str(e)}")
            raise

    def download_file(self, session_id: str, filename: str) -> bytes:
        """Download file from workspace (direct method call)"""
        session_data = get_session(session_id)
        if not session_data:
            raise SessionExpiredError(f"Session {session_id} not found or expired")

        # Validate filename (prevent path traversal)
        if '..' in filename or filename.startswith('/'):
            raise ValueError('Invalid filename')

        try:
            container = client.containers.get(session_data['container_id'])

            # Check if file exists
            check_result = container.exec_run(
                f'test -f {settings.WORKSPACE_DIR}/{filename}',
                user=settings.SANDBOX_USER
            )

            if check_result.exit_code != 0:
                raise FileNotFoundError(f"File not found in workspace: {filename}")

            # Get file as tar archive
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

            logger.info(f"[SANDBOX] event=file_downloaded session={session_id[:12]} filename={filename}")

            return file_data

        except Exception as e:
            logger.error(f"[SANDBOX] event=file_download_failed session={session_id[:12]} error={str(e)}")
            raise

    def list_files(self, session_id: str) -> Dict:
        """List all files in workspace (direct method call)"""
        session_data = get_session(session_id)
        if not session_data:
            raise SessionExpiredError(f"Session {session_id} not found or expired")

        try:
            container = client.containers.get(session_data['container_id'])

            # List files with metadata
            result = container.exec_run(
                f'ls -la --time-style=iso {settings.WORKSPACE_DIR}',
                user=settings.SANDBOX_USER
            )

            if result.exit_code != 0:
                raise Exception('Failed to list files')

            # Parse ls output
            lines = result.output.decode('utf-8').strip().split('\n')[1:]  # Skip 'total' line
            files = []
            total_size = 0

            for line in lines:
                parts = line.split()
                # Expect at least: perms, links, owner, group, size, date, [time], name
                if len(parts) < 7:
                    continue

                filename = parts[-1]
                if filename in ['.', '..']:
                    continue

                size = int(parts[4])
                # modified may be date only or date+time
                if len(parts) >= 8:
                    modified = f"{parts[5]}T{parts[6]}Z"
                else:
                    modified = parts[5]

                file_info = {
                    'name': filename,
                    'size_bytes': size,
                    'modified': modified,
                    'permissions': parts[0]
                }
                files.append(file_info)
                total_size += size

            # Sort by modification time (newest first)
            files.sort(key=lambda x: x['modified'], reverse=True)

            return {
                'session_id': session_id,
                'workspace_dir': settings.WORKSPACE_DIR,
                'files': files,
                'total_files': len(files),
                'total_size_bytes': total_size
            }

        except Exception as e:
            logger.error(f"[SANDBOX] event=list_files_failed session={session_id[:12]} error={str(e)}")
            raise

    def cleanup_session(self, session_id: str):
        """Cleanup session (direct method call)"""
        cleanup_session_internal(session_id)
        logger.info(f"[SANDBOX] event=session_cleaned_up session={session_id[:12]}")


# Global server instance for local mode
_server_instance: Optional[SandboxServer] = None


def get_server_instance() -> SandboxServer:
    """Get or create server instance for local mode"""
    global _server_instance
    if _server_instance is None:
        _server_instance = SandboxServer()
    return _server_instance


# ============================================================================
# FastAPI App and Endpoints
# ============================================================================

app = FastAPI(title="Sandbox System V2 Enhanced")


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


@app.get('/health')
def health():
    """Health check endpoint"""
    pool_stats = pool.get_stats()

    return {
        'status': 'healthy',
        'worker_id': settings.WORKER_ID,
        'pool': pool_stats,
        'active_sessions': len(active_sessions) if not settings.REDIS_ENABLED else 'N/A (Redis)',
        'redis_connected': settings.REDIS_ENABLED,
        'config': {
            'pool_size': settings.POOL_SIZE,
            'max_pool_size': settings.MAX_POOL_SIZE,
            'aggressive_cleanup': settings.AGGRESSIVE_CLEANUP
        }
    }


@app.get('/get_session')
def get_session_endpoint(thread_id: str):
    """Get session info by thread_id"""
    if not thread_id:
        raise HTTPException(status_code=400, detail='thread_id required')

    session_id = get_session_by_thread(thread_id)
    if not session_id:
        raise HTTPException(
            status_code=404,
            detail={
                'error': 'No active session found for thread_id',
                'thread_id': thread_id
            }
        )

    session_data = get_session(session_id)
    if not session_data:
        # Stale mapping, cleanup
        remove_thread_mapping(thread_id)
        raise HTTPException(
            status_code=404,
            detail={'error': 'Session expired', 'thread_id': thread_id}
        )

    return {
        'session_id': session_id,
        'thread_id': thread_id,
        'status': 'active',
        'created_at': session_data.get('created_at'),
        'last_activity': session_data.get('last_activity'),
        'workspace_dir': settings.WORKSPACE_DIR
    }


@app.post('/create_session', status_code=201)
def create_session(request: CreateSessionRequest):
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
            raise HTTPException(status_code=503, detail="Pool at max capacity, try again later")

        # Store session
        store_session(session_id, container.id, user_id, thread_id)

        # Store thread mapping
        store_thread_mapping(thread_id, session_id)

        logger.info(f"[SANDBOX] event=session_created user={user_id[:8]} thread={thread_id[:12]} session={session_id[:12]}")

        return {
            'session_id': session_id,
            'thread_id': thread_id,
            'status': 'created',
            'workspace_dir': settings.WORKSPACE_DIR,
            'user': settings.SANDBOX_USER,
            'expires_at': (datetime.now() + timedelta(minutes=timeout_minutes)).isoformat()
        }

    except Exception as e:
        logger.error(f"[SANDBOX] event=session_creation_failed error={str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post('/execute')
def execute_command(request: ExecuteRequest):
    """Execute command with server-side validation"""
    session_id = request.session_id
    command = request.command
    timeout = request.timeout

    # SERVER-SIDE VALIDATION (defense in depth)
    validation_result = validate_command(command)
    if not validation_result["valid"]:
        logger.warning(f"[SANDBOX] event=validation_failed session={session_id[:12]} error={validation_result['error']}")
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
        raise HTTPException(status_code=404, detail='Invalid or expired session')

    try:
        container = client.containers.get(session_data['container_id'])

        # Execute with timing
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

        logger.info(
            f"[SANDBOX] event=command_executed session={session_id[:12]} "
            f"exit_code={exec_instance.exit_code} duration_ms={execution_time_ms}"
        )

        return {
            'exit_code': exec_instance.exit_code,
            'stdout': output_stdout,
            'stderr': output_stderr,
            'execution_time_ms': execution_time_ms
        }

    except Exception as e:
        logger.error(f"[SANDBOX] event=command_failed session={session_id[:12]} error={str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post('/upload_file')
async def upload_file(
    session_id: str = Form(...),
    file: UploadFile = File(...)
):
    """Upload file with size and count limits"""
    if not session_id:
        raise HTTPException(status_code=400, detail='session_id required')

    session_data = get_session(session_id)
    if not session_data:
        raise HTTPException(status_code=404, detail='Invalid or expired session')

    try:
        filename = file.filename
        file_data = await file.read()
        file_size = len(file_data)

        # Check file size limit
        if file_size > settings.MAX_FILE_SIZE:
            raise HTTPException(
                status_code=413,
                detail={
                    'error': 'File size exceeds maximum allowed size',
                    'max_size_mb': settings.MAX_FILE_SIZE_MB,
                    'uploaded_size_mb': round(file_size / (1024 * 1024), 2)
                }
            )

        container = client.containers.get(session_data['container_id'])

        # Check workspace size and file count
        workspace_info = get_workspace_info(container)

        if workspace_info['total_files'] >= settings.MAX_TOTAL_FILES:
            raise HTTPException(
                status_code=507,
                detail={
                    'error': 'Maximum file count exceeded',
                    'max_files': settings.MAX_TOTAL_FILES,
                    'current_files': workspace_info['total_files']
                }
            )

        if workspace_info['total_size'] + file_size > settings.MAX_WORKSPACE_SIZE:
            raise HTTPException(
                status_code=507,
                detail={
                    'error': 'Workspace size limit exceeded',
                    'max_workspace_mb': settings.MAX_WORKSPACE_SIZE_MB,
                    'current_workspace_mb': round(workspace_info['total_size'] / (1024 * 1024), 2),
                    'file_size_mb': round(file_size / (1024 * 1024), 2)
                }
            )

        # Upload file
        tar_stream = io.BytesIO()
        tar = tarfile.TarFile(fileobj=tar_stream, mode='w')
        tarinfo = tarfile.TarInfo(name=filename)
        tarinfo.size = file_size
        tarinfo.mtime = int(time.time())
        tar.addfile(tarinfo, io.BytesIO(file_data))
        tar.close()

        tar_stream.seek(0)
        container.put_archive(settings.WORKSPACE_DIR, tar_stream)

        # Fix permissions (handle subdirectories)
        # Use chown -R on parent directory if file is in a subdirectory
        file_path = f'{settings.WORKSPACE_DIR}/{filename}'
        if '/' in filename:
            # File is in subdirectory, chown the parent dir recursively
            parent_dir = os.path.dirname(file_path)
            container.exec_run(
                f'chown -R {settings.SANDBOX_USER}:{settings.SANDBOX_USER} {parent_dir}',
                user='root'
            )
        else:
            # File is in root workspace, chown just the file
            container.exec_run(
                f'chown {settings.SANDBOX_USER}:{settings.SANDBOX_USER} {file_path}',
                user='root'
            )

        update_session_activity(session_id)

        logger.info(f"[SANDBOX] event=file_uploaded session={session_id[:12]} filename={filename} size_bytes={file_size}")

        return {
            'status': 'uploaded',
            'filename': filename,
            'path': f'{settings.WORKSPACE_DIR}/{filename}',
            'size_bytes': file_size
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[SANDBOX] event=file_upload_failed session={session_id[:12]} error={str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post('/download_file')
def download_file(request: DownloadRequest):
    """Download file from workspace"""
    session_id = request.session_id
    filename = request.filename

    if not session_id or not filename:
        raise HTTPException(status_code=400, detail='session_id and filename required')

    # Validate filename (prevent path traversal)
    if '..' in filename or filename.startswith('/'):
        raise HTTPException(status_code=400, detail='Invalid filename')

    session_data = get_session(session_id)
    if not session_data:
        raise HTTPException(status_code=404, detail='Invalid or expired session')

    try:
        container = client.containers.get(session_data['container_id'])

        # Check if file exists
        check_result = container.exec_run(
            f'test -f {settings.WORKSPACE_DIR}/{filename}',
            user=settings.SANDBOX_USER
        )

        if check_result.exit_code != 0:
            raise HTTPException(
                status_code=404,
                detail={
                    'error': 'File not found in workspace',
                    'filename': filename,
                    'workspace_dir': settings.WORKSPACE_DIR
                }
            )

        # Get file as tar archive
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

        logger.info(f"[SANDBOX] event=file_downloaded session={session_id[:12]} filename={filename}")

        # Return as binary response
        return Response(
            content=file_data,
            media_type='application/octet-stream',
            headers={
                'Content-Disposition': f'attachment; filename="{filename}"',
                'Content-Length': str(len(file_data))
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[SANDBOX] event=file_download_failed session={session_id[:12]} error={str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get('/list_files')
def list_files(session_id: str):
    """List all files in workspace"""
    if not session_id:
        raise HTTPException(status_code=400, detail='session_id required')

    session_data = get_session(session_id)
    if not session_data:
        raise HTTPException(status_code=404, detail='Invalid or expired session')

    try:
        container = client.containers.get(session_data['container_id'])

        # List files with metadata
        result = container.exec_run(
            f'ls -la --time-style=iso {settings.WORKSPACE_DIR}',
            user=settings.SANDBOX_USER
        )

        if result.exit_code != 0:
            raise HTTPException(status_code=500, detail='Failed to list files')

        # Parse ls output
        lines = result.output.decode('utf-8').strip().split('\n')[1:]  # Skip 'total' line
        files = []
        total_size = 0

        for line in lines:
            parts = line.split()
            # Expect at least: perms, links, owner, group, size, date, [time], name
            if len(parts) < 7:
                continue

            filename = parts[-1]
            if filename in ['.', '..']:
                continue

            size = int(parts[4])
            if len(parts) >= 8:
                modified = f"{parts[5]}T{parts[6]}Z"
            else:
                modified = parts[5]

            file_info = {
                'name': filename,
                'size_bytes': size,
                'modified': modified,
                'permissions': parts[0]
            }
            files.append(file_info)
            total_size += size

        # Sort by modification time (newest first)
        files.sort(key=lambda x: x['modified'], reverse=True)

        return {
            'session_id': session_id,
            'workspace_dir': settings.WORKSPACE_DIR,
            'files': files,
            'total_files': len(files),
            'total_size_bytes': total_size
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[SANDBOX] event=list_files_failed session={session_id[:12]} error={str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post('/cleanup')
def cleanup(request: CleanupRequest):
    """Cleanup session and thread mapping"""
    session_id = request.session_id

    if not session_id:
        raise HTTPException(status_code=400, detail='session_id required')

    # Get session data to find thread_id
    session_data = get_session(session_id)
    if session_data:
        thread_id = session_data.get('thread_id')
        if thread_id:
            remove_thread_mapping(thread_id)

    cleanup_session_internal(session_id)
    logger.info(f"[SANDBOX] event=session_cleaned_up session={session_id[:12]}")

    return {'status': 'cleaned_up', 'session_id': session_id}


@app.get('/status/{session_id}')
def status(session_id: str):
    """Check if a session is still active"""
    session_data = get_session(session_id)
    if session_data:
        return {
            'status': 'active',
            'worker': session_data.get('worker', 'unknown'),
            'created_at': session_data.get('created_at'),
            'last_activity': session_data.get('last_activity')
        }
    raise HTTPException(status_code=404, detail={'status': 'not found'})


# ============================================================================
# Shutdown Handler
# ============================================================================

def shutdown_handler(signum=None, frame=None):
    """Clean up containers on shutdown"""
    logger.info("\n⚙ Shutting down server...")
    logger.info("  Cleaning up container pool...")
    pool.cleanup_all()
    logger.info("✓ Cleanup complete")
    sys.exit(0)


# ============================================================================
# Main Entry Point
# ============================================================================

if __name__ == '__main__':
    import uvicorn

    # Validate configuration
    try:
        settings.validate()
    except ValueError as e:
        logger.error(f"✗ Configuration error: {e}")
        sys.exit(1)

    # Print configuration
    settings.print_config()

    # Register shutdown handlers
    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)
    atexit.register(shutdown_handler)

    # Initialize pool in background
    Thread(target=init_pool, daemon=True).start()

    # Give pool a moment to start initializing
    time.sleep(1)

    # Start server
    try:
        uvicorn.run(
            app,
            host=settings.HOST,
            port=settings.PORT,
            log_level="info"
        )
    except KeyboardInterrupt:
        shutdown_handler()
