#!/usr/bin/env python3
"""
Interactive Sandbox Shell with cd support (Sandbox V2)
Works like a real shell - cd persists between commands!

Supports both LOCAL and REMOTE modes:
- LOCAL: Direct in-process calls (no HTTP overhead)
- REMOTE: HTTP calls to remote sandbox server
"""

import atexit
import uuid
from typing import Literal, Optional

# Try to import readline for Unix (optional, for better command history)
try:
    import readline
except ImportError:
    # readline not available on Windows, but input() still works fine
    pass

# Import from sandbox package
from sandbox.client import SandboxClient

class SandboxShell:
    """Interactive shell for sandbox V2"""

    def __init__(self, mode: Literal["local", "remote"] = "local", server_url: Optional[str] = None):
        """
        Initialize sandbox shell.

        Args:
            mode: "local" or "remote"
            server_url: Required for remote mode
        """
        self.mode = mode
        self.current_dir = "/workspace"

        # Initialize client
        self.client = SandboxClient(mode=mode, server_url=server_url)

        # Create session with unique thread_id
        self.thread_id = f"shell_{uuid.uuid4().hex[:8]}"
        self.user_id = "shell_user"

        self._create_session()
        atexit.register(self.cleanup)

    def _create_session(self):
        print(f"🚀 Initializing sandbox in {self.mode.upper()} mode...")

        session_info = self.client.get_or_create_session(
            user_id=self.user_id,
            thread_id=self.thread_id,
            timeout_minutes=30
        )

        print(f"✅ Session: {session_info['session_id'][:12]}...")
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

        result = self.client.execute(full_command, timeout=timeout)

        # Combine stdout and stderr for output
        output = result['stdout']
        if result['stderr']:
            output += result['stderr']

        return output, result['exit_code']
    
    def _handle_cd(self, command: str):
        """Handle cd command"""
        parts = command.split(maxsplit=1)

        if len(parts) == 1 or parts[1] == '~':
            target = "/workspace"
        else:
            target = parts[1].strip()

        full_command = f"cd {self.current_dir} && cd {target} && pwd"

        result = self.client.execute(full_command, timeout=30)

        if result['exit_code'] == 0:
            self.current_dir = result['stdout'].strip()
            return "", 0
        else:
            # Combine stdout and stderr for error output
            output = result['stdout']
            if result['stderr']:
                output += result['stderr']
            return output, result['exit_code']
    
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
        """Cleanup session on exit"""
        try:
            self.client.close_session()
        except:
            pass


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(
        description='Interactive Sandbox Shell (V2)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Local mode (in-process, no HTTP)
  python sandbox_shell.py
  python sandbox_shell.py --mode local

  # Remote mode (HTTP to remote server)
  python sandbox_shell.py --mode remote --url http://YOUR_VPS_IP:20110
        """
    )

    parser.add_argument(
        '--mode',
        choices=['local', 'remote'],
        default='local',
        help='Sandbox mode: local (in-process) or remote (HTTP)'
    )

    parser.add_argument(
        '--url',
        help='Server URL for remote mode (e.g., http://localhost:20110)'
    )

    args = parser.parse_args()

    # Validate arguments
    if args.mode == 'remote' and not args.url:
        parser.error("--url is required for remote mode")

    try:
        shell = SandboxShell(mode=args.mode, server_url=args.url)
        shell.run_shell()
    except KeyboardInterrupt:
        print("\n\n👋 Interrupted")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()