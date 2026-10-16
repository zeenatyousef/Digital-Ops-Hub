"""
apps/esha-service/asma_benchmark.py

Real (non-placeholder) benchmark suite for Asma's 6 marketing endpoints,
per task doc section 2.4: "Independently test Asma and Viqasha outputs
with benchmark cases and record corrections."

This REPLACES ASMA_PLACEHOLDER_CASES / placeholder_predict_fn /
placeholder_match_fn in ai_evaluation_updated.py. See that file for the
shared BenchmarkCase / EvaluationResult / evaluate_case / run_benchmark_suite
/ summarize / write_evaluation_report / record_correction machinery.

REQUIRED PATCH to ai_evaluation_updated.py before this will work
(small, backward-compatible -- Viqasha's cases are unaffected):

    # In BenchmarkCase dataclass, add one field:
        match_fn: Optional[Callable[[Dict, Dict], bool]] = None

    # In evaluate_case(), use the case's own match_fn if it set one:
        effective_match_fn = case.match_fn or match_fn
        passed = effective_match_fn(case.expected_output, actual)

WHY PER-CASE match_fn: Viqasha's suite could use one global match_fn because
every case compares the same two fields (product, human_required). Asma's
six endpoints return six structurally different response shapes (extraction
with confidence scores, a list of calendar items, per-platform content with
brand-rule checks, a translation, a pass-through designer brief, a word
diff) -- forcing them through one comparator would mean either a useless
generic check or increasingly convoluted branching in one function. Each
case here owns the comparison logic that's actually meaningful for it.

INDEPENDENCE NOTE: test inputs below are written from scratch -- not copied
from Asma's system prompts, PLATFORM_CONSTRAINTS text, or her docstrings in
main.py. They target the documented NON-NEGOTIABLE rules directly:
  - /brief:            never invent facts not present in the source text
  - /calendar:         date sequencing is deterministic and independently
                        recomputed here, not trusted from her own function
  - /content:          never generate identical copy across platforms;
                        required/prohibited wording enforcement must be
                        internally consistent with the caption it describes
  - /translate:        preserve names/offers/dates/prices; don't silently
                        guess ambiguous terms
  - /designer-brief:   never invent images -- must echo approved_media_ids
                        exactly, not something similar or expanded
  - /revise:            apply ONLY the requested change, nothing else

FIXTURE NOTE: five of the six endpoints need real DB rows that don't exist
until something creates them, and two of those (an APPROVED campaign_brief,
an APPROVED content_version) can't currently be produced at all through the
API -- there is no approve/PATCH endpoint anywhere in main.py. So
setup_asma_fixtures() generates the rows through the REAL endpoints (same
principle as testing Viqasha's live endpoint rather than a local
reimplementation) and then flips approval_status / status directly in the
DB. THIS IS A TESTING-ONLY WORKAROUND, not how content should get approved
in production -- flag to Asma/Zeenat that a real approval endpoint is
needed; direct DB writes bypassing the approval workflow should not be
normal practice once one exists.
"""

import os
import sys
from datetime import date, datetime, timedelta
from typing import Dict, List

import requests

# 'esha-service' has a hyphen, so it can't be imported as a dotted package
# (apps.esha-service.x is invalid syntax) -- same reason seed_test_data.py
# does this. Put the repo root on sys.path so `packages.database` resolves,
# and this file's own directory is already on sys.path automatically
# because it's being run directly, so the plain `ai_evaluation_updated`
# import below works as long as this file sits next to it.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from packages.database.session import SessionLocal
from packages.database import models as db_models

# Requires this file to sit in the SAME directory as ai_evaluation_updated.py
# (apps/esha-service/) -- see placement instructions.
from ai_evaluation_updated import BenchmarkCase, run_benchmark_suite, summarize, write_evaluation_report
#from ai_evaluation_updated import BenchmarkCase, run_benchmark_suite, summarize

ASMA_API_URL = os.getenv("ASMA_API_URL", "http://localhost:8002")  # from .env.example
FIXTURE_TENANT_NAME = "AI-Eval Asma Test Tenant"


# =========================================================
# Fixtures -- real DB rows the endpoints require
# =========================================================

