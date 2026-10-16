# Handover Notes — Campaign, Calendar and Content AI Module

**Module owner (during build):** Asma
**Role:** Campaign, Calendar and Content AI Lead
**Handover date:** August 2026

This document is for whoever maintains this module after handover —
where things live, who to contact for what, and how to keep it running.

---

## 1. Files and what they do

All module code lives in `apps/asma-service/`:

| File | Purpose |
|---|---|
| `main.py` | FastAPI app — all 6 endpoints, request/response models, business logic |
| `groq_client.py` | Groq API wrapper — model config, JSON-mode calls, error handling |
| `esha_client.py` | Calls Esha's hashtag/quality service, degrades gracefully if unreachable |
| `README.md` | Setup instructions, environment variables, known limitations |
| `PROMPTS.md` | Why each Groq prompt is shaped the way it is — read this before changing any prompt |
| `TEST_REPORT.md` | Full test results against the task's Testing Responsibilities table |
| `seed_test_data.py` | Dev helper — creates minimal test data. Not for production use. |
| `uat_seed_scenarios.py` | Dev helper — creates 2 realistic UAT scenarios. Not for production use. |

Shared database models this module owns (in `packages/database/models.py`,
shared file — owned jointly with Zeenat):
`BrandProfile`, `CampaignBrief`, `CalendarItem`, `DesignerBrief`, plus
marketing-specific fields on the shared `ContentVersion` table
(`platform`, `language`, `caption`, `cta`, `hashtags_reference`, `reviewer_id`).

---

## 2. Who owns what

| Area | Owner | Contact for |
|---|---|---|
| This module's endpoints/logic | Asma | Bugs in brief/calendar/content/translate/designer-brief/revise logic, prompt behavior |
| Gateway, DB schema, UI integration, deployment | Zeenat | Routing, migrations, Content Studio/Poster Studio screens, production infra |
| Hashtag/quality scoring | Esha | `/quality/hashtags/suggest` behavior, hashtag suggestions returning null |
| Source conversation summaries | Viqasha | Message summarization feeding into brief extraction |

---

## 3. Environment / secrets

- `GROQ_API_KEY` — required. Get a new one at https://console.groq.com/keys
  if it's ever rotated/revoked. **If this is ever unset, do not assume the
  service silently falls back to something safe** — check `groq_client.py`
  for the current mock-mode behavior (see Section 5, "Watch out for," below).
- `ESHA_API_URL` — points at Esha's service. Update this if/when the gateway
  proxy route to her service changes.
- `DATABASE_URL` / `REDIS_URL` — standard shared connection strings, see
  root `.env.example`.

---

## 4. Maintenance steps

### Adding a new platform to `/marketing/content`
1. Add it to the `Platform` enum in `main.py`.
2. Add a matching entry to `PLATFORM_CONSTRAINTS` describing that
   platform's tone/length/format norms.
3. No other changes needed — the endpoint loops over whatever platforms
   are requested.

### Changing a Groq prompt
1. Read the relevant section in `PROMPTS.md` first — most prompts encode a
   specific fix for a specific failure mode (e.g. the Roman Urdu
   vocabulary fix). Changing wording carelessly can reintroduce old bugs.
2. Test against `uat_seed_scenarios.py`'s two scenarios after any prompt
   change — they cover two different tones/rule sets and catch regressions
   that a single generic test case wouldn't.

### If Groq deprecates the current model
`GROQ_MODEL` is a single constant in `groq_client.py`. This already
happened once (`llama-3.3-70b-versatile` → `openai/gpt-oss-120b`,
Aug 2026) — check https://console.groq.com/docs/models for current
supported models, update the constant, redeploy.

### Running migrations for this module's tables
Standard Alembic flow from the repo root:
```bash
python -m alembic upgrade head
```
Any new fields on `BrandProfile`/`CampaignBrief`/`CalendarItem`/
`DesignerBrief` go through Zeenat's shared `packages/database/models.py`
and a new Alembic migration — same process used to originally add these
tables (see migration `a93c726359f1_update_asma_module_schemas`).

---

## 5. Watch out for

1. **Mock-mode fallback in `groq_client.py`.** As of the last handover
   check, a fallback exists that returns hardcoded content when
   `GROQ_API_KEY` is missing or starts with `"gsk_mock"`, intended for
   offline/local testing. This was flagged to Zeenat as a risk — if this
   is still keyed on a missing/prefixed API key rather than an explicit
   `MOCK_MODE` flag, it can silently return invented content in a real
   environment with no visible error. **Confirm this has been gated
   behind an explicit opt-in flag before relying on `/health` or `502`
   errors as your signal that Groq is actually being called.**

2. **`campaign_briefs` isn't linked to `campaigns`.** `/marketing/content`
   requires the caller to separately supply `campaign_id` because of this
   schema gap. If this is fixed later (a real FK added), the endpoint can
   be simplified to look it up instead of requiring it as input — but
   that's a breaking API change, coordinate with whoever's consuming it.

3. **No assets/media table exists.** `approved_media_ids` on
   `/marketing/designer-brief` aren't validated against the database —
   any string is accepted. If a real media table gets added, add validation
   here so invalid/unapproved IDs are rejected rather than silently passed
   through.

4. **Esha's hashtag service reachability.** `hashtags_ref` on
   `/marketing/content` will keep coming back `null` until
   `ESHA_API_URL` points at a gateway-routed address that's actually
   reachable from this service. This fails silently by design (content
   generation shouldn't break because hashtags aren't available) — so a
   consistently-null `hashtags_ref` isn't necessarily a bug, check
   connectivity to Esha's service first.

5. **Confidence scores on `/marketing/brief`** are the model's own
   self-reported certainty, not independently verified. Don't build
   automated decisions (e.g. auto-approve above some confidence threshold)
   on top of them without separately validating that they're well-calibrated.

---

## 6. Where to find more

- Full API contracts (request/response shapes, error codes): `/docs`
  (Swagger UI) when the service is running, or read the Pydantic models
  directly in `main.py`.
- Design rationale for prompts: `PROMPTS.md`
- Test evidence: `TEST_REPORT.md`
- Original task assignment (scope, non-negotiable rules, day-by-day plan):
  see the project's task assignment PDF, kept by National Wireless management.