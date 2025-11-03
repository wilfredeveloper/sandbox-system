"""
Enhanced Sandbox Server with Hybrid Pool Management
- Pre-warmed containers for instant sessions
- On-demand scaling with aggressive cleanup
- Non-root user execution
- Redis support for distributed setup
- Optimized for AI agent bash execution
"""

from flask import Flask, request, jsonify
import docker
import uuid
import redis
import json
from datetime import datetime
from threading import Thread, Lock
import time
import signal
import sys
import atexit

from settings import settings

app = Flask(__name__)
client = docker.from_env()

# Redis configuration
if settings.REDIS_ENABLED:
    redis_client = redis.Redis(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        decode_responses=True
    )
    print(f"✓ Redis enabled - distributed mode ({settings.REDIS_HOST}:{settings.REDIS_PORT})")
else:
    redis_client = None
    print("✓ Redis disabled - standalone mode")

# Storage for active sessions
active_sessions = {}  # {session_id: session_data}
session_last_activity = {}  # {session_id: last_activity_timestamp}


class ContainerPool:
    """Hybrid pool manager with aggressive cleanup for resource efficiency"""

    def __init__(self, size=settings.POOL_SIZE):
        self.size = size
        self.containers = []  # Available containers ready for use
        self.allocated_containers = {}  # {container_id: allocation_time}
        self.lock = Lock()

    def initialize(self):
        """Create initial pool of containers"""
        print(f"⚙ Initializing container pool with {self.size} containers...")
        for i in range(self.size):
            container = self._create_container()
            if container:
                self.containers.append(container)
                print(f"  ✓ Container {i+1}/{self.size} ready")
        print(f"✓ Pool initialized with {len(self.containers)} containers")

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
            print(f"✗ Error creating container: {e}")
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
                    print(f"⚠ Pool at max capacity ({settings.MAX_POOL_SIZE})")
                    return None

                print(f"⚙ Pool empty, creating container on demand...")
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
                        print(f"⚙ Destroying idle container (pool size: {current_pool_size})")
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
            print(f"✗ Error returning container: {e}")
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
                print(f"⚙ Refilling pool: {current_size} -> {settings.MIN_POOL_SIZE}")
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


def init_pool():
    """Initialize pool in background"""
    pool.initialize()
    # Start background cleanup thread
    Thread(target=cleanup_loop, daemon=True).start()


def store_session(session_id, container_id):
    """Store session info (Redis or local)"""
    session_data = {
        'container_id': container_id,
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
                print(f"⚙ Cleaning up expired session: {sid}")

        for sid in expired:
            cleanup_session(sid)


def cleanup_idle_containers():
    """Remove containers that have been idle for CONTAINER_IDLE_TIMEOUT"""
    if not settings.REDIS_ENABLED:
        now = datetime.now()
        idle = []

        for sid, last_activity in list(session_last_activity.items()):
            if now - last_activity > settings.CONTAINER_IDLE_TIMEOUT:
                idle.append(sid)
                print(f"⚙ Cleaning up idle container: {sid}")

        for sid in idle:
            cleanup_session(sid)


def cleanup_session(session_id):
    """Stop and remove a container, return to pool if possible"""
    session_data = get_session(session_id)
    if session_data:
        try:
            container = client.containers.get(session_data['container_id'])
            pool.return_container(container)
        except Exception as e:
            print(f"✗ Error cleaning up {session_id}: {e}")
        finally:
            delete_session(session_id)


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    pool_stats = pool.get_stats()

    return jsonify({
        'status': 'healthy',
        'worker_id': settings.WORKER_ID,
        'pool': pool_stats,
        'active_sessions': len(active_sessions) if not settings.REDIS_ENABLED else 'N/A (Redis)',
        'config': {
            'pool_size': settings.POOL_SIZE,
            'max_pool_size': settings.MAX_POOL_SIZE,
            'aggressive_cleanup': settings.AGGRESSIVE_CLEANUP
        }
    })


@app.route('/create_session', methods=['POST'])
def create_session():
    """Create a new sandboxed session (instant with pooling)"""
    session_id = str(uuid.uuid4())

    try:
        # Get container from pool (instant if pre-warmed, ~2-3s if on-demand)
        container = pool.get_container()

        if not container:
            return jsonify({'error': 'Pool at max capacity, try again later'}), 503

        # Store session
        store_session(session_id, container.id)

        return jsonify({
            'session_id': session_id,
            'status': 'created',
            'user': settings.SANDBOX_USER,
            'workspace': settings.WORKSPACE_DIR
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/execute', methods=['POST'])
def execute_command():
    """Execute a bash command in a session's container"""
    data = request.json
    session_id = data.get('session_id')
    command = data.get('command')
    timeout = data.get('timeout', settings.DEFAULT_COMMAND_TIMEOUT)

    if not session_id or not command:
        return jsonify({'error': 'session_id and command required'}), 400

    session_data = get_session(session_id)
    if not session_data:
        return jsonify({'error': 'Invalid or expired session'}), 404

    try:
        container = client.containers.get(session_data['container_id'])

        # Execute command as non-root user
        exec_instance = container.exec_run(
            ['bash', '-c', command],
            workdir=settings.WORKSPACE_DIR,
            user=settings.SANDBOX_USER,
            demux=True
        )

        # Update activity timestamp
        update_session_activity(session_id)

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
        container.put_archive(settings.WORKSPACE_DIR, tar_stream)

        # Fix permissions
        container.exec_run(
            f'chown {settings.SANDBOX_USER}:{settings.SANDBOX_USER} {settings.WORKSPACE_DIR}/{filename}',
            user='root'
        )

        # Update activity timestamp
        update_session_activity(session_id)

        return jsonify({
            'status': 'uploaded',
            'filename': filename,
            'path': f'{settings.WORKSPACE_DIR}/{filename}'
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
            'worker': session_data.get('worker', 'unknown'),
            'created_at': session_data.get('created_at'),
            'last_activity': session_data.get('last_activity')
        })
    return jsonify({'status': 'not found'}), 404


def shutdown_handler(signum=None, frame=None):
    """Clean up containers on shutdown"""
    print("\n⚙ Shutting down server...")
    print("  Cleaning up container pool...")
    pool.cleanup_all()
    print("✓ Cleanup complete")
    sys.exit(0)


if __name__ == '__main__':
    # Validate configuration
    try:
        settings.validate()
    except ValueError as e:
        print(f"✗ Configuration error: {e}")
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
        app.run(host=settings.HOST, port=settings.PORT, debug=settings.DEBUG, threaded=True)
    except KeyboardInterrupt:
        shutdown_handler()
