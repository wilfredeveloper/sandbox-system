"""
Unified Command Whitelist for Sandbox System V2

This is the SINGLE SOURCE OF TRUTH for allowed/forbidden commands.
Both server.py and bash_tools.py should import from here.

Design Philosophy:
- ALLOW: Commands useful for code execution, data processing, file management
- FORBID: Only commands that can harm the VPS host or escape the container
- Defense-in-depth: Container is already isolated, so be permissive for dev UX
"""

# ============================================================================
# ALLOWED COMMANDS (Whitelist)
# ============================================================================

ALLOWED_COMMANDS = {
    # ==================== Text Processing ====================
    'jq',           # JSON processor
    'awk',          # Pattern scanning and processing
    'grep',         # Search text
    'sed',          # Stream editor
    'sort',         # Sort lines
    'uniq',         # Remove duplicate lines
    'head',         # Output first part of files
    'tail',         # Output last part of files
    'wc',           # Word, line, character count
    'cut',          # Cut out sections from lines
    'tr',           # Translate or delete characters
    'cat',          # Concatenate files
    'echo',         # Display text
    'printf',       # Formatted output
    'tee',          # Read from stdin, write to stdout and files
    'comm',         # Compare sorted files line by line
    'diff',         # Compare files line by line
    'patch',        # Apply a diff file
    'column',       # Columnate lists
    'expand',       # Convert tabs to spaces
    'unexpand',     # Convert spaces to tabs
    'fold',         # Wrap text to fit width
    'fmt',          # Simple text formatter
    'nl',           # Number lines
    'paste',        # Merge lines of files
    'split',        # Split a file into pieces
    'strings',      # Print printable strings from files

    # ==================== File Operations ====================
    'ls',           # List directory contents
    'find',         # Search for files
    'locate',       # Find files by name (uses database)
    'which',        # Locate a command
    'whereis',      # Locate binary, source, man page
    'file',         # Determine file type
    'stat',         # Display file status
    'basename',     # Strip directory from filename
    'dirname',      # Strip filename from path
    'realpath',     # Print absolute path
    'readlink',     # Print symbolic link target
    'mkdir',        # Make directories
    'rmdir',        # Remove empty directories
    'touch',        # Change file timestamps / create empty file
    'cp',           # Copy files
    'mv',           # Move/rename files
    'rm',           # Remove files (safe in isolated container)
    'ln',           # Create links
    'chmod',        # Change file permissions
    'chown',        # Change file owner (non-root, so limited effect)
    'chgrp',        # Change group ownership
    'umask',        # Set file creation mask
    'du',           # Disk usage
    'df',           # Disk free space
    'tree',         # Display directory tree

    # ==================== Compression & Archives ====================
    'tar',          # Tape archive
    'gzip',         # Compress files
    'gunzip',       # Decompress gzip files
    'bzip2',        # Compress files
    'bunzip2',      # Decompress bzip2 files
    'xz',           # Compress files
    'unxz',         # Decompress xz files
    'zip',          # Package and compress files
    'unzip',        # Extract zip archives
    '7z',           # 7-Zip compression
    'zcat',         # Concatenate compressed files
    'zgrep',        # Search compressed files

    # ==================== Navigation & Environment ====================
    'cd',           # Change directory
    'pwd',          # Print working directory
    'pushd',        # Push directory onto stack
    'popd',         # Pop directory from stack
    'dirs',         # Display directory stack
    'env',          # Display environment variables
    'printenv',     # Print environment
    'export',       # Set environment variable (shell builtin)
    'unset',        # Unset environment variable
    'whoami',       # Print effective user
    'id',           # Print user/group IDs
    'groups',       # Print group memberships
    'date',         # Display/set date and time
    'uptime',       # Show uptime
    'uname',        # Print system information
    'hostname',     # Show/set system hostname

    # ==================== Programming & Execution ====================
    'python3',      # Python 3 interpreter
    'python',       # Python interpreter
    'python2',      # Python 2 (if available)
    'pip',          # Python package installer
    'pip3',         # Python 3 package installer
    'node',         # Node.js runtime
    'npm',          # Node package manager
    'npx',          # Execute npm packages
    'yarn',         # Yarn package manager
    'ruby',         # Ruby interpreter
    'gem',          # Ruby package manager
    'perl',         # Perl interpreter
    'php',          # PHP interpreter
    'java',         # Java runtime
    'javac',        # Java compiler
    'gcc',          # GNU C compiler
    'g++',          # GNU C++ compiler
    'make',         # Build automation
    'cmake',        # Cross-platform build system
    'cargo',        # Rust package manager
    'rustc',        # Rust compiler
    'go',           # Go compiler
    'bash',         # Bash shell
    'sh',           # POSIX shell
    'zsh',          # Z shell
    'fish',         # Friendly shell
    'awk',          # Pattern scanning
    'bc',           # Calculator
    'expr',         # Evaluate expressions
    'test',         # Evaluate conditional expression
    '[',            # Test command (alias)
    'true',         # Return success
    'false',        # Return failure
    'yes',          # Output string repeatedly
    'seq',          # Generate sequences
    'sleep',        # Delay for specified time
    'time',         # Time command execution
    'timeout',      # Run command with time limit
    'xargs',        # Build and execute commands

    # ==================== Version Control ====================
    'git',          # Git version control
    'svn',          # Subversion
    'hg',           # Mercurial

    # ==================== Database & Data Tools ====================
    'sqlite3',      # SQLite database
    'mysql',        # MySQL client
    'psql',         # PostgreSQL client
    'mongo',        # MongoDB client
    'redis-cli',    # Redis client

    # ==================== Process & System Info ====================
    'ps',           # Process status
    'top',          # Display processes
    'htop',         # Interactive process viewer
    'kill',         # Send signal to process (limited in container)
    'killall',      # Kill processes by name
    'pkill',        # Signal processes by pattern
    'pgrep',        # Find processes by pattern
    'jobs',         # List background jobs
    'bg',           # Resume job in background
    'fg',           # Resume job in foreground
    'nohup',        # Run command immune to hangups
    'nice',         # Run with modified priority
    'renice',       # Alter priority of running process
    'watch',        # Execute program periodically
    'free',         # Display memory usage
    'vmstat',       # Virtual memory statistics

    # ==================== Miscellaneous Utilities ====================
    'md5sum',       # Calculate MD5 checksum
    'sha1sum',      # Calculate SHA1 checksum
    'sha256sum',    # Calculate SHA256 checksum
    'sha512sum',    # Calculate SHA512 checksum
    'base64',       # Base64 encode/decode
    'hexdump',      # Hexadecimal dump
    'xxd',          # Make hexdump / reverse
    'od',           # Octal dump
    'tac',          # Reverse cat
    'rev',          # Reverse lines
    'shuf',         # Shuffle lines
    'factor',       # Factor numbers
    'numfmt',       # Reformat numbers
    'tsort',        # Topological sort
    'join',         # Join lines of two files
    'look',         # Display lines beginning with string
    'clear',        # Clear terminal screen
    'reset',        # Reset terminal
    'history',      # Command history
    'alias',        # Create command alias
    'unalias',      # Remove alias
    'type',         # Display command type
    'command',      # Execute command
    'builtin',      # Execute shell builtin
    'source',       # Execute commands from file
    '.',            # Execute commands from file (POSIX)
    'eval',         # Evaluate arguments as shell command
    'exec',         # Replace shell with command
    'exit',         # Exit shell
    'logout',       # Exit login shell
    'read',         # Read line from input
    'getopts',      # Parse positional parameters
    'shift',        # Shift positional parameters
    'wait',         # Wait for process completion
    'trap',         # Trap signals
    'ulimit',       # Control user limits
    'set',          # Set shell options
    'unset',        # Unset variables/functions
    'declare',      # Declare variables
    'local',        # Declare local variables
    'readonly',     # Mark variables as readonly
    'typeset',      # Declare variables (ksh/bash)
    'let',          # Evaluate arithmetic expression
    'return',       # Return from function
    'break',        # Break loop
    'continue',     # Continue loop
    'while',        # While loop
    'for',          # For loop
    'if',           # Conditional
    'then',         # Then clause
    'else',         # Else clause
    'elif',         # Else-if clause
    'fi',           # End if
    'case',         # Case statement
    'esac',         # End case
    'do',           # Do clause
    'done',         # End do
    'function',     # Define function
    'select',       # Select from list
    'until',        # Until loop
}

