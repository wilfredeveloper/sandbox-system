"""
Sandbox Client for LangGraph Agents
Use this in your LangGraph nodes to execute bash commands safely
"""

import requests
from typing import Optional

class SandboxClient:
    def __init__(self, server_url: str = "http://localhost:5000"):
        self.server_url = server_url
        self.session_id: Optional[str] = None
    
    def create_session(self) -> str:
        """Create a new sandbox session"""
        response = requests.post(f"{self.server_url}/create_session")
        response.raise_for_status()
        
        self.session_id = response.json()['session_id']
        return self.session_id
    
    def execute(self, command: str) -> dict:
        """Execute a bash command in the sandbox"""
        if not self.session_id:
            raise ValueError("No active session. Call create_session() first.")
        
        response = requests.post(
            f"{self.server_url}/execute",
            json={
                'session_id': self.session_id,
                'command': command
            }
        )
        response.raise_for_status()
        return response.json()
    
    def cleanup(self):
        """Cleanup the sandbox session"""
        if self.session_id:
            requests.post(
                f"{self.server_url}/cleanup",
                json={'session_id': self.session_id}
            )
            self.session_id = None
    
    def __enter__(self):
        """Context manager support"""
        self.create_session()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Auto-cleanup when using 'with' statement"""
        self.cleanup()


# Example usage in a LangGraph node
def bash_executor_node(state: dict) -> dict:
    """
    Example LangGraph node that executes bash commands
    """
    command = state.get('command', 'echo "Hello from sandbox"')
    
    # Use context manager for auto-cleanup
    with SandboxClient(server_url="http://your-vps-ip:5000") as sandbox:
        result = sandbox.execute(command)
        
        return {
            'output': result['output'],
            'exit_code': result['exit_code']
        }


# Simple test
if __name__ == '__main__':
    # Example 1: Using context manager (recommended)
    print("Example 1: Context manager")
    with SandboxClient() as sandbox:
        result = sandbox.execute("ls -la")
        print(f"Exit code: {result['exit_code']}")
        print(f"Output:\n{result['output']}")
    
    # Example 2: Manual session management
    print("\nExample 2: Manual management")
    client = SandboxClient()
    client.create_session()
    
    result = client.execute("echo 'Hello World' && pwd")
    print(f"Output: {result['output']}")
    
    result = client.execute("whoami")
    print(f"User: {result['output']}")
    
    client.cleanup()
