import sys
import os
import re
import json
import calendar
from collections import Counter
from datetime import datetime, date, timezone
from typing import List, Optional, Dict, Any
from uuid import UUID

from fastapi import FastAPI, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from packages.database.session import SessionLocal
from packages.database.models import (
    Tenant, Client, HashtagSet, HashtagItem, QualityRun, AnalyticsEvent, ReportSnapshot,
    Campaign, PublishingJob, Defect
)

app = FastAPI(title="Esha Service - Hashtag, Analytics & Quality API")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Canonical demo tenant UUID — matches the real demo Super Admin login
# (Atif Zaheer), as proposed by Viqasha and tracked in DEF-007. If the team
# confirms a different canonical UUID, update this single constant only.
CANONICAL_TENANT_ID = UUID("00000000-0000-0000-0000-00000000000a")


def get_or_create_dev_tenant(db: Session) -> Tenant:
    """Resolves the dev/demo tenant by its fixed canonical UUID instead of by
    name, so every environment/database converges on the same tenant instead
    of drifting per-database (DEF-007). Previously this looked up by the name
    "esha-dev-tenant" and let each fresh database auto-generate its own
    random UUID, which meant esha-service's data lived under a tenant the
    real demo login never used."""
    tenant = db.query(Tenant).filter(Tenant.id == CANONICAL_TENANT_ID).first()
    if not tenant:
        tenant = Tenant(id=CANONICAL_TENANT_ID, name="esha-dev-tenant", status="active")
        db.add(tenant)
        db.commit()
        db.refresh(tenant)
    return tenant


def get_or_create_client(db: Session, tenant_id, client_name: str) -> Client:
    """Looks up a real Client row by company_name, creates one if it doesn't exist yet
    (useful for local dev/testing before real clients are onboarded through the UI)."""
    existing = db.query(Client).filter(
        Client.tenant_id == tenant_id, Client.company_name == client_name
    ).first()
    if existing:
        return existing
    new_client = Client(tenant_id=tenant_id, company_name=client_name, contact_email=f"{client_name}@example.com")
    db.add(new_client)
    db.commit()
    db.refresh(new_client)
    return new_client


BANNED_TAGS = {"#follow4follow", "#f4f", "#spam", "#buyfollowers"}
GENERIC_HIGH_VOLUME_TAGS = {"#love", "#instagood", "#follow", "#like4like", "#photooftheday"}
PROHIBITED_WORDS = {"guaranteed", "100% risk-free", "cheapest in pakistan"}
CTA_WORDS = {"shop", "call", "visit", "book", "dm", "order", "buy", "sign up"}
RULE_VERSION = "v1.1"  # bumped: added repetition + wrong-contact-detail checks (§8 required test cases)

# Words short/common enough that repeating them isn't a quality issue (stopwords + CTA words,
# since CTA words are expected to repeat as part of a legitimate call-to-action).
REPETITION_IGNORE_WORDS = {
    "the", "a", "an", "and", "or", "for", "to", "of", "in", "on", "at", "is", "are",
    "this", "that", "with", "your", "our", "you", "we", "it", "be", "as", "by", "from",
} | CTA_WORDS

EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
# Loosely matches common phone formats (e.g. 0300-1234567, +92 300 1234567, (021) 1234567)
PHONE_PATTERN = re.compile(r"(\+?\d[\d\-\s()]{7,}\d)")


class Warning(BaseModel):
    type: str
    tag: Optional[str] = None
    message: str


class Issue(BaseModel):
    severity: str
    location: str
    message: str


def score_to_label(score: int) -> str:
    if score >= 80:
        return "Strong"
    if score >= 50:
        return "Needs Work"
    return "Weak"


@app.get("/health")
def health_check(db: Session = Depends(get_db)):
    return {"status": "ok", "service": "esha-service", "tenants_in_db": db.query(Tenant).count()}


# =========================================================
# HASHTAGS — now using real client_id, platform, category columns
# =========================================================

class HashtagRequest(BaseModel):
    tags: List[str]
    client: str
    platform: str

class HashtagResponse(BaseModel):
    recommended_tags: List[str]
    warnings: List[Warning]
    quality_score: int

@app.post("/quality/hashtags/suggest", response_model=HashtagResponse)
def suggest_hashtags(payload: HashtagRequest, db: Session = Depends(get_db)):
    tenant = get_or_create_dev_tenant(db)
    client_row = get_or_create_client(db, tenant.id, payload.client)
    submitted = [t.lower() for t in payload.tags]

    # Real filtered lookup — client_id and platform are now actual columns,
    # so this is a proper SQL WHERE clause, not a name-encoding trick.
    hashtag_set = (
        db.query(HashtagSet)
        .filter(
            HashtagSet.tenant_id == tenant.id,
            HashtagSet.client_id == client_row.id,
            HashtagSet.platform == payload.platform.lower(),
            HashtagSet.is_active == True,
        )
        .order_by(HashtagSet.version.desc())  # get the latest version if multiple exist
        .first()
    )

    if hashtag_set:
        recommended = [item.tag for item in hashtag_set.hashtag_items]
    else:
        recommended = ["#LocalBusiness", "#SupportLocal"]

    warnings: List[Warning] = []
    seen = set()
    for tag in submitted:
        if tag in seen:
            warnings.append(Warning(type="duplicate", tag=tag, message=f"'{tag}' was submitted more than once."))
        seen.add(tag)
    for tag in submitted:
        if tag in BANNED_TAGS:
            warnings.append(Warning(type="banned", tag=tag, message=f"'{tag}' is on the banned list."))
    generic_count = sum(1 for tag in submitted if tag in GENERIC_HIGH_VOLUME_TAGS)
    if submitted and (generic_count / len(submitted)) > 0.4:
        warnings.append(Warning(type="spam_risk",
                                 message=f"{generic_count} of {len(submitted)} tags are generic/high-volume."))

    score = 100
    score -= sum(1 for w in warnings if w.type == "banned") * 30
    score -= sum(1 for w in warnings if w.type == "duplicate") * 10
    score -= sum(1 for w in warnings if w.type == "spam_risk") * 20
    score = max(score, 0)

    # Now uses separate `checks` and `issues` columns, not one merged `results` blob.
    run = QualityRun(
        tenant_id=tenant.id,
        input_version=json.dumps(payload.tags),
        run_type="hashtags",
        checks=json.dumps({"submitted_count": len(submitted)}),
        issues=json.dumps([w.model_dump() for w in warnings]),
        score=float(score),
        rule_version=RULE_VERSION,
    )
    db.add(run)
    db.commit()

    return HashtagResponse(recommended_tags=recommended, warnings=warnings, quality_score=score)


