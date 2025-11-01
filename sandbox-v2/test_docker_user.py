#!/usr/bin/env python3
"""Test script to verify Docker user behavior"""

import docker

client = docker.from_env()

print("Test 1: Creating container with user='sandboxuser'")
container = client.containers.run(
    "sandbox-secure:latest",
    command="sleep infinity",
    detach=True,
    user="sandboxuser",
    working_dir="/workspace"
)

print(f"Container ID: {container.id[:12]}")

# Test exec_run with user specified
print("\nTest 2: exec_run with user='sandboxuser'")
result = container.exec_run(
    ['bash', '-c', 'whoami'],
    user='sandboxuser'
)
print(f"Output: {result.output.decode().strip()}")
print(f"Exit code: {result.exit_code}")

# Test exec_run WITHOUT user specified
print("\nTest 3: exec_run WITHOUT user parameter")
result = container.exec_run(
    ['bash', '-c', 'whoami']
)
print(f"Output: {result.output.decode().strip()}")
print(f"Exit code: {result.exit_code}")

# Test with id command
print("\nTest 4: exec_run 'id' with user='sandboxuser'")
result = container.exec_run(
    ['bash', '-c', 'id'],
    user='sandboxuser'
)
print(f"Output: {result.output.decode().strip()}")

# Cleanup
print("\nCleaning up...")
container.stop(timeout=2)
container.remove()
print("Done!")
