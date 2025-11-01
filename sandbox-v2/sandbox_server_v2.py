"""
Enhanced Sandbox Server with Container Pooling
- Pre-warmed containers for instant sessions
- Non-root user execution
- Better resource management
- Redis support for distributed setup
"""

from flask import Flask, request, jsonify
import docker
import uuid
import os
import redis
import json
from datetime import datetime, timedelta
from threading import Thread, Lock
import time
import signal
import sys
import atexit

app = Flask(__name__)
client = docker.from_env()

# Configuration
POOL_SIZE = 5  # Number of pre-warmed containers
MIN_POOL_SIZE = 2  # Minimum containers to maintain
MAX_POOL_SIZE = 20  # Maximum pool size
SESSION_TIMEOUT = timedelta(hours=1)
CONTAINER_IMAGE = "sandbox-secure:latest"  # Our custom non-root image
MEMORY_LIMIT = "512m"
CPU_QUOTA = 50000
SANDBOX_USER = "sandboxuser"  # Non-root user
WORKSPACE_DIR = "/workspace"

# Redis configuration (optional - for distributed setup)
REDIS_ENABLED = os.getenv('REDIS_HOST') is not None
if REDIS_ENABLED:
    redis_client = redis.Redis(
        host=os.getenv('REDIS_HOST', 'localhost'),
        port=int(os.getenv('REDIS_PORT', 6379)),
        decode_responses=True
    )
    print("Redis enabled - distributed mode")
else:
    redis_client = None
    print("Redis disabled - standalone mode")

# Container pool
container_pool = []
pool_lock = Lock()
active_sessions = {}  # {session_id: container_id}

class ContainerPool:
    """Manages a pool of pre-warmed containers"""
    
    def __init__(self, size=POOL_SIZE):
        self.size = size
        self.containers = []
        self.lock = Lock()
        
    def initialize(self):
        """Create initial pool of containers"""
        print(f" Initializing container pool with {self.size} containers...")
        for i in range(self.size):
            container = self._create_container()
            if container:
                self.containers.append(container)
                print(f"   Container {i+1}/{self.size} ready")
        print(f" Pool initialized with {len(self.containers)} containers")
    
    def _create_container(self):
        """Create a single container"""
        try:
            container = client.containers.run(
                CONTAINER_IMAGE,
                command="sleep infinity",
                detach=True,
                mem_limit=MEMORY_LIMIT,
                cpu_quota=CPU_QUOTA,
                network_mode="none",
                remove=False,
                user=SANDBOX_USER,  # Run as non-root user
                working_dir=WORKSPACE_DIR
            )
            return container
        except Exception as e:
            print(f" Error creating container: {e}")
            return None
    
    def get_container(self):
        """Get a container from the pool (non-blocking)"""
        with self.lock:
            if self.containers:
                container = self.containers.pop()
                # Start refill in background
                Thread(target=self._refill_pool, daemon=True).start()
                return container
            else:
                # Pool empty - create on demand
                print("  Pool empty, creating container on demand...")
                return self._create_container()
    
    def return_container(self, container):
        """Return a container to the pool after cleanup"""
        try:
            # Reset the container state (run as sandboxuser to avoid permission issues)
            container.exec_run(
                f"sh -c 'rm -rf {WORKSPACE_DIR}/* {WORKSPACE_DIR}/.*' 2>/dev/null || true",
                user=SANDBOX_USER
            )
            
            with self.lock:
                if len(self.containers) < MAX_POOL_SIZE:
                    self.containers.append(container)
                else:
                    # Pool full, remove the container
                    container.stop(timeout=2)
                    container.remove()
        except Exception as e:
            print(f" Error returning container: {e}")
            try:
                container.stop(timeout=2)
                container.remove()
            except:
                pass
    
    def _refill_pool(self):
        """Refill the pool to minimum size"""
        with self.lock:
            current_size = len(self.containers)
            if current_size < MIN_POOL_SIZE:
                needed = MIN_POOL_SIZE - current_size
                for _ in range(needed):
                    container = self._create_container()
                    if container:
                        self.containers.append(container)
    
    def cleanup_all(self):
        """Clean up all containers in the pool"""
        with self.lock:
            for container in self.containers:
                try:
                    container.stop(timeout=2)
                    container.remove()
                except:
                    pass
            self.containers = []

# Initialize the pool
pool = ContainerPool(size=POOL_SIZE)

def init_pool():
    """Initialize pool in background"""
    pool.initialize()
    # Start background cleanup thread
    Thread(target=cleanup_expired_sessions_loop, daemon=True).start()

def store_session(session_id, container_id):
    """Store session info (Redis or local)"""
    session_data = {
        'container_id': container_id,
        'created_at': datetime.now().isoformat(),
        'worker': os.getenv('WORKER_ID', 'standalone')
    }
    
    if REDIS_ENABLED:
        redis_client.setex(
            f"session:{session_id}",
            int(SESSION_TIMEOUT.total_seconds()),
            json.dumps(session_data)
        )
    else:
        active_sessions[session_id] = session_data

def get_session(session_id):
    """Get session info (Redis or local)"""
    if REDIS_ENABLED:
        data = redis_client.get(f"session:{session_id}")
        return json.loads(data) if data else None
    else:
        return active_sessions.get(session_id)

def delete_session(session_id):
    """Delete session info (Redis or local)"""
    if REDIS_ENABLED:
        redis_client.delete(f"session:{session_id}")
    else:
        active_sessions.pop(session_id, None)