class SaveHashtagSetRequest(BaseModel):
    client: str
    platform: str
    category: str = "brand"   # "brand" | "local" | "campaign" | "industry"
    tags: List[str]

class SaveHashtagSetResponse(BaseModel):
    hashtag_set_id: str
    version: int
    saved_tags: List[str]

@app.post("/quality/hashtags/save", response_model=SaveHashtagSetResponse)
def save_hashtag_set(payload: SaveHashtagSetRequest, db: Session = Depends(get_db)):
    tenant = get_or_create_dev_tenant(db)
    client_row = get_or_create_client(db, tenant.id, payload.client)

    existing = (
        db.query(HashtagSet)
        .filter(
            HashtagSet.tenant_id == tenant.id,
            HashtagSet.client_id == client_row.id,
            HashtagSet.platform == payload.platform.lower(),
        )
        .order_by(HashtagSet.version.desc())
        .first()
    )
    next_version = (existing.version + 1) if existing else 1

    # Old versions are kept (not overwritten) — matches task doc's "versioned signatures" requirement.
    if existing:
        existing.is_active = False
        db.add(existing)

    new_set = HashtagSet(
        tenant_id=tenant.id, client_id=client_row.id, name=f"{payload.client} {payload.platform} set",
        category=payload.category, platform=payload.platform.lower(),
        version=next_version, is_active=True,
    )
    db.add(new_set)
    db.commit()
    db.refresh(new_set)

    for tag in payload.tags:
        db.add(HashtagItem(hashtag_set_id=new_set.id, tag=tag))
    db.commit()

    return SaveHashtagSetResponse(hashtag_set_id=str(new_set.id), version=next_version, saved_tags=payload.tags)


# =========================================================
# CONTENT QUALITY — scoring logic unchanged, now logs to real `issues`/`checks` columns
# =========================================================

class ContentRequest(BaseModel):
    caption: str
    client: str

class ContentResponse(BaseModel):
    score: int
    label: str
    brand_match: int
    clarity: int
    cta_strength: int
    duplicate_risk: str
    issues: List[Issue]

def check_repetition(caption_lower: str) -> List[str]:
    """§8 required case: 'repetition' — flags a word repeated enough times to read as
    spammy/filler, ignoring stopwords and CTA words (CTA words are expected to repeat)."""
    words = re.findall(r"[a-z']+", caption_lower)
    counts = Counter(w for w in words if w not in REPETITION_IGNORE_WORDS and len(w) > 2)
    return [word for word, n in counts.items() if n >= 3]


def check_wrong_contact_detail(caption: str, client_row: Client) -> List[str]:
    """§8 required case: 'wrong contact detail' — flags an email in the caption that
    doesn't match the client's registered contact_email. NOTE: Client currently only
    has contact_email in the schema available to this service, so phone numbers found
    in the caption are only detected, not verified against a canonical number — if a
    canonical client phone field exists or gets added, extend this check to verify it too."""
    problems = []
    found_emails = EMAIL_PATTERN.findall(caption)
    for email in found_emails:
        if client_row.contact_email and email.lower() != client_row.contact_email.lower():
            problems.append(f"Email '{email}' does not match client's registered contact ({client_row.contact_email}).")
    if PHONE_PATTERN.search(caption):
        problems.append("Phone number detected in caption — verify manually against the client's correct number (no canonical phone field to check against yet).")
    return problems


