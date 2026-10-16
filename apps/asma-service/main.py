"""
apps/asma-service/main.py

NW Digital Operations Hub V3
Campaign, Calendar and Content AI Service — owned by Asma

Exposes the 6 marketing endpoints from the task assignment:
  POST /marketing/brief
  POST /marketing/calendar
  POST /marketing/content
  POST /marketing/translate
  POST /marketing/designer-brief
  POST /marketing/revise

Run locally:
  python -m uvicorn apps.asma-service.main:app --port 8002 --reload

NOTE: Port 8002 is a placeholder — confirm the assigned port with Zeenat
so the gateway proxy rules match. (.env.example already sets
ASMA_API_URL=http://localhost:8002, so 8002 is likely correct.)
"""

import os
import time
import uuid
import difflib
from datetime import datetime, timedelta
from typing import Optional
from enum import Enum

from fastapi import FastAPI, Depends, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from .groq_client import call_groq_json, GroqClientError
from .esha_client import get_hashtag_suggestions

# Only reading from the shared `messages` table here (owned by Zeenat) —
# not touching tenants/users/clients, and not writing to campaign_briefs
# yet since that table's final field shape is still pending from Zeenat.
from packages.database.session import get_db
from packages.database import models as db_models
from sqlalchemy.orm import Session
from sqlalchemy import text

load_dotenv()

# ---------------------------------------------------------------------------
# App setup — mirrors apps/core-gateway/main.py conventions
# ---------------------------------------------------------------------------

