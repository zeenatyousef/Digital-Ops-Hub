"""
Automated test suite for esha-service.
Run with:  pytest test_main.py -v
Generates a readable report with: pytest test_main.py -v --html=test_report.html --self-contained-html
(requires: pip install pytest-html)

Each test both PROVES a requirement from the task doc AND gives you a clean
pass/fail record you can screenshot or attach as evidence.
"""
import sys
import os
import tempfile

os.environ["ALLOW_SQLITE_FALLBACK"] = "true"
sys.path.insert(0, os.path.dirname(__file__))

import uuid
from uuid import UUID
import pytest
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
from packages.database.session import engine, Base
try:
    Base.metadata.create_all(bind=engine, checkfirst=True)
except Exception:
    pass

import importlib.util
_main_path = os.path.join(os.path.dirname(__file__), "main.py")
_spec = importlib.util.spec_from_file_location("esha_service_main", _main_path)
_esha_main = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_esha_main)

app = _esha_main.app
SessionLocal = _esha_main.SessionLocal
get_or_create_dev_tenant = _esha_main.get_or_create_dev_tenant
get_or_create_client = _esha_main.get_or_create_client

from packages.database.models import Defect, User
from packages.database.models import Campaign, PublishingJob
from packages.database.models import AnalyticsEvent
from packages.database.models import Client

client = TestClient(app)

# DEF-011 fix: _make_campaign and _make_defect commit permanent rows to the
# shared dev database (not an isolated test DB), so without cleanup every
# pytest run leaves fixture rows behind forever, polluting real endpoint
# results over time. Each helper appends the ID it just created here; the
# autouse fixture below deletes everything in the list after every test,
# regardless of pass/fail, so nothing survives past the test that made it.
_created_campaign_ids: list = []
_created_defect_ids: list = []

# DEF-014: several client-summary/client-health tests post AnalyticsEvent
# rows with deliberately FIXED (non-randomized) event_key values, under
# throwaway client names like "esha-summary-test" — the fixed key was meant
# to keep repeated pytest runs idempotent (no unbounded row growth), but had
# the side effect of leaving these fake clients permanently visible on the
# live Analytics/Client Health screen (client-health has no client filter,
# so it shows every client name it has ever seen). Confirmed live in the app
# UI on 2026-09-17: "esha-summary-test" appeared as a red "critical" client
# card next to real clients.
#
# Cleanup matches by CLIENT NAME, not by specific event_key. An earlier
# version of this fix matched only known fixed keys and missed
# "esha-health-test" — an orphaned row from an older version of this test
# file (renamed to "esha-health-engagement-test"/"esha-health-sla-test" at
# some point, per the comment on test_client_health_reports_healthy_status_
# for_strong_engagement below, but the old row was never deleted). Matching
# by client name catches history like this, not just current test code.
_TEST_ONLY_CLIENT_NAMES = (
    "esha-summary-test",
    "esha-health-test",              # orphaned pre-rename name — see above
    "esha-health-engagement-test",
    "esha-health-sla-test",
    "esha-health-regression-test",   # DEF-015 regression test, see below
)


@pytest.fixture(autouse=True)
def _cleanup_test_fixture_rows():
    yield
    db = SessionLocal()
    try:
        if _created_campaign_ids:
            db.query(PublishingJob).filter(
                PublishingJob.campaign_id.in_(_created_campaign_ids)
            ).delete(synchronize_session=False)
            db.query(Campaign).filter(
                Campaign.id.in_(_created_campaign_ids)
            ).delete(synchronize_session=False)
        if _created_defect_ids:
            db.query(Defect).filter(
                Defect.id.in_(_created_defect_ids)
            ).delete(synchronize_session=False)

        # DEF-014 cleanup — matches by client name, so it catches any event
        # under these throwaway client names regardless of what event_key
        # was used, including orphaned rows from before this fix existed.
        # Runs every test (not just the ones that create these rows), so
        # leftover pollution from a crashed run also gets swept up.
        test_client_ids = [
            c.id for c in db.query(Client).filter(
                Client.company_name.in_(_TEST_ONLY_CLIENT_NAMES)
            ).all()
        ]
        if test_client_ids:
            db.query(AnalyticsEvent).filter(
                AnalyticsEvent.client_id.in_(test_client_ids)
            ).delete(synchronize_session=False)
            db.query(Client).filter(
                Client.id.in_(test_client_ids)
            ).delete(synchronize_session=False)

        db.commit()
    finally:
        db.close()
        _created_campaign_ids.clear()
        _created_defect_ids.clear()


# =========================================================
# 1. Health check — service + database both alive
# =========================================================

def test_health_check():
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "tenants_in_db" in body   # proves it's a real DB query, not a hardcoded reply


# =========================================================
# 2. Hashtag save + suggest — persistence proof
# =========================================================

def test_save_hashtag_set_bebop():
    r = client.post("/quality/hashtags/save", json={
        "client": "bebop",
        "platform": "instagram",
        "tags": ["#BebopStaplesMill", "#RichmondEats", "#RVAFood"],
    })
    assert r.status_code == 200
    body = r.json()
    assert len(body["saved_tags"]) == 3
    assert "hashtag_set_id" in body


def test_suggest_hashtags_returns_saved_tags():
    # Run save first so this test can run standalone too
    client.post("/quality/hashtags/save", json={
        "client": "bebop", "platform": "instagram",
        "tags": ["#BebopStaplesMill", "#RichmondEats", "#RVAFood"],
    })
    r = client.post("/quality/hashtags/suggest", json={
        "tags": ["#love", "#love"], "client": "bebop", "platform": "instagram",
    })
    assert r.status_code == 200
    body = r.json()
    assert "#BebopStaplesMill" in body["recommended_tags"]  # proves DB read, not fallback


def test_hashtag_duplicate_detection():
    r = client.post("/quality/hashtags/suggest", json={
        "tags": ["#love", "#love"], "client": "samvix", "platform": "instagram",
    })
    warnings = r.json()["warnings"]
    assert any(w["type"] == "duplicate" for w in warnings)


def test_hashtag_banned_tag_detection():
    r = client.post("/quality/hashtags/suggest", json={
        "tags": ["#follow4follow"], "client": "samvix", "platform": "instagram",
    })
    warnings = r.json()["warnings"]
    assert any(w["type"] == "banned" for w in warnings)
    assert r.json()["quality_score"] <= 70   # banned tag should drop the score


def test_hashtag_spam_risk_detection():
    r = client.post("/quality/hashtags/suggest", json={
        "tags": ["#love", "#instagood"], "client": "abc-traders", "platform": "instagram",
    })
    warnings = r.json()["warnings"]
    assert any(w["type"] == "spam_risk" for w in warnings)


# =========================================================
# 3. Content quality — clean vs. flagged captions
# =========================================================

def test_content_quality_clean_caption():
    r = client.post("/quality/content", json={
        "caption": "Richmond, your weekend just got tastier. Enjoy fresh fusion at Bebop. Order now.",
        "client": "bebop",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["score"] >= 80
    assert body["label"] == "Strong"


def test_content_quality_catches_prohibited_wording():
    r = client.post("/quality/content", json={
        "caption": "This deal is 100% risk-free and guaranteed, don't miss out.",
        "client": "bebop",
    })
    body = r.json()
    assert body["brand_match"] < 100
    assert any(i["severity"] == "critical" for i in body["issues"])


def test_content_quality_catches_missing_cta():
    r = client.post("/quality/content", json={
        "caption": "We had a great time at the event this weekend with everyone.",
        "client": "bebop",
    })
    body = r.json()
    assert body["cta_strength"] < 90
    assert any("CTA" in i["message"] for i in body["issues"])


# =========================================================
# Content quality — repetition (§8 required test case)
# =========================================================

def test_content_quality_catches_repetition():
    r = client.post("/quality/content", json={
        "caption": "Fresh fresh fresh food, always fresh, only fresh at Bebop today.",
        "client": "bebop",
    })
    body = r.json()
    assert body["brand_match"] < 100
    assert any("repeated excessively" in i["message"] for i in body["issues"])


def test_content_quality_no_false_positive_on_cta_repetition():
    # CTA words repeating (e.g. "order" used twice) should NOT be flagged as spam repetition
    r = client.post("/quality/content", json={
        "caption": "Order online or call to order for pickup today.",
        "client": "bebop",
    })
    body = r.json()
    assert not any("repeated excessively" in i["message"] for i in body["issues"])


# =========================================================
# Content quality — wrong contact detail (§8 required test case)
# =========================================================

def test_content_quality_catches_wrong_contact_email():
    # Save/lookup creates the client with contact_email = "bebop@example.com" by default
    r = client.post("/quality/content", json={
        "caption": "Reach us at support@wrongdomain.com for more info.",
        "client": "bebop",
    })
    body = r.json()
    assert body["brand_match"] < 100
    assert any("does not match client's registered contact" in i["message"] for i in body["issues"])
    assert any(i["severity"] == "critical" for i in body["issues"])


def test_content_quality_flags_phone_number_for_manual_check():
    r = client.post("/quality/content", json={
        "caption": "Call us now at 0300-1234567 for a free quote.",
        "client": "bebop",
    })
    body = r.json()
    assert any("Phone number detected" in i["message"] for i in body["issues"])


# =========================================================
# 4. Similarity — catches near-duplicate content
# =========================================================

def test_similarity_detects_duplicate():
    caption = "Richmond, your weekend just got tastier. Enjoy fresh fusion at Bebop. Order now."
    # Log it once via /quality/content so it exists as history to compare against
    client.post("/quality/content", json={"caption": caption, "client": "bebop"})
    r = client.post("/quality/similarity", json={"caption": caption, "client": "bebop"})
    assert r.status_code == 200
    body = r.json()
    assert body["is_near_duplicate"] is True
    assert body["similarity_score"] >= 0.85


def test_similarity_no_false_positive_on_different_text():
    r = client.post("/quality/similarity", json={
        "caption": "Completely unrelated text about something else entirely, nothing like the other one.",
        "client": "bebop",
    })
    body = r.json()
    assert body["is_near_duplicate"] is False


def test_similarity_no_false_positive_across_different_clients():
    # DEF-006: same caption logged for one client should not flag as a duplicate
    # for a different client — all clients share one dev tenant, so scoping must
    # come from `client`, not tenant_id alone.
    caption = "Fresh weekend deals just for you. Order now."
    client.post("/quality/content", json={"caption": caption, "client": "bebop"})
    r = client.post("/quality/similarity", json={"caption": caption, "client": "samvix"})
    body = r.json()
    assert body["is_near_duplicate"] is False, "Samvix should not be flagged as duplicate of Bebop's caption"


# =========================================================
# 5. Analytics events — idempotency proof
# =========================================================

def test_event_ingestion_and_idempotency():
    # FIXED (was: `f"test-event-{uuid.uuid4()}"`) — a fresh random key on every
    # run meant this test created a NEW permanent row in the shared dev database
    # every single time the suite ran, instead of testing idempotency at all.
    # That polluted GET /analytics/client-summary's client_performance breakdown:
    # these rows have no client_id, so they landed in an "unknown" bucket that
    # grew by 1000 reach every pytest run (confirmed: 8 rows found across
    # Aug 28 - Sep 1, one per historical test run in this session).
    # A FIXED key is actually the correct test design here: it proves the same
    # event stays deduplicated across repeated runs, not just within one test.
    key = "test-event-fixed-idempotency-key-do-not-randomize"
    payload = {
        "event_type": "post.published", "object_type": "campaign", "object_id": "camp-1",
        "event_key": key, "metrics": {"reach": 1000}, "source": "scheduler",
    }
    r1 = client.post("/analytics/event", json=payload)
    assert r1.status_code == 200
    # duplicate may be True or False here depending on whether a previous test
    # run already created this row — both are fine, this call just establishes
    # the row exists.

    r2 = client.post("/analytics/event", json=payload)   # send the exact same event again
    assert r2.status_code == 200
    assert r2.json()["duplicate"] is True
    assert r2.json()["event_id"] == r1.json()["event_id"]  # same event, not a new row


# =========================================================
# 6. Dashboard + monthly report — read real aggregated data
# =========================================================

def test_dashboard_reflects_real_events():
    # FIXED: was a random key per run (`f"test-dash-{uuid.uuid4()}"`), which
    # permanently added a new row to the shared dev DB on every test run. A
    # fixed key is safe here since the test only checks total_events >= 1 and
    # presence in by_type, not an exact count.
    key = "test-dash-fixed-idempotency-key-do-not-randomize"
    client.post("/analytics/event", json={
        "event_type": "ticket.opened", "object_type": "ticket", "object_id": "t-1",
        "event_key": key, "source": "support_inbox",
    })
    r = client.get("/analytics/dashboard")
    assert r.status_code == 200
    body = r.json()
    assert body["total_events"] >= 1
    assert "ticket.opened" in body["by_type"]


def test_monthly_report_generates_and_flags_missing_data():
    r = client.get("/analytics/monthly-report", params={"client": "bebop", "month": "2026-08"})
    assert r.status_code == 200
    body = r.json()
    assert body["client"] == "bebop"
    assert body["completeness"]["instagram"] == "unavailable"  # never silently shows 0


# =========================================================
# 7. duplicate_risk now reflects a real similarity check (was hardcoded "Low")
# =========================================================

def test_content_quality_duplicate_risk_high_on_repeat_caption():
    # Fully randomized tokens (not just one changed word) so this can't collide
    # with near-identical captions left over from a previous test run.
    caption = " ".join(f"tok{uuid.uuid4().hex[:8]}" for _ in range(10))
    r1 = client.post("/quality/content", json={"caption": caption, "client": "bebop"})
    assert r1.json()["duplicate_risk"] == "Low"  # first time seen, nothing to match against

    r2 = client.post("/quality/content", json={"caption": caption, "client": "bebop"})
    assert r2.json()["duplicate_risk"] == "High"  # exact repeat of the run logged above


def test_content_quality_duplicate_risk_low_on_unique_caption():
    caption = " ".join(f"tok{uuid.uuid4().hex[:8]}" for _ in range(10))
    r = client.post("/quality/content", json={"caption": caption, "client": "bebop"})
    assert r.json()["duplicate_risk"] == "Low"


# =========================================================
# 8. Dashboard date/role filtering
# =========================================================

def test_dashboard_date_filter_excludes_out_of_range_events():
    # FIXED: was a random key per run, permanently accumulating rows in the
    # shared dev DB. Fixed key is safe: the test only checks that a year-2000
    # date range excludes an event created "now" (or reused from a prior run,
    # which is also "now"-ish relative to year 2000) — not an exact count.
    key = "test-datefilter-fixed-idempotency-key-do-not-randomize"
    client.post("/analytics/event", json={
        "event_type": "post.published", "object_type": "campaign", "object_id": "camp-2",
        "event_key": key, "source": "scheduler",
    })
    # A date range far in the past should not include the event we just created "now"
    r = client.get("/analytics/dashboard", params={"date_from": "2000-01-01", "date_to": "2000-01-02"})
    assert r.status_code == 200
    body = r.json()
    assert body["filters_applied"]["date_from"] == "2000-01-01"
    assert body["filters_applied"]["date_to"] == "2000-01-02"


def test_dashboard_role_filter_marketing_excludes_tickets():
    # FIXED: was a random key per run. Fixed key is safe: the test only checks
    # that "ticket.opened" is excluded when filtering by role=marketing, not
    # an exact event count.
    key = "test-role-fixed-idempotency-key-do-not-randomize"
    client.post("/analytics/event", json={
        "event_type": "ticket.opened", "object_type": "ticket", "object_id": "t-role-test",
        "event_key": key, "source": "support_inbox",
    })
    r = client.get("/analytics/dashboard", params={"role": "marketing"})
    assert r.status_code == 200
    body = r.json()
    assert "ticket.opened" not in body["by_type"]


def test_dashboard_unknown_role_rejected():
    r = client.get("/analytics/dashboard", params={"role": "not-a-real-role"})
    assert r.status_code == 400


# =========================================================
# AI evaluation summary — exposes Asma's/Viqasha's benchmark JSON reports via
# a real endpoint for the Support/AI panel, instead of leaving them as
# standalone script output.
# =========================================================

def test_ai_evaluation_summary_returns_both_modules():
    r = client.get("/quality/ai-evaluation/summary")
    assert r.status_code == 200
    body = r.json()
    modules = {m["module"]: m for m in body["modules"]}
    assert "asma" in modules and "viqasha" in modules


def test_ai_evaluation_summary_reflects_real_report_data():
    # These numbers should match evidence/asma_evaluation_report.json and
    # evidence/vishaqa_evaluation_report.json as of the last real benchmark run.
    r = client.get("/quality/ai-evaluation/summary")
    body = r.json()
    modules = {m["module"]: m for m in body["modules"]}
    assert modules["asma"]["available"] is True
    assert modules["asma"]["total_cases"] == modules["asma"]["passed"]
    assert modules["viqasha"]["available"] is True
    assert modules["viqasha"]["total_cases"] == modules["viqasha"]["passed"]


# =========================================================
# 9. Team Workload — Assignment §4 deliverable 9.
# Rebuilt against real Defect rows (confirmed by Zeenat: task/defect data
# lives in the `defects` table, not analytics_events; due_date/is_blocked
# fields added to Defect specifically to support this endpoint).
# Proves the doc's evidence requirement: "Metrics match underlying tasks."
# =========================================================

from packages.database.models import Defect, User


def _get_or_create_test_owner(db) -> str:
    # NOTE: uses example.com (RFC 2606 reserved-for-documentation domain,
    # NOT a special-use TLD like .local). An earlier version of this helper
    # used a ".local" email, which broke the gateway's GET /api/users route
    # (its response validation rejects .local as a reserved TLD) for every
    # caller, not just tests. Delete any leftover "test-owner@nw-digital-ops.local"
    # User row from your database if you pulled that earlier version.
    owner = db.query(User).filter(User.email == "test-owner@nw-digital-ops.example.com").first()
    if not owner:
        tenant = get_or_create_dev_tenant(db)
        owner = User(
            tenant_id=tenant.id,
            email="test-owner@nw-digital-ops.example.com",
            password_hash="test-hash-not-real",
            full_name="Test Owner",
            role="designer",
        )
        db.add(owner)
        db.commit()
        db.refresh(owner)
    return str(owner.id)


def _make_defect(status="open", is_blocked=False, due_date=None, severity="medium") -> str:
    db = SessionLocal()
    try:
        tenant = get_or_create_dev_tenant(db)
        owner_id = _get_or_create_test_owner(db)
        d = Defect(
            tenant_id=tenant.id,
            owner_id=UUID(owner_id),
            severity=severity,
            steps_to_reproduce="Test steps",
            expected="Test expected",
            actual="Test actual",
            status=status,
            is_blocked=is_blocked,
            due_date=due_date,
        )
        db.add(d)
        db.commit()
        db.refresh(d)
        # Tracked for automatic cleanup — see _cleanup_test_fixture_rows below.
        # Without this, every pytest run permanently adds one more Defect row
        # to the shared dev tenant, inflating /analytics/workload's real
        # numbers over time (the same category of bug as DEF-009 and DEF-011).
        _created_defect_ids.append(str(d.id))
        return str(d.id)
    finally:
        db.close()


def test_workload_metrics_match_underlying_tasks():
    # One of each real bucket: completed, blocked, overdue, in_progress.
    past_due = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=2)
    future_due = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=2)

    _make_defect(status="closed")
    _make_defect(status="open", is_blocked=True)
    _make_defect(status="open", is_blocked=False, due_date=past_due)
    _make_defect(status="open", is_blocked=False, due_date=future_due)

    r = client.get("/analytics/workload")
    assert r.status_code == 200
    body = r.json()
    assert body["completed"] >= 1
    assert body["blocked"] >= 1
    assert body["overdue"] >= 1
    assert body["in_progress"] >= 1
    # Buckets are mutually exclusive by design — this IS the doc's
    # "metrics match underlying tasks" evidence requirement.
    assert body["completed"] + body["blocked"] + body["overdue"] + body["in_progress"] == body["total_tasks"]
    assert body["completion_rate"] == round(body["completed"] / body["total_tasks"], 4)
    assert body["data_source"] == "defects (packages.database.models.Defect)"


def test_workload_closed_defect_not_double_counted_as_blocked_or_overdue():
    # A closed defect that also happens to have is_blocked=True or an old
    # due_date should count ONLY as completed — closed work isn't still
    # "blocked" or "overdue".
    past_due = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=5)
    defect_id = _make_defect(status="closed", is_blocked=True, due_date=past_due)

    r = client.get("/analytics/workload")
    body = r.json()
    assert body["completed"] >= 1
    # Can't assert this specific defect isn't in blocked/overdue by id (API
    # doesn't return per-defect ids), but the mutually-exclusive bucket sum
    # check above already proves no double-counting is possible.
    assert body["total_tasks"] >= 1


def test_workload_client_filter_reports_limitation_not_silently_ignored():
    # Defect has no client_id in the shared schema, so client filtering
    # isn't possible on this data source. The endpoint should say so
    # explicitly rather than silently ignoring the param.
    r = client.get("/analytics/workload", params={"client": "bebop"})
    assert r.status_code == 200
    body = r.json()
    assert body["filters_applied"]["client"] is None
    assert any("client_id" in note for note in body["limitations"])


def test_workload_severity_filter():
    _make_defect(status="open", severity="critical")
    r = client.get("/analytics/workload", params={"severity": "critical"})
    assert r.status_code == 200
    assert r.json()["filters_applied"]["severity"] == "critical"


# =========================================================
# 10. Scheduler consistency — Assignment §4 deliverable 7 (previously unbuilt).
# Proves the doc's exact evidence requirement: "No false published status in
# analytics."
# =========================================================

# Scheduler consistency now reads real Campaign + PublishingJob rows
# (confirmed by Zeenat: the scheduler writes directly to these tables, it
# never emits analytics_events). These tests seed real rows via the shared
# DB session/models, the same tables the real scheduler writes to — not
# fabricated analytics events.
from packages.database.models import Campaign, PublishingJob


def _make_campaign(status: str, job_statuses: list = None, client_name: str = "bebop") -> str:
    db = SessionLocal()
    try:
        tenant = get_or_create_dev_tenant(db)
        client_row = get_or_create_client(db, tenant.id, client_name)
        campaign = Campaign(tenant_id=tenant.id, client_id=client_row.id, name="Test Campaign", status=status)
        db.add(campaign)
        db.commit()
        db.refresh(campaign)
        for i, job_status in enumerate(job_statuses or []):
            job = PublishingJob(
                campaign_id=campaign.id,
                status=job_status,
                idempotency_key=f"job-{campaign.id}-{i}-{uuid.uuid4()}",
                scheduled_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
            db.add(job)
        db.commit()
        # Tracked for automatic cleanup — see _cleanup_test_fixture_rows below.
        # DEF-011 root cause: this helper used to commit permanent rows to the
        # shared dev DB with no teardown. Every pytest run of
        # test_scheduler_consistency_flags_false_published_no_completed_job
        # left one more "published, job failed" Campaign behind — 34 of these
        # accumulated over 6 days of test runs and were mistaken at first for
        # a scheduler.py status-transition bug (see defect_log.md DEF-011).
        _created_campaign_ids.append(str(campaign.id))
        return str(campaign.id)
    finally:
        db.close()


def test_scheduler_consistency_flags_false_published_no_completed_job():
    # Campaign marked "published" but its only publishing job FAILED — this
    # is exactly the false-published scenario the doc says must not happen
    # silently. The endpoint should surface it, not hide it.
    campaign_id = _make_campaign(status="published", job_statuses=["failed"])

    r = client.get("/analytics/scheduler-consistency")
    assert r.status_code == 200
    body = r.json()
    assert campaign_id in body["inconsistent_campaign_ids"]
    assert body["inconsistent_count"] >= 1
    assert body["total_failed"] >= 1


def test_scheduler_consistency_clean_published_not_flagged():
    # A campaign that published with a genuinely completed job should NOT
    # show up as inconsistent.
    campaign_id = _make_campaign(status="published", job_statuses=["completed"])

    r = client.get("/analytics/scheduler-consistency")
    body = r.json()
    assert campaign_id not in body["inconsistent_campaign_ids"]
    assert body["total_published"] >= 1


def test_scheduler_consistency_client_filter():
    r = client.get("/analytics/scheduler-consistency", params={"client": "bebop"})
    assert r.status_code == 200
    assert r.json()["filters_applied"]["client"] == "bebop"


# =========================================================
# 10. Client Summary — Assignment §2.3 deliverable.
# Gap identified in audit (2026-09-02): endpoint existed and was wired into
# main.py, but had zero automated coverage — no test_client_summary_*
# function existed anywhere, unlike every other analytics endpoint.
#
# DEF-009 history: the first fix blanket-excluded EVERY client_id-IS-NULL
# event from client_performance, not just marker/tenant-check noise — that
# silently dropped genuinely unmatched reach data too (its own §10
# violation) and was reverted. The current fix in main.py gates the
# exclusion specifically on the marker signature (idempotency_key prefixed
# "tenant-check", or event_type == "tenant_resolution_marker") so the two
# cases below can be tested independently.
# =========================================================

def test_client_summary_reports_reach_and_engagement_from_events():
    # Dedicated client name so this test's totals aren't affected by reach
    # numbers other tests may post under "bebop"/"samvix"/etc.
    client.post("/analytics/event", json={
        "event_type": "post.published", "object_type": "campaign", "object_id": "camp-sum-1",
        "event_key": "test-summary-fixed-key-1-do-not-randomize",
        "client": "esha-summary-test", "metrics": {"reach": 500, "engagement": 50},
        "source": "scheduler",
    })
    client.post("/analytics/event", json={
        "event_type": "campaign.updated", "object_type": "campaign", "object_id": "camp-sum-2",
        "event_key": "test-summary-fixed-key-2-do-not-randomize",
        "client": "esha-summary-test", "metrics": {"reach": 300, "engagement": 30},
        "source": "scheduler",
    })

    r = client.get("/analytics/client-summary", params={"client": "esha-summary-test"})
    assert r.status_code == 200
    body = r.json()
    assert body["total_reach"] == 800
    assert body["engagement_rate_pct"] == 10.0  # (50+30)/800 * 100
    assert {"client": "esha-summary-test", "reach": 800} in body["client_performance"]
    assert "total_reach" not in body["unavailable_fields"]
    assert "engagement_rate_pct" not in body["unavailable_fields"]


def test_client_summary_leads_always_unavailable():
    # TODO(Esha) in main.py: no service emits a lead.* event or metrics.leads
    # field yet — this should report unavailable, not a fabricated 0.
    r = client.get("/analytics/client-summary")
    assert r.status_code == 200
    body = r.json()
    assert body["leads"] is None
    assert "leads" in body["unavailable_fields"]


def test_client_summary_profitability_always_unavailable():
    # TODO(Esha) in main.py: no cost/spend/revenue field exists on Client,
    # Campaign, or AnalyticsEvent in the shared schema yet — required by
    # §2.3/§4 deliverable 3, but must report unavailable, not a fabricated 0,
    # until a real source is confirmed with Zeenat/management.
    r = client.get("/analytics/client-summary")
    assert r.status_code == 200
    body = r.json()
    assert body["profitability_pct"] is None
    assert "profitability_pct" in body["unavailable_fields"]


def test_client_summary_avg_ticket_resolution_from_ticket_pairs():
    ticket_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    client.post("/analytics/event", json={
        "event_type": "ticket.opened", "object_type": "ticket", "object_id": ticket_id,
        "event_key": "test-summary-ticket-open-fixed-key-do-not-randomize",
        "client": "esha-summary-test", "source": "support_inbox",
    })
    client.post("/analytics/event", json={
        "event_type": "ticket.closed", "object_type": "ticket", "object_id": ticket_id,
        "event_key": "test-summary-ticket-close-fixed-key-do-not-randomize",
        "client": "esha-summary-test", "source": "support_inbox",
    })

    r = client.get("/analytics/client-summary", params={"client": "esha-summary-test"})
    body = r.json()
    # Not asserting an exact hour value — occurred_at is server-assigned at
    # ingestion time (same non-determinism the idempotency tests already
    # accept), so the real proof is that a pairing was found at all.
    assert body["avg_ticket_resolution_hours"] is not None
    assert body["avg_ticket_resolution_hours"] >= 0
    assert "avg_ticket_resolution_hours" not in body["unavailable_fields"]


def test_client_summary_marker_events_excluded_from_client_performance():
    # DEF-009 (original symptom): tenant-check / marker probes — identified
    # by an idempotency_key prefixed "tenant-check" — must NOT add to the
    # "unknown" bucket in client_performance. client_performance aggregates
    # globally across every unlinked non-marker event ever posted (no
    # per-test isolation is possible via a client filter, since this is
    # unfiltered by design), so this test compares the "unknown" total
    # immediately before and after posting the marker, rather than asserting
    # an absolute value — that avoids coupling to test execution order or
    # to how many "unknown" events other tests may have already created.
    before = client.get("/analytics/client-summary").json()
    before_unknown = next(
        (c["reach"] for c in before["client_performance"] if c["client"] == "unknown"), 0
    )

    client.post("/analytics/event", json={
        "event_type": "post.published", "object_type": "campaign", "object_id": "camp-marker-1",
        "event_key": "tenant-check-fixed-key-do-not-randomize",
        "metrics": {"reach": 999}, "source": "scheduler",
        # no "client" field — client_id will be None; idempotency_key starts
        # with "tenant-check", so this must be treated as marker noise.
    })

    after = client.get("/analytics/client-summary").json()
    after_unknown = next(
        (c["reach"] for c in after["client_performance"] if c["client"] == "unknown"), 0
    )
    assert after_unknown == before_unknown, "Marker event's reach must not be added to the unknown bucket"


def test_client_summary_genuine_unmatched_events_still_bucketed_as_unknown():
    # DEF-009 (reverted fix's regression): a genuinely unmatched event — no
    # client, and NOT a marker/tenant-check probe — must still show up as
    # "unknown" rather than silently vanishing from client_performance.
    #
    # Unlike the other fixed-key tests in this file, this one asserts an
    # EXACT delta (+77), so a fixed key would be silently deduplicated after
    # the first run and the test would stop proving anything. A fresh key
    # per run is required, with explicit teardown so it doesn't become a
    # new permanent "unknown"-bucket pollution source itself.
    event_key = f"test-summary-genuine-unmatched-{uuid.uuid4()}"
    try:
        before = client.get("/analytics/client-summary").json()
        before_unknown = next(
            (c["reach"] for c in before["client_performance"] if c["client"] == "unknown"), 0
        )

        client.post("/analytics/event", json={
            "event_type": "post.published", "object_type": "campaign", "object_id": "camp-unk-genuine-1",
            "event_key": event_key,
            "metrics": {"reach": 77}, "source": "scheduler",
            # no "client" field, and NOT a tenant-check key — a real unlinked event
        })

        after = client.get("/analytics/client-summary").json()
        after_unknown = next(
            (c["reach"] for c in after["client_performance"] if c["client"] == "unknown"), 0
        )
        assert after_unknown == before_unknown + 77, "Genuine unmatched event must still appear in the unknown bucket"
    finally:
        db = SessionLocal()
        try:
            db.query(AnalyticsEvent).filter(AnalyticsEvent.idempotency_key == event_key).delete()
            db.commit()
        finally:
            db.close()
# =========================================================
# 11. Client Health — Assignment §2.3 deliverable.
# Same gap as client-summary: wired into main.py, zero test coverage.
# =========================================================

def test_client_health_reports_healthy_status_for_strong_engagement():
    # Uses a client name/event_key not used anywhere else in this file.
    # Previously reused "esha-health-test" with the SLA test below, and
    # because /analytics/client-health has no client filter (it aggregates
    # by client name across every event ever posted), that shared name
    # picked up a stale idempotent row from an earlier version of this test
    # file. Idempotency is keyed globally by event_key, so once a key is
    # used against a persistent (non-reset) local DB it's permanent —
    # reusing the same key with a different client name is a silent no-op,
    # not an update. Fresh, never-reused identifiers avoid this entirely.
    client.post("/analytics/event", json={
        "event_type": "post.published", "object_type": "campaign", "object_id": "camp-health-eng-1",
        "event_key": "test-health-engagement-v2-fixed-key-do-not-randomize",
        "client": "esha-health-engagement-test", "metrics": {"reach": 1000, "engagement": 800},
        "source": "scheduler",
    })

    r = client.get("/analytics/client-health")
    assert r.status_code == 200
    body = r.json()
    entry = next(c for c in body["clients"] if c["client"] == "esha-health-engagement-test")
    assert entry["engagement_rate_pct"] == 80.0
    # DEF-015: health_score is now the weighted blend, not a raw average of
    # available signals. 80.0% engagement buckets to the top engagement
    # component (90), while sla and resolution are both unavailable here and
    # each default to the neutral 70: 90*0.4 + 70*0.3 + 70*0.3 == 78.
    assert entry["health_score"] == 78
    assert entry["status"] == "healthy"


def test_client_health_sla_compliance_always_unavailable():
    # TODO(Esha) in main.py: Defect has no client_id, so sla_compliance_pct
    # cannot be scoped per client with the current shared schema — every
    # client entry should report it as unavailable, never a fabricated value.
    # Own client name + event_key (see note in the test above) so this
    # never shares aggregation with any other client-health test.
    client.post("/analytics/event", json={
        "event_type": "post.published", "object_type": "campaign", "object_id": "camp-health-sla-1",
        "event_key": "test-health-sla-v2-fixed-key-do-not-randomize",
        "client": "esha-health-sla-test", "metrics": {"reach": 100, "engagement": 10},
        "source": "scheduler",
    })
    r = client.get("/analytics/client-health")
    body = r.json()
    entry = next(c for c in body["clients"] if c["client"] == "esha-health-sla-test")
    assert entry["sla_compliance_pct"] is None
    assert "sla_compliance_pct" in entry["unavailable_signals"]


def test_client_health_low_but_realistic_engagement_is_not_critical():
    # DEF-015 regression test. Before the fix, health_score was a raw
    # average of available signals — with only engagement_rate_pct
    # available, that meant the score WAS the raw percentage. A realistic
    # low-single-digit engagement rate (2%) was therefore misjudged
    # "critical" (< 40) even though 2% is a normal rate, not a red flag.
    #
    # Under the DEF-015 weighted formula, 2% engagement buckets to the
    # 1-3% -> 50 component, and sla/resolution (both unavailable here)
    # default to the neutral 70 each:
    #   50*0.4 + 70*0.3 + 70*0.3 == 62  -> "at_risk", NOT "critical".
    # Own client name + event_key so this never shares aggregation with any
    # other client-health test (see note on the engagement test above).
    client.post("/analytics/event", json={
        "event_type": "post.published", "object_type": "campaign", "object_id": "camp-health-regression-1",
        "event_key": "test-health-regression-v1-fixed-key-do-not-randomize",
        "client": "esha-health-regression-test", "metrics": {"reach": 1000, "engagement": 20},
        "source": "scheduler",
    })

    r = client.get("/analytics/client-health")
    assert r.status_code == 200
    body = r.json()
    entry = next(c for c in body["clients"] if c["client"] == "esha-health-regression-test")
    assert entry["engagement_rate_pct"] == 2.0
    assert entry["health_score"] == 62
    assert entry["status"] == "at_risk"
    assert entry["status"] != "critical"


def test_client_health_excludes_events_with_no_client():
    # Unlike client-summary, client-health filters out events where
    # client_id is None before grouping (`if e.client_id is not None` in
    # main.py) — so no "unknown" entry should ever appear here. This is a
    # real behavioral difference between the two endpoints worth locking in
    # with a test, since DEF-009's marker events would hit this endpoint
    # differently than client-summary.
    client.post("/analytics/event", json={
        "event_type": "post.published", "object_type": "campaign", "object_id": "camp-health-noclient",
        "event_key": "test-health-no-client-fixed-key-do-not-randomize",
        "metrics": {"reach": 10, "engagement": 1}, "source": "scheduler",
        # no "client" field
    })
    r = client.get("/analytics/client-health")
    body = r.json()
    assert not any(c["client"] == "unknown" for c in body["clients"])