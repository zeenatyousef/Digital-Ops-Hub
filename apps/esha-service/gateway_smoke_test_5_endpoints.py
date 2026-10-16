"""
Gateway verification smoke test for the 5 endpoints not yet proven through
core_gateway (per evidence/section12_walkthrough.md): client-summary,
client-health, workload, scheduler-consistency, ai-evaluation/summary.

Follows the exact pattern already used to close DEF-004 and DEF-005: call
each endpoint BOTH directly against esha-service (port 8003, ground truth)
and through the real gateway (port 8000, with a real auth token), then
compare. Three possible outcomes per endpoint:

  MISSING  - gateway returns 404 -> route was never added to proxy.py
             (same shape as the original DEF-004 gap)
  FALLBACK - gateway returns 200 but with a fallback/stub shape instead of
             matching the direct call (same shape as DEF-005 - e.g. dropped
             query params, wrong forwarding)
  PASS     - gateway response matches the direct esha-service response

Usage:
    1. Make sure core_gateway (8000) and esha-service (8003) are both
       running locally.
    2. No real login needed - by default this self-registers a throwaway
       tenant_admin test account (same approach already used to close
       DEF-004: "Registered a real test user against the esha-dev-tenant").
       If you'd rather use a real account, set GW_USER / GW_PASS as
       environment variables and it'll try those first.
    3. Run: python gateway_smoke_test_5_endpoints.py
    4. Paste the output straight into evidence/defect_log.md or
       evidence/smoke_checklist.md - it's formatted to drop in directly.
"""
import os
import sys
import json
import requests

GATEWAY_BASE = os.environ.get("GATEWAY_BASE", "http://127.0.0.1:8000")
DIRECT_BASE = os.environ.get("DIRECT_BASE", "http://127.0.0.1:8003")
GATEWAY_USERNAME = os.environ.get("GW_USER", "")
GATEWAY_PASSWORD = os.environ.get("GW_PASS", "")

# (name, gateway path under /api, direct path on esha-service, query params)
ENDPOINTS = [
    ("client-summary", "/api/analytics/client-summary", "/analytics/client-summary", {}),
    ("client-health", "/api/analytics/client-health", "/analytics/client-health", {}),
    ("workload", "/api/analytics/workload", "/analytics/workload", {}),
    ("scheduler-consistency", "/api/analytics/scheduler-consistency",
     "/analytics/scheduler-consistency", {}),
    ("ai-evaluation-summary", "/api/quality/ai-evaluation/summary",
     "/quality/ai-evaluation/summary", {}),
]

# Known fallback markers seen in this codebase's fallback responses
# (DEF-005 used "service_version": "v1.0-fallback" as its tell). Add more
# here if the gateway uses a different marker for these routes.
FALLBACK_MARKERS = ["v1.0-fallback", "fallback", "stub"]


CANONICAL_TENANT_ID = "00000000-0000-0000-0000-00000000000a"


def register_and_login() -> str:
    """Self-registers a throwaway test tenant_admin account and logs in,
    the same approach used to close DEF-004 ("Registered a real test user
    against the esha-dev-tenant, logged in via /api/auth/login" -
    see evidence/defect_log.md). Avoids needing the real demo Super Admin
    (Atif Zaheer) credentials, which aren't stored anywhere in this repo.

    Matches apps/core_gateway/routers/auth.py exactly:
      - POST /api/auth/register takes JSON (UserCreate): tenant_id, email,
        password, full_name, role, phone_number (optional).
      - POST /api/auth/login takes OAuth2PasswordRequestForm - i.e. a
        form-encoded body (NOT JSON), field named "username" but matched
        against User.email server-side.
    """
    email = os.environ.get("GW_USER") or "esha-smoketest-user@example.com"
    password = os.environ.get("GW_PASS") or "SmokeTest123!"

    reg = requests.post(f"{GATEWAY_BASE}/api/auth/register", json={
        "tenant_id": CANONICAL_TENANT_ID,
        "email": email,
        "password": password,
        "full_name": "Esha Smoke Test User",
        "role": "tenant_admin",
    })
    # 201 = created fresh, 400 = "Email already registered" from a previous
    # run - either is fine, we just need the account to exist before login.
    if reg.status_code not in (200, 201, 400):
        print(f"WARNING: registration returned unexpected status "
              f"{reg.status_code}: {reg.text[:300]}")

    # Login is OAuth2PasswordRequestForm -> form-encoded, not JSON.
    # form_data.username is matched against User.email server-side.
    r = requests.post(f"{GATEWAY_BASE}/api/auth/login", data={
        "username": email, "password": password,
    })
    if r.status_code != 200:
        print(f"ERROR: login failed ({r.status_code}): {r.text}")
        sys.exit(1)
    token = r.json().get("access_token")
    if not token:
        print(f"ERROR: login succeeded but no access_token in response: {r.json()}")
        sys.exit(1)
    return token


