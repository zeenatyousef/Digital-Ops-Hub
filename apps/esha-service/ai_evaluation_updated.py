"""
AI evaluation framework — task doc section 2.4.

"Independently test Asma and Viqasha outputs with benchmark cases and record corrections."
Testing responsibilities table: "Known support and marketing benchmarks, confidence and
human correction." Evidence required: "Versioned evaluation report."

WHY THIS IS SCHEMA-AGNOSTIC:
As of writing this, we don't yet know the exact input/output shape of Asma's or
Viqasha's modules (waiting on answers from them — see the questions list). So this
framework doesn't hardcode field names. Instead:
  - A BenchmarkCase just holds a raw `input` dict and an `expected_output` dict.
  - You plug in a `predict_fn(input) -> actual_output dict` for whichever module
    you're testing (a real API/function call once you have it; a hand-typed stand-in
    for now if you want to dry-run the framework before their answers arrive).
  - `evaluate_case` compares expected vs actual using a `match_fn` you define per
    module, since "correct" means different things for a classifier vs generated text.

Once you get real answers from Asma/Viqasha, you mostly just need to:
  1. Fill in real BenchmarkCase entries (replace the PLACEHOLDER ones below).
  2. Write a real predict_fn that calls their actual module/API.
  3. Write a real match_fn that compares fields relevant to their actual output shape.
Nothing else in this file should need to change.
"""
import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional
from uuid import uuid4

import requests

RULE_VERSION = "ai-eval-v1.0"  # bump whenever benchmark cases or scoring logic change


# =========================================================
# Core data shapes
# =========================================================

@dataclass
class BenchmarkCase:
    id: str
    module: str            # "asma" | "viqasha"
    category: str          # "marketing" | "support" (per task doc's testing table)
    description: str       # human-readable: what this case is checking for
    input: Dict
    expected_output: Dict
    match_fn: Optional[Callable[[Dict, Dict], bool]] = None


@dataclass
class EvaluationResult:
    case_id: str
    module: str
    category: str
    passed: bool
    actual_output: Dict
    expected_output: Dict
    confidence: Optional[float] = None
    correction: Optional[str] = None       # what a human corrected the output to, if it failed
    correction_reason: Optional[str] = None
    corrected_by: Optional[str] = None
    evaluated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    rule_version: str = RULE_VERSION


# =========================================================
# Runner
# =========================================================

def evaluate_case(
    case: BenchmarkCase,
    predict_fn: Callable[[Dict], Dict],
    match_fn: Callable[[Dict, Dict], bool],
    confidence_fn: Optional[Callable[[Dict], float]] = None,
) -> EvaluationResult:
    """Run one benchmark case through predict_fn and score it with match_fn.
    confidence_fn is optional — pass one once Asma/Viqasha confirm whether
    a confidence score is attached to their output."""
    actual = predict_fn(case.input)
    effective_match_fn = case.match_fn or match_fn
    passed = effective_match_fn(case.expected_output, actual)
    confidence = confidence_fn(actual) if confidence_fn else None

    return EvaluationResult(
        case_id=case.id,
        module=case.module,
        category=case.category,
        passed=passed,
        actual_output=actual,
        expected_output=case.expected_output,
        confidence=confidence,
    )


def record_correction(result: EvaluationResult, correction: Dict, reason: str, corrected_by: str) -> EvaluationResult:
    """Call this for any failed case where a human overrides the AI's output.
    Non-negotiable rule from the task doc: never change an AI output in the
    evaluation dataset without recording the correction — this is how you do that."""
    result.correction = json.dumps(correction)
    result.correction_reason = reason
    result.corrected_by = corrected_by
    return result


def run_benchmark_suite(
    cases: List[BenchmarkCase],
    predict_fn: Callable[[Dict], Dict],
    match_fn: Callable[[Dict, Dict], bool],
    confidence_fn: Optional[Callable[[Dict], float]] = None,
) -> List[EvaluationResult]:
    return [evaluate_case(c, predict_fn, match_fn, confidence_fn) for c in cases]


