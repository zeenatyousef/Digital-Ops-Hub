"""
apps/esha-service/vishaqa_benchmark.py

Real (non-placeholder) benchmark suite for Viqasha's /support/classify endpoint,
per task doc section 2.4: "Independently test Asma and Viqasha outputs with
benchmark cases and record corrections."

This REPLACES VIQASHA_PLACEHOLDER_CASES / viqasha_predict_fn / viqasha_match_fn
in ai_evaluation_updated.py, mirroring the same "promote to a dedicated file"
treatment asma_benchmark.py already got. The 8 cases below are unchanged in
content from ai_evaluation_updated.py -- they were already independently
written (see INDEPENDENCE NOTE below) -- only the execution target and file
organization changed.

DEF-001 -- RESOLVED 2026-08-27:
This benchmark originally hit an unhandled FK violation (-> 500 on every case)
because VIQASHA_TEST_TENANT_ID was not seeded on the shared DB. Viqasha fixed
this in commit 1360600 (wrapped DB logging in try/except across classify,
summarize, suggest-reply, and escalation, so a failed log no longer breaks the
response). Retested the same day against this exact tenant id, still absent
from the DB: 8/8 real classification responses, zero errors. See
evidence/defect_log.md, DEF-001 (Closed) for full retest evidence.

INDEPENDENCE NOTE: these messages are deliberately written from scratch, NOT
copied or lightly reworded from her guardrail keyword lists in
apps/vishaqa-service/main.py. The task doc requires INDEPENDENT testing -- if
our benchmark cases used her exact trigger words, we'd only be confirming her
code matches her own keyword list, not verifying it handles real-world
phrasing correctly. Some cases below intentionally avoid her literal trigger
words to test whether the classifier generalizes, and some are edge cases /
near-misses to probe boundaries.
"""

import os

import requests

from ai_evaluation_updated import (
    BenchmarkCase,
    record_correction,
    run_benchmark_suite,
    summarize,
    write_evaluation_report,
)

VIQASHA_API_URL = os.getenv("VIQASHA_API_URL", "http://localhost:8001")

# Original test tenant from Viqasha's README. Confirmed absent from the shared
# DB, and confirmed (2026-08-27, DEF-001 retest) that her service now handles
# this gracefully instead of crashing. Kept as-is rather than switched to a
# seeded tenant, since testing against a genuinely unseeded tenant is a more
# realistic check of the fix than testing against one that happens to exist.
VIQASHA_TEST_TENANT_ID = "d5de8b4d-b089-4d4e-9283-fd952f8df783"


# =========================================================
# Benchmark cases
# =========================================================

VIQASHA_CASES = [
    BenchmarkCase(
        id="viqasha-01",
        module="viqasha",
        category="support",
        description="Clear account breach report, phrased without her exact 'hacked/breach' combos",
        input={"message": "Someone I don't recognize logged into my account and changed my settings."},
        expected_output={"product": "Security", "human_required": True},
    ),
    BenchmarkCase(
        id="viqasha-02",
        module="viqasha",
        category="support",
        description="Billing complaint phrased naturally, not using her exact 'refund/charged me' words",
        input={"message": "I noticed I was billed for two subscriptions this month, only one should exist."},
        expected_output={"product": "Financial", "human_required": True},
    ),
    BenchmarkCase(
        id="viqasha-03",
        module="viqasha",
        category="support",
        description="FBR invoice failing to submit — should route to FBR product, not generic fallback",
        input={"message": "None of our invoices are going through to FBR today, they just fail."},
        expected_output={"product": "FBR Digital Invoicing", "human_required": False},
    ),
    BenchmarkCase(
        id="viqasha-04",
        module="viqasha",
        category="support",
        description="POS printing issue using inflected form 'printing' — regression check for her documented bug fix",
        input={"message": "The receipts at the front counter are not printing anymore."},
        expected_output={"product": "POS", "human_required": False},
    ),
    BenchmarkCase(
        id="viqasha-05",
        module="viqasha",
        category="support",
        description="Ambiguous 'checkout is down' — tests guardrail-vs-website overlap she flagged as a known limitation",
        input={"message": "Customers say checkout is completely down on the website right now."},
        expected_output={"product": "Production Outage", "human_required": True},
    ),
    BenchmarkCase(
        id="viqasha-06",
        module="viqasha",
        category="support",
        description="Genuinely vague message with no product signal — should hit the low-confidence fallback, not guess",
        input={"message": "Something feels off today, can someone take a look when free?"},
        expected_output={"product": "Unclassified", "human_required": True},
    ),
    BenchmarkCase(
        id="viqasha-07",
        module="viqasha",
        category="support",
        description="Data-deletion request phrased conversationally, not using her literal 'delete/wipe data' combo",
        input={"message": "Can you please remove all our old customer records from the system permanently?"},
        expected_output={"product": "Destructive Action", "human_required": True},
    ),
    BenchmarkCase(
        id="viqasha-08",
        module="viqasha",
        category="support",
        description="Simple how-to question, should be low severity and NOT require a human",
        input={"message": "New here — how do I add a second cashier to the POS system?"},
        expected_output={"product": "POS", "human_required": False},
    ),
]