app = FastAPI(
    title="NW Digital Operations Hub - Marketing Intelligence Service",
    description="Campaign, Calendar and Content AI — owned by Asma",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_process_time_and_trace_id(request: Request, call_next):
    start_time = time.time()
    correlation_id = request.headers.get("X-Correlation-ID", f"trace-{int(time.time() * 1000)}")
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = str(process_time)
    response.headers["X-Correlation-ID"] = correlation_id
    return response


@app.get("/")
def read_root():
    return {
        "status": "online",
        "service": "Asma Marketing Intelligence Service",
        "version": "0.1.0",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


@app.get("/health")
def healthcheck(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as e:
        db_status = f"error: {e}"

    return {
        "status": "healthy",
        "database": db_status,
        "groq_api": "untested",
    }


# ---------------------------------------------------------------------------
# Shared enums / small models
# ---------------------------------------------------------------------------

class Platform(str, Enum):
    facebook = "facebook"
    instagram = "instagram"
    tiktok = "tiktok"
    linkedin = "linkedin"
    google_business = "google_business"
    whatsapp = "whatsapp"


class FieldConfidence(BaseModel):
    value: Optional[str] = None
    confidence: float = Field(ge=0.0, le=1.0)
    source_message_ids: list[str] = []


# ---------------------------------------------------------------------------
# 1. POST /marketing/brief
# ---------------------------------------------------------------------------

class BriefRequest(BaseModel):
    client_id: str
    tenant_id: str
    brand_profile_id: str  # required — campaign_briefs.brand_profile_id is not nullable
    source_message_ids: list[str]
    raw_text: Optional[str] = None  # combined client conversation text
    title: Optional[str] = None  # falls back to the extracted objective if not given


class BriefResponse(BaseModel):
    campaign_brief_id: str
    objective: FieldConfidence
    audience: FieldConfidence
    location: FieldConfidence
    offer: FieldConfidence
    dates: FieldConfidence
    deliverables: FieldConfidence
    platforms: FieldConfidence
    assets: FieldConfidence
    missing_fields: list[str]
    status: str = "draft"


BRIEF_SYSTEM_PROMPT = """You are a marketing operations assistant for a digital agency.
You extract structured campaign information from raw client conversation text.

Rules you must follow strictly:
- NEVER invent, guess, or infer facts that are not explicitly present in the text
  (no made-up prices, dates, offers, addresses, or claims).
- If a field is not mentioned in the text, its value must be null and it must be
  listed in "missing_fields".
- For every field you DO extract, give a confidence score between 0.0 and 1.0
  based on how explicitly it was stated (e.g. an exact date = high confidence,
  a vague implied timeframe = lower confidence).
- Respond with ONLY a single JSON object, no prose, no markdown fences.

Return JSON in exactly this shape:
{
  "objective": {"value": string|null, "confidence": float},
  "audience": {"value": string|null, "confidence": float},
  "location": {"value": string|null, "confidence": float},
  "offer": {"value": string|null, "confidence": float},
  "dates": {"value": string|null, "confidence": float},
  "deliverables": {"value": string|null, "confidence": float},
  "platforms": {"value": string|null, "confidence": float},
  "assets": {"value": string|null, "confidence": float},
  "missing_fields": [string, ...]
}
"""


@app.post("/marketing/brief", response_model=BriefResponse)
def generate_campaign_brief(payload: BriefRequest, db: Session = Depends(get_db)):
    """
    Extract objective, audience, location, offer, dates, deliverables,
    platforms, assets and missing information from client messages, and
    persist the result to campaign_briefs.

    Current state:
      - If payload.raw_text is given, uses it directly (useful for manual testing).
      - Otherwise fetches the messages in payload.source_message_ids from the
        shared `messages` table (read-only — owned by Zeenat), ordered by
        created_at, and concatenates their content as the source text.
      - Calls Groq (LLaMA 3.3 70B) with a structured-JSON-output prompt.
      - Persists the extracted fields to a new campaign_briefs row, linked
        to payload.brand_profile_id, with approval_status="pending".
    """
    raw_text = payload.raw_text

    if not raw_text:
        if not payload.source_message_ids:
            raise HTTPException(
                status_code=400,
                detail="Provide either raw_text or at least one source_message_id.",
            )

        messages = (
            db.query(db_models.Message)
            .filter(db_models.Message.id.in_([uuid.UUID(mid) for mid in payload.source_message_ids]))
            .order_by(db_models.Message.created_at.asc())
            .all()
        )

        if not messages:
            raise HTTPException(
                status_code=404,
                detail=f"No messages found for source_message_ids: {payload.source_message_ids}",
            )

        # Only use client-visible content — internal notes shouldn't leak into
        # a client-facing brief extraction.
        raw_text = "\n".join(
            m.content for m in messages if m.visibility == "external" and m.content
        )

        if not raw_text:
            raise HTTPException(
                status_code=422,
                detail="Matched messages contained no external/client-visible content to extract from.",
            )

    # Confirm the brand profile actually exists before we attach a brief to it —
    # the FK would fail anyway, but this gives a clean 404 instead of a DB error.
    brand_profile = (
        db.query(db_models.BrandProfile)
        .filter(db_models.BrandProfile.id == uuid.UUID(payload.brand_profile_id))
        .first()
    )
    if not brand_profile:
        raise HTTPException(
            status_code=404,
            detail=f"No brand_profile found with id: {payload.brand_profile_id}",
        )

    try:
        extracted = call_groq_json(
            system_prompt=BRIEF_SYSTEM_PROMPT,
            user_prompt=f"Client conversation:\n\n{raw_text}",
        )
    except GroqClientError as e:
        raise HTTPException(status_code=502, detail=f"Groq extraction failed: {e}")

    def build_field(key: str) -> FieldConfidence:
        field_data = extracted.get(key, {}) or {}
        return FieldConfidence(
            value=field_data.get("value"),
            confidence=field_data.get("confidence", 0.0),
            source_message_ids=payload.source_message_ids,
        )

    def value_of(key: str) -> Optional[str]:
        return (extracted.get(key, {}) or {}).get("value")

    missing_fields = extracted.get("missing_fields", [])
    title = payload.title or value_of("objective") or "Untitled campaign"

    brief_row = db_models.CampaignBrief(
        tenant_id=uuid.UUID(payload.tenant_id),
        brand_profile_id=uuid.UUID(payload.brand_profile_id),
        title=title,
        audience=value_of("audience"),
        location=value_of("location"),
        offer=value_of("offer"),
        dates=value_of("dates"),
        deliverables=value_of("deliverables"),
        platforms=value_of("platforms"),
        assets=value_of("assets"),
        source_message_ids=payload.source_message_ids,
        missing_fields=missing_fields,
        approval_status="pending",
    )
    db.add(brief_row)
    db.commit()
    db.refresh(brief_row)

    return BriefResponse(
        campaign_brief_id=str(brief_row.id),
        objective=build_field("objective"),
        audience=build_field("audience"),
        location=build_field("location"),
        offer=build_field("offer"),
        dates=build_field("dates"),
        deliverables=build_field("deliverables"),
        platforms=build_field("platforms"),
        assets=build_field("assets"),
        missing_fields=missing_fields,
        status=brief_row.approval_status,
    )


# ---------------------------------------------------------------------------
# 2. POST /marketing/calendar
# ---------------------------------------------------------------------------

class CalendarRequest(BaseModel):
    campaign_brief_id: str
    date_range_start: datetime
    date_range_end: datetime
    frequency: str  # "daily", "weekly", "3x_week", or "event_based"
    platforms: list[Platform]
    production_lead_days: int = 2
    owner: Optional[str] = None


class CalendarItem(BaseModel):
    id: str
    scheduled_date: datetime
    platform: Platform
    objective: str
    content_ref: Optional[str] = None
    design_ref: Optional[str] = None
    deadline: datetime
    status: str = "draft"
    owner: Optional[str] = None


class CalendarResponse(BaseModel):
    campaign_brief_id: str
    items: list[CalendarItem]


SUPPORTED_FREQUENCIES = {"daily", "weekly", "3x_week", "event_based"}


def _generate_schedule_dates(start: datetime, end: datetime, frequency: str) -> list[datetime]:
    """Pure date-sequencing logic — no AI involved, deterministic and testable."""
    if start > end:
        raise HTTPException(status_code=400, detail="date_range_start must be before date_range_end.")

    dates: list[datetime] = []

    if frequency == "event_based":
        dates = [start]

    elif frequency == "daily":
        current = start
        while current <= end:
            dates.append(current)
            current += timedelta(days=1)

    elif frequency == "weekly":
        current = start
        while current <= end:
            dates.append(current)
            current += timedelta(days=7)

    elif frequency == "3x_week":
        # Mon / Wed / Fri within the range, each week
        current = start
        while current <= end:
            if current.weekday() in (0, 2, 4):  # Mon=0, Wed=2, Fri=4
                dates.append(current)
            current += timedelta(days=1)

    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported frequency '{frequency}'. Use one of: {sorted(SUPPORTED_FREQUENCIES)}.",
        )

    return dates


@app.post("/marketing/calendar", response_model=CalendarResponse)
def generate_social_calendar(payload: CalendarRequest, db: Session = Depends(get_db)):
    """
    Generate editable weekly/monthly/event calendars with sequencing
    and realistic production deadlines from an APPROVED brief.

    - Verifies the campaign_brief exists and is approved before generating.
    - Builds a deterministic date sequence (no AI call needed here — this
      is scheduling logic, not extraction/generation).
    - Creates one calendar_items row per (date, platform) combination.
    - Each item's deadline is production_lead_days before its scheduled date.
    """
    brief = (
        db.query(db_models.CampaignBrief)
        .filter(db_models.CampaignBrief.id == uuid.UUID(payload.campaign_brief_id))
        .first()
    )
    if not brief:
        raise HTTPException(
            status_code=404,
            detail=f"No campaign_brief found with id: {payload.campaign_brief_id}",
        )
    if brief.approval_status != "approved":
        raise HTTPException(
            status_code=409,
            detail=f"campaign_brief {payload.campaign_brief_id} is not approved yet "
            f"(current status: '{brief.approval_status}'). Calendars can only be "
            "generated from approved briefs.",
        )
    if not payload.platforms:
        raise HTTPException(status_code=400, detail="At least one platform is required.")

    schedule_dates = _generate_schedule_dates(
        payload.date_range_start, payload.date_range_end, payload.frequency
    )
    if not schedule_dates:
        raise HTTPException(
            status_code=422,
            detail="No dates fell within the given range for this frequency.",
        )

    objective = brief.title or "Untitled campaign"
    created_rows = []

    for scheduled_date in schedule_dates:
        deadline = scheduled_date - timedelta(days=payload.production_lead_days)
        for platform in payload.platforms:
            row = db_models.CalendarItem(
                tenant_id=brief.tenant_id,
                campaign_brief_id=brief.id,
                scheduled_time=scheduled_date,
                platform=platform.value,
                objective=objective,
                status="draft",
                owner=payload.owner,
            )
            db.add(row)
            created_rows.append((row, deadline, platform))

    db.commit()
    for row, _, _ in created_rows:
        db.refresh(row)

    items = [
        CalendarItem(
            id=str(row.id),
            scheduled_date=row.scheduled_time,
            platform=platform,
            objective=row.objective,
            content_ref=None,  # linked once /marketing/content generates a content_version
            design_ref=None,   # linked once /marketing/designer-brief generates a designer_brief
            deadline=deadline,
            status=row.status,
            owner=row.owner,
        )
        for row, deadline, platform in created_rows
    ]

    return CalendarResponse(campaign_brief_id=str(brief.id), items=items)


# ---------------------------------------------------------------------------
# 3. POST /marketing/content
# ---------------------------------------------------------------------------

class ContentRequest(BaseModel):
    campaign_brief_id: str
    campaign_id: str  # content_versions.campaign_id is required — campaign_briefs
    # isn't linked to campaigns in the shared schema yet, so the caller
    # must supply which Campaign this content belongs to. Flag to Zeenat
    # if this should instead be a real FK on campaign_briefs.
    platforms: list[Platform]
    brand_profile_id: str


class PlatformContent(BaseModel):
    platform: Platform
    caption: str
    cta: str
    hashtags_ref: Optional[str] = None  # reference to Esha's hashtag signature, not duplicated
    word_count: int
    brand_rule_check: dict  # e.g. {"policy_risk": "none", "prohibited_terms_found": []}


class ContentResponse(BaseModel):
    campaign_brief_id: str
    versions: list[PlatformContent]


PLATFORM_CONSTRAINTS = {
    Platform.facebook: "Facebook: conversational, 1-3 short paragraphs OK, light emoji use, CTA can be a full sentence.",
    Platform.instagram: "Instagram: punchy and visual, short lines, emoji-friendly, CTA short and energetic.",
    Platform.tiktok: "TikTok: very casual, trend-aware tone, very short (under ~150 chars), CTA is a quick hook.",
    Platform.linkedin: "LinkedIn: professional tone, no excessive emoji, can be longer and more detailed, CTA is business-oriented.",
    Platform.google_business: "Google Business: concise, factual, local-intent (hours/location/offer), minimal emoji, CTA is direct (Call/Visit/Order).",
    Platform.whatsapp: "WhatsApp: personal and direct, like a message to a customer, short, CTA is a simple next step (reply/click).",
}

CONTENT_SYSTEM_PROMPT = """You are a social media copywriter. Given a campaign brief and a
brand profile, write ONE platform-specific caption and CTA for the platform described.

Rules:
- The caption MUST be written specifically for this platform's tone/length/format —
  never write generic copy that could be pasted onto any platform unchanged.
- Do NOT invent offers, prices, dates, or claims beyond what's given in the brief.
- Respect the brand voice and any required or prohibited wording given.
- Respond with ONLY a single JSON object, no prose, no markdown fences.

Return JSON in exactly this shape:
{"caption": string, "cta": string}
"""


def _check_brand_rules(text: str, brand_profile: "db_models.BrandProfile") -> dict:
    """
    Deterministic, code-based check — not left to the AI's judgment, since
    brand-rule compliance needs to be verifiable, not just self-reported.
    """
    text_lower = text.lower()
    issues = []

    if brand_profile.prohibited_wording:
        for term in brand_profile.prohibited_wording.split(","):
            term = term.strip()
            if term and term.lower() in text_lower:
                issues.append(f"prohibited term found: '{term}'")

    missing_required = []
    if brand_profile.required_wording:
        for term in brand_profile.required_wording.split(","):
            term = term.strip()
            if term and term.lower() not in text_lower:
                missing_required.append(term)

    return {
        "policy_risk": "high" if issues else "none",
        "prohibited_terms_found": issues,
        "missing_required_wording": missing_required,
    }


@app.post("/marketing/content", response_model=ContentResponse)
def generate_platform_content(payload: ContentRequest, db: Session = Depends(get_db)):
    """
    Generate distinct copy + CTA per platform. Never generate one
    identical caption for every platform (non-negotiable rule).

    - One Groq call per platform, each with platform-specific tone/length
      constraints baked into the prompt, so outputs are genuinely different.
    - Brand rule compliance (required/prohibited wording) is checked in code
      after generation, not left to the model's self-report.
    - hashtags_ref is a placeholder for now — pending Esha's hashtag-signature
      service details (asked, not yet confirmed). TODO: wire in once available.
    - Persists one NEW content_versions row per platform (never overwrites).
    """
    brief = (
        db.query(db_models.CampaignBrief)
        .filter(db_models.CampaignBrief.id == uuid.UUID(payload.campaign_brief_id))
        .first()
    )
    if not brief:
        raise HTTPException(status_code=404, detail=f"No campaign_brief found with id: {payload.campaign_brief_id}")

    brand_profile = (
        db.query(db_models.BrandProfile)
        .filter(db_models.BrandProfile.id == uuid.UUID(payload.brand_profile_id))
        .first()
    )
    if not brand_profile:
        raise HTTPException(status_code=404, detail=f"No brand_profile found with id: {payload.brand_profile_id}")

    campaign = (
        db.query(db_models.Campaign)
        .filter(db_models.Campaign.id == uuid.UUID(payload.campaign_id))
        .first()
    )
    if not campaign:
        raise HTTPException(status_code=404, detail=f"No campaign found with id: {payload.campaign_id}")

    if not payload.platforms:
        raise HTTPException(status_code=400, detail="At least one platform is required.")

    brief_context = (
        f"Objective/title: {brief.title}\n"
        f"Audience: {brief.audience or 'not specified'}\n"
        f"Location: {brief.location or 'not specified'}\n"
        f"Offer: {brief.offer or 'not specified'}\n"
        f"Dates: {brief.dates or 'not specified'}\n"
        f"Deliverables: {brief.deliverables or 'not specified'}\n"
    )
    brand_context = (
        f"Brand: {brand_profile.brand_name}\n"
        f"Brand voice: {brand_profile.brand_voice or 'not specified'}\n"
        f"Required wording: {brand_profile.required_wording or 'none'}\n"
        f"Prohibited wording: {brand_profile.prohibited_wording or 'none'}\n"
    )

    versions = []

    for platform in payload.platforms:
        user_prompt = (
            f"Platform: {platform.value}\n"
            f"Platform style guide: {PLATFORM_CONSTRAINTS[platform]}\n\n"
            f"Campaign brief:\n{brief_context}\n"
            f"Brand profile:\n{brand_context}"
        )

        try:
            result = call_groq_json(system_prompt=CONTENT_SYSTEM_PROMPT, user_prompt=user_prompt)
        except GroqClientError as e:
            raise HTTPException(status_code=502, detail=f"Groq content generation failed for {platform.value}: {e}")

        caption = result.get("caption", "")
        cta = result.get("cta", "")
        full_text = f"{caption} {cta}"

        rule_check = _check_brand_rules(full_text, brand_profile)

        # Ask Esha's hashtag/quality service for suggestions. This is
        # best-effort — get_hashtag_suggestions returns None (never raises)
        # if her service isn't reachable, e.g. because the gateway proxy
        # route isn't wired up yet. Content generation must not fail just
        # because hashtag suggestions aren't available.
        hashtag_result = get_hashtag_suggestions(
            client=brand_profile.brand_name,
            platform=platform.value,
            existing_tags=[],
        )
        hashtags_ref = None
        if hashtag_result and hashtag_result.get("recommended_tags"):
            hashtags_ref = ", ".join(hashtag_result["recommended_tags"])

        content_row = db_models.ContentVersion(
            campaign_id=campaign.id,
            version_number=1,
            ai_output=f"{caption}\n\nCTA: {cta}",
            status="pending",
            platform=platform.value,
            language="en",
            caption=caption,
            cta=cta,
            hashtags_reference=hashtags_ref,
        )
        db.add(content_row)
        db.commit()
        db.refresh(content_row)

        versions.append(
            PlatformContent(
                platform=platform,
                caption=caption,
                cta=cta,
                hashtags_ref=hashtags_ref,
                word_count=len(full_text.split()),
                brand_rule_check=rule_check,
            )
        )

    return ContentResponse(campaign_brief_id=str(brief.id), versions=versions)


# ---------------------------------------------------------------------------
# 4. POST /marketing/translate
# ---------------------------------------------------------------------------

class TranslateRequest(BaseModel):
    content_version_id: str
    target_language: str  # e.g. "es", "ur-Latn" (Roman Urdu)


class TranslateResponse(BaseModel):
    content_version_id: str
    translated_text: str
    target_language: str
    ambiguous_term_warnings: list[str] = []


TRANSLATE_SYSTEM_PROMPT = """You are a professional marketing translator. Translate the given
text into the target language while preserving names, offers, prices, dates, addresses,
phone numbers, and any required brand lines EXACTLY as given (do not translate proper
nouns, numbers, or fixed brand phrases — carry them over unchanged).

If any term in the source text is ambiguous or could be mistranslated (e.g. idioms,
brand-specific slang, a word with multiple possible meanings), list it in
"ambiguous_terms" instead of silently guessing a translation for it.

If the target language is "Roman Urdu" (Urdu written in Latin script), use everyday
Pakistani Urdu vocabulary and idiom — the words a Pakistani customer actually uses —
not Hindi/Sanskrit-origin vocabulary (e.g. use "khushi" or "maza" rather than "anand";
use "shukriya" rather than "dhanyavaad"). Do not borrow words that read as Hindi.

Respond with ONLY a single JSON object, no prose, no markdown fences.
Return JSON in exactly this shape:
{"translated_text": string, "ambiguous_terms": [string, ...]}
"""


@app.post("/marketing/translate", response_model=TranslateResponse)
def translate_content(payload: TranslateRequest, db: Session = Depends(get_db)):
    """
    Translate APPROVED content while preserving names, offers, dates,
    prices and required lines.

    - Only accepts a content_version with status == "approved".
    - Calls Groq with an entity-preservation prompt; ambiguous terms are
      flagged rather than silently guessed.
    - Persists the translation as a NEW content_versions row (never
      overwrites the approved source version) — same campaign/platform,
      language set to target_language, version_number incremented.
    """
    source = (
        db.query(db_models.ContentVersion)
        .filter(db_models.ContentVersion.id == uuid.UUID(payload.content_version_id))
        .first()
    )
    if not source:
        raise HTTPException(
            status_code=404,
            detail=f"No content_version found with id: {payload.content_version_id}",
        )
    if source.status != "approved":
        raise HTTPException(
            status_code=409,
            detail=f"content_version {payload.content_version_id} is not approved yet "
            f"(current status: '{source.status}'). Only approved content can be translated.",
        )

    source_text = f"{source.caption or ''}\n\nCTA: {source.cta or ''}".strip()
    if not source_text:
        raise HTTPException(status_code=422, detail="Source content_version has no caption/cta text to translate.")

    try:
        result = call_groq_json(
            system_prompt=TRANSLATE_SYSTEM_PROMPT,
            user_prompt=f"Target language: {payload.target_language}\n\nText to translate:\n{source_text}",
        )
    except GroqClientError as e:
        raise HTTPException(status_code=502, detail=f"Groq translation failed: {e}")

    translated_text = result.get("translated_text", "")
    ambiguous_terms = result.get("ambiguous_terms", [])

    # Next version number for this campaign+platform lineage
    latest_version_number = (
        db.query(db_models.ContentVersion.version_number)
        .filter(db_models.ContentVersion.campaign_id == source.campaign_id)
        .order_by(db_models.ContentVersion.version_number.desc())
        .first()
    )
    next_version = (latest_version_number[0] if latest_version_number else source.version_number) + 1

    translated_row = db_models.ContentVersion(
        campaign_id=source.campaign_id,
        version_number=next_version,
        ai_output=translated_text,
        status="pending",  # translated output needs its own approval, not auto-approved
        platform=source.platform,
        language=payload.target_language,
        caption=translated_text,
        cta=None,  # translated_text already includes the CTA inline
        hashtags_reference=source.hashtags_reference,
    )
    db.add(translated_row)
    db.commit()
    db.refresh(translated_row)

    return TranslateResponse(
        content_version_id=str(translated_row.id),
        translated_text=translated_text,
        target_language=payload.target_language,
        ambiguous_term_warnings=ambiguous_terms,
    )


# ---------------------------------------------------------------------------
# 5. POST /marketing/designer-brief
# ---------------------------------------------------------------------------

class DesignerBriefRequest(BaseModel):
    content_version_id: str
    approved_media_ids: list[str]  # must reference existing approved assets only


class DesignerBriefResponse(BaseModel):
    designer_brief_id: str
    main_heading: str
    supporting_text: str
    cta: str
    visual_direction: str
    asset_references: list[str]
    sizes: list[str]
    logo_qr_rules: str
    restrictions: str


DESIGNER_BRIEF_SYSTEM_PROMPT = """You are a marketing designer-brief writer. Given approved
campaign copy, write clear instructions for a graphic designer to turn it into a poster/ad.

Rules:
- Do NOT invent product claims, offers, or images beyond what's in the source copy.
- visual_direction should describe mood/composition/color guidance, not name a specific
  stock image or invented product photo.
- Keep main_heading short (a few words), supporting_text can be a sentence or two.
- Suggest 2-4 common ad sizes (e.g. "1080x1080 square", "1080x1920 story") appropriate
  for the platform if you can tell it from the copy, otherwise general social sizes.
- Respond with ONLY a single JSON object, no prose, no markdown fences.

Return JSON in exactly this shape:
{
  "main_heading": string,
  "supporting_text": string,
  "visual_direction": string,
  "sizes": [string, ...],
  "logo_qr_rules": string,
  "restrictions": string
}
"""


@app.post("/marketing/designer-brief", response_model=DesignerBriefResponse)
def generate_designer_brief(payload: DesignerBriefRequest, db: Session = Depends(get_db)):
    """
    Generate exact text hierarchy, visual direction, assets, size and
    restrictions. Must use approved_media_ids only — never invent
    product images (non-negotiable rule). Does not control logo lock
    (that's a fixed rule, not something the AI decides — see logo_qr_rules
    in the response, which states the constraint rather than overriding it).

    NOTE: there's no assets/media table in the shared schema yet, so
    approved_media_ids can't be validated against the DB — they're taken
    as given and passed through as asset_references. Flag to Zeenat if/when
    a media table exists so this can be validated properly.
    """
    content_version = (
        db.query(db_models.ContentVersion)
        .filter(db_models.ContentVersion.id == uuid.UUID(payload.content_version_id))
        .first()
    )
    if not content_version:
        raise HTTPException(
            status_code=404,
            detail=f"No content_version found with id: {payload.content_version_id}",
        )
    if content_version.status != "approved":
        raise HTTPException(
            status_code=409,
            detail=f"content_version {payload.content_version_id} is not approved yet "
            f"(current status: '{content_version.status}'). Designer briefs are only "
            "generated from approved content.",
        )
    if not payload.approved_media_ids:
        raise HTTPException(
            status_code=400,
            detail="At least one approved_media_id is required — designer briefs can't "
            "reference invented images.",
        )

    campaign = (
        db.query(db_models.Campaign)
        .filter(db_models.Campaign.id == content_version.campaign_id)
        .first()
    )

    source_copy = (
        f"Platform: {content_version.platform}\n"
        f"Caption: {content_version.caption}\n"
        f"CTA: {content_version.cta or 'not specified'}\n"
    )

    try:
        result = call_groq_json(
            system_prompt=DESIGNER_BRIEF_SYSTEM_PROMPT,
            user_prompt=f"Approved campaign copy:\n\n{source_copy}",
        )
    except GroqClientError as e:
        raise HTTPException(status_code=502, detail=f"Groq designer-brief generation failed: {e}")

    logo_qr_rules = result.get("logo_qr_rules") or "Do not move, resize, recolor, or otherwise alter the approved logo lock-up."

    brief_row = db_models.DesignerBrief(
        tenant_id=campaign.tenant_id if campaign else None,
        campaign_id=content_version.campaign_id,
        content_version_id=content_version.id,
        main_heading=result.get("main_heading", ""),
        supporting_text=result.get("supporting_text", ""),
        cta=content_version.cta or result.get("cta", ""),
        visual_direction=result.get("visual_direction", ""),
        asset_references=", ".join(payload.approved_media_ids),
        sizes=", ".join(result.get("sizes", [])),
        logo_qr_rules=logo_qr_rules,
        restrictions=result.get("restrictions", ""),
    )
    db.add(brief_row)
    db.commit()
    db.refresh(brief_row)

    return DesignerBriefResponse(
        designer_brief_id=str(brief_row.id),
        main_heading=brief_row.main_heading,
        supporting_text=brief_row.supporting_text,
        cta=brief_row.cta,
        visual_direction=brief_row.visual_direction,
        asset_references=payload.approved_media_ids,
        sizes=result.get("sizes", []),
        logo_qr_rules=brief_row.logo_qr_rules,
        restrictions=brief_row.restrictions,
    )


# ---------------------------------------------------------------------------
# 6. POST /marketing/revise
# ---------------------------------------------------------------------------

class ReviseRequest(BaseModel):
    content_version_id: str  # the version being revised
    reviewer_comments: str
    reviewer_id: str


class ReviseResponse(BaseModel):
    new_content_version_id: str
    version_number: int
    diff_summary: str


REVISE_SYSTEM_PROMPT = """You are editing existing approved marketing copy based on a
reviewer's comment. Apply ONLY the change the reviewer asked for — do not rewrite,
rephrase, or "improve" anything else in the text. Keep everything the reviewer didn't
mention exactly as it was.

Respond with ONLY a single JSON object, no prose, no markdown fences.
Return JSON in exactly this shape:
{"revised_caption": string, "revised_cta": string}
"""


def _word_diff_summary(original: str, revised: str) -> str:
    """
    Code-computed diff (not AI-narrated) so the diff is trustworthy evidence
    of exactly what changed — matches the task's "Version diff" test evidence.
    """
    original_words = original.split()
    revised_words = revised.split()
    diff = difflib.ndiff(original_words, revised_words)
    changes = [d for d in diff if d.startswith("+ ") or d.startswith("- ")]
    return " ".join(changes) if changes else "No word-level changes detected."


@app.post("/marketing/revise", response_model=ReviseResponse)
def apply_revision(payload: ReviseRequest, db: Session = Depends(get_db)):
    """
    Apply reviewer comments to a NEW version. Never overwrite an
    existing content_version — the source row is left untouched, and a
    new row is created with an incremented version_number.

    - Groq is instructed to change ONLY what the reviewer's comment asks for.
    - The diff shown to the reviewer is computed in code (word-level diff),
      not self-reported by the model, so it's reliable evidence of exactly
      what changed — catching unrelated changes is the whole point of this
      endpoint's test requirement.
    """
    source = (
        db.query(db_models.ContentVersion)
        .filter(db_models.ContentVersion.id == uuid.UUID(payload.content_version_id))
        .first()
    )
    if not source:
        raise HTTPException(
            status_code=404,
            detail=f"No content_version found with id: {payload.content_version_id}",
        )

    reviewer = (
        db.query(db_models.User)
        .filter(db_models.User.id == uuid.UUID(payload.reviewer_id))
        .first()
    )
    if not reviewer:
        raise HTTPException(status_code=404, detail=f"No user found with id: {payload.reviewer_id}")

    original_text = f"{source.caption or ''} CTA: {source.cta or ''}".strip()

    try:
        result = call_groq_json(
            system_prompt=REVISE_SYSTEM_PROMPT,
            user_prompt=(
                f"Original caption: {source.caption}\n"
                f"Original CTA: {source.cta}\n\n"
                f"Reviewer comment: {payload.reviewer_comments}"
            ),
        )
    except GroqClientError as e:
        raise HTTPException(status_code=502, detail=f"Groq revision failed: {e}")

    revised_caption = result.get("revised_caption", source.caption)
    revised_cta = result.get("revised_cta", source.cta)
    revised_text = f"{revised_caption or ''} CTA: {revised_cta or ''}".strip()

    diff_summary = _word_diff_summary(original_text, revised_text)

    latest_version_number = (
        db.query(db_models.ContentVersion.version_number)
        .filter(db_models.ContentVersion.campaign_id == source.campaign_id)
        .order_by(db_models.ContentVersion.version_number.desc())
        .first()
    )
    next_version = (latest_version_number[0] if latest_version_number else source.version_number) + 1

    revised_row = db_models.ContentVersion(
        campaign_id=source.campaign_id,
        version_number=next_version,
        ai_output=revised_text,
        status="pending",  # a revision needs its own review, not auto-approved
        platform=source.platform,
        language=source.language,
        caption=revised_caption,
        cta=revised_cta,
        hashtags_reference=source.hashtags_reference,
        reviewer_id=reviewer.id,
    )
    db.add(revised_row)
    db.commit()
    db.refresh(revised_row)

    return ReviseResponse(
        new_content_version_id=str(revised_row.id),
        version_number=revised_row.version_number,
        diff_summary=diff_summary,
    )


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8002))
    host = os.getenv("HOST", "0.0.0.0")
    uvicorn.run(app, host=host, port=port)