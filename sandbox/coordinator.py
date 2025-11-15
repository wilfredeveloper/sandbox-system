"""
Sandbox Coordinator - Load Balancer
Routes requests to multiple sandbox workers
Uses Redis for session affinity
"""

from flask import Flask, request, jsonify, Response
import requests
import redis
import json
import os
from datetime import timedelta
import random

app = Flask(__name__)

# Configuration
REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
REDIS_PORT = int(os.getenv('REDIS_PORT', 6379))
REDIS_PASSWORD = os.getenv('REDIS_PASSWORD', None)
SESSION_TIMEOUT = timedelta(hours=1)

# Resolve Redis hostname to IPv4 (fixes IPv6 auth issue with Redis)
# Docker DNS sometimes returns IPv6 first, which has auth problems
# Also prioritize sandbox network (10.0.19.x) over coolify network (10.0.1.x)
import socket
def resolve_to_ipv4(hostname):
    """Resolve hostname to IPv4 address, preferring sandbox network"""
    try:
        # Get all IPv4 addresses for the hostname
        addr_info = socket.getaddrinfo(hostname, None, socket.AF_INET, socket.SOCK_STREAM)
        if addr_info:
            # Extract all IPv4 addresses
            ipv4_addrs = [addr[4][0] for addr in addr_info]

            # Prefer sandbox network (10.0.19.x) if available
            for ip in ipv4_addrs:
                if ip.startswith('10.0.19.'):
                    print(f"   Using sandbox network Redis: {ip}")
                    return ip

            # Prefer l00og network (10.0.18.x) as second choice
            for ip in ipv4_addrs:
                if ip.startswith('10.0.18.'):
                    print(f"   Using l00og network Redis: {ip}")
                    return ip

            # Otherwise use first IPv4
            print(f"   Using first available IPv4: {ipv4_addrs[0]}")
            return ipv4_addrs[0]
    except socket.gaierror:
        pass
    # Fallback to original hostname if resolution fails
    return hostname

# Connect to Redis using IPv4 address
REDIS_HOST_IPV4 = resolve_to_ipv4(REDIS_HOST)
redis_client = redis.Redis(
    host=REDIS_HOST_IPV4,
    port=REDIS_PORT,
    password=REDIS_PASSWORD,
    decode_responses=True
)

# Worker nodes - can be configured via environment or config file
WORKERS = os.getenv('WORKERS', 'http://localhost:5001,http://localhost:5002').split(',')

print(f"🎯 Coordinator starting with {len(WORKERS)} workers:")
for i, worker in enumerate(WORKERS, 1):
    print(f"   Worker {i}: {worker}")

def get_healthy_workers():
    """Check which workers are healthy"""
    healthy = []
    for worker in WORKERS:
        try:
            response = requests.get(f"{worker}/health", timeout=2)
            if response.status_code == 200:
                healthy.append(worker)
        except:
            pass
    return healthy

def select_worker():
    """Select a worker using round-robin with health check"""
    healthy_workers = get_healthy_workers()
    
    if not healthy_workers:
        return None
    
    # Simple round-robin
    return random.choice(healthy_workers)

def get_worker_for_session(session_id):
    """Get the worker handling a specific session"""
    worker = redis_client.get(f"session:{session_id}:worker")
    return worker

def set_worker_for_session(session_id, worker):
    """Store which worker is handling a session"""
    redis_client.setex(
        f"session:{session_id}:worker",
        int(SESSION_TIMEOUT.total_seconds()),
        worker
    )

@app.route('/health', methods=['GET'])
def health():
    """Coordinator health check"""
    healthy_workers = get_healthy_workers()
    return jsonify({
        'status': 'healthy',
        'workers_total': len(WORKERS),
        'workers_healthy': len(healthy_workers),
        'workers': [
            {
                'url': w,
                'status': 'healthy' if w in healthy_workers else 'unhealthy'
            }
            for w in WORKERS
        ]
    })

@app.route('/get_session', methods=['GET'])
def get_session():
    """Get session by thread_id - check all workers"""
    thread_id = request.args.get('thread_id')

    if not thread_id:
        return jsonify({'error': 'thread_id required'}), 400

    # Try to find session in Redis first
    # Check if we have a session_id stored for this thread_id
    session_key = f"thread:{thread_id}:session"
    session_id = redis_client.get(session_key)

    if session_id:
        # We know which worker has this session
        worker = get_worker_for_session(session_id)
        if worker:
            try:
                response = requests.get(
                    f"{worker}/get_session",
                    params={"thread_id": thread_id},
                    timeout=5
                )
                if response.status_code == 200:
                    return Response(
                        response.content,
                        status=response.status_code,
                        content_type=response.headers['Content-Type']
                    )
            except Exception:
                pass

    # If not found in Redis, check all healthy workers
    healthy_workers = get_healthy_workers()
    for worker in healthy_workers:
        try:
            response = requests.get(
                f"{worker}/get_session",
                params={"thread_id": thread_id},
                timeout=5
            )
            if response.status_code == 200:
                # Found it! Store the mapping
                data = response.json()
                session_id = data.get('session_id')
                if session_id:
                    set_worker_for_session(session_id, worker)
                    redis_client.setex(session_key, int(SESSION_TIMEOUT.total_seconds()), session_id)
                return Response(
                    response.content,
                    status=response.status_code,
                    content_type=response.headers['Content-Type']
                )
        except Exception:
            continue

    # Not found on any worker
    return jsonify({'error': 'Session not found'}), 404