@app.post("/quality/content", response_model=ContentResponse)
def check_content_quality(payload: ContentRequest, db: Session = Depends(get_db)):
    tenant = get_or_create_dev_tenant(db)
    client_row = get_or_create_client(db, tenant.id, payload.client)
    caption = payload.caption
    caption_lower = caption.lower()
    issues: List[Issue] = []

    sentences = [s.strip() for s in caption.split(".") if s.strip()]
    long_sentences = sum(1 for s in sentences if len(s.split()) > 30)
    for i, s in enumerate(sentences):
        if len(s.split()) > 30:
            issues.append(Issue(severity="warning", location=f"sentence {i+1}", message="Sentence is over 30 words."))
    clarity = round(100 * (1 - long_sentences / len(sentences))) if sentences else 100

    cta_hits = [w for w in CTA_WORDS if w in caption_lower]
    cta_strength = (100 if len(cta_hits) > 1 else 90) if cta_hits else 40
    if not cta_hits:
        issues.append(Issue(severity="warning", location="whole caption", message="No clear CTA found."))

    brand_match = 100
    for phrase in PROHIBITED_WORDS:
        if phrase in caption_lower:
            brand_match -= 35
            issues.append(Issue(severity="critical", location="whole caption",
                                 message=f"Prohibited phrase used: '{phrase}'."))

    repeated_words = check_repetition(caption_lower)
    for word in repeated_words:
        brand_match -= 10
        issues.append(Issue(severity="warning", location="whole caption",
                             message=f"Word '{word}' is repeated excessively (3+ times)."))

    contact_problems = check_wrong_contact_detail(caption, client_row)
    for problem in contact_problems:
        brand_match -= 25
        issues.append(Issue(severity="critical", location="whole caption", message=problem))

    brand_match = max(brand_match, 0)

    # Real similarity check against past content runs — was previously hardcoded to "Low".
    is_dup, sim_score, _matched_id = compute_similarity(caption, tenant.id, payload.client, db)
    if is_dup:
        duplicate_risk = "High"
    elif sim_score >= 0.5:
        duplicate_risk = "Medium"
    else:
        duplicate_risk = "Low"

    overall = round(0.3 * clarity + 0.3 * cta_strength + 0.4 * brand_match)

    run = QualityRun(
        tenant_id=tenant.id,
        input_version=caption,
        run_type="content",
        checks=json.dumps({"brand_match": brand_match, "clarity": clarity, "cta_strength": cta_strength, "client": payload.client}),
        issues=json.dumps([i.model_dump() for i in issues]),
        score=float(overall),
        rule_version=RULE_VERSION,
    )
    db.add(run)
    db.commit()

    return ContentResponse(score=overall, label=score_to_label(overall), brand_match=brand_match,
                            clarity=clarity, cta_strength=cta_strength, duplicate_risk=duplicate_risk, issues=issues)


# =========================================================
# SIMILARITY — compares against real input_version text of past "content" runs
# =========================================================

class SimilarityRequest(BaseModel):
    caption: str
    client: str
    threshold: float = 0.85

class SimilarityResponse(BaseModel):
    is_near_duplicate: bool
    similarity_score: float
    source_ids: List[str]

def word_overlap_ratio(a: str, b: str) -> float:
    wa, wb = set(a.lower().split()), set(b.lower().split())
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / min(len(wa), len(wb))


def compute_similarity(caption: str, tenant_id, client: str, db: Session, threshold: float = 0.85):
    """Shared lookup used by both /quality/similarity and /quality/content, so
    duplicate_risk in the content-quality response reflects the same logic
    the dedicated similarity endpoint uses, instead of a placeholder value.

    DEF-006 fix: scoped by client, not just tenant_id. All clients currently
    share one dev tenant (see get_or_create_dev_tenant), so filtering on
    tenant_id alone let Client A's caption get flagged as a near-duplicate of
    Client B's caption. QualityRun has no client_id column yet, so the client
    is stashed in the `checks` JSON blob at write time and read back here."""
    past_runs = (
        db.query(QualityRun)
        .filter(QualityRun.tenant_id == tenant_id, QualityRun.run_type == "content")
        .order_by(QualityRun.created_at.desc())
        .limit(50)
        .all()
    )
    best_score, matched_id = 0.0, None
    for run in past_runs:
        if not run.input_version:
            continue
        try:
            run_client = json.loads(run.checks).get("client") if run.checks else None
        except (ValueError, AttributeError):
            run_client = None
        if run_client != client:
            continue
        score = word_overlap_ratio(caption, run.input_version)
        if score > best_score:
            best_score, matched_id = score, str(run.id)

    is_duplicate = best_score >= threshold
    return is_duplicate, round(best_score, 2), matched_id


@app.post("/quality/similarity", response_model=SimilarityResponse)
def check_similarity(payload: SimilarityRequest, db: Session = Depends(get_db)):
    tenant = get_or_create_dev_tenant(db)
    is_duplicate, best_score, matched_id = compute_similarity(
        payload.caption, tenant.id, payload.client, db, payload.threshold
    )
    return SimilarityResponse(is_near_duplicate=is_duplicate, similarity_score=best_score,
                               source_ids=[matched_id] if is_duplicate and matched_id else [])


# =========================================================
# ANALYTICS EVENTS — now using real client_id, object_type, object_id, metrics, source columns
# =========================================================

class EventRequest(BaseModel):
    event_type: str
    object_type: str
    object_id: str
    event_key: str
    client: Optional[str] = None
    metrics: Dict = {}
    source: str

class EventResponse(BaseModel):
    accepted: bool
    duplicate: bool
    event_id: str