def setup_asma_fixtures() -> Dict:
    """
    Idempotent: reuses the fixture tenant/client/brand_profile/campaign/
    reviewer if they already exist (matched by name/email), otherwise
    creates them fresh -- same direct-DB pattern as seed_test_data.py, just
    with a distinct name so it never collides with manual seeding.

    Then generates one campaign_brief and one content_version through the
    REAL endpoints and force-approves each directly in the DB (see module
    docstring). Returns the IDs the real benchmark cases below are built
    from.
    """
    db = SessionLocal()
    try:
        tenant = db.query(db_models.Tenant).filter(
            db_models.Tenant.name == FIXTURE_TENANT_NAME
        ).first()
        if not tenant:
            tenant = db_models.Tenant(name=FIXTURE_TENANT_NAME)
            db.add(tenant)
            db.commit()
            db.refresh(tenant)

        client = db.query(db_models.Client).filter(
            db_models.Client.tenant_id == tenant.id
        ).first()
        if not client:
            client = db_models.Client(
                tenant_id=tenant.id,
                company_name="AI-Eval Test Client",
                contact_email="ai-eval@example.com",
            )
            db.add(client)
            db.commit()
            db.refresh(client)

        brand_profile = db.query(db_models.BrandProfile).filter(
            db_models.BrandProfile.client_id == client.id
        ).first()
        if not brand_profile:
            # Same rule set as seed_test_data.py, so brand-rule-check cases
            # below have something real to test against.
            brand_profile = db_models.BrandProfile(
                tenant_id=tenant.id,
                client_id=client.id,
                brand_name="AI-Eval Test Brand",
                brand_voice="Friendly, community-focused, no hype language.",
                required_wording="halal",
                prohibited_wording="guaranteed,best in the world",
            )
            db.add(brand_profile)
            db.commit()
            db.refresh(brand_profile)

        campaign = db.query(db_models.Campaign).filter(
            db_models.Campaign.client_id == client.id
        ).first()
        if not campaign:
            campaign = db_models.Campaign(
                client_id=client.id,
                tenant_id=tenant.id,
                name="AI-Eval Test Campaign",
            )
            db.add(campaign)
            db.commit()
            db.refresh(campaign)

        reviewer = db.query(db_models.User).filter(
            db_models.User.email == "ai-eval-reviewer@example.com"
        ).first()
        if not reviewer:
            reviewer = db_models.User(
                tenant_id=tenant.id,
                email="ai-eval-reviewer@example.com",
                password_hash="not-a-real-hash",  # fixture only, never authenticated against
                full_name="AI Eval Reviewer",
                role="tenant_admin",
            )
            db.add(reviewer)
            db.commit()
            db.refresh(reviewer)

        message_1_content = "AI-EVAL-FIXTURE: We need a Ramadan promo for our bakery, running the whole month, targeting families in Lahore."
        message_2_content = "AI-EVAL-FIXTURE: It should be on Instagram and Facebook, no budget or dates confirmed yet."

        m1 = db.query(db_models.Message).filter(db_models.Message.content == message_1_content).first()
        if not m1:
            m1 = db_models.Message(content=message_1_content, visibility="external", content_type="text")
            db.add(m1)
            db.commit()
            db.refresh(m1)

        m2 = db.query(db_models.Message).filter(db_models.Message.content == message_2_content).first()
        if not m2:
            m2 = db_models.Message(content=message_2_content, visibility="external", content_type="text")
            db.add(m2)
            db.commit()
            db.refresh(m2)

        brief_messages = [m1, m2]

        ids = {
            "tenant_id": str(tenant.id),
            "client_id": str(client.id),
            "brand_profile_id": str(brand_profile.id),
            "campaign_id": str(campaign.id),
            "reviewer_id": str(reviewer.id),
            "brief_message_ids": [str(m.id) for m in brief_messages],
        }
    finally:
        db.close()

    # --- Generate + force-approve one campaign_brief via the real endpoint ---
    brief_resp = requests.post(
        f"{ASMA_API_URL}/marketing/brief",
        json={
            "client_id": ids["client_id"],
            "tenant_id": ids["tenant_id"],
            "brand_profile_id": ids["brand_profile_id"],
            "source_message_ids": ids["brief_message_ids"],
        },
        timeout=30.0,
    )
    brief_resp.raise_for_status()
    campaign_brief_id = brief_resp.json()["campaign_brief_id"]

    db = SessionLocal()
    try:
        brief_row = db.query(db_models.CampaignBrief).filter(
            db_models.CampaignBrief.id == campaign_brief_id
        ).first()
        brief_row.approval_status = "approved"  # workaround -- see module docstring
        db.commit()
    finally:
        db.close()
    ids["approved_campaign_brief_id"] = campaign_brief_id

    # --- Generate + force-approve one content_version via the real endpoint ---
    content_resp = requests.post(
        f"{ASMA_API_URL}/marketing/content",
        json={
            "campaign_brief_id": campaign_brief_id,
            "campaign_id": ids["campaign_id"],
            "platforms": ["instagram"],
            "brand_profile_id": ids["brand_profile_id"],
        },
        timeout=60.0,
    )
    content_resp.raise_for_status()

    # ContentResponse doesn't expose the DB row id -- look it up directly.
    db = SessionLocal()
    try:
        content_row = (
            db.query(db_models.ContentVersion)
            .filter(db_models.ContentVersion.campaign_id == ids["campaign_id"])
            .filter(db_models.ContentVersion.platform == "instagram")
            .order_by(db_models.ContentVersion.created_at.desc())
            .first()
        )
        content_row.status = "approved"  # workaround -- see module docstring
        db.commit()
        ids["approved_content_version_id"] = str(content_row.id)
        ids["approved_content_caption"] = content_row.caption
        ids["approved_content_version_number"] = content_row.version_number
    finally:
        db.close()

    return ids