@app.route('/create_session', methods=['POST'])
def create_session():
    """Route session creation to a worker"""
    worker = select_worker()

    if not worker:
        return jsonify({'error': 'No healthy workers available'}), 503

    try:
        # Forward request to worker
        response = requests.post(
            f"{worker}/create_session",
            json=request.json,
            timeout=10
        )

        if response.status_code in [200, 201]:
            data = response.json()
            session_id = data.get('session_id')
            thread_id = request.json.get('thread_id')

            # Store worker assignment
            set_worker_for_session(session_id, worker)

            # Store thread_id -> session_id mapping
            if thread_id:
                session_key = f"thread:{thread_id}:session"
                redis_client.setex(session_key, int(SESSION_TIMEOUT.total_seconds()), session_id)

            # Add worker info to response
            data['worker'] = worker

        return Response(
            response.content,
            status=response.status_code,
            content_type=response.headers['Content-Type']
        )

    except Exception as e:
        return jsonify({'error': f'Worker communication failed: {str(e)}'}), 500

@app.route('/execute', methods=['POST'])
def execute():
    """Route execution to the correct worker"""
    data = request.json
    session_id = data.get('session_id')
    
    if not session_id:
        return jsonify({'error': 'session_id required'}), 400
    
    # Find which worker has this session
    worker = get_worker_for_session(session_id)
    
    if not worker:
        return jsonify({'error': 'Session not found or expired'}), 404
    
    try:
        response = requests.post(
            f"{worker}/execute",
            json=request.json,
            timeout=60
        )
        
        return Response(
            response.content,
            status=response.status_code,
            content_type=response.headers['Content-Type']
        )
    
    except Exception as e:
        return jsonify({'error': f'Worker communication failed: {str(e)}'}), 500

@app.route('/upload_file', methods=['POST'])
def upload_file():
    """Route file upload to the correct worker"""
    session_id = request.form.get('session_id')
    
    if not session_id:
        return jsonify({'error': 'session_id required'}), 400
    
    worker = get_worker_for_session(session_id)
    
    if not worker:
        return jsonify({'error': 'Session not found or expired'}), 404
    
    try:
        # Forward multipart request
        files = {'file': request.files['file']}
        response = requests.post(
            f"{worker}/upload_file",
            files=files,
            data={'session_id': session_id},
            timeout=60
        )
        
        return Response(
            response.content,
            status=response.status_code,
            content_type=response.headers['Content-Type']
        )
    
    except Exception as e:
        return jsonify({'error': f'Worker communication failed: {str(e)}'}), 500

@app.route('/cleanup', methods=['POST'])
def cleanup():
    """Route cleanup to the correct worker"""
    data = request.json
    session_id = data.get('session_id')
    
    if not session_id:
        return jsonify({'error': 'session_id required'}), 400
    
    worker = get_worker_for_session(session_id)
    
    if not worker:
        return jsonify({'error': 'Session not found or expired'}), 404
    
    try:
        response = requests.post(
            f"{worker}/cleanup",
            json=request.json,
            timeout=10
        )
        
        # Clean up worker assignment
        redis_client.delete(f"session:{session_id}:worker")
        
        return Response(
            response.content,
            status=response.status_code,
            content_type=response.headers['Content-Type']
        )
    
    except Exception as e:
        return jsonify({'error': f'Worker communication failed: {str(e)}'}), 500

@app.route('/status/<session_id>', methods=['GET'])
def status(session_id):
    """Check session status"""
    worker = get_worker_for_session(session_id)
    
    if not worker:
        return jsonify({'status': 'not found'}), 404
    
    try:
        response = requests.get(f"{worker}/status/{session_id}", timeout=5)
        return Response(
            response.content,
            status=response.status_code,
            content_type=response.headers['Content-Type']
        )
    except Exception as e:
        return jsonify({'error': f'Worker communication failed: {str(e)}'}), 500

def on_starting(server):
    """Gunicorn hook - called before workers are forked"""
    print("🚀 Sandbox Coordinator starting...")
    print(f"   Redis: {REDIS_HOST}:{REDIS_PORT} (resolved to {REDIS_HOST_IPV4})")

    # Test Redis connection
    try:
        redis_client.ping()
        print("   ✅ Redis connected")
    except Exception as e:
        print(f"   ❌ Redis connection failed: {e}")
        exit(1)

    port = int(os.getenv('PORT', 8000))
    print(f"   Listening on port {port}")


if __name__ == '__main__':
    # Development mode - run with Flask dev server
    print("🚀 Sandbox Coordinator starting (DEV MODE)...")
    print(f"   Redis: {REDIS_HOST}:{REDIS_PORT} (resolved to {REDIS_HOST_IPV4})")

    # Test Redis connection
    try:
        redis_client.ping()
        print("   ✅ Redis connected")
    except Exception as e:
        print(f"   ❌ Redis connection failed: {e}")
        exit(1)

    port = int(os.getenv('PORT', 8000))
    print(f"   Listening on port {port}")

    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
