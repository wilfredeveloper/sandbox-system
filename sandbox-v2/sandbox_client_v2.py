"""
Enhanced Sandbox Client
Works with both standalone and distributed setups
"""

import requests
from typing import Optional, Dict, Any
import time

class SandboxClient:
    """Client for interacting with the sandbox system"""
    
    def __init__(self, server_url: str = "http://localhost:8000"):
        """
        Initialize client
        
        Args:
            server_url: URL of coordinator (distributed) or worker (standalone)
        """
        self.server_url = server_url.rstrip('/')
        self.session_id: Optional[str] = None
        self.worker_url: Optional[str] = None
    
    def create_session(self) -> Dict[str, Any]:
        """Create a new sandbox session"""
        response = requests.post(f"{self.server_url}/create_session", timeout=10)
        response.raise_for_status()
        
        data = response.json()
        self.session_id = data['session_id']
        self.worker_url = data.get('worker')
        
        return data
    
    def execute(self, command: str, timeout: int = 30) -> Dict[str, Any]:
        """
        Execute a bash command in the sandbox
        
        Args:
            command: Bash command to execute
            timeout: Command timeout in seconds (default 30)
            
        Returns:
            Dict with 'exit_code' and 'output' keys
        """
        if not self.session_id:
            raise ValueError("No active session. Call create_session() first.")
        
        response = requests.post(
            f"{self.server_url}/execute",
            json={
                'session_id': self.session_id,
                'command': command,
                'timeout': timeout
            },
            timeout=timeout + 5  # Give extra time for network
        )
        response.raise_for_status()
        return response.json()
    
    def upload_file(self, file_path: str, remote_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Upload a file to the sandbox workspace
        
        Args:
            file_path: Local path to file
            remote_name: Optional custom name for remote file
            
        Returns:
            Dict with upload status and remote path
        """
        if not self.session_id:
            raise ValueError("No active session. Call create_session() first.")
        
        import os
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
        
        filename = remote_name or os.path.basename(file_path)
        
        with open(file_path, 'rb') as f:
            files = {'file': (filename, f)}
            response = requests.post(
                f"{self.server_url}/upload_file",
                files=files,
                data={'session_id': self.session_id},
                timeout=60
            )
        
        response.raise_for_status()
        return response.json()
    
    def get_status(self) -> Dict[str, Any]:
        """Check if session is still active"""
        if not self.session_id:
            raise ValueError("No active session.")
        
        response = requests.get(
            f"{self.server_url}/status/{self.session_id}",
            timeout=5
        )
        response.raise_for_status()
        return response.json()
    
    def cleanup(self):
        """Cleanup the sandbox session"""
        if self.session_id:
            try:
                requests.post(
                    f"{self.server_url}/cleanup",
                    json={'session_id': self.session_id},
                    timeout=10
                )
            except Exception as e:
                print(f"Warning: Cleanup failed: {e}")
            finally:
                self.session_id = None
                self.worker_url = None
    
    def __enter__(self):
        """Context manager support"""
        self.create_session()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Auto-cleanup when using 'with' statement"""
        self.cleanup()


class BatchSandboxClient:
    """Client for executing multiple commands efficiently"""
    
    def __init__(self, server_url: str = "http://localhost:8000"):
        self.server_url = server_url
        self.client = SandboxClient(server_url)
    
    def execute_batch(self, commands: list[str], timeout: int = 30) -> list[Dict[str, Any]]:
        """
        Execute multiple commands in sequence in the same sandbox
        
        Args:
            commands: List of bash commands
            timeout: Timeout per command
            
        Returns:
            List of results, one per command
        """
        results = []
        
        with self.client:
            for command in commands:
                try:
                    result = self.client.execute(command, timeout=timeout)
                    results.append(result)
                    
                    # Stop on first error if desired
                    if result['exit_code'] != 0:
                        print(f"Command failed with exit code {result['exit_code']}")
                        # Uncomment to stop on error:
                        # break
                        
                except Exception as e:
                    results.append({
                        'exit_code': -1,
                        'output': f"Error: {str(e)}"
                    })
        
        return results


# Simple command-line interface
if __name__ == '__main__':
    import sys
    
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python sandbox_client_v2.py --test [--url URL]")
        print("  python sandbox_client_v2.py --batch 'cmd1' 'cmd2' 'cmd3' [--url URL]")
        print("  python sandbox_client_v2.py 'single command' [--url URL]")
        print("")
        print("Default URLs:")
        print("  Standalone mode: http://localhost:5000 (worker directly)")
        print("  Distributed mode: http://localhost:8000 (coordinator)")
        sys.exit(1)

    # Parse URL flag
    server_url = "http://localhost:5000"  # Default to standalone mode
    args = sys.argv[1:]

    if '--url' in args:
        url_index = args.index('--url')
        if url_index + 1 < len(args):
            server_url = args[url_index + 1]
            # Remove --url and its value from args
            args.pop(url_index)
            args.pop(url_index)

    if len(args) == 0:
        print("Error: No command specified")
        sys.exit(1)

    if args[0] == '--test':
        # Run test commands
        print(" Testing sandbox client...\n")
        
        with SandboxClient(server_url) as sandbox:
            print(f" Session created: {sandbox.session_id}")
            if sandbox.worker_url:
                print(f"   Assigned to worker: {sandbox.worker_url}")
            
            # Test 1: whoami (should not be root!)
            print("\n Test 1: whoami")
            result = sandbox.execute("whoami")
            print(f"   User: {result['output'].strip()}")
            print(f"   Exit code: {result['exit_code']}")
            
            # Test 2: pwd
            print("\n Test 2: pwd")
            result = sandbox.execute("pwd")
            print(f"   Working directory: {result['output'].strip()}")
            
            # Test 3: create and list file
            print("\n Test 3: File operations")
            sandbox.execute("echo 'Hello from sandbox!' > test.txt")
            result = sandbox.execute("cat test.txt && ls -lh test.txt")
            print(f"   Output:\n{result['output']}")
            
            # Test 4: Python
            print("\n Test 4: Python version")
            result = sandbox.execute("python3 --version")
            print(f"   {result['output'].strip()}")
            
            # Test 5: Check permissions
            print("\n Test 5: Check user permissions")
            result = sandbox.execute("id")
            print(f"   {result['output'].strip()}")
            
        print("\nAll tests completed!")

    elif args[0] == '--batch':
        # Batch execution
        commands = args[1:]
        print(f" Executing {len(commands)} commands in batch...\n")
        
        client = BatchSandboxClient(server_url)
        results = client.execute_batch(commands)
        
        for i, (cmd, result) in enumerate(zip(commands, results), 1):
            print(f"\n{'='*60}")
            print(f"Command {i}: {cmd}")
            print(f"Exit code: {result['exit_code']}")
            print(f"Output:\n{result['output']}")
    
    else:
        # Single command
        command = args[0]
        print(f" Executing: {command}\n")
        
        with SandboxClient(server_url) as sandbox:
            result = sandbox.execute(command)
            print(result['output'])
            sys.exit(result['exit_code'])