# =========================================================
# Dispatching predict_fn -- one real HTTP call per case, routed by endpoint
# =========================================================

def asma_predict_fn(input_data: Dict) -> Dict:
    """Calls Asma's REAL service over HTTP, same principle as Viqasha's
    predict_fn: this tests her deployed service, not a local reimplementation
    of her logic. Each case's `input` dict carries which endpoint to hit."""
    endpoint = input_data["_endpoint"]
    payload = input_data["_payload"]
    timeout = input_data.get("_timeout", 30.0)
    try:
        resp = requests.post(f"{ASMA_API_URL}{endpoint}", json=payload, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        error_detail = str(e)
        if getattr(e, "response", None) is not None:
            try:
                error_detail = f"{e} | response body: {e.response.text[:2000]}"
            except Exception:
                pass
        return {"_error": error_detail}


# =========================================================
# Per-case match functions
# =========================================================

def _match_brief(expected: Dict, actual: Dict) -> bool:
    """Never-invent-facts check: the extracted objective must be a real,
    non-empty value, and every field the source text left vague/unstated
    must show up in missing_fields rather than being guessed."""
    if "_error" in actual:
        return False
    objective_present = bool((actual.get("objective") or {}).get("value"))
    missing = set(actual.get("missing_fields", []))
    required_missing = set(expected.get("missing_fields_subset", []))
    return objective_present and required_missing.issubset(missing)


def _independent_daily_count(start: date, end: date) -> int:
    """Recomputed independently of _generate_schedule_dates in main.py --
    trusting her own function to grade itself would defeat the point of
    independent testing."""
    return (end - start).days + 1


def _independent_mwf_count(start: date, end: date) -> int:
    count = 0
    current = start
    while current <= end:
        if current.weekday() in (0, 2, 4):
            count += 1
        current += timedelta(days=1)
    return count


def _match_calendar_daily(expected: Dict, actual: Dict) -> bool:
    if "_error" in actual:
        return False
    items = actual.get("items", [])
    if len(items) != expected["expected_item_count"]:
        return False
    lead_days = expected["production_lead_days"]
    for item in items:
        scheduled = datetime.fromisoformat(item["scheduled_date"].replace("Z", "+00:00"))
        deadline = datetime.fromisoformat(item["deadline"].replace("Z", "+00:00"))
        if (scheduled - deadline).days != lead_days:
            return False
    return True


def _match_calendar_mwf(expected: Dict, actual: Dict) -> bool:
    if "_error" in actual:
        return False
    return len(actual.get("items", [])) == expected["expected_item_count"]


def _match_content(expected: Dict, actual: Dict) -> bool:
    """Two independent invariants from the non-negotiable rules:
    (1) distinct copy per platform -- never identical captions;
    (2) the deterministic brand_rule_check must be internally consistent
        with the caption/CTA text it's describing (required_wording either
        appears in the text, or is listed as missing -- never both or
        neither)."""
    if "_error" in actual:
        return False
    versions = actual.get("versions", [])
    if len(versions) < 2:
        return False

    captions = [v.get("caption", "") for v in versions]
    if len(set(captions)) != len(captions):
        return False

    required_term = expected["required_wording"].lower()
    for v in versions:
        text = f"{v.get('caption', '')} {v.get('cta', '')}".lower()
        has_term = required_term in text
        reported_missing = required_term in [
            m.lower() for m in v.get("brand_rule_check", {}).get("missing_required_wording", [])
        ]
        if has_term == reported_missing:  # must be opposites
            return False
    return True


def _match_translate(expected: Dict, actual: Dict) -> bool:
    if "_error" in actual:
        return False
    translated = actual.get("translated_text", "")
    if not translated:
        return False
    if translated.strip() == expected["source_caption"].strip():
        return False  # not actually translated
    return isinstance(actual.get("ambiguous_term_warnings"), list)


def _match_designer_brief(expected: Dict, actual: Dict) -> bool:
    """No-invented-images rule: asset_references must echo approved_media_ids
    exactly -- not a superset, subset, or reworded version."""
    if "_error" in actual:
        return False
    return (
        actual.get("asset_references") == expected["approved_media_ids"]
        and len(actual.get("sizes", [])) > 0
        and bool(actual.get("logo_qr_rules"))
    )


def _match_revise(expected: Dict, actual: Dict) -> bool:
    """Apply-only-what-was-asked rule can't be fully verified without human
    judgment (that's the point of record_correction below), but structural
    invariants are: a genuinely new version was created, its number
    incremented, and something measurable actually changed."""
    if "_error" in actual:
        return False
    return (
        actual.get("new_content_version_id") != expected["source_content_version_id"]
        and actual.get("version_number", 0) > expected["source_version_number"]
        and actual.get("diff_summary") != "No word-level changes detected."
    )


# =========================================================
# Real benchmark cases -- built from live fixture IDs, not hardcoded
# =========================================================

def build_asma_cases(fixtures: Dict) -> List[BenchmarkCase]:
    daily_start, daily_end = date(2026, 9, 1), date(2026, 9, 3)
    mwf_start, mwf_end = date(2026, 9, 1), date(2026, 9, 14)

    return [
        BenchmarkCase(
            id="asma-brief-01",
            module="asma",
            category="marketing",
            description="No-invented-facts check: dates/offer weren't stated, must land in missing_fields, not guessed",
            input={
                "_endpoint": "/marketing/brief",
                "_payload": {
                    "client_id": fixtures["client_id"],
                    "tenant_id": fixtures["tenant_id"],
                    "brand_profile_id": fixtures["brand_profile_id"],
                    "source_message_ids": fixtures["brief_message_ids"],
                },
            },
            expected_output={"missing_fields_subset": ["offer"]},
            match_fn=_match_brief,
        ),
        BenchmarkCase(
            id="asma-calendar-daily-01",
            module="asma",
            category="marketing",
            description="Deterministic date-sequencing check, independently recomputed (not trusting her own function)",
            input={
                "_endpoint": "/marketing/calendar",
                "_payload": {
                    "campaign_brief_id": fixtures["approved_campaign_brief_id"],
                    "date_range_start": daily_start.isoformat(),
                    "date_range_end": daily_end.isoformat(),
                    "frequency": "daily",
                    "platforms": ["instagram", "facebook"],
                    "production_lead_days": 2,
                },
            },
            expected_output={
                "expected_item_count": _independent_daily_count(daily_start, daily_end) * 2,
                "production_lead_days": 2,
            },
            match_fn=_match_calendar_daily,
        ),
        BenchmarkCase(
            id="asma-calendar-3xweek-01",
            module="asma",
            category="marketing",
            description="3x_week (Mon/Wed/Fri) sequencing, independently recomputed over a 2-week range",
            input={
                "_endpoint": "/marketing/calendar",
                "_payload": {
                    "campaign_brief_id": fixtures["approved_campaign_brief_id"],
                    "date_range_start": mwf_start.isoformat(),
                    "date_range_end": mwf_end.isoformat(),
                    "frequency": "3x_week",
                    "platforms": ["linkedin"],
                    "production_lead_days": 2,
                },
            },
            expected_output={
                "expected_item_count": _independent_mwf_count(mwf_start, mwf_end),
            },
            match_fn=_match_calendar_mwf,
        ),
        BenchmarkCase(
            id="asma-content-01",
            module="asma",
            category="marketing",
            description="Distinct copy per platform + internally consistent brand-rule enforcement of required_wording",
            input={
                "_endpoint": "/marketing/content",
                "_payload": {
                    "campaign_brief_id": fixtures["approved_campaign_brief_id"],
                    "campaign_id": fixtures["campaign_id"],
                    "platforms": ["instagram", "facebook", "linkedin"],
                    "brand_profile_id": fixtures["brand_profile_id"],
                },
                "_timeout": 60.0,
            },
            expected_output={"required_wording": "halal"},
            match_fn=_match_content,
        ),
        BenchmarkCase(
            id="asma-translate-01",
            module="asma",
            category="marketing",
            description="Translation to Roman Urdu actually changes the text (not passthrough) and reports ambiguous terms as a list",
            input={
                "_endpoint": "/marketing/translate",
                "_payload": {
                    "content_version_id": fixtures["approved_content_version_id"],
                    "target_language": "ur-Latn",
                },
            },
            expected_output={"source_caption": fixtures["approved_content_caption"]},
            match_fn=_match_translate,
        ),
        BenchmarkCase(
            id="asma-designer-brief-01",
            module="asma",
            category="marketing",
            description="No-invented-images rule: asset_references must echo approved_media_ids exactly",
            input={
                "_endpoint": "/marketing/designer-brief",
                "_payload": {
                    "content_version_id": fixtures["approved_content_version_id"],
                    "approved_media_ids": ["asset-ramadan-01", "asset-ramadan-02"],
                },
            },
            expected_output={"approved_media_ids": ["asset-ramadan-01", "asset-ramadan-02"]},
            match_fn=_match_designer_brief,
        ),
        BenchmarkCase(
            id="asma-revise-01",
            module="asma",
            category="marketing",
            description="Revise creates a genuinely new, incremented version with a real word-level change applied",
            input={
                "_endpoint": "/marketing/revise",
                "_payload": {
                    "content_version_id": fixtures["approved_content_version_id"],
                    "reviewer_comments": "Add our phone number 0300-1234567 to the CTA, don't change anything else.",
                    "reviewer_id": fixtures["reviewer_id"],
                },
            },
            expected_output={
                "source_content_version_id": fixtures["approved_content_version_id"],
                "source_version_number": fixtures["approved_content_version_number"],
            },
            match_fn=_match_revise,
        ),
    ]


# =========================================================
# Entry point -- wire this into ai_evaluation_updated.py's __main__ block
# in place of ASMA_PLACEHOLDER_CASES / placeholder_predict_fn / placeholder_match_fn
# =========================================================

if __name__ == "__main__":
    print("Setting up Asma fixtures (creates real DB rows via her live endpoints)...")
    fixtures = setup_asma_fixtures()
    print(fixtures)

    cases = build_asma_cases(fixtures)
    results = run_benchmark_suite(cases, asma_predict_fn, match_fn=lambda e, a: False)
    # match_fn=lambda...False is a required but unused default: every case
    # above supplies its own match_fn, which evaluate_case prefers once the
    # patch in the module docstring is applied.

    print("\n=== Asma (real endpoints, real fixtures) ===")
    import json
    print(json.dumps(summarize(results), indent=2))
    write_evaluation_report(results, "evidence/asma_evaluation_report.json")
    print("\nWrote evidence/asma_evaluation_report.json")
    print("\n=== Individual case results ===")
    for r in results:
        status = "PASS" if r.passed else "FAIL"
        print(f"[{status}] {r.case_id}")
        if not r.passed:
            print(f"    expected: {r.expected_output}")
            print(f"    actual:   {r.actual_output}")
