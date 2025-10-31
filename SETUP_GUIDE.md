# Simple Sandbox Setup Guide

## Prerequisites
- A VPS with Ubuntu 20.04+ (or similar Linux distro)
- Root or sudo access
- At least 2GB RAM recommended

## Step 1: Install Docker on Your VPS

```bash
# Update package list
sudo apt-get update

# Install dependencies
sudo apt-get install -y ca-certificates curl gnupg lsb-release

# Add Docker's official GPG key
sudo mkdir -p /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg

# Set up the repository
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Install Docker
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# Start Docker
sudo systemctl start docker
sudo systemctl enable docker

# Add your user to docker group (so you don't need sudo)
sudo usermod -aG docker $USER

# Log out and back in for group changes to take effect
```

## Step 2: Set Up Python Environment

```bash
# Install Python and pip
sudo apt-get install -y python3 python3-pip python3-venv

# Create a directory for your sandbox server
mkdir ~/sandbox-server
cd ~/sandbox-server

# Copy the files (sandbox_server.py, requirements.txt) to this directory
# Then install dependencies
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Step 3: Pull the Ubuntu Image

```bash
# Pull the base image (this may take a few minutes)
docker pull ubuntu:22.04
```

## Step 4: Run the Sandbox Server

```bash
# Make sure you're in the sandbox-server directory with venv activated
source venv/bin/activate
python sandbox_server.py
```

The server will run on port 5000.

## Step 5: Test It Locally

In another terminal:

```bash
# Test creating a session
curl -X POST http://localhost:5000/create_session

# You'll get back a session_id, use it for commands:
curl -X POST http://localhost:5000/execute \
  -H "Content-Type: application/json" \
  -d '{"session_id": "YOUR_SESSION_ID", "command": "ls -la"}'
```

## Step 6: Make It Production-Ready

### Option A: Run with systemd (Recommended)

Create a systemd service file:

```bash
sudo nano /etc/systemd/system/sandbox-server.service
```

Paste this content (adjust paths):

```ini
[Unit]
Description=Sandbox Server for LangGraph
After=docker.service
Requires=docker.service

[Service]
Type=simple
User=your_username
WorkingDirectory=/home/your_username/sandbox-server
Environment="PATH=/home/your_username/sandbox-server/venv/bin"
ExecStart=/home/your_username/sandbox-server/venv/bin/python sandbox_server.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl start sandbox-server
sudo systemctl enable sandbox-server
sudo systemctl status sandbox-server
```

### Option B: Run with screen (Quick & Dirty)

```bash
screen -S sandbox
source venv/bin/activate
python sandbox_server.py
# Press Ctrl+A, then D to detach
```

## Step 7: Configure Firewall

```bash
# Allow port 5000 (adjust if using a different port)
sudo ufw allow 5000/tcp

# Make sure ufw is enabled
sudo ufw enable
sudo ufw status
```

## Step 8: Use from Your LangGraph Agent

Update the client to use your VPS IP:

```python
from sandbox_client import SandboxClient

# Use your VPS IP address
client = SandboxClient(server_url="http://YOUR_VPS_IP:5000")
```

## Security Considerations (for production)

1. **Add Authentication**: 
   - Add API key authentication to your Flask app
   - Use HTTPS with nginx reverse proxy

2. **Use HTTPS**: 
   - Set up nginx with Let's Encrypt SSL
   - Never expose the raw Flask server to the internet

3. **Tighten Container Limits**:
   - Adjust memory/CPU limits based on your needs
   - Add disk space limits

4. **Network Isolation**:
   - The default config has `network_mode="none"` (no network)
   - If you need network access, use Docker networks with restrictions

## Troubleshooting

**Docker permission denied?**
```bash
sudo usermod -aG docker $USER
# Log out and back in
```

**Port already in use?**
Change the port in `sandbox_server.py`:
```python
app.run(host='0.0.0.0', port=5001)  # Change to 5001 or any free port
```

**Container won't start?**
Check Docker logs:
```bash
docker logs <container_id>
```

## Next Steps

1. Test with simple commands first
2. Integrate with your LangGraph agent
3. Add monitoring and logging
4. Set up automatic cleanup of old containers
5. Consider adding rate limiting per user