def cleanup_expired_sessions_loop():
    """Background thread to cleanup expired sessions"""
    while True:
        time.sleep(300)  # Check every 5 minutes
        cleanup_expired_sessions()

def cleanup_expired_sessions():
    """Remove expired sessions"""
    if not REDIS_ENABLED:
        now = datetime.now()
        expired = []
        for sid, data in list(active_sessions.items()):
            created = datetime.fromisoformat(data['created_at'])
            if now - created > SESSION_TIMEOUT:
                expired.append(sid)
        
        for sid in expired:
            cleanup_session(sid)

def cleanup_session(session_id):
    """Stop and remove a container"""
    session_data = get_session(session_id)
    if session_data:
        try:
            container = client.containers.get(session_data['container_id'])
            pool.return_container(container)  # Return to pool instead of destroying
        except Exception as e:
            print(f"Error cleaning up {session_id}: {e}")
        finally:
            delete_session(session_id)

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'pool_size': len(pool.containers),
        'active_sessions': len(active_sessions) if not REDIS_ENABLED else 'N/A (Redis)',
        'worker_id': os.getenv('WORKER_ID', 'standalone')
    })

@app.route('/create_session', methods=['POST'])
def create_session():
    """Create a new sandboxed session (instant with pooling)"""
    session_id = str(uuid.uuid4())
    
    try:
        # Get container from pool (instant!)
        container = pool.get_container()
        
        if not container:
            return jsonify({'error': 'Failed to create container'}), 500
        
        # Store session
        store_session(session_id, container.id)
        
        return jsonify({
            'session_id': session_id,
            'status': 'created',
            'user': SANDBOX_USER,
            'workspace': WORKSPACE_DIR
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/execute', methods=['POST'])
def execute_command():
    """Execute a bash command in a session's container"""
    data = request.json
    session_id = data.get('session_id')
    command = data.get('command')
    timeout = data.get('timeout', 30)  # Default 30 second timeout
    
    if not session_id or not command:
        return jsonify({'error': 'session_id and command required'}), 400
    
    session_data = get_session(session_id)
    if not session_data:
        return jsonify({'error': 'Invalid or expired session'}), 404
    
    try:
        container = client.containers.get(session_data['container_id'])

        # Debug: Log the user we're executing as
        print(f" Executing command as user: {SANDBOX_USER}")

        # Execute command as non-root user with timeout
        exec_instance = container.exec_run(
            ['bash', '-c', command],
            workdir=WORKSPACE_DIR,
            user=SANDBOX_USER,
            demux=True
        )
        
        # Combine stdout and stderr
        output = ""
        if exec_instance.output:
            stdout, stderr = exec_instance.output
            if stdout:
                output += stdout.decode('utf-8', errors='replace')
            if stderr:
                output += stderr.decode('utf-8', errors='replace')
        
        return jsonify({
            'exit_code': exec_instance.exit_code,
            'output': output
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/upload_file', methods=['POST'])
def upload_file():
    """Upload a file to the session's workspace"""
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
        filename = file.filename
        
        container = client.containers.get(session_data['container_id'])
        
        # Upload file to container
        import tarfile
        import io
        
        tar_stream = io.BytesIO()
        tar = tarfile.TarFile(fileobj=tar_stream, mode='w')
        
        file_data = file.read()
        tarinfo = tarfile.TarInfo(name=filename)
        tarinfo.size = len(file_data)
        tar.addfile(tarinfo, io.BytesIO(file_data))
        tar.close()
        
        tar_stream.seek(0)
        container.put_archive(WORKSPACE_DIR, tar_stream)

        # Fix permissions (need to run as root to chown)
        container.exec_run(
            f'chown {SANDBOX_USER}:{SANDBOX_USER} {WORKSPACE_DIR}/{filename}',
            user='root'
        )
        
        return jsonify({
            'status': 'uploaded',
            'filename': filename,
            'path': f'{WORKSPACE_DIR}/{filename}'
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/cleanup', methods=['POST'])
def cleanup():
    """Cleanup a specific session"""
    data = request.json
    session_id = data.get('session_id')
    
    if not session_id:
        return jsonify({'error': 'session_id required'}), 400
    
    cleanup_session(session_id)
    return jsonify({'status': 'cleaned up'})

@app.route('/status/<session_id>', methods=['GET'])
def status(session_id):
    """Check if a session is still active"""
    session_data = get_session(session_id)
    if session_data:
        return jsonify({
            'status': 'active',
            'worker': session_data.get('worker', 'unknown')
        })
    return jsonify({'status': 'not found'}), 404

def shutdown_handler(signum=None, frame=None):
    """Clean up containers on shutdown"""
    print("\n Shutting down server...")
    print("   Cleaning up container pool...")
    pool.cleanup_all()
    print("    Cleanup complete")
    sys.exit(0)

if __name__ == '__main__':
    # Register shutdown handlers
    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)
    atexit.register(shutdown_handler)

    # Initialize pool before starting server
    print(" Starting Enhanced Sandbox Server")
    print(f"   Pool size: {POOL_SIZE}")
    print(f"   Container image: {CONTAINER_IMAGE}")
    print(f"   User: {SANDBOX_USER}")

    # Initialize pool in background
    Thread(target=init_pool, daemon=True).start()

    # Give pool a moment to start initializing
    time.sleep(1)

    # Start server
    port = int(os.getenv('PORT', 5000))
    try:
        app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
    except KeyboardInterrupt:
        shutdown_handler()
