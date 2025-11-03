import requests
import time
import random
import string
from statistics import mean

BASE_URL = "https://backend.spinwish.tech"
SIGNUP_ENDPOINT = f"{BASE_URL}/api/v1/users/signup"
LOGIN_ENDPOINT = f"{BASE_URL}/api/v1/users/login"

RUNS = 5

def random_string(length=8):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))

def test_signup(role="DJ"):
    email = f"user_{int(time.time())}_{random_string()}@example.com"
    payload = {
        "emailAddress": email,
        "username": f"user_{random_string()}",
        "password": "Password@123",
        "confirmPassword": "Password@123",
        "phoneNumber": "0712345678",
        "roleName": role
    }

    start = time.time()
    response = requests.post(SIGNUP_ENDPOINT, json=payload)
    elapsed = time.time() - start

    success = response.status_code in [200, 201]
    return response, elapsed, success

def test_login(email, password="Password@123"):
    payload = {
        "emailAddress": email,
        "password": password
    }

    start = time.time()
    response = requests.post(LOGIN_ENDPOINT, json=payload)
    elapsed = time.time() - start

    success = response.status_code == 200
    return response, elapsed, success

def run_tests():
    print(f"Running {RUNS} full auth cycles...\n")

    # Step 1: Confirm backend + roles
    print("Checking API health & available roles...")
    resp, _, ok = test_signup(role="ADMIN")
    if not ok:
        print("❌ Server unreachable or error on ADMIN signup. Aborting.")
        print(resp.text)
        return

    print("✅ API reachable.")
    active_role = "DJ"

    # Try USER role test
    resp_user, _, ok_user = test_signup(role="DJ")
    if not ok_user:
        print("⚠️ DJ role failed — falling back to ADMIN.")
        active_role = "ADMIN"
    else:
        print("✅ DJ role is active.\n")

    signup_times = []
    login_times = []
    success_count = 0

    for i in range(RUNS):
        print(f"Cycle {i+1}:")
        resp, signup_elapsed, signup_ok = test_signup(role=active_role)
        print(f"  Signup: {resp.status_code} in {signup_elapsed:.3f}s")

        if not signup_ok:
            print("  ❌ Signup failed, skipping login.\n")
            continue

        signup_times.append(signup_elapsed)
        email = resp.json().get("emailAddress")

        # Test login immediately
        resp_login, login_elapsed, login_ok = test_login(email)
        print(f"  Login: {resp_login.status_code} in {login_elapsed:.3f}s\n")

        if login_ok:
            login_times.append(login_elapsed)
            success_count += 1

    print("\n==== Final Report ====\n")
    if signup_times:
        print("📊 SIGNUP PERFORMANCE")
        print(f"  • Runs: {len(signup_times)}")
        print(f"  • Avg Response: {mean(signup_times):.3f}s")
        print(f"  • 95th Percentile: {sorted(signup_times)[int(0.95 * len(signup_times)) - 1]:.3f}s")
    else:
        print("No successful signup runs recorded.")

    if login_times:
        print("\n🔐 LOGIN PERFORMANCE")
        print(f"  • Runs: {len(login_times)}")
        print(f"  • Avg Response: {mean(login_times):.3f}s")
        print(f"  • 95th Percentile: {sorted(login_times)[int(0.95 * len(login_times)) - 1]:.3f}s")
    else:
        print("\nNo successful login runs recorded.")

    print(f"\n✅ Total successful auth flows: {success_count}/{RUNS}")

if __name__ == "__main__":
    run_tests()
