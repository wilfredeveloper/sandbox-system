"""
Enhanced Sandbox Client V2 SDK
- Dual mode: Local (in-process) and Remote (HTTP)
- Thread-scoped session management
- Auto-retry on session expiry
- File upload/download capabilities
"""

from typing import Optional, Dict, Any, Literal
import requests
import logging
import os

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# Custom exception for local mode
class SessionExpiredError(Exception):
    """Raised when session is expired in local mode"""
    pass


class SandboxClient:
    """
    Enhanced SDK client with thread-scoped sessions and auto-retry.

    Supports two modes:
    - local: Direct in-process calls (no HTTP overhead)
    - remote: HTTP calls to remote sandbox server
    """

    def __init__(
        self,
        mode: Literal["local", "remote"] = "local",
        server_url: Optional[str] = None
    ):
        """
        Initialize sandbox client.

        Args:
            mode: "local" for in-process, "remote" for HTTP
            server_url: Required for remote mode (e.g., "http://localhost:7575")
        """
        self.mode = mode
        self.server_url = server_url.rstrip('/') if server_url else None
        self.session_id: Optional[str] = None
        self.thread_id: Optional[str] = None
        self.user_id: Optional[str] = None

        # For local mode, import server instance
        if mode == "local":
            try:
                # Import server module and get instance
                import sys
                # Add sandbox-v2 to path if not already there
                sandbox_dir = os.path.dirname(os.path.abspath(__file__))
                if sandbox_dir not in sys.path:
                    sys.path.insert(0, sandbox_dir)

                from server import get_server_instance, SessionExpiredError as ServerSessionExpiredError
                self._server = get_server_instance()
                self._SessionExpiredError = ServerSessionExpiredError
                logger.info("✓ Sandbox client initialized in LOCAL mode")
            except Exception as e:
                raise ImportError(f"Failed to import server for local mode: {e}")
        else:
            if not server_url:
                raise ValueError("server_url required for remote mode")
            self._server = None
            self._SessionExpiredError = None
            logger.info(f"✓ Sandbox client initialized in REMOTE mode (server: {server_url})")

    def get_or_create_session(
        self,
        user_id: str,
        thread_id: str,
        timeout_minutes: int = 30
    ) -> Dict[str, Any]:
        """
        Get existing session for thread_id or create new one.

        This is the PRIMARY method for session initialization.
        Replaces the old create_session() method.

        Args:
            user_id: User identifier (for logging/metrics)
            thread_id: Conversation/thread identifier (PRIMARY KEY)
            timeout_minutes: Session idle timeout

        Returns:
            Session info dict with session_id, status, workspace_dir
        """
        if self.mode == "local":
            # Direct method call (no HTTP)
            session_info = self._server.get_session_by_thread(thread_id)
            if session_info:
                self.session_id = session_info['session_id']
                self.thread_id = thread_id
                self.user_id = user_id
                logger.info(f"Reusing existing session {self.session_id[:12]} for thread {thread_id[:12]}")
                return session_info

            # Create new session
            session_info = self._server.create_session(user_id, thread_id, timeout_minutes)
            self.session_id = session_info['session_id']
            self.thread_id = thread_id
            self.user_id = user_id
            logger.info(f"Created new session {self.session_id[:12]} for thread {thread_id[:12]}")
            return session_info
        else:
            # Remote mode: HTTP calls
            try:
                response = requests.get(
                    f"{self.server_url}/get_session",
                    params={"thread_id": thread_id},
                    timeout=5
                )
                if response.status_code == 200:
                    # Session exists, reuse it
                    data = response.json()
                    self.session_id = data['session_id']
                    self.thread_id = thread_id
                    self.user_id = user_id
                    logger.info(f"Reusing existing session {self.session_id[:12]} for thread {thread_id[:12]}")
                    return data
            except requests.RequestException:
                pass  # Session doesn't exist, create new one

            # Step 2: Create new session
            response = requests.post(
                f"{self.server_url}/create_session",
                json={
                    "user_id": user_id,
                    "thread_id": thread_id,
                    "timeout_minutes": timeout_minutes
                },
                timeout=10
            )
            response.raise_for_status()

            data = response.json()
            self.session_id = data['session_id']
            self.thread_id = thread_id
            self.user_id = user_id
            logger.info(f"Created new session {self.session_id[:12]} for thread {thread_id[:12]}")

            return data

    def execute(
        self,
        command: str,
        timeout: int = 30,
        auto_retry: bool = True
    ) -> Dict[str, Any]:
        """
        Execute bash command with auto-retry on session expiry.

        Args:
            command: Bash command to execute
            timeout: Command timeout in seconds
            auto_retry: Auto-recreate session if expired

        Returns:
            Dict with exit_code, stdout, stderr, execution_time_ms
        """
        if not self.session_id:
            raise ValueError("No active session. Call get_or_create_session() first.")

        try:
            return self._execute_internal(command, timeout)
        except (requests.HTTPError, SessionExpiredError, Exception) as e:
            # Handle both HTTP 404 (remote) and SessionExpiredError (local)
            is_expired = (
                (isinstance(e, requests.HTTPError) and hasattr(e.response, 'status_code') and e.response.status_code == 404) or
                (self.mode == "local" and isinstance(e, self._SessionExpiredError))
            )
            if is_expired and auto_retry:
                # Session expired, recreate and retry
                logger.info(f"Session expired for thread {self.thread_id}, recreating...")
                self.get_or_create_session(
                    user_id=self.user_id,
                    thread_id=self.thread_id
                )
                return self._execute_internal(command, timeout)
            raise

    def _execute_internal(self, command: str, timeout: int) -> Dict[str, Any]:
        """Internal execute without retry logic"""
        if self.mode == "local":
            # Direct method call
            return self._server.execute_command(self.session_id, command, timeout)
        else:
            # Remote HTTP call
            response = requests.post(
                f"{self.server_url}/execute",
                json={
                    "session_id": self.session_id,
                    "command": command,
                    "timeout": timeout
                },
                timeout=timeout + 5
            )
            response.raise_for_status()
            return response.json()

    def upload_file(
        self,
        file_path: str,
        remote_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """Upload file to workspace"""
        if not self.session_id:
            raise ValueError("No active session. Call get_or_create_session() first.")

        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        filename = remote_name or os.path.basename(file_path)

        if self.mode == "local":
            # Direct method call
            with open(file_path, 'rb') as f:
                file_data = f.read()
            return self._server.upload_file(self.session_id, filename, file_data)
        else:
            # Remote HTTP call
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

    def upload_file_from_bytes(
        self,
        filename: str,
        file_data: bytes
    ) -> Dict[str, Any]:
        """Upload file from bytes data to workspace"""
        if not self.session_id:
            raise ValueError("No active session. Call get_or_create_session() first.")

        if self.mode == "local":
            if self._server is None:
                raise RuntimeError(
                    "Local server is not initialized. Call start_local_server() or set self._server before using local mode."
                )
            return self._server.upload_file(self.session_id, filename, file_data)
        else:
            files = {'file': (filename, file_data)}
            response = requests.post(
                f"{self.server_url}/upload_file",
                files=files,
                data={'session_id': self.session_id},
                timeout=60
            )
            response.raise_for_status()
            return response.json()

    def download_file(
        self,
        remote_name: str,
        local_path: Optional[str] = None
    ) -> str:
        """
        Download file from workspace.

        Args:
            remote_name: Filename in workspace
            local_path: Local path to save (defaults to current dir)

        Returns:
            Path to downloaded file
        """
        if not self.session_id:
            raise ValueError("No active session. Call get_or_create_session() first.")

        if self.mode == "local":
            # Direct method call
            file_data = self._server.download_file(self.session_id, remote_name)
            save_path = local_path or os.path.join(os.getcwd(), remote_name)
            with open(save_path, 'wb') as f:
                f.write(file_data)
            logger.info(f"Downloaded {remote_name} to {save_path}")
            return save_path
        else:
            # Remote HTTP call
            response = requests.post(
                f"{self.server_url}/download_file",
                json={
                    "session_id": self.session_id,
                    "filename": remote_name
                },
                timeout=60
            )
            response.raise_for_status()

            # Save to local path
            save_path = local_path or os.path.join(os.getcwd(), remote_name)
            with open(save_path, 'wb') as f:
                f.write(response.content)

            logger.info(f"Downloaded {remote_name} to {save_path}")
            return save_path

    def list_files(self) -> Dict[str, Any]:
        """List all files in workspace"""
        if not self.session_id:
            raise ValueError("No active session. Call get_or_create_session() first.")

        if self.mode == "local":
            return self._server.list_files(self.session_id)
        else:
            response = requests.get(
                f"{self.server_url}/list_files",
                params={"session_id": self.session_id},
                timeout=5
            )
            response.raise_for_status()
            return response.json()

    def close_session(self):
        """Explicitly cleanup session"""
        if self.session_id:
            try:
                if self.mode == "local":
                    self._server.cleanup_session(self.session_id)
                else:
                    requests.post(
                        f"{self.server_url}/cleanup",
                        json={'session_id': self.session_id},
                        timeout=10
                    )
                logger.info(f"Closed session {self.session_id[:12]}")
            except Exception as e:
                logger.warning(f"Cleanup failed: {e}")
            finally:
                self.session_id = None
                self.thread_id = None
                self.user_id = None

    def __enter__(self):
        """Context manager support"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Auto-cleanup on exit"""
        self.close_session()


class BatchSandboxClient:
    """Client for executing multiple commands efficiently"""

    def __init__(
        self,
        mode: Literal["local", "remote"] = "local",
        server_url: Optional[str] = None
    ):
        """
        Initialize batch client.

        Args:
            mode: "local" for in-process, "remote" for HTTP
            server_url: Required for remote mode
        """
        self.mode = mode
        self.server_url = server_url
        self.client = SandboxClient(mode=mode, server_url=server_url)

    def execute_batch(
        self,
        commands: list[str],
        timeout: int = 30,
        user_id: str = "batch_user",
        thread_id: Optional[str] = None
    ) -> list[Dict[str, Any]]:
        """
        Execute multiple commands in sequence in the same sandbox

        Args:
            commands: List of bash commands
            timeout: Timeout per command
            user_id: User identifier
            thread_id: Thread identifier (auto-generated if not provided)

        Returns:
            List of results, one per command
        """
        import uuid

        if not thread_id:
            thread_id = f"batch_{uuid.uuid4().hex[:12]}"

        results = []

        # Create session
        self.client.get_or_create_session(
            user_id=user_id,
            thread_id=thread_id
        )

        try:
            for i, command in enumerate(commands):
                try:
                    logger.info(f"Executing command {i+1}/{len(commands)}: {command[:50]}...")
                    result = self.client.execute(command, timeout=timeout)
                    results.append(result)

                    # Stop on first error if desired
                    if result['exit_code'] != 0:
                        logger.warning(f"Command failed with exit code {result['exit_code']}")
                        # Uncomment to stop on error:
                        # break

                except Exception as e:
                    logger.error(f"Command {i+1} failed: {e}")
                    results.append({
                        'exit_code': -1,
                        'stdout': '',
                        'stderr': f"Error: {str(e)}",
                        'execution_time_ms': 0
                    })
        finally:
            self.client.close_session()

        return results


# Simple command-line interface
if __name__ == '__main__':
    import sys

    if len(sys.argv) < 2:
        print("Usage:")
        print("  python sandbox_client_v2.py --test [--mode local|remote] [--url URL]")
        print("  python sandbox_client_v2.py --batch 'cmd1' 'cmd2' 'cmd3' [--mode local|remote] [--url URL]")
        print("  python sandbox_client_v2.py 'single command' [--mode local|remote] [--url URL]")
        print("")
        print("Modes:")
        print("  local: Direct in-process calls (default, no HTTP)")
        print("  remote: HTTP calls to remote server")
        print("")
        print("Default URLs for remote mode:")
        print("  Standalone mode: http://localhost:7575 (worker directly)")
        print("  Distributed mode: http://localhost:7575 (coordinator)")
        sys.exit(1)

    # Parse flags
    mode = "local"  # Default to local mode
    server_url = None
    args = sys.argv[1:]

    if '--mode' in args:
        mode_index = args.index('--mode')
        if mode_index + 1 < len(args):
            mode = args[mode_index + 1]
            if mode not in ['local', 'remote']:
                print(f"Error: Invalid mode '{mode}'. Must be 'local' or 'remote'")
                sys.exit(1)
            args.pop(mode_index)
            args.pop(mode_index)

    if '--url' in args:
        url_index = args.index('--url')
        if url_index + 1 < len(args):
            server_url = args[url_index + 1]
            args.pop(url_index)
            args.pop(url_index)

    # For remote mode, require URL
    if mode == "remote" and not server_url:
        server_url = "http://localhost:7575"  # Default

    if len(args) == 0:
        print("Error: No command specified")
        sys.exit(1)

    print(f"Mode: {mode.upper()}")
    if mode == "remote":
        print(f"Server URL: {server_url}")
    print()

    if args[0] == '--test':
        # Run test commands
        print("Testing sandbox client...\n")

        client = SandboxClient(mode=mode, server_url=server_url)

        # Get or create session
        import uuid
        thread_id = f"test_{uuid.uuid4().hex[:12]}"
        session_info = client.get_or_create_session(
            user_id="test_user",
            thread_id=thread_id
        )

        print(f"Session created: {client.session_id}")
        print(f"  Thread ID: {thread_id}")
        print(f"  Status: {session_info.get('status')}")
        print(f"  Workspace: {session_info.get('workspace_dir')}")

        try:
            # Test 1: whoami (should not be root!)
            print("\nTest 1: whoami")
            result = client.execute("whoami")
            print(f"   User: {result['stdout'].strip()}")
            print(f"   Exit code: {result['exit_code']}")

            # Test 2: pwd
            print("\nTest 2: pwd")
            result = client.execute("pwd")
            print(f"   Working directory: {result['stdout'].strip()}")

            # Test 3: create and list file
            print("\nTest 3: File operations")
            client.execute("echo 'Hello from sandbox!' > test.txt")
            result = client.execute("cat test.txt && ls -lh test.txt")
            print(f"   Output:\n{result['stdout']}")

            # Test 4: Python
            print("\nTest 4: Python version")
            result = client.execute("python3 --version")
            print(f"   {result['stdout'].strip()}")

            # Test 5: List files
            print("\nTest 5: List files")
            files_info = client.list_files()
            print(f"   Total files: {files_info['total_files']}")
            for file_info in files_info['files']:
                print(f"     - {file_info['name']} ({file_info['size_bytes']} bytes)")

        finally:
            client.close_session()

        print("\nAll tests completed!")

    elif args[0] == '--batch':
        # Batch execution
        commands = args[1:]
        print(f"Executing {len(commands)} commands in batch...\n")

        batch_client = BatchSandboxClient(mode=mode, server_url=server_url)
        results = batch_client.execute_batch(commands)

        for i, (cmd, result) in enumerate(zip(commands, results), 1):
            print(f"\n{'='*60}")
            print(f"Command {i}: {cmd}")
            print(f"Exit code: {result['exit_code']}")
            print(f"Stdout:\n{result['stdout']}")
            if result['stderr']:
                print(f"Stderr:\n{result['stderr']}")

    else:
        # Single command
        command = args[0]
        print(f"Executing: {command}\n")

        client = SandboxClient(mode=mode, server_url=server_url)

        import uuid
        thread_id = f"single_{uuid.uuid4().hex[:12]}"

        client.get_or_create_session(
            user_id="cli_user",
            thread_id=thread_id
        )

        try:
            result = client.execute(command)
            print(result['stdout'])
            if result['stderr']:
                print(result['stderr'], file=sys.stderr)
            sys.exit(result['exit_code'])
        finally:
            client.close_session()
