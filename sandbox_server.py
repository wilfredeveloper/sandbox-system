"""
Simple Sandbox Server for LangGraph Agents
Uses Docker containers to provide isolated bash execution per user
"""

from flask import Flask, request, jsonify
import docker
import uuid
import os
from datetime import datetime, timedelta

app = Flask(__name__)
client = docker.from_env()

# Store active sessions: {session_id: {container, created_at}}
active_sessions = {}

# Configuration
SESSION_TIMEOUT = timedelta(hours=1)  # Auto-cleanup after 1 hour
CONTAINER_IMAGE = "ubuntu:22.04"
MEMORY_LIMIT = "512m"  # Limit memory per container
CPU_QUOTA = 50000  # Limit CPU (50% of one core)

def cleanup_expired_sessions():
    """Remove expired sessions"""
    now = datetime.now()
    expired = [
        sid for sid, data in active_sessions.items()
        if now - data['created_at'] > SESSION_TIMEOUT
    ]
    for sid in expired:
        cleanup_session(sid)

def cleanup_session(session_id):
    """Stop and remove a container"""
    if session_id in active_sessions:
        try:
            container = active_sessions[session_id]['container']
            container.stop(timeout=5)
            container.remove()
        except Exception as e:
            print(f"Error cleaning up {session_id}: {e}")
        finally:
            del active_sessions[session_id]

@app.route('/create_session', methods=['POST'])
def create_session():
    """Create a new sandboxed session"""
    cleanup_expired_sessions()
    
    session_id = str(uuid.uuid4())
    
    try:
        # Create container with resource limits
        container = client.containers.run(
            CONTAINER_IMAGE,
            command="sleep infinity",  # Keep container running
            detach=True,
            mem_limit=MEMORY_LIMIT,
            cpu_quota=CPU_QUOTA,
            network_mode="none",  # No network access by default
            remove=False  # We'll remove manually
        )
        
        active_sessions[session_id] = {
            'container': container,
            'created_at': datetime.now()
        }
        
        return jsonify({
            'session_id': session_id,
            'status': 'created'
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/execute', methods=['POST'])
def execute_command():
    """Execute a bash command in a session's container"""
    data = request.json
    session_id = data.get('session_id')
    command = data.get('command')
    
    if not session_id or not command:
        return jsonify({'error': 'session_id and command required'}), 400
    
    if session_id not in active_sessions:
        return jsonify({'error': 'Invalid or expired session'}), 404
    
    try:
        container = active_sessions[session_id]['container']
        
        # Execute command with timeout
        result = container.exec_run(
            f"bash -c '{command}'",
            workdir="/workspace",
            user="root"
        )
        
        return jsonify({
            'exit_code': result.exit_code,
            'output': result.output.decode('utf-8', errors='replace')
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
    if session_id in active_sessions:
        return jsonify({'status': 'active'})
    return jsonify({'status': 'not found'}), 404

if __name__ == '__main__':
    # Run on all interfaces so it's accessible from your VPS
    app.run(host='0.0.0.0', port=5000, debug=False)