def summarize(results: List[EvaluationResult]) -> Dict:
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    corrected = sum(1 for r in results if r.correction is not None)
    by_category: Dict[str, Dict[str, int]] = {}
    for r in results:
        bucket = by_category.setdefault(r.category, {"total": 0, "passed": 0})
        bucket["total"] += 1
        bucket["passed"] += int(r.passed)

    return {
        "total_cases": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": round(passed / total, 3) if total else None,
        "corrections_logged": corrected,
        "by_category": by_category,
        "rule_version": RULE_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def write_evaluation_report(results: List[EvaluationResult], path: str) -> None:
    """Writes the versioned evaluation report the task doc requires as evidence
    for days 14-16. Human-readable JSON — swap for HTML/Markdown later if you
    want something more presentable for the handover package."""
    report = {
        "summary": summarize(results),
        "results": [asdict(r) for r in results],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)


# =========================================================
# PLACEHOLDER benchmark cases and match functions
# Replace these once you get real answers from Asma and Viqasha.
# Kept here so the framework is runnable/testable right now.
# =========================================================

VIQASHA_PLACEHOLDER_CASES = [
    # =========================================================
    # REAL cases against Viqasha's actual /support/classify service.
    #
    # INDEPENDENCE NOTE: these messages are deliberately written from scratch,
    # NOT copied or lightly reworded from her guardrail keyword lists in
    # apps/vishaqa-service/main.py. The task doc requires INDEPENDENT testing —
    # if our benchmark cases used her exact trigger words, we'd only be
    # confirming her code matches her own keyword list, not verifying it
    # handles real-world phrasing correctly. Some cases below intentionally
    # avoid her literal trigger words to test whether the classifier
    # generalizes, and some are edge cases / near-misses to probe boundaries.
    # =========================================================

    BenchmarkCase(
        id=str(uuid4()), module="viqasha", category="support",
        description="Clear account breach report, phrased without her exact 'hacked/breach' combos",
        input={"message": "Someone I don't recognize logged into my account and changed my settings."},
        expected_output={"product": "Security", "human_required": True},
    ),
    BenchmarkCase(
        id=str(uuid4()), module="viqasha", category="support",
        description="Billing complaint phrased naturally, not using her exact 'refund/charged me' words",
        input={"message": "I noticed I was billed for two subscriptions this month, only one should exist."},
        expected_output={"product": "Financial", "human_required": True},
    ),
    BenchmarkCase(
        id=str(uuid4()), module="viqasha", category="support",
        description="FBR invoice failing to submit — should route to FBR product, not generic fallback",
        input={"message": "None of our invoices are going through to FBR today, they just fail."},
        expected_output={"product": "FBR Digital Invoicing", "human_required": False},
    ),
    BenchmarkCase(
        id=str(uuid4()), module="viqasha", category="support",
        description="POS printing issue using inflected form 'printing' — regression check for her documented bug fix",
        input={"message": "The receipts at the front counter are not printing anymore."},
        expected_output={"product": "POS", "human_required": False},
    ),
    BenchmarkCase(
        id=str(uuid4()), module="viqasha", category="support",
        description="Ambiguous 'checkout is down' — tests guardrail-vs-website overlap she flagged as a known limitation",
        input={"message": "Customers say checkout is completely down on the website right now."},
        expected_output={"product": "Production Outage", "human_required": True},
    ),
    BenchmarkCase(
        id=str(uuid4()), module="viqasha", category="support",
        description="Genuinely vague message with no product signal — should hit the low-confidence fallback, not guess",
        input={"message": "Something feels off today, can someone take a look when free?"},
        expected_output={"product": "Unclassified", "human_required": True},
    ),
    BenchmarkCase(
        id=str(uuid4()), module="viqasha", category="support",
        description="Data-deletion request phrased conversationally, not using her literal 'delete/wipe data' combo",
        input={"message": "Can you please remove all our old customer records from the system permanently?"},
        expected_output={"product": "Destructive Action", "human_required": True},
    ),
    BenchmarkCase(
        id=str(uuid4()), module="viqasha", category="support",
        description="Simple how-to question, should be low severity and NOT require a human",
        input={"message": "New here — how do I add a second cashier to the POS system?"},
        expected_output={"product": "POS", "human_required": False},
    ),
]

ASMA_PLACEHOLDER_CASES = [
    BenchmarkCase(
        id=str(uuid4()),
        module="asma",
        category="marketing",
        description="PLACEHOLDER: still waiting on Asma's real output schema for content drafts",
        input={"caption": "This deal is 100% risk-free and guaranteed, don't miss out."},
        expected_output={"flagged": True, "reason_contains": "prohibited"},
    ),
]


VIQASHA_API_URL = os.getenv("VIQASHA_API_URL", "http://localhost:8001")  # confirmed with Viqasha


VIQASHA_TEST_TENANT_ID = "d5de8b4d-b089-4d4e-9283-fd952f8df783"  # confirmed real seeded tenant, from her README


def viqasha_predict_fn(input_data: Dict) -> Dict:
    """Calls Viqasha's REAL /support/classify endpoint over HTTP — this is the
    actual integration, not a local reimplementation of her rules. Testing a
    local copy of her logic would only prove the copy is self-consistent, not
    that her deployed service behaves correctly."""
    payload = {
        "tenant_id": input_data.get("tenant_id", VIQASHA_TEST_TENANT_ID),
        "message": input_data["message"],
    }
    try:
        resp = requests.post(f"{VIQASHA_API_URL}/support/classify", json=payload, timeout=10.0)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        # Service unreachable OR responding with an error status (e.g. 500).
        # `str(e)` alone (the old behaviour) only says "500 Server Error" with
        # no body, which isn't enough to tell a connection problem apart from
        # a real bug in her handler. Capture the response body too — if her
        # endpoint is running FastAPI with default settings, a 500 body often
        # contains the actual exception/traceback, which is what you need to
        # report back to Viqasha (or fix, if it's on your side).
        error_detail = str(e)
        if e.response is not None:
            try:
                error_detail = f"{e} | response body: {e.response.text[:2000]}"
            except Exception:
                pass
        return {"_error": error_detail}


def viqasha_match_fn(expected: Dict, actual: Dict) -> bool:
    if "_error" in actual:
        return False
    # Match on product (primary classification) and human_required (the
    # safety-critical field — a wrong product with correct human_required
    # is a smaller problem than a missed guardrail, but both matter, so we
    # require both to agree for a full pass).
    return (
        actual.get("product") == expected.get("product")
        and actual.get("human_required") == expected.get("human_required")
    )


def placeholder_predict_fn(input_data: Dict) -> Dict:
    """Stand-in so this file can run end-to-end before real integration exists.
    DELETE this and replace with a real call to Asma's/Viqasha's actual
    module/API once you have it."""
    return {"category": "unknown", "priority": "unknown", "flagged": False, "reason_contains": ""}


def placeholder_match_fn(expected: Dict, actual: Dict) -> bool:
    """Naive placeholder matcher — replace with real field comparisons once
    you know the real output shape."""
    return all(actual.get(k) == v for k, v in expected.items() if k in actual)


if __name__ == "__main__":
    # Viqasha's cases now call her REAL service. This will show connection
    # errors (not wrong answers) until Zeenat wires up the gateway route --
    # that's the same blocker documented in Asma's esha_client.py, and it's
    # expected until that routing exists. Once it's wired, real predictions
    # will come back and can be scored properly.
    viqasha_results = run_benchmark_suite(VIQASHA_PLACEHOLDER_CASES, viqasha_predict_fn, viqasha_match_fn)
    print("=== Viqasha (real endpoint, may show connection errors until gateway is wired) ===")
    print(json.dumps(summarize(viqasha_results), indent=2))

    # Asma's cases are still on the old placeholder fn, pending her real schema.
    asma_results = run_benchmark_suite(ASMA_PLACEHOLDER_CASES, placeholder_predict_fn, placeholder_match_fn)
    print("\n=== Asma (still placeholder, pending real schema from her) ===")
    print(json.dumps(summarize(asma_results), indent=2))

    write_evaluation_report(viqasha_results + asma_results, "evidence/ai_evaluation_report.json")
    print("\nWrote evidence/ai_evaluation_report.json")