def login() -> str:
    if GATEWAY_USERNAME and GATEWAY_PASSWORD:
        r = requests.post(f"{GATEWAY_BASE}/api/auth/login", data={
            "username": GATEWAY_USERNAME, "password": GATEWAY_PASSWORD,
        })
        if r.status_code == 200:
            token = r.json().get("access_token")
            if token:
                return token
        print("Provided GW_USER/GW_PASS didn't work as a login, falling back "
              "to self-registration...")
    return register_and_login()


def looks_like_fallback(body: dict) -> bool:
    blob = json.dumps(body).lower()
    return any(marker in blob for marker in FALLBACK_MARKERS)


def run():
    token = login()
    headers = {"Authorization": f"Bearer {token}"}

    results = []
    for name, gw_path, direct_path, params in ENDPOINTS:
        direct_r = requests.get(f"{DIRECT_BASE}{direct_path}", params=params)
        gw_r = requests.get(f"{GATEWAY_BASE}{gw_path}", params=params, headers=headers)

        if gw_r.status_code == 404:
            status = "MISSING"
            detail = "Gateway route does not exist (404) - not wired in proxy.py yet."
        elif gw_r.status_code == 403:
            status = "FORBIDDEN"
            detail = ("Gateway rejected this role (403) - tenant_admin may not be "
                      "authorized for this endpoint; try Super Admin or check RBAC.")
        elif gw_r.status_code != 200:
            status = "FAIL"
            detail = f"Gateway returned {gw_r.status_code}: {gw_r.text[:200]}"
        elif direct_r.status_code != 200:
            status = "FAIL"
            detail = f"Direct call to esha-service failed ({direct_r.status_code}) - can't compare."
        else:
            gw_body = gw_r.json()
            if looks_like_fallback(gw_body):
                status = "FALLBACK"
                detail = "Gateway returned 200 but response looks like a fallback/stub shape."
            elif gw_body == direct_r.json():
                status = "PASS"
                detail = "Gateway response matches direct esha-service response exactly."
            else:
                status = "MISMATCH"
                detail = "Gateway returned 200 real-looking data but it differs from the direct call - inspect manually."

        results.append((name, status, detail))

    print("\n=== Gateway verification results (5 previously-unverified endpoints) ===\n")
    print(f"{'Endpoint':<24} {'Status':<10} Detail")
    print("-" * 100)
    for name, status, detail in results:
        print(f"{name:<24} {status:<10} {detail}")

    n_pass = sum(1 for _, s, _ in results if s == "PASS")
    print(f"\n{n_pass}/{len(results)} PASS through the real gateway.")

    failing = [(n, s, d) for n, s, d in results if s != "PASS"]
    if failing:
        print("\n--- Items needing a defect_log.md entry (MISSING/FALLBACK/MISMATCH/FAIL) ---")
        for name, status, detail in failing:
            print(f"  {name}: {status} - {detail}")


if __name__ == "__main__":
    run()