# ============================================================================
# FORBIDDEN PATTERNS (Commands that can harm VPS host)
# ============================================================================

FORBIDDEN_PATTERNS = [
    # ==================== Network Access (to prevent data exfiltration) ====================
    r'\bcurl\b',            # HTTP client
    r'\bwget\b',            # Download files
    r'\bfetch\b',           # BSD fetch utility
    r'\blynx\b',            # Text web browser
    r'\bw3m\b',             # Text web browser
    r'\btelnet\b',          # Telnet client
    r'\bnc\b',              # Netcat
    r'\bnetcat\b',          # Netcat
    r'\bsocat\b',           # Multipurpose relay
    r'\bssh\b',             # SSH client
    r'\bscp\b',             # Secure copy
    r'\bsftp\b',            # Secure FTP
    r'\brsync\b',           # Remote sync
    r'\bftp\b',             # FTP client
    r'\bping\b',            # ICMP echo
    r'\bdig\b',             # DNS lookup
    r'\bnslookup\b',        # DNS query
    r'\bhost\b',            # DNS lookup
    r'\btraceroute\b',      # Trace route
    r'\bip\b',              # IP configuration
    r'\bifconfig\b',        # Network interface configuration
    r'\bnetstat\b',         # Network statistics
    r'\bss\b',              # Socket statistics
    r'\blsof\b',            # List open files (can reveal host info)

    # ==================== Privilege Escalation ====================
    r'\bsudo\b',            # Execute as superuser
    r'\bsu\b',              # Switch user
    r'\bdoas\b',            # OpenBSD sudo alternative
    r'\bpkexec\b',          # PolicyKit execute

    # ==================== Dangerous Disk Operations ====================
    r'\bdd\b',              # Disk destroyer (can wipe drives)
    r'\bfdisk\b',           # Disk partitioner
    r'\bparted\b',          # Partition editor
    r'\bgdisk\b',           # GPT fdisk
    r'\bmkfs\b',            # Make filesystem
    r'\bmount\b',           # Mount filesystem
    r'\bumount\b',          # Unmount filesystem
    r'\bswapon\b',          # Enable swap
    r'\bswapoff\b',         # Disable swap
    r'\blosetup\b',         # Setup loop devices

    # ==================== Kernel & System Modification ====================
    r'\bmodprobe\b',        # Load kernel modules
    r'\binsmod\b',          # Insert kernel module
    r'\brmmod\b',           # Remove kernel module
    r'\blsmod\b',           # List loaded modules
    r'\bsysctl\b',          # Kernel parameters
    r'\bdmesg\b',           # Kernel ring buffer (can reveal host info)
    r'\bkexec\b',           # Load new kernel
    r'\breboot\b',          # Reboot system
    r'\bshutdown\b',        # Shutdown system
    r'\bhalt\b',            # Halt system
    r'\bpoweroff\b',        # Power off system
    r'\binit\b',            # Init system
    r'\bsystemctl\b',       # systemd control
    r'\bservice\b',         # Service control

    # ==================== Container Escape Attempts ====================
    r'\bdocker\b',          # Docker client (can't access from inside)
    r'\bkubectl\b',         # Kubernetes control
    r'\bpodman\b',          # Podman container runtime
    r'\brunc\b',            # OCI runtime
    r'\bcontainerd\b',      # Container runtime
    r'\bcrictl\b',          # CRI CLI
    r'\bchroot\b',          # Change root directory
    r'\bunshare\b',         # Run program with namespaces unshared
    r'\bnsenter\b',         # Enter namespaces

    # ==================== Backdoors & Persistence ====================
    r'\bcrontab\b',         # Schedule tasks
    r'\bat\b',              # Schedule one-time tasks
    r'\bbatch\b',           # Schedule batch jobs
]

# ============================================================================
# VALIDATION LOGIC
# ============================================================================

def get_allowed_commands():
    """Get the allowed commands set."""
    return ALLOWED_COMMANDS

def get_forbidden_patterns():
    """Get the forbidden patterns list."""
    return FORBIDDEN_PATTERNS
