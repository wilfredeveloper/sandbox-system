#!/usr/bin/env python3
"""
Interactive Sandbox Shell with cd support
Works like a real shell - cd persists between commands!
"""

import requests
import sys
import atexit

# Try to import readline for Unix (optional, for better command history)
try:
    import readline
except ImportError:
    # readline not available on Windows, but input() still works fine
    pass

class SandboxShell:
    """Interactive shell for sandbox"""
    
    def __init__(self, server_url: str):
        self.server_url = server_url.rstrip('/')
        self.session_id = None
        self.current_dir = "/workspace"
        self._create_session()
        atexit.register(self.cleanup)
    
    def _create_session(self):
        print(f"🚀 Connecting to {self.server_url}...")
        response = requests.post(f"{self.server_url}/create_session", timeout=10)
        response.raise_for_status()
        
        data = response.json()
        self.session_id = data['session_id']
        print(f"✅ Session: {self.session_id}")
        print(f"📁 Working directory: {self.current_dir}")
        print(f"💡 Type 'exit' or 'quit' to close\n")
    
    def run(self, command: str, timeout: int = 30):
        """Execute command"""
        cmd_stripped = command.strip()
        
        # Handle cd specially
        if cmd_stripped.startswith('cd ') or cmd_stripped == 'cd':
            return self._handle_cd(cmd_stripped)
        
        # Prepend cd for directory context
        full_command = f"cd {self.current_dir} && {command}"
        
        response = requests.post(
            f"{self.server_url}/execute",
            json={
                'session_id': self.session_id,
                'command': full_command,
                'timeout': timeout
            },
            timeout=timeout + 5
        )
        response.raise_for_status()
        result = response.json()
        
        return result['output'], result['exit_code']
    
    def _handle_cd(self, command: str):
        """Handle cd command"""
        parts = command.split(maxsplit=1)
        
        if len(parts) == 1 or parts[1] == '~':
            target = "/workspace"
        else:
            target = parts[1].strip()
        
        full_command = f"cd {self.current_dir} && cd {target} && pwd"
        
        response = requests.post(
            f"{self.server_url}/execute",
            json={'session_id': self.session_id, 'command': full_command, 'timeout': 30},
            timeout=35
        )
        response.raise_for_status()
        result = response.json()
        
        if result['exit_code'] == 0:
            self.current_dir = result['output'].strip()
            return "", 0
        else:
            return result['output'], result['exit_code']
    
    def get_prompt(self):
        """Get shell prompt"""
        # Show shortened path if it's long
        display_dir = self.current_dir
        if len(display_dir) > 30:
            display_dir = "..." + display_dir[-27:]
        return f"\033[1;34msandbox\033[0m:\033[1;32m{display_dir}\033[0m$ "
    
    def run_shell(self):
        """Main interactive loop"""
        while True:
            try:
                command = input(self.get_prompt()).strip()
                
                if not command:
                    continue
                
                if command.lower() in ['exit', 'quit', 'q']:
                    break
                
                # Handle special commands
                if command == 'pwd':
                    print(self.current_dir)
                    continue
                
                output, exit_code = self.run(command)
                
                if output:
                    print(output, end='')
                
                if exit_code != 0 and not output:
                    print(f"\033[1;31m[Exit code: {exit_code}]\033[0m")
                    
            except KeyboardInterrupt:
                print("\n(Use 'exit' to quit)")
                continue
            except EOFError:
                print()
                break
            except Exception as e:
                print(f"\033[1;31m❌ Error: {e}\033[0m")
        
        print("\n👋 Goodbye!")
    
    def cleanup(self):
        if self.session_id:
            try:
                requests.post(
                    f"{self.server_url}/cleanup",
                    json={'session_id': self.session_id},
                    timeout=10
                )
            except:
                pass


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python sandbox_shell.py <server_url>")
        print("Example: python sandbox_shell.py http://YOUR_VPS_IP:2205")
        sys.exit(1)
    
    server_url = sys.argv[1]
    
    try:
        shell = SandboxShell(server_url)
        shell.run_shell()
    except KeyboardInterrupt:
        print("\n\n👋 Interrupted")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()