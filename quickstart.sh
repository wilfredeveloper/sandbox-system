#!/bin/bash

# Quick Start Script for Sandbox Server
# Run this to set up everything quickly

set -e  # Exit on error

echo "================================"
echo "Sandbox Server Quick Start"
echo "================================"

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed. Please install Docker first."
    echo "Run: curl -fsSL https://get.docker.com | sh"
    exit 1
fi

echo "✅ Docker is installed"

# Check if uv is installed
if ! command -v uv &> /dev/null; then
    echo "❌ uv is not installed. Please install uv first."
    echo "Run: curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

echo "✅ uv is installed"

# Check if venv exists
if [ ! -d "venv" ]; then
    echo "⚠️  Virtual environment not found. Creating one with uv..."
    uv venv
fi

# Activate virtual environment
source venv/bin/activate

# Install requirements
echo "📦 Installing Python dependencies with uv..."
uv pip install -q -r requirements.txt

# Build custom sandbox image (optional)
read -p "Do you want to build a custom sandbox image with more tools? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "🔨 Building custom sandbox image..."
    docker build -f Dockerfile.sandbox -t custom-sandbox:latest .
    
    # Update sandbox_server.py to use custom image
    sed -i 's/CONTAINER_IMAGE = "ubuntu:22.04"/CONTAINER_IMAGE = "custom-sandbox:latest"/' sandbox_server.py
    echo "✅ Custom image built and configured"
else
    echo "📥 Pulling ubuntu:22.04 image..."
    docker pull ubuntu:22.04
fi

# Check if port 5000 is available
if lsof -Pi :5000 -sTCP:LISTEN -t >/dev/null 2>&1 ; then
    echo "⚠️  Port 5000 is already in use. The server might already be running."
    read -p "Try to start anyway? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

echo ""
echo "================================"
echo "✅ Setup complete!"
echo "================================"
echo ""
echo "To start the server:"
echo "  python sandbox_server.py"
echo ""
echo "To test the client:"
echo "  python sandbox_client.py"
echo ""
echo "To see LangGraph examples:"
echo "  python langgraph_example.py"
echo ""
echo "Server will run on: http://0.0.0.0:5000"
echo ""

read -p "Start the server now? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "🚀 Starting sandbox server..."
    python sandbox_server.py
fi
