# Simple Sandbox for LangGraph Agents

A lightweight, Docker-based sandbox system that allows LangGraph agents to safely execute bash commands in isolated environments with per-user sessions.

## 🎯 Features

- **Per-user isolation**: Each user gets their own Docker container
- **Resource limits**: CPU and memory controls to prevent abuse
- **Automatic cleanup**: Sessions expire after 1 hour
- **No network access**: Containers are isolated by default (configurable)
- **Simple API**: Easy to integrate with LangGraph
- **Stateful sessions**: Execute multiple commands in the same environment

## 📁 Project Structure

```
.
├── sandbox_server.py      # Flask API server for managing containers
├── sandbox_client.py      # Python client for LangGraph integration
├── langgraph_example.py   # Example LangGraph agents using the sandbox
├── Dockerfile.sandbox     # Custom sandbox image with pre-installed tools
├── requirements.txt       # Python dependencies
├── quickstart.sh          # Quick setup script
├── SETUP_GUIDE.md        # Detailed setup instructions
└── README.md             # This file
```

## 🚀 Quick Start

### 1. Prerequisites

- Linux VPS with Ubuntu 20.04+
- Docker installed
- Python 3.8+
- 2GB+ RAM recommended

### 2. Easy Setup

```bash
# Clone or download the files to your VPS
cd ~/sandbox-server

# Make quickstart script executable
chmod +x quickstart.sh

# Run the quickstart script
./quickstart.sh
```

That's it! The script will:
- Check dependencies
- Set up Python virtual environment
- Pull/build Docker images
- Start the server

### 3. Manual Setup

If you prefer manual setup:

```bash
# Install dependencies
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Pull base image
docker pull ubuntu:22.04

# Start the server
python sandbox_server.py
```

## 📖 Usage

### Basic Client Usage

```python
from sandbox_client import SandboxClient

# Create a sandbox and execute commands
with SandboxClient(server_url="http://localhost:5000") as sandbox:
    result = sandbox.execute("ls -la")
    print(result['output'])
```

### LangGraph Integration

```python
from langgraph.graph import StateGraph
from sandbox_client import SandboxClient

def bash_node(state):
    with SandboxClient() as sandbox:
        result = sandbox.execute(state['command'])
        return {'output': result['output']}

# Build your graph...
```

See `langgraph_example.py` for complete examples.

### API Endpoints

#### Create Session
```bash
curl -X POST http://your-vps:5000/create_session
# Returns: {"session_id": "uuid", "status": "created"}
```

#### Execute Command
```bash
curl -X POST http://your-vps:5000/execute \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "your-session-id",
    "command": "echo Hello"
  }'
# Returns: {"exit_code": 0, "output": "Hello\n"}
```

#### Cleanup Session
```bash
curl -X POST http://your-vps:5000/cleanup \
  -H "Content-Type: application/json" \
  -d '{"session_id": "your-session-id"}'
```

## ⚙️ Configuration

Edit `sandbox_server.py` to customize:

```python
SESSION_TIMEOUT = timedelta(hours=1)  # Session expiration
MEMORY_LIMIT = "512m"                 # Memory per container
CPU_QUOTA = 50000                     # CPU limit (50% of one core)
CONTAINER_IMAGE = "ubuntu:22.04"      # Base image
```

## 🔒 Security Considerations

This is a **simple** implementation for getting started. For production:

1. **Add Authentication**
   - Implement API key authentication
   - Add rate limiting per user

2. **Use HTTPS**
   - Set up nginx reverse proxy
   - Get SSL certificate (Let's Encrypt)

3. **Enhance Container Security**
   - Use read-only root filesystem
   - Drop unnecessary capabilities
   - Use seccomp profiles

4. **Monitor Resources**
   - Set up logging and monitoring
   - Add alerts for high resource usage

5. **Network Security**
   - Keep containers network-isolated unless needed
   - Use firewall rules to restrict access

Example nginx config:
```nginx
server {
    listen 443 ssl;
    server_name your-domain.com;
    
    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;
    
    location / {
        proxy_pass http://localhost:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

## 🎨 Custom Sandbox Image

Build a custom image with your preferred tools:

```bash
docker build -f Dockerfile.sandbox -t custom-sandbox:latest .
```

Then update `sandbox_server.py`:
```python
CONTAINER_IMAGE = "custom-sandbox:latest"
```

## 🔧 Troubleshooting

**Docker permission denied?**
```bash
sudo usermod -aG docker $USER
# Log out and back in
```

**Port already in use?**
```bash
# Check what's using port 5000
sudo lsof -i :5000

# Change port in sandbox_server.py if needed
```

**Containers not cleaning up?**
```bash
# Manually clean up containers
docker ps -a | grep ubuntu | awk '{print $1}' | xargs docker rm -f
```

**Out of disk space?**
```bash
# Clean up unused Docker resources
docker system prune -a
```

## 📊 Resource Usage

Typical resource usage per container:
- **Memory**: 50-100MB idle, up to configured limit under load
- **CPU**: Minimal when idle, limited by CPU_QUOTA setting
- **Disk**: ~100MB for base Ubuntu image

## 🛣️ Roadmap

Future enhancements:
- [ ] Add file upload/download support
- [ ] Implement WebSocket for real-time output
- [ ] Add persistent storage volumes per user
- [ ] Support for other languages (Python, Node.js REPL)
- [ ] Web-based terminal interface
- [ ] Usage analytics and logging

## 📝 License

This is a simple example implementation for educational purposes. Use at your own risk and enhance security before production use.

## 🤝 Contributing

This is a starter template. Feel free to:
- Add authentication mechanisms
- Improve security
- Add more features
- Share your improvements!

## 📚 Additional Resources

- [Docker Security Best Practices](https://docs.docker.com/engine/security/)
- [LangGraph Documentation](https://python.langchain.com/docs/langgraph)
- [Flask Security Guidelines](https://flask.palletsprojects.com/en/latest/security/)
