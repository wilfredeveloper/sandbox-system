"""
Configuration settings for Sandbox Server v2
All settings can be overridden via environment variables
"""

import os
from datetime import timedelta


class Settings:
    """Centralized configuration management"""

    # Server Configuration
    PORT = int(os.getenv('PORT', 7575))
    HOST = os.getenv('HOST', '0.0.0.0')
    DEBUG = os.getenv('DEBUG', 'false').lower() == 'true'
    WORKER_ID = os.getenv('WORKER_ID', 'standalone')

    # Container Pool Configuration
    POOL_SIZE = int(os.getenv('POOL_SIZE', 10))
    MIN_POOL_SIZE = int(os.getenv('MIN_POOL_SIZE', 3))
    MAX_POOL_SIZE = int(os.getenv('MAX_POOL_SIZE', 80))

    # Container Resource Limits
    CONTAINER_IMAGE = os.getenv('CONTAINER_IMAGE', 'sandbox-secure:latest')
    MEMORY_LIMIT = os.getenv('MEMORY_LIMIT', '256m')
    CPU_QUOTA = int(os.getenv('CPU_QUOTA', 25000))  # 25% of one core
    SANDBOX_USER = os.getenv('SANDBOX_USER', 'sandboxuser')
    WORKSPACE_DIR = os.getenv('WORKSPACE_DIR', '/workspace')

    # Session and Timeout Configuration
    SESSION_TIMEOUT_MINUTES = int(os.getenv('SESSION_TIMEOUT_MINUTES', 15))
    SESSION_TIMEOUT = timedelta(minutes=SESSION_TIMEOUT_MINUTES)

    CONTAINER_IDLE_TIMEOUT_MINUTES = int(os.getenv('CONTAINER_IDLE_TIMEOUT_MINUTES', 5))
    CONTAINER_IDLE_TIMEOUT = timedelta(minutes=CONTAINER_IDLE_TIMEOUT_MINUTES)

    CLEANUP_INTERVAL_SECONDS = int(os.getenv('CLEANUP_INTERVAL_SECONDS', 300))  # 5 minutes

    # Aggressive cleanup for resource efficiency
    AGGRESSIVE_CLEANUP = os.getenv('AGGRESSIVE_CLEANUP', 'true').lower() == 'true'

    # Pool refill behavior
    POOL_REFILL_DELAY_SECONDS = int(os.getenv('POOL_REFILL_DELAY_SECONDS', 60))

    # Redis Configuration (optional - for distributed setup)
    REDIS_HOST = os.getenv('REDIS_HOST')
    REDIS_PORT = int(os.getenv('REDIS_PORT', 6379))
    REDIS_PASSWORD = os.getenv('REDIS_PASSWORD', None)
    REDIS_ENABLED = REDIS_HOST is not None

    # Docker Configuration
    DOCKER_NETWORK_MODE = os.getenv('DOCKER_NETWORK_MODE', 'none')

    # Execution defaults
    DEFAULT_COMMAND_TIMEOUT = int(os.getenv('DEFAULT_COMMAND_TIMEOUT', 30))

    # File and workspace limits (NEW)
    MAX_FILE_SIZE_MB = int(os.getenv('MAX_FILE_SIZE_MB', 100))
    MAX_FILE_SIZE = MAX_FILE_SIZE_MB * 1024 * 1024  # 100MB

    MAX_TOTAL_FILES = int(os.getenv('MAX_TOTAL_FILES', 1000))

    MAX_WORKSPACE_SIZE_MB = int(os.getenv('MAX_WORKSPACE_SIZE_MB', 500))
    MAX_WORKSPACE_SIZE = MAX_WORKSPACE_SIZE_MB * 1024 * 1024  # 500MB

    @classmethod
    def print_config(cls):
        """Print current configuration for debugging"""
        print("=" * 60)
        print("Sandbox Server v2 Configuration")
        print("=" * 60)
        print(f"Server:")
        print(f"  Host: {cls.HOST}:{cls.PORT}")
        print(f"  Worker ID: {cls.WORKER_ID}")
        print(f"  Debug: {cls.DEBUG}")
        print()
        print(f"Container Pool:")
        print(f"  Initial Size: {cls.POOL_SIZE}")
        print(f"  Min Size: {cls.MIN_POOL_SIZE}")
        print(f"  Max Size: {cls.MAX_POOL_SIZE}")
        print(f"  Aggressive Cleanup: {cls.AGGRESSIVE_CLEANUP}")
        print()
        print(f"Container Resources:")
        print(f"  Image: {cls.CONTAINER_IMAGE}")
        print(f"  Memory: {cls.MEMORY_LIMIT}")
        print(f"  CPU Quota: {cls.CPU_QUOTA} (≈{cls.CPU_QUOTA/1000}%)")
        print(f"  User: {cls.SANDBOX_USER}")
        print(f"  Workspace: {cls.WORKSPACE_DIR}")
        print()
        print(f"Timeouts:")
        print(f"  Session Timeout: {cls.SESSION_TIMEOUT_MINUTES} minutes")
        print(f"  Container Idle Timeout: {cls.CONTAINER_IDLE_TIMEOUT_MINUTES} minutes")
        print(f"  Cleanup Interval: {cls.CLEANUP_INTERVAL_SECONDS} seconds")
        print(f"  Command Timeout: {cls.DEFAULT_COMMAND_TIMEOUT} seconds")
        print()
        print(f"Resource Limits:")
        print(f"  Max File Size: {cls.MAX_FILE_SIZE_MB} MB")
        print(f"  Max Total Files: {cls.MAX_TOTAL_FILES}")
        print(f"  Max Workspace Size: {cls.MAX_WORKSPACE_SIZE_MB} MB")
        print()
        print(f"Redis:")
        print(f"  Enabled: {cls.REDIS_ENABLED}")
        if cls.REDIS_ENABLED:
            print(f"  Host: {cls.REDIS_HOST}:{cls.REDIS_PORT}")
        print("=" * 60)

    @classmethod
    def validate(cls):
        """Validate configuration settings"""
        errors = []

        if cls.MIN_POOL_SIZE > cls.POOL_SIZE:
            errors.append("MIN_POOL_SIZE cannot be greater than POOL_SIZE")

        if cls.POOL_SIZE > cls.MAX_POOL_SIZE:
            errors.append("POOL_SIZE cannot be greater than MAX_POOL_SIZE")

        if cls.MIN_POOL_SIZE < 0:
            errors.append("MIN_POOL_SIZE must be >= 0")

        if cls.SESSION_TIMEOUT_MINUTES < 1:
            errors.append("SESSION_TIMEOUT_MINUTES must be >= 1")

        if cls.CONTAINER_IDLE_TIMEOUT_MINUTES < 1:
            errors.append("CONTAINER_IDLE_TIMEOUT_MINUTES must be >= 1")

        if cls.CPU_QUOTA < 1000 or cls.CPU_QUOTA > 100000:
            errors.append("CPU_QUOTA must be between 1000 and 100000")

        if errors:
            raise ValueError("Configuration validation failed:\n  " + "\n  ".join(errors))

        return True


# Create a singleton instance
settings = Settings()