# =========================================================
# predict_fn / match_fn
# =========================================================

def viqasha_predict_fn(input_data: dict) -> dict:
    payload = {
        "message": input_data["message"],
        "tenant_id": input_data.get("tenant_id", VIQASHA_TEST_TENANT_ID),
    }
    try:
        resp = requests.post(f"{VIQASHA_API_URL}/support/classify", json=payload, timeout=10.0)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as e:
        return {"_error": str(e)}


def viqasha_match_fn(expected: dict, actual: dict) -> bool:
    if "_error" in actual:
        return False
    return (
        actual.get("product") == expected.get("product")
        and actual.get("human_required") == expected.get("human_required")
    )


# =========================================================
# Entry point
# =========================================================

if __name__ == "__main__":
    import json

    print(f"Running Viqasha benchmark against {VIQASHA_API_URL} "
          f"using tenant {VIQASHA_TEST_TENANT_ID} (unseeded — DEF-001 fix verification)...")

    results = run_benchmark_suite(VIQASHA_CASES, viqasha_predict_fn, viqasha_match_fn)

    # Real classification misses found on the 2026-08-25 run (no longer 500s —
    # DEF-001's crash is worked around; these are genuine model corrections,
    # recorded per the task doc's non-negotiable rule: never change/ignore an
    # AI output in the evaluation dataset without recording the correction).
    CORRECTIONS = {
        "viqasha-01": {
            "correction": {"product": "Security", "human_required": True},
            "reason": (
                "Model returned Unclassified (confidence 0.4) for a clear unauthorized-"
                "account-access report phrased without her literal 'hacked/breach' "
                "trigger words. This suggests the classifier is keyword-matching rather "
                "than generalizing — a real account-compromise report should never fall "
                "through to the low-confidence fallback."
            ),
        },
        "viqasha-02": {
            "correction": {"product": "Financial", "human_required": True},
            "reason": (
                "Model returned Unclassified (confidence 0.4) for a naturally-phrased "
                "duplicate-billing complaint that avoided her exact 'refund/charged me' "
                "wording. Same generalization gap as viqasha-01."
            ),
        },
        "viqasha-04": {
            "correction": {"product": "POS", "human_required": False},
            "reason": (
                "REGRESSION: this case targets her own documented bug fix for the "
                "inflected form 'printing' (vs. base form 'print'). Model returned "
                "Unclassified (confidence 0.4), meaning the fix either regressed or "
                "never covered this exact phrasing. Flag to Viqasha directly — this is "
                "a repeat of a bug she already claimed to have fixed."
            ),
        },
        "viqasha-07": {
            "correction": {"product": "Destructive Action", "human_required": True},
            "reason": (
                "Model returned Unclassified (confidence 0.4, severity Medium) for a "
                "permanent customer-data-deletion request. This is the most severe "
                "miss in the set: a destructive/irreversible action landing in general "
                "support with Medium severity, instead of being flagged as high-risk, "
                "is a real safety gap, not just a routing inconvenience."
            ),
        },
    }

    for r in results:
        if not r.passed and r.case_id in CORRECTIONS:
            c = CORRECTIONS[r.case_id]
            record_correction(r, correction=c["correction"], reason=c["reason"], corrected_by="Esha")

    print("\n=== Viqasha (real endpoint, DEF-001 workaround tenant) ===")
    print(json.dumps(summarize(results), indent=2))

    write_evaluation_report(results, "evidence/vishaqa_evaluation_report.json")
    print("\nWrote evidence/vishaqa_evaluation_report.json (with corrections logged)")

    print("\n=== Individual case results ===")
    for r in results:
        status = "PASS" if r.passed else "FAIL"
        print(f"[{status}] {r.case_id}: {r.actual_output}")
        if r.correction:
            print(f"    -> CORRECTED to: {r.correction}")
