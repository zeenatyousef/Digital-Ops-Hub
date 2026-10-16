# asma-service — Campaign, Calendar and Content AI

Marketing intelligence service for NW Digital Operations Hub V3. Converts
verified client requests into structured campaign briefs, social calendars,
platform-specific content, translations, and designer/poster instructions.

Owned by: Asma (Campaign, Calendar and Content AI Lead)

---

## What this service does

| Endpoint | Purpose |
|---|---|
| `POST /marketing/brief` | Extract a structured campaign brief from client messages or raw text |
| `POST /marketing/calendar` | Generate a scheduled calendar of posts from an **approved** brief |
| `POST /marketing/content` | Generate distinct per-platform captions/CTAs with brand-rule checks |
| `POST /marketing/translate` | Translate **approved** content while preserving names/prices/dates |
| `POST /marketing/designer-brief` | Generate poster/designer instructions from **approved** content |
| `POST /marketing/revise` | Apply a targeted reviewer edit as a new content version |

See `PROMPTS.md` for the reasoning behind each endpoint's Groq prompt.

---

## Setup

### 1. Prerequisites
- Python 3.13+
- Docker Desktop (for Postgres + Redis)
- A Groq API key: https://console.groq.com/keys

### 2. Install dependencies
From the repo root:
```bash
pip install -r requirements.txt
```

### 3. Environment variables
Copy `.env.example` to `.env` in the repo root and fill in:

| Variable | Purpose | Notes |
|---|---|---|
| `DATABASE_URL` | Postgres connection string | Local dev may need a remapped port if 5432 conflicts with another project (this dev environment uses 5433) |
| `REDIS_URL` | Redis connection string | Same — local dev used 6380 to avoid a port conflict |
| `GROQ_API_KEY` | Groq API key | **Required** — service returns a clear error on startup calls if missing, does not silently degrade |
| `ASMA_API_URL` | This service's own address | Used by the gateway to route `/marketing/*` requests here (default `http://localhost:8002`) |
| `ESHA_API_URL` | Esha's hashtag/quality service | Used by `/marketing/content` for hashtag suggestions — see "Known limitations" below |

### 4. Start the database
From the repo root:
```bash
docker-compose up -d
docker ps   # confirm nw-digital-ops-db and nw-digital-ops-redis are Up
```

### 5. Run migrations
```bash
python -m alembic upgrade head
```

### 6. Run the service
```bash
python -m uvicorn apps.asma-service.main:app --port 8002 --reload
```

### 7. Verify
- `http://localhost:8002/health` → should show `"database": "connected"`
- `http://localhost:8002/docs` → interactive Swagger UI for all 6 endpoints

---

## Testing

- `TEST_REPORT.md` — full results against the task assignment's Testing
  Responsibilities table (brief extraction, platform adaptation, brand
  compliance, multilingual, revision, failure/fallback). All groups PASS.
- `apps/asma-service/seed_test_data.py` — creates a minimal test
  Tenant → Client → BrandProfile → Campaign chain for manual `/docs` testing.
  Not committed; run locally as needed.
- `apps/asma-service/uat_seed_scenarios.py` — creates 2 realistic UAT
  scenarios (a restaurant with halal compliance rules, a fashion boutique
  with a dual B2B/B2C audience) with sample client request text ready to
  feed into `/marketing/brief`. Also not committed.

---

## Known limitations

1. **Esha's hashtag service isn't gateway-reachable yet.** `/marketing/content`
   calls `esha_client.py`, which degrades gracefully — `hashtags_ref` comes
   back `null` if her service can't be reached, but the request never fails
   because of it. Once Zeenat wires the gateway proxy route and
   `ESHA_API_URL` points at it, this starts working with no code changes.

2. **`campaign_briefs` isn't linked to `campaigns`.** The shared schema has
   no foreign key between them, so `/marketing/content` requires the caller
   to separately supply a `campaign_id` (needed because `content_versions`
   belongs to `campaigns`, not `campaign_briefs`). Flagged to Zeenat as a
   potential schema improvement.

3. **No assets/media table exists yet.** `/marketing/designer-brief` accepts
   `approved_media_ids` as given, with no DB validation that they're real,
   approved assets. Flagged to Zeenat.

4. **Confidence scores on `/marketing/brief`** are the model's own
   self-assessed certainty — useful as a signal for a human reviewer, not
   an independently verified guarantee.

---

## Deployment notes

- Groq model is currently `openai/gpt-oss-120b` (see `groq_client.py`) —
  if Groq deprecates this model too, update `GROQ_MODEL` in one place.
- All 5 AI-backed endpoints degrade to a clean `502` (via `GroqClientError`)
  if Groq is unreachable or returns malformed output — no raw exception is
  ever shown to the caller, and no content is invented as a fallback.
- Database connection failures surface as clean `500`s via SQLAlchemy —
  same principle, no silent wrong answers.