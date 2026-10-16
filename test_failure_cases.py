"""
NW Digital Operations Hub - Vishaqa Support Intelligence
Failure / Fallback Behaviour Test Runner

Tests edge cases that the assignment's Testing Responsibilities (Section 8)
requires: empty input, unsupported language, malformed input, and knowledge
unavailable. Confirms the service never crashes and always returns a safe,
structured response instead of an unhandled error.

USAGE:
    1. Make sure the service is running:
       python -m uvicorn apps.vishaqa-service.main:app --port 8001 --reload
    2. Run:  python test_failure_cases.py
"""

import requests

BASE_URL = "http://127.0.0.1:8001"
TEST_TENANT = "00000000-0000-0000-0000-00000000000a"

results = []


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    results.append((name, status, detail))
    print(f"{name}: {status}" + (f"  -->  {detail}" if detail else ""))


# ---- 1. Empty message ----
try:
    resp = requests.post(f"{BASE_URL}/support/classify", json={
        "tenant_id": TEST_TENANT, "message": "", "client_id": None
    }, timeout=10)
    ok = resp.status_code == 200 and resp.json().get("human_required") is True
    check("Empty message -> safe fallback (human_required)", ok, f"status={resp.status_code}, body={resp.json() if resp.status_code == 200 else resp.text}")
except Exception as e:
    check("Empty message -> safe fallback (human_required)", False, str(e))

# ---- 2. Whitespace-only message ----
try:
    resp = requests.post(f"{BASE_URL}/support/classify", json={
        "tenant_id": TEST_TENANT, "message": "     ", "client_id": None
    }, timeout=10)
    ok = resp.status_code == 200
    check("Whitespace-only message -> no crash", ok, f"status={resp.status_code}")
except Exception as e:
    check("Whitespace-only message -> no crash", False, str(e))

# ---- 3. Unsupported / non-English language (Urdu script) ----
try:
    resp = requests.post(f"{BASE_URL}/support/classify", json={
        "tenant_id": TEST_TENANT, "message": "میرا پاس ورڈ کام نہیں کر رہا", "client_id": None
    }, timeout=10)
    ok = resp.status_code == 200
    check("Unsupported language (Urdu) -> no crash, safe fallback", ok, f"status={resp.status_code}, body={resp.json() if resp.status_code == 200 else resp.text}")
except Exception as e:
    check("Unsupported language (Urdu) -> no crash, safe fallback", False, str(e))

# ---- 4. Missing required field (no 'message' key at all) ----
try:
    resp = requests.post(f"{BASE_URL}/support/classify", json={
        "tenant_id": TEST_TENANT, "client_id": None
    }, timeout=10)
    # FastAPI/Pydantic should reject this with 422, not crash with 500
    ok = resp.status_code == 422
    check("Missing required field -> structured 422 (not a crash)", ok, f"status={resp.status_code}")
except Exception as e:
    check("Missing required field -> structured 422 (not a crash)", False, str(e))

# ---- 5. Invalid tenant_id (not a UUID) ----
try:
    resp = requests.post(f"{BASE_URL}/support/classify", json={
        "tenant_id": "not-a-real-uuid", "message": "test", "client_id": None
    }, timeout=10)
    ok = resp.status_code == 200
    check("Invalid tenant_id -> graceful (no DB crash)", ok, f"status={resp.status_code}")
except Exception as e:
    check("Invalid tenant_id -> graceful (no DB crash)", False, str(e))

# ---- 6. Knowledge unavailable (product with zero matching articles) ----
try:
    resp = requests.post(f"{BASE_URL}/support/retrieve", json={
        "tenant_id": TEST_TENANT, "product": "NonExistentProductXYZ", "query": None
    }, timeout=10)
    ok = resp.status_code == 200 and resp.json().get("total_found") == 0
    check("Knowledge unavailable -> empty result, not an error", ok, f"status={resp.status_code}, body={resp.json() if resp.status_code == 200 else resp.text}")
except Exception as e:
    check("Knowledge unavailable -> empty result, not an error", False, str(e))

# ---- 7. Suggest-reply when no articles retrieved -> must require human ----
try:
    resp = requests.post(f"{BASE_URL}/support/suggest-reply", json={
        "tenant_id": TEST_TENANT, "ticket_message": "How do I use the POS system?",
        "product": "POS", "retrieved_article_ids": []
    }, timeout=10)
    data = resp.json() if resp.status_code == 200 else {}
    ok = resp.status_code == 200 and data.get("human_required") is True and data.get("proposed_reply") is None
    check("No KB articles -> suggest-reply requires human, no invented reply", ok, f"status={resp.status_code}, body={data}")
except Exception as e:
    check("No KB articles -> suggest-reply requires human, no invented reply", False, str(e))

# ---- 8. Summarize with empty messages list ----
try:
    resp = requests.post(f"{BASE_URL}/support/summarize", json={
        "tenant_id": TEST_TENANT, "client_room_id": "652989ef-c0d7-4234-a565-cc5b2b5f9dc5", "messages": []
    }, timeout=10)
    ok = resp.status_code == 200
    check("Empty conversation -> no crash", ok, f"status={resp.status_code}, body={resp.json() if resp.status_code == 200 else resp.text}")
except Exception as e:
    check("Empty conversation -> no crash", False, str(e))

# ---- 9. Very long message (stress test) ----
try:
    long_msg = "production system down " * 500  # ~11,500 chars
    resp = requests.post(f"{BASE_URL}/support/classify", json={
        "tenant_id": TEST_TENANT, "message": long_msg, "client_id": None
    }, timeout=15)
    ok = resp.status_code == 200
    check("Very long message -> no crash/timeout", ok, f"status={resp.status_code}")
except Exception as e:
    check("Very long message -> no crash/timeout", False, str(e))


# ---- Summary ----
total = len(results)
passed = sum(1 for _, s, _ in results if s == "PASS")
print(f"\n=== SUMMARY ===")
print(f"Total: {total} | Pass: {passed} | Fail: {total - passed}")
print(f"Pass rate: {round((passed/total)*100, 1)}%")

if passed < total:
    print("\nFailed cases:")
    for name, status, detail in results:
        if status == "FAIL":
            print(f"  - {name}: {detail}")
