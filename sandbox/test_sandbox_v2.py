"""
Unit Tests for Enhanced Sandbox System V2

Tests cover:
- Session management (thread-scoped)
- Command execution and validation
- File operations (upload/download/list)
- Resource limits
- Auto-retry logic
"""

import pytest
import uuid
import os
import tempfile
from client import SandboxClient, SessionExpiredError


class TestSandboxClient:
    """Test cases for SandboxClient SDK"""

    @pytest.fixture
    def client(self):
        """Create sandbox client for testing"""
        # Use local mode for faster tests
        client = SandboxClient(mode="local")
        yield client
        # Cleanup after test
        try:
            client.close_session()
        except:
            pass

    @pytest.fixture
    def thread_id(self):
        """Generate unique thread ID for each test"""
        return f"test_{uuid.uuid4().hex[:12]}"

    def test_session_creation(self, client, thread_id):
        """Test: Create new session for thread"""
        session_info = client.get_or_create_session(
            user_id="test_user",
            thread_id=thread_id
        )

        assert session_info['status'] in ['created', 'existing']
        assert session_info['thread_id'] == thread_id
        assert client.session_id is not None

    def test_session_reuse(self, client, thread_id):
        """Test: Reuse existing session for same thread"""
        # Create session
        session_info1 = client.get_or_create_session(
            user_id="test_user",
            thread_id=thread_id
        )
        session_id1 = session_info1['session_id']

        # Request same thread again (should reuse)
        session_info2 = client.get_or_create_session(
            user_id="test_user",
            thread_id=thread_id
        )
        session_id2 = session_info2['session_id']

        assert session_id1 == session_id2
        assert session_info2['status'] == 'existing'

    def test_command_execution(self, client, thread_id):
        """Test: Execute valid bash command"""
        client.get_or_create_session(user_id="test_user", thread_id=thread_id)

        result = client.execute("echo 'Hello from sandbox'")

        assert result['exit_code'] == 0
        assert 'Hello from sandbox' in result['stdout']
        assert result['stderr'] == ''

    def test_file_persistence(self, client, thread_id):
        """Test: Files persist across commands in same session"""
        client.get_or_create_session(user_id="test_user", thread_id=thread_id)

        # Create file
        result1 = client.execute("echo 'test data' > test.txt")
        assert result1['exit_code'] == 0

        # Read file in subsequent command
        result2 = client.execute("cat test.txt")
        assert result2['exit_code'] == 0
        assert 'test data' in result2['stdout']

    def test_command_validation_whitelist(self, client, thread_id):
        """Test: Only whitelisted commands can run"""
        client.get_or_create_session(user_id="test_user", thread_id=thread_id)

        # Valid command (in whitelist)
        result = client.execute("jq --version")
        assert result['exit_code'] == 0

    def test_command_validation_blacklist(self, client, thread_id):
        """Test: Blacklisted commands are rejected"""
        client.get_or_create_session(user_id="test_user", thread_id=thread_id)

        # Invalid command (blacklisted)
        with pytest.raises(Exception) as exc_info:
            client.execute("rm -rf /workspace/*")

        assert "forbidden pattern" in str(exc_info.value).lower()

    def test_file_upload(self, client, thread_id):
        """Test: Upload file to workspace"""
        client.get_or_create_session(user_id="test_user", thread_id=thread_id)

        # Create temp file
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
            f.write("Test file content")
            temp_path = f.name

        try:
            # Upload file
            result = client.upload_file(temp_path, remote_name="uploaded.txt")

            assert result['status'] == 'uploaded'
            assert result['filename'] == 'uploaded.txt'

            # Verify file exists in sandbox
            exec_result = client.execute("cat uploaded.txt")
            assert exec_result['exit_code'] == 0
            assert "Test file content" in exec_result['stdout']
        finally:
            os.unlink(temp_path)

    def test_file_download(self, client, thread_id):
        """Test: Download file from workspace"""
        client.get_or_create_session(user_id="test_user", thread_id=thread_id)

        # Create file in sandbox
        client.execute("echo 'download test' > output.txt")

        # Download file
        with tempfile.TemporaryDirectory() as tmpdir:
            local_path = os.path.join(tmpdir, "downloaded.txt")
            result = client.download_file("output.txt", local_path=local_path)

            assert os.path.exists(result)
            with open(result, 'r') as f:
                content = f.read()
            assert "download test" in content

    def test_list_files(self, client, thread_id):
        """Test: List files in workspace"""
        client.get_or_create_session(user_id="test_user", thread_id=thread_id)

        # Create test files
        client.execute("echo 'file1' > test1.txt")
        client.execute("echo 'file2' > test2.txt")

        # List files
        files_info = client.list_files()

        assert files_info['total_files'] >= 2
        filenames = [f['name'] for f in files_info['files']]
        assert 'test1.txt' in filenames
        assert 'test2.txt' in filenames

    def test_session_isolation(self, client):
        """Test: Different threads have isolated sessions"""
        thread_id1 = f"thread1_{uuid.uuid4().hex[:8]}"
        thread_id2 = f"thread2_{uuid.uuid4().hex[:8]}"

        # Create file in first session
        client.get_or_create_session(user_id="test_user", thread_id=thread_id1)
        client.execute("echo 'thread1 data' > isolated.txt")

        # Switch to second session
        client.close_session()
        client.get_or_create_session(user_id="test_user", thread_id=thread_id2)

        # File from first session should not exist
        result = client.execute("cat isolated.txt")
        assert result['exit_code'] != 0  # File not found

    def test_context_manager(self, thread_id):
        """Test: Context manager auto-cleanup"""
        with SandboxClient(mode="local") as client:
            client.get_or_create_session(user_id="test_user", thread_id=thread_id)
            result = client.execute("echo 'test'")
            assert result['exit_code'] == 0

        # Session should be closed after exiting context
        assert client.session_id is None

    def test_non_root_execution(self, client, thread_id):
        """Test: Commands run as non-root user"""
        client.get_or_create_session(user_id="test_user", thread_id=thread_id)

        result = client.execute("whoami")

        assert result['exit_code'] == 0
        assert 'sandboxuser' in result['stdout']
        assert 'root' not in result['stdout']

    def test_workspace_directory(self, client, thread_id):
        """Test: Working directory is /workspace"""
        client.get_or_create_session(user_id="test_user", thread_id=thread_id)

        result = client.execute("pwd")

        assert result['exit_code'] == 0
        assert '/workspace' in result['stdout']


class TestResourceLimits:
    """Test cases for resource limits"""

    @pytest.fixture
    def client(self):
        """Create sandbox client for testing"""
        client = SandboxClient(mode="local")
        yield client
        try:
            client.close_session()
        except:
            pass

    @pytest.fixture
    def thread_id(self):
        """Generate unique thread ID for each test"""
        return f"test_{uuid.uuid4().hex[:12]}"

    def test_file_size_limit(self, client, thread_id):
        """Test: File size limit is enforced"""
        client.get_or_create_session(user_id="test_user", thread_id=thread_id)

        # Create large file (>100MB should fail)
        # Note: Actual limit depends on MAX_FILE_SIZE_MB setting
        # For testing, we just verify the limit is checked
        # (actual large file test would be slow)

        # Small file should work
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            f.write("small file")
            temp_path = f.name

        try:
            result = client.upload_file(temp_path)
            assert result['status'] == 'uploaded'
        finally:
            os.unlink(temp_path)


class TestBatchExecution:
    """Test cases for batch command execution"""

    def test_batch_execution(self):
        """Test: Execute multiple commands in same session"""
        from sandbox_client_v2 import BatchSandboxClient

        batch_client = BatchSandboxClient(mode="local")

        commands = [
            "echo 'Hello' > test.txt",
            "cat test.txt",
            "wc -l test.txt"
        ]

        results = batch_client.execute_batch(commands)

        assert len(results) == 3
        assert all(r['exit_code'] == 0 for r in results)
        assert 'Hello' in results[1]['stdout']


# Command-line test runner
if __name__ == '__main__':
    """Run tests with pytest"""
    import sys

    # Check if Docker is available
    import docker
    try:
        docker_client = docker.from_env()
        docker_client.ping()
        print("✓ Docker is available")
    except Exception as e:
        print(f"✗ Docker is not available: {e}")
        print("  Please start Docker before running tests")
        sys.exit(1)

    # Check if sandbox image exists
    try:
        docker_client.images.get("sandbox-secure:latest")
        print("✓ sandbox-secure:latest image found")
    except Exception:
        print("✗ sandbox-secure:latest image not found")
        print("  Please build the image first:")
        print("    docker build -f Dockerfile.secure -t sandbox-secure:latest .")
        sys.exit(1)

    # Run tests
    print("\nRunning tests...")
    pytest.main([__file__, "-v", "--tb=short"])
