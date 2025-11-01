#!/usr/bin/env python3
"""Test script to verify Docker exec_run user parameter"""

import docker

client = docker.from_env()

# Get a running sandbox container
containers = client.containers.list(filters={"ancestor": "sandbox-secure:latest"})

if not containers:
    print("❌ No sandbox-secure containers running")
    exit(1)

container = containers[0]
print(f"Testing container: {container.id[:12]}")

# Test 1: Default exec (should be sandboxuser from Dockerfile)
print("\n1. Default exec (no user parameter):")
result = container.exec_run("whoami")
print(f"   Output: {result.output.decode().strip()}")

# Test 2: Explicit sandboxuser
print("\n2. Explicit user='sandboxuser':")
result = container.exec_run("whoami", user="sandboxuser")
print(f"   Output: {result.output.decode().strip()}")

# Test 3: Explicit root
print("\n3. Explicit user='root':")
result = container.exec_run("whoami", user="root")
print(f"   Output: {result.output.decode().strip()}")

# Test 4: With bash -c (like the server does)
print("\n4. With bash -c and user='sandboxuser':")
result = container.exec_run(['bash', '-c', 'whoami'], user='sandboxuser')
print(f"   Output: {result.output.decode().strip()}")

# Test 5: Check what the server variable would be
SANDBOX_USER = "sandboxuser"
print(f"\n5. Using SANDBOX_USER variable ('{SANDBOX_USER}'):")
result = container.exec_run(['bash', '-c', 'whoami'], user=SANDBOX_USER)
print(f"   Output: {result.output.decode().strip()}")

