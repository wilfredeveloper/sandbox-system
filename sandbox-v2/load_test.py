#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Load Testing Script for Sandbox Server
Simulates concurrent users creating sessions and executing commands
"""

import requests
import time
import threading
import statistics
from datetime import datetime
from collections import defaultdict
import json
import sys
import io

# Fix Windows console encoding
if sys.platform == 'win32':
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except:
        pass  # Already wrapped or running in different environment

class LoadTester:
    def __init__(self, server_url="http://localhost:2205", num_workers=10, requests_per_worker=10):
        self.server_url = server_url.rstrip('/')
        self.num_workers = num_workers
        self.requests_per_worker = requests_per_worker
        self.results = {
            'create_session': [],
            'execute': [],
            'errors': []
        }
        self.lock = threading.Lock()

    def test_health(self):
        """Test if server is healthy"""
        print("Testing server health...")
        try:
            response = requests.get(f"{self.server_url}/health", timeout=5)
            if response.status_code == 200:
                data = response.json()
                print(f"Server is healthy")
                print(f"   Pool size: {data.get('pool_size', 'N/A')}")
                print(f"   Active sessions: {data.get('active_sessions', 'N/A')}")
                print(f"   Worker ID: {data.get('worker_id', 'standalone')}")
                return True
            else:
                print(f"Health check failed: {response.status_code}")
                return False
        except Exception as e:
            print(f"Cannot connect to server: {e}")
            import traceback
            traceback.print_exc()
            return False

    def create_session(self):
        """Create a single session and measure time"""
        start = time.time()
        try:
            response = requests.post(
                f"{self.server_url}/create_session",
                json={},
                timeout=10
            )
            latency = (time.time() - start) * 1000  # Convert to ms

            if response.status_code == 200:
                data = response.json()
                with self.lock:
                    self.results['create_session'].append({
                        'latency': latency,
                        'session_id': data.get('session_id'),
                        'success': True
                    })
                return data.get('session_id'), latency
            else:
                with self.lock:
                    self.results['errors'].append({
                        'endpoint': 'create_session',
                        'error': f"HTTP {response.status_code}",
                        'latency': latency
                    })
                return None, latency
        except Exception as e:
            latency = (time.time() - start) * 1000
            with self.lock:
                self.results['errors'].append({
                    'endpoint': 'create_session',
                    'error': str(e),
                    'latency': latency
                })
            return None, latency

    def execute_command(self, session_id, command="whoami"):
        """Execute a command and measure time"""
        start = time.time()
        try:
            response = requests.post(
                f"{self.server_url}/execute",
                json={
                    'session_id': session_id,
                    'command': command,
                    'timeout': 30
                },
                timeout=35
            )
            latency = (time.time() - start) * 1000

            if response.status_code == 200:
                data = response.json()
                with self.lock:
                    self.results['execute'].append({
                        'latency': latency,
                        'exit_code': data.get('exit_code'),
                        'success': True
                    })
                return True, latency
            else:
                with self.lock:
                    self.results['errors'].append({
                        'endpoint': 'execute',
                        'error': f"HTTP {response.status_code}",
                        'latency': latency
                    })
                return False, latency
        except Exception as e:
            latency = (time.time() - start) * 1000
            with self.lock:
                self.results['errors'].append({
                    'endpoint': 'execute',
                    'error': str(e),
                    'latency': latency
                })
            return False, latency

    def cleanup_session(self, session_id):
        """Cleanup a session"""
        try:
            requests.post(
                f"{self.server_url}/cleanup",
                json={'session_id': session_id},
                timeout=10
            )
        except:
            pass

    def worker_thread(self, worker_id):
        """Each worker creates sessions and executes commands"""
        for i in range(self.requests_per_worker):
            # Create session
            session_id, create_latency = self.create_session()

            if session_id:
                # Execute some commands
                self.execute_command(session_id, "whoami")
                self.execute_command(session_id, "pwd")
                self.execute_command(session_id, "echo 'Hello World'")

                # Cleanup
                self.cleanup_session(session_id)

            # Small delay between iterations
            time.sleep(0.1)

    def run_test(self):
        """Run the load test"""
        print(f"\n{'='*60}")
        print(f"🚀 LOAD TEST STARTING")
        print(f"{'='*60}")
        print(f"Server: {self.server_url}")
        print(f"Concurrent workers: {self.num_workers}")
        print(f"Requests per worker: {self.requests_per_worker}")
        print(f"Total requests: {self.num_workers * self.requests_per_worker}")
        print(f"{'='*60}\n")

        # Test health first
        if not self.test_health():
            print("\n❌ Server is not healthy. Aborting test.")
            return

        print(f"\n⏱️  Starting test at {datetime.now().strftime('%H:%M:%S')}\n")

        start_time = time.time()

        # Create and start worker threads
        threads = []
        for i in range(self.num_workers):
            t = threading.Thread(target=self.worker_thread, args=(i,))
            t.start()
            threads.append(t)

        # Wait for all threads to complete
        for t in threads:
            t.join()

        end_time = time.time()
        total_duration = end_time - start_time

        # Print results
        self.print_results(total_duration)

    def print_results(self, total_duration):
        """Print detailed test results"""
        print(f"\n{'='*60}")
        print(f"📊 TEST RESULTS")
        print(f"{'='*60}\n")

        # Overall stats
        print(f"⏱️  Total Duration: {total_duration:.2f} seconds")
        print(f"📈 Requests per second: {len(self.results['create_session']) / total_duration:.2f}\n")

        # Create session stats
        if self.results['create_session']:
            create_latencies = [r['latency'] for r in self.results['create_session']]
            print(f"🎯 CREATE SESSION ENDPOINT")
            print(f"   Total requests: {len(create_latencies)}")
            print(f"   Success rate: {len([r for r in self.results['create_session'] if r['success']]) / len(create_latencies) * 100:.1f}%")
            print(f"   Min latency: {min(create_latencies):.2f}ms")
            print(f"   Max latency: {max(create_latencies):.2f}ms")
            print(f"   Avg latency: {statistics.mean(create_latencies):.2f}ms")
            print(f"   Median latency: {statistics.median(create_latencies):.2f}ms")
            if len(create_latencies) > 1:
                print(f"   Std deviation: {statistics.stdev(create_latencies):.2f}ms")

            # Percentiles
            sorted_latencies = sorted(create_latencies)
            p50 = sorted_latencies[len(sorted_latencies) * 50 // 100]
            p90 = sorted_latencies[len(sorted_latencies) * 90 // 100]
            p95 = sorted_latencies[len(sorted_latencies) * 95 // 100]
            p99 = sorted_latencies[len(sorted_latencies) * 99 // 100]

            print(f"   P50 (median): {p50:.2f}ms")
            print(f"   P90: {p90:.2f}ms")
            print(f"   P95: {p95:.2f}ms")
            print(f"   P99: {p99:.2f}ms\n")

        # Execute command stats
        if self.results['execute']:
            exec_latencies = [r['latency'] for r in self.results['execute']]
            print(f"⚡ EXECUTE ENDPOINT")
            print(f"   Total requests: {len(exec_latencies)}")
            print(f"   Success rate: {len([r for r in self.results['execute'] if r['success']]) / len(exec_latencies) * 100:.1f}%")
            print(f"   Min latency: {min(exec_latencies):.2f}ms")
            print(f"   Max latency: {max(exec_latencies):.2f}ms")
            print(f"   Avg latency: {statistics.mean(exec_latencies):.2f}ms")
            print(f"   Median latency: {statistics.median(exec_latencies):.2f}ms")
            if len(exec_latencies) > 1:
                print(f"   Std deviation: {statistics.stdev(exec_latencies):.2f}ms\n")

        # Error stats
        if self.results['errors']:
            print(f"❌ ERRORS")
            print(f"   Total errors: {len(self.results['errors'])}")

            # Group errors by type
            error_types = defaultdict(int)
            for error in self.results['errors']:
                error_types[f"{error['endpoint']}: {error['error']}"] += 1

            for error_msg, count in error_types.items():
                print(f"   - {error_msg}: {count}")
            print()

        # Final summary
        total_requests = len(self.results['create_session']) + len(self.results['execute'])
        total_errors = len(self.results['errors'])
        success_rate = (total_requests - total_errors) / total_requests * 100 if total_requests > 0 else 0

        print(f"{'='*60}")
        print(f"✅ OVERALL SUCCESS RATE: {success_rate:.1f}%")
        print(f"{'='*60}\n")

        # Recommendations
        self.print_recommendations()

    def print_recommendations(self):
        """Print performance recommendations"""
        if not self.results['create_session']:
            return

        avg_create = statistics.mean([r['latency'] for r in self.results['create_session']])

        print(f"💡 RECOMMENDATIONS\n")

        if avg_create < 100:
            print(f"   🎉 Excellent! Average session creation is {avg_create:.0f}ms")
            print(f"   Your server is performing well with container pooling.\n")
        elif avg_create < 500:
            print(f"   ✅ Good! Average session creation is {avg_create:.0f}ms")
            print(f"   Pool is working. Consider increasing pool size for better performance.\n")
        else:
            print(f"   ⚠️  Slow! Average session creation is {avg_create:.0f}ms")
            print(f"   Recommendations:")
            print(f"   - Increase POOL_SIZE in sandbox_server_v2.py")
            print(f"   - Ensure pool is fully initialized before testing")
            print(f"   - Check Docker performance on your system\n")

        if len(self.results['errors']) > 0:
            error_rate = len(self.results['errors']) / (len(self.results['create_session']) + len(self.results['execute'])) * 100
            if error_rate > 5:
                print(f"   ⚠️  High error rate ({error_rate:.1f}%)")
                print(f"   - Pool might be exhausted")
                print(f"   - Consider scaling to distributed mode with docker-compose\n")


if __name__ == '__main__':
    import sys

    # Parse command line arguments
    server_url = "http://localhost:2205"
    workers = 10
    num_requests = 10

    if '--help' in sys.argv or '-h' in sys.argv:
        print("Usage: python load_test.py [OPTIONS]")
        print("\nOptions:")
        print("  --url URL          Server URL (default: http://localhost:2205)")
        print("  --workers N        Number of concurrent workers (default: 10)")
        print("  --requests N       Requests per worker (default: 10)")
        print("\nExamples:")
        print("  python load_test.py --workers 20 --requests 5")
        print("  python load_test.py --url http://localhost:8000 --workers 50")
        sys.exit(0)

    # Parse arguments
    for i, arg in enumerate(sys.argv):
        if arg == '--url' and i + 1 < len(sys.argv):
            server_url = sys.argv[i + 1]
        elif arg == '--workers' and i + 1 < len(sys.argv):
            workers = int(sys.argv[i + 1])
        elif arg == '--num-requests' and i + 1 < len(sys.argv):
            num_requests = int(sys.argv[i + 1])
        elif arg == '--requests' and i + 1 < len(sys.argv):  # Keep backward compat
            num_requests = int(sys.argv[i + 1])

    # Run test
    tester = LoadTester(server_url=server_url, num_workers=workers, requests_per_worker=num_requests)
    tester.run_test()