@app.post("/analytics/event", response_model=EventResponse)
def ingest_event(payload: EventRequest, db: Session = Depends(get_db)):
    tenant = get_or_create_dev_tenant(db)

    existing = db.query(AnalyticsEvent).filter(AnalyticsEvent.idempotency_key == payload.event_key).first()
    if existing:
        return EventResponse(accepted=True, duplicate=True, event_id=str(existing.id))

    client_row = get_or_create_client(db, tenant.id, payload.client) if payload.client else None

    # object_id is a real UUID column now, not free text — try to parse it as one.
    # If the caller passes a non-UUID string (e.g. "test-campaign-1"), store it as
    # None here and keep the original string inside event_data so nothing is lost.
    try:
        parsed_object_id = UUID(payload.object_id)
    except (ValueError, AttributeError, TypeError):
        parsed_object_id = None

    event = AnalyticsEvent(
        tenant_id=tenant.id,
        client_id=client_row.id if client_row else None,
        event_type=payload.event_type,
        object_type=payload.object_type,
        object_id=parsed_object_id,
        metrics=json.dumps(payload.metrics),
        event_data=json.dumps({"object_id_raw": payload.object_id}) if parsed_object_id is None else None,
        source=payload.source,
        occurred_at=datetime.now(timezone.utc),
        idempotency_key=payload.event_key,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return EventResponse(accepted=True, duplicate=False, event_id=str(event.id))


# =========================================================
# DASHBOARD & MONTHLY REPORT — now with real client_id filtering
# =========================================================

# TODO(Esha): confirm this role->event-type mapping against the real product roles
# once Zeenat/Atif finalize the role list. This is a reasonable first pass, not
# the final tenant/permission model (that's enforced upstream by the core API
# per the task doc — this is just role-relevant filtering within our own data).
ROLE_EVENT_PREFIXES: Dict[str, tuple] = {
    "marketing": ("post.", "campaign."),
    "support": ("ticket.",),
    "management": (),  # empty tuple = no restriction, sees everything
}


class DashboardResponse(BaseModel):
    total_events: int
    by_type: Dict[str, int]
    filters_applied: Dict[str, Optional[str]]

@app.get("/analytics/dashboard", response_model=DashboardResponse)
def get_dashboard(
    client: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    role: Optional[str] = None,
    db: Session = Depends(get_db),
):
    tenant = get_or_create_dev_tenant(db)
    query = db.query(AnalyticsEvent).filter(AnalyticsEvent.tenant_id == tenant.id)

    if client:
        client_row = get_or_create_client(db, tenant.id, client)
        query = query.filter(AnalyticsEvent.client_id == client_row.id)

    if date_from:
        query = query.filter(AnalyticsEvent.occurred_at >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        query = query.filter(AnalyticsEvent.occurred_at <= datetime.combine(date_to, datetime.max.time()))

    if role and role not in ROLE_EVENT_PREFIXES:
        raise HTTPException(status_code=400, detail=f"Unknown role '{role}'. Expected one of {list(ROLE_EVENT_PREFIXES)}.")

    events = query.all()

    prefixes = ROLE_EVENT_PREFIXES.get(role, ()) if role else ()
    if prefixes:
        events = [e for e in events if e.event_type.startswith(prefixes)]

    by_type: Dict[str, int] = {}
    for e in events:
        by_type[e.event_type] = by_type.get(e.event_type, 0) + 1

    return DashboardResponse(
        total_events=len(events),
        by_type=by_type,
        filters_applied={
            "client": client,
            "date_from": date_from.isoformat() if date_from else None,
            "date_to": date_to.isoformat() if date_to else None,
            "role": role,
        },
    )


# =========================================================
# CLIENT SUMMARY — Assignment §3 Analytics screen: "Total Reach", "Engagement
# Rate", "Leads", "Avg Ticket Resolution" cards + "Client Performance" chart.
#
# Built against real data already flowing through /analytics/event:
#   - reach / engagement come from AnalyticsEvent.metrics (already accepted
#     per API_SPEC.md: {"reach": 1200, "engagement": 45}), summed over
#     post.*/campaign.* events in range.
#   - avg_ticket_resolution_hours comes from real ticket.opened -> ticket.closed
#     event pairs (matched by object_id), confirmed real via smoke_checklist.md
#     ("ticket.opened: 13").
#
# Per §10 non-negotiable rule: a field is only ever a computed number when at
# least one matching event actually carried that data. If nothing in range
# has a "reach" key at all, total_reach reports "unavailable" — NOT 0. If
# events exist with reach=0, that's a real zero and is reported as 0.
#
# TODO(Esha): "leads" has no confirmed source yet. No service currently
# emits a lead.* event type or a metrics.leads field — confirm with
# Asma/Zeenat before wiring this up. Reports "unavailable" until then.
# =========================================================

class ClientSummaryResponse(BaseModel):
    total_reach: Optional[int]
    engagement_rate_pct: Optional[float]
    leads: Optional[int]
    # TODO(Esha): profitability has NO confirmed source — Assignment §2.3 and
    # §4 deliverable 3 both require it alongside SLA/workload/client health,
    # but nothing in the shared schema (Client, Campaign, AnalyticsEvent,
    # PublishingJob) carries cost, spend, or revenue data as of this repo.
    # Flag to Zeenat/management: does profitability come from a new
    # Client.monthly_budget-style field, a Campaign.spend field, or an
    # external billing source not yet modeled? Reported as unavailable
    # (never 0) per §10 until a real source is confirmed.
    profitability_pct: Optional[float]
    avg_ticket_resolution_hours: Optional[float]
    client_performance: List[Dict[str, Any]]  # [{"client": "bebop", "reach": 1200}, ...]
    filters_applied: Dict[str, Optional[str]]
    unavailable_fields: List[str]
    data_source: str


def _extract_metrics(event: AnalyticsEvent) -> Dict:
    if not event.metrics:
        return {}
    try:
        return json.loads(event.metrics)
    except (ValueError, TypeError):
        return {}


@app.get("/analytics/client-summary", response_model=ClientSummaryResponse)
def get_client_summary(
    client: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    db: Session = Depends(get_db),
):
    tenant = get_or_create_dev_tenant(db)
    query = db.query(AnalyticsEvent).filter(AnalyticsEvent.tenant_id == tenant.id)

    client_row = None
    if client:
        client_row = get_or_create_client(db, tenant.id, client)
        query = query.filter(AnalyticsEvent.client_id == client_row.id)
    if date_from:
        query = query.filter(AnalyticsEvent.occurred_at >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        query = query.filter(AnalyticsEvent.occurred_at <= datetime.combine(date_to, datetime.max.time()))

    events = query.all()
    unavailable: List[str] = []

    # Explicit id->name lookup rather than assuming an AnalyticsEvent.client
    # relationship exists on the shared model (not visible in this repo —
    # matches the rest of this file, which always queries Client directly).
    client_ids = {e.client_id for e in events if e.client_id is not None}
    client_names: Dict[Any, str] = {
        c.id: c.company_name
        for c in db.query(Client).filter(Client.id.in_(client_ids)).all()
    } if client_ids else {}

    # --- Reach / Engagement: sum metrics across post.*/campaign.* events ---
    reach_values, engagement_values = [], []
    reach_by_client: Dict[str, int] = {}

    for e in events:
        if not e.event_type.startswith(("post.", "campaign.")):
            continue
        m = _extract_metrics(e)
        if "reach" in m:
            reach_values.append(m["reach"])
            # DEF-009 fix (v2): the earlier fix excluded EVERY client_id-IS-NULL
            # event from client_performance, not just marker/tenant-check noise —
            # that silently dropped genuinely unmatched reach data too, which is
            # its own §10 violation. Gate specifically on the marker signature:
            # tenant-check probes carry an idempotency_key prefixed "tenant-check"
            # (event_type check kept defensively in case a literal marker type is
            # ever allowed past the post./campaign. filter above).
            is_marker = (
                e.event_type == "tenant_resolution_marker"
                or (e.idempotency_key or "").startswith("tenant-check")
            )
            if e.client_id is not None:
                client_name = client_names.get(e.client_id, "unknown")
                reach_by_client[client_name] = reach_by_client.get(client_name, 0) + m["reach"]
            elif not is_marker:
                # Genuinely unmatched (non-marker) event — still show as "unknown"
                # rather than silently vanishing from the breakdown.
                reach_by_client["unknown"] = reach_by_client.get("unknown", 0) + m["reach"]
        if "engagement" in m:
            engagement_values.append(m["engagement"])

    total_reach = sum(reach_values) if reach_values else None
    if total_reach is None:
        unavailable.append("total_reach")

    total_engagement = sum(engagement_values) if engagement_values else None
    if total_engagement is None or total_reach is None or total_reach == 0:
        engagement_rate = None
        unavailable.append("engagement_rate_pct")
    else:
        engagement_rate = round((total_engagement / total_reach) * 100, 2)

    # --- Leads: no confirmed source yet — see TODO above ---
    leads = None
    unavailable.append("leads")

    # --- Profitability: no confirmed source yet — see TODO above ---
    profitability_pct = None
    unavailable.append("profitability_pct")

    # --- Avg ticket resolution: match ticket.opened -> ticket.closed by object_id ---
    opened: Dict[str, datetime] = {}
    resolution_hours = []
    for e in sorted(events, key=lambda x: x.occurred_at):
        if e.event_type == "ticket.opened" and e.object_id:
            opened[str(e.object_id)] = e.occurred_at
        elif e.event_type == "ticket.closed" and e.object_id:
            key = str(e.object_id)
            if key in opened:
                delta = (e.occurred_at - opened.pop(key)).total_seconds() / 3600
                resolution_hours.append(delta)

    avg_resolution = round(sum(resolution_hours) / len(resolution_hours), 2) if resolution_hours else None
    if avg_resolution is None:
        unavailable.append("avg_ticket_resolution_hours")

    client_performance = [
        {"client": name, "reach": total} for name, total in reach_by_client.items()
    ]

    return ClientSummaryResponse(
        total_reach=total_reach,
        engagement_rate_pct=engagement_rate,
        leads=leads,
        profitability_pct=profitability_pct,
        avg_ticket_resolution_hours=avg_resolution,
        client_performance=client_performance,
        filters_applied={
            "client": client,
            "date_from": date_from.isoformat() if date_from else None,
            "date_to": date_to.isoformat() if date_to else None,
        },
        unavailable_fields=unavailable,
        data_source="analytics_events.metrics + ticket.opened/ticket.closed pairs",
    )


# =========================================================
# CLIENT HEALTH — Assignment §2.3 deliverable: "client health" report.
#
# DEF-015 fix (formula confirmed by Zeenat, 2026-09): health_score is now a
# WEIGHTED blend of three signals, each first normalized onto a 0-100 scale,
# rather than averaging raw signal values directly. The previous version
# averaged raw engagement_rate_pct (a single-digit percentage in practice)
# straight against the 0-100 healthy/at_risk/critical thresholds, which
# meant a perfectly normal ~2-5% engagement rate was misread as "critical".
#
#   engagement (40%): bucketed off engagement_rate_pct —
#       >=5%  -> 90   3-5%  -> 70   1-3%  -> 50   <1%  -> 20
#   sla_compliance (30%): used directly (already 0-100) when available
#   ticket resolution speed (30%): max(0, 100 - avg_ticket_resolution_hours*5)
#
#   health_score = engagement*0.4 + sla*0.3 + resolution*0.3
#
# If a signal's underlying data isn't available (e.g. sla_compliance_pct,
# which has no confirmed source at all — see TODO below), that component
# defaults to 70 (neutral) in the weighted formula, and the raw field is
# still reported as None/unavailable and listed in unavailable_signals so
# the gap stays visible. Thresholds are unchanged: >=70 healthy, 40-69
# at_risk, <40 critical.
#
# TODO(Esha): sla_compliance_pct has NO confirmed source — Defect has no
# client_id (see /analytics/workload's own documented limitation), so SLA
# can't be scoped per client with current shared schema. Flag to Zeenat:
# does client-level SLA need a client_id added to Defect, or does it come
# from client-rooms/ticket data instead?
# =========================================================


def _engagement_component_score(engagement_rate_pct: Optional[float]) -> Optional[int]:
    """Buckets a real engagement_rate_pct (e.g. 4.2) onto the 0-100 scale
    used by the weighted health_score formula. Returns None only when the
    rate itself is unavailable — callers apply the neutral-70 default."""
    if engagement_rate_pct is None:
        return None
    if engagement_rate_pct >= 5:
        return 90
    if engagement_rate_pct >= 3:
        return 70
    if engagement_rate_pct >= 1:
        return 50
    return 20


def _resolution_component_score(avg_ticket_resolution_hours: Optional[float]) -> Optional[int]:
    """Converts avg ticket resolution time (hours) into a 0-100 "speed"
    score for the weighted health_score formula. Returns None only when
    the underlying hours figure is unavailable."""
    if avg_ticket_resolution_hours is None:
        return None
    return max(0, 100 - avg_ticket_resolution_hours * 5)

class ClientHealthSignal(BaseModel):
    client: str
    health_score: Optional[int]
    status: str  # "healthy" | "at_risk" | "critical" | "unavailable"
    avg_ticket_resolution_hours: Optional[float]
    engagement_rate_pct: Optional[float]
    sla_compliance_pct: Optional[float]  # always None today — no confirmed source
    unavailable_signals: List[str]


class ClientHealthResponse(BaseModel):
    clients: List[ClientHealthSignal]
    filters_applied: Dict[str, Optional[str]]
    data_source: str
    limitations: List[str]


@app.get("/analytics/client-health", response_model=ClientHealthResponse)
def get_client_health(
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    db: Session = Depends(get_db),
):
    tenant = get_or_create_dev_tenant(db)
    query = db.query(AnalyticsEvent).filter(AnalyticsEvent.tenant_id == tenant.id)
    if date_from:
        query = query.filter(AnalyticsEvent.occurred_at >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        query = query.filter(AnalyticsEvent.occurred_at <= datetime.combine(date_to, datetime.max.time()))

    events = [e for e in query.all() if e.client_id is not None]

    # Explicit id->name lookup — see note in /analytics/client-summary above
    # on why this doesn't assume an AnalyticsEvent.client relationship.
    client_ids = {e.client_id for e in events}
    client_names: Dict[Any, str] = {
        c.id: c.company_name
        for c in db.query(Client).filter(Client.id.in_(client_ids)).all()
    } if client_ids else {}

    by_client: Dict[str, List[AnalyticsEvent]] = {}
    for e in events:
        name = client_names.get(e.client_id, "unknown")
        by_client.setdefault(name, []).append(e)

    results: List[ClientHealthSignal] = []
    for name, client_events in by_client.items():
        # Ticket resolution for this client
        opened, resolution_hours = {}, []
        for e in sorted(client_events, key=lambda x: x.occurred_at):
            if e.event_type == "ticket.opened" and e.object_id:
                opened[str(e.object_id)] = e.occurred_at
            elif e.event_type == "ticket.closed" and e.object_id:
                key = str(e.object_id)
                if key in opened:
                    resolution_hours.append((e.occurred_at - opened.pop(key)).total_seconds() / 3600)
        avg_resolution = round(sum(resolution_hours) / len(resolution_hours), 2) if resolution_hours else None

        # Engagement for this client
        reach_vals, engagement_vals = [], []
        for e in client_events:
            m = _extract_metrics(e)
            if "reach" in m:
                reach_vals.append(m["reach"])
            if "engagement" in m:
                engagement_vals.append(m["engagement"])
        engagement_rate = (
            round((sum(engagement_vals) / sum(reach_vals)) * 100, 2)
            if reach_vals and sum(reach_vals) > 0 and engagement_vals
            else None
        )

        sla_compliance_pct = None  # no confirmed source, see TODO

        unavailable = ["sla_compliance_pct"]
        if avg_resolution is None:
            unavailable.append("avg_ticket_resolution_hours")
        if engagement_rate is None:
            unavailable.append("engagement_rate_pct")

        # DEF-015: weighted blend of three 0-100 component scores. A missing
        # signal's component defaults to 70 (neutral) rather than dropping
        # out of the average — this is what keeps a client with only
        # engagement data from being scored on engagement alone.
        NEUTRAL_DEFAULT = 70
        engagement_component = _engagement_component_score(engagement_rate)
        engagement_component = NEUTRAL_DEFAULT if engagement_component is None else engagement_component
        sla_component = sla_compliance_pct if sla_compliance_pct is not None else NEUTRAL_DEFAULT
        resolution_component = _resolution_component_score(avg_resolution)
        resolution_component = NEUTRAL_DEFAULT if resolution_component is None else resolution_component

        score = round(
            engagement_component * 0.4 + sla_component * 0.3 + resolution_component * 0.3
        )

        results.append(ClientHealthSignal(
            client=name,
            health_score=score,
            status=(
                "healthy" if score >= 70 else
                "at_risk" if score >= 40 else "critical"
            ),
            avg_ticket_resolution_hours=avg_resolution,
            engagement_rate_pct=engagement_rate,
            sla_compliance_pct=sla_compliance_pct,
            unavailable_signals=unavailable,
        ))

    return ClientHealthResponse(
        clients=results,
        filters_applied={
            "date_from": date_from.isoformat() if date_from else None,
            "date_to": date_to.isoformat() if date_to else None,
        },
        data_source="analytics_events (metrics + ticket.opened/ticket.closed pairs)",
        limitations=[
            "sla_compliance_pct has no confirmed data source — Defect has no client_id "
            "in the shared schema (same limitation as /analytics/workload). Needs "
            "confirmation from Zeenat before this can be added. Until then, its "
            "health_score component defaults to a neutral 70.",
            "health_score is a weighted blend (engagement 40% / sla 30% / resolution "
            "30%, confirmed by Zeenat) where any missing signal's component defaults "
            "to a neutral 70 rather than being dropped from the average.",
        ],
    )


# =========================================================
# AI EVALUATION SUMMARY — exposes Asma's/Viqasha's benchmark results via a
# real endpoint instead of leaving them as standalone script output
# (asma_benchmark.py, vishaqa_benchmark.py). Read-only: this service does not
# run the benchmarks itself, it just serves the most recent report files each
# script already writes to evidence/.
# =========================================================

EVIDENCE_DIR = os.path.join(os.path.dirname(__file__), "evidence")
AI_EVAL_REPORT_FILES = {
    "asma": "asma_evaluation_report.json",
    "viqasha": "vishaqa_evaluation_report.json",
}


class ModuleSummary(BaseModel):
    module: str
    available: bool
    total_cases: Optional[int] = None
    passed: Optional[int] = None
    failed: Optional[int] = None
    pass_rate: Optional[float] = None
    corrections_logged: Optional[int] = None
    rule_version: Optional[str] = None
    generated_at: Optional[str] = None
    error: Optional[str] = None


class AIEvaluationSummaryResponse(BaseModel):
    modules: List[ModuleSummary]


def _load_module_summary(module: str, filename: str) -> ModuleSummary:
    path = os.path.join(EVIDENCE_DIR, filename)
    if not os.path.exists(path):
        return ModuleSummary(module=module, available=False, error=f"{filename} not found")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        summary = data.get("summary", {})
        return ModuleSummary(
            module=module,
            available=True,
            total_cases=summary.get("total_cases"),
            passed=summary.get("passed"),
            failed=summary.get("failed"),
            pass_rate=summary.get("pass_rate"),
            corrections_logged=summary.get("corrections_logged"),
            rule_version=summary.get("rule_version"),
            generated_at=summary.get("generated_at"),
        )
    except (json.JSONDecodeError, OSError) as e:
        return ModuleSummary(module=module, available=False, error=f"could not read {filename}: {e}")


@app.get("/quality/ai-evaluation/summary", response_model=AIEvaluationSummaryResponse)
def get_ai_evaluation_summary():
    """Serves the latest benchmark/correction counts for the Support/AI panel.
    Each module (asma, viqasha) reads its own most-recently-written report
    file from evidence/. If a module's benchmark hasn't been run yet, or its
    report file is missing/corrupt, that module comes back with
    available=false and an error message instead of failing the whole call —
    so the panel can show partial data rather than nothing."""
    modules = [
        _load_module_summary(module, filename)
        for module, filename in AI_EVAL_REPORT_FILES.items()
    ]
    return AIEvaluationSummaryResponse(modules=modules)


class MonthlyReportResponse(BaseModel):
    client: str
    period: str
    dataset: Dict
    completeness: Dict[str, str]

@app.get("/analytics/monthly-report", response_model=MonthlyReportResponse)
def get_monthly_report(client: str, month: str, db: Session = Depends(get_db)):
    tenant = get_or_create_dev_tenant(db)
    client_row = get_or_create_client(db, tenant.id, client)

    events = db.query(AnalyticsEvent).filter(
        AnalyticsEvent.tenant_id == tenant.id, AnalyticsEvent.client_id == client_row.id
    ).all()
    dataset = {"total_events": len(events)}
    completeness = {"instagram": "unavailable", "facebook": "unavailable"}

    parts = month.split("-")
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        raise HTTPException(
            status_code=400,
            detail="month must be in YYYY-MM format, e.g. 2026-08"
        )
    year, mon = parts
    year, mon = int(year), int(mon)
    if not (1 <= mon <= 12):
        raise HTTPException(status_code=400, detail="month value must be between 01 and 12")
    snapshot = ReportSnapshot(
        tenant_id=tenant.id,
        client_id=client_row.id,
        report_type="monthly",
        period_start=date(year, mon, 1),
        period_end=date(year, mon, calendar.monthrange(year, mon)[1]),
        dataset=json.dumps(dataset), completeness=json.dumps(completeness),
    )
    db.add(snapshot)
    db.commit()

    return MonthlyReportResponse(client=client, period=month, dataset=dataset, completeness=completeness)


# =========================================================
# TEAM WORKLOAD — Assignment §4 deliverable 9.
#
# REBUILT against real data, confirmed directly by Zeenat (2026-08-31):
# live task/defect data (owner, severity, actual/expected, status) lives in
# the shared `defects` table (the Defect model), not analytics_events.
# Zeenat's team subsequently added `due_date` (DateTime, nullable) and
# `is_blocked` (Boolean, default False) to Defect specifically so this
# endpoint could report real overdue/blocked metrics instead of the
# "unavailable" placeholder used while those fields didn't exist yet
# (confirmed present in packages/database/models.py as of migration
# 67c7b363204b_add_due_date_and_is_blocked_to_defect).
#
# (Earlier version of this endpoint assumed analytics_events with
# object_type="task" — confirmed wrong by Zeenat, replaced.)
#
# Bucketing (mutually exclusive, so buckets sum to total_tasks — this is
# what makes "metrics match underlying tasks", the doc's §4 evidence
# requirement, provable):
#   completed   = status == "closed"
#   blocked     = not completed AND is_blocked == True
#   overdue     = not completed, not blocked, due_date set AND due_date < now
#   in_progress = everything else (open/retested, not blocked, not overdue)
#
# NOTE: Defect has no client_id — defects aren't linked to a client in the
# shared schema — so client-level filtering isn't possible on this data
# source. The `client` param is accepted for API-shape compatibility but is
# not applied; `filters_applied.client` will always report null to make
# that limitation visible rather than silently ignoring the filter.
# =========================================================

class WorkloadResponse(BaseModel):
    client: Optional[str]
    total_tasks: int
    completed: int
    overdue: int
    blocked: int
    in_progress: int
    completion_rate: float
    filters_applied: Dict[str, Optional[str]]
    data_source: str
    limitations: List[str]

@app.get("/analytics/workload", response_model=WorkloadResponse)
def get_team_workload(
    client: Optional[str] = None,
    severity: Optional[str] = None,
    db: Session = Depends(get_db),
):
    tenant = get_or_create_dev_tenant(db)
    query = db.query(Defect).filter(Defect.tenant_id == tenant.id)

    if severity:
        query = query.filter(Defect.severity == severity)

    defects = query.all()
    # datetime.utcnow() is deprecated (Python 3.12+); this is the drop-in
    # replacement that still returns a naive UTC datetime, matching the
    # naive `due_date` column it's compared against below.
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    completed = overdue = blocked = in_progress = 0
    for d in defects:
        if d.status == "closed":
            completed += 1
        elif d.is_blocked:
            blocked += 1
        elif d.due_date is not None and d.due_date < now:
            overdue += 1
        else:
            in_progress += 1

    total = len(defects)
    completion_rate = round(completed / total, 4) if total else 0.0

    limitations = []
    if client:
        limitations.append(
            "client filter requested but not applied: the Defect table has no "
            "client_id in the shared schema, so workload cannot be scoped per client."
        )

    return WorkloadResponse(
        client=None,
        total_tasks=total,
        completed=completed,
        overdue=overdue,
        blocked=blocked,
        in_progress=in_progress,
        completion_rate=completion_rate,
        filters_applied={
            "client": None,
            "severity": severity,
        },
        data_source="defects (packages.database.models.Defect)",
        limitations=limitations,
    )


# =========================================================
# SCHEDULER CONSISTENCY — Assignment §4 deliverable 7.
#
# Doc requirement: "Display scheduled/published/failed data and event
# consistency." Evidence: "No false published status in analytics."
#
# REBUILT against real data, confirmed directly by Zeenat (2026-08-31):
# the scheduler does NOT emit analytics_events at all. It writes straight
# to the database:
#   - PublishingJob.status: queued -> processing -> completed / failed
#   - Campaign.status: draft -> pending_approval -> approved -> scheduled
#     -> published
# (Earlier version of this endpoint assumed "post.scheduled/published/
# failed" analytics_events existed — confirmed wrong, replaced.)
#
# Consistency rule (this IS the doc's "no false published status" check):
# a Campaign marked "published" is a FALSE published status if it has no
# PublishingJob with status "completed" backing it — either no job ran at
# all, or the only job(s) that ran ended in "failed". Both cases mean the
# analytics-visible "published" state doesn't match what actually happened
# during publishing.
# =========================================================

class SchedulerConsistencyResponse(BaseModel):
    client: Optional[str]
    total_scheduled: int
    total_published: int
    total_failed: int
    inconsistent_count: int
    inconsistent_campaign_ids: List[str]
    filters_applied: Dict[str, Optional[str]]

@app.get("/analytics/scheduler-consistency", response_model=SchedulerConsistencyResponse)
def get_scheduler_consistency(
    client: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    db: Session = Depends(get_db),
):
    tenant = get_or_create_dev_tenant(db)
    query = db.query(Campaign).filter(Campaign.tenant_id == tenant.id)

    if client:
        client_row = get_or_create_client(db, tenant.id, client)
        query = query.filter(Campaign.client_id == client_row.id)
    if date_from:
        query = query.filter(Campaign.created_at >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        query = query.filter(Campaign.created_at <= datetime.combine(date_to, datetime.max.time()))

    campaigns = query.all()

    total_scheduled = sum(1 for c in campaigns if c.status == "scheduled")
    total_published = sum(1 for c in campaigns if c.status == "published")

    # A campaign counts toward "failed" if ANY of its publishing jobs failed,
    # regardless of the campaign's own status field — this is what surfaces
    # a false "published" if the campaign status wasn't updated to match.
    inconsistent_ids: List[str] = []
    total_failed = 0
    for c in campaigns:
        jobs = c.publishing_jobs or []
        has_completed_job = any(j.status == "completed" for j in jobs)
        has_failed_job = any(j.status == "failed" for j in jobs)
        if has_failed_job:
            total_failed += 1
        if c.status == "published" and not has_completed_job:
            # False published status: analytics would show "published" with
            # nothing to prove it actually completed a publish job.
            inconsistent_ids.append(str(c.id))

    return SchedulerConsistencyResponse(
        client=client,
        total_scheduled=total_scheduled,
        total_published=total_published,
        total_failed=total_failed,
        inconsistent_count=len(inconsistent_ids),
        inconsistent_campaign_ids=inconsistent_ids,
        filters_applied={
            "client": client,
            "date_from": date_from.isoformat() if date_from else None,
            "date_to": date_to.isoformat() if date_to else None,
        },
    )