# Vishaqa - AI Support Intelligence Service

Part of the **NW Digital Operations Hub** monorepo (`apps/vishaqa-service/`).

Owner: **Vishaqa** — AI Support, Conversation Intelligence and Knowledge Lead

## 1. What this service does

This FastAPI service provides AI-assisted support intelligence for client tickets:

- Classifies incoming support messages (product, category, severity, owner team, confidence)
- Applies safety guardrails (security, financial, destructive-action, production-outage cases always require a human)
- Summarizes long client conversations (actions, dates, missing information, sentiment)
- Retrieves approved knowledge base articles (tenant-isolated, draft/unapproved articles never returned)
- Suggests safe replies strictly based on retrieved approved articles
- Determines escalation routing and acknowledgement targets based on severity
- Lets a human reviewer correct a wrong prediction (feedback loop for future calibration)

All results include `service_version` so responses are traceable to a specific rules version.

## 2. Tech stack

- **Framework:** FastAPI
- **DB access:** SQLAlchemy ORM, via shared `packages/database` (Postgres)
- **Validation:** Pydantic models
- **Local DB/cache:** Docker — `postgres:15-alpine`, `redis:7-alpine`

## 3. Setup (local development)

### Prerequisites
- Python 3.11+
- Docker Desktop (WSL2 backend on Windows)
- Access to the shared monorepo: `github.com/zeenatyousef/NW-digital-ops-hub`

### Steps

```powershell
# 1. Clone repo and enter project root
cd "A:\National Wireless\NW-digital-ops-hub"

# 2. Create and activate virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 3. Install dependencies
pip install -r requirements.txt

# 4. Start Docker containers (Postgres + Redis)
docker compose up -d

# 5. Apply database migrations
alembic upgrade head

# 6. Run the service
python -m uvicorn apps.vishaqa-service.main:app --port 8001 --reload
```

Swagger UI (interactive API docs): **http://127.0.0.1:8001/docs**

### Environment variables (`.env`)

```
DATABASE_URL=postgresql://nw_admin:nw_password_2026@localhost:5432/nw_digital_ops_hub
```

> Note: if a locally-installed Postgres service (e.g. `postgresql-x64-17`) is also running on port 5432, stop it or set its Startup Type to Manual — otherwise it will conflict with the Docker container and cause `password authentication failed` errors.

## 4. API Reference

All endpoints accept and return JSON. `tenant_id` must be a valid UUID string — invalid UUIDs are handled gracefully (no crash; empty/default result returned).

### `POST /support/classify`
Classifies a ticket message into product, category, severity, owner team, and confidence.

**Request**
```json
{
  "tenant_id": "d5de8b4d-b089-4d4e-9283-fd952f8df783",
  "message": "Production system is completely down",
  "client_id": null
}
```

**Response**
```json
{
  "product": "Production Outage",
  "category": "Critical production system down",
  "severity": "Critical",
  "owner_team": "Director/Escalation",
  "confidence": 0.9,
  "human_required": true,
  "service_version": "v1.0"
}
```

Logs to `ai_runs` and saves a row to `ticket_predictions`.

---

### `GET /support/health`
Simple readiness check.

**Response**
```json
{ "status": "ok", "service": "vishaqa-support-ai", "timestamp": "..." }
```

---

### `POST /support/summarize`
Summarizes a conversation thread: sentiment, extracted actions, dates, and missing information.

**Request**
```json
{
  "tenant_id": "...",
  "client_room_id": "...",
  "messages": [
    { "message_id": "m1", "sender": "client", "text": "Please fix this urgently", "timestamp": null }
  ]
}
```

**Response**
```json
{
  "summary_text": "...",
  "source_message_ids": ["m1"],
  "extracted_actions": ["Please fix this urgently"],
  "extracted_dates": [],
  "missing_information": ["No specific date mentioned"],
  "sentiment": "negative",
  "service_version": "v1.0"
}
```

Logs to `ai_runs` and saves to `conversation_summaries`.

---

### `POST /support/retrieve`
Returns approved knowledge base articles for a tenant/product. Draft, rejected, or other-tenant articles are never returned.

**Request**
```json
{
  "tenant_id": "...",
  "product": "FBR Digital Invoicing",
  "query": null
}
```

**Response**
```json
{
  "articles": [
    {
      "article_id": "...",
      "title": "How to resolve FBR invoice gateway errors",
      "product": "FBR Digital Invoicing",
      "risk_level": "low",
      "review_status": "approved"
    }
  ],
  "total_found": 1,
  "service_version": "v1.0"
}
```

---

### `POST /support/suggest-reply`
Suggests a safe reply strictly based on retrieved approved articles. Never auto-replies to guardrail (human-required) cases.

**Request**
```json
{
  "tenant_id": "...",
  "ticket_message": "My POS scanner isn't scanning barcodes",
  "product": "POS",
  "retrieved_article_ids": ["c5fb7f33-..."]
}
```

**Response**
```json
{
  "proposed_reply": "Thank you for reaching out. Based on our approved documentation ...",
  "human_required": false,
  "reasons": ["Reply generated from approved knowledge article(s) within guardrail policy."],
  "used_article_ids": ["c5fb7f33-..."],
  "service_version": "v1.0"
}
```

If `human_required` is `true`, `proposed_reply` is always `null`.

---

### `POST /support/escalation`
Determines escalation routing based on severity (auto-classified if not provided).

**Request**
```json
{
  "tenant_id": "...",
  "ticket_message": "Production system is completely down",
  "severity": null
}
```

**Response**
```json
{
  "severity": "Critical",
  "escalation_target": "Director/Escalation",
  "acknowledgement_target_minutes": 15,
  "escalation_required": true,
  "service_version": "v1.0"
}
```

Acknowledgement targets: Critical = 15 min, High = 60 min, Medium = 240 min, Low = 1440 min.

---

### `POST /support/predictions/correct`
Allows a human reviewer to correct a wrong prediction. Closes the feedback loop for calibration.

**Request**
```json
{
  "tenant_id": "...",
  "prediction_id": "d6c11a55-...",
  "actual_category": "POS device offline",
  "corrected_by_id": null
}
```

**Response**
```json
{
  "prediction_id": "d6c11a55-...",
  "predicted_category": "POS not scanning/printing",
  "actual_category": "POS device offline",
  "corrected": true,
  "service_version": "v1.0"
}
```

If the `prediction_id` does not belong to the given `tenant_id`, or either ID is not a valid UUID, `corrected: false` is returned and nothing is changed — this enforces tenant isolation (verified by testing).

## 5. Guardrail categories (always `human_required: true`)

- Suspected security incident/breach
- Password reset / login access / credentials
- Destructive action (delete/wipe data)
- Financial (refund/billing dispute)
- Production outage

Guardrails are intentionally **recall-biased**: broader synonym coverage on purpose, since missing a real security/financial/destructive/outage case is worse than one extra manual review.

## 6. Database tables owned/used

| Table | Purpose |
|---|---|
| `ticket_taxonomy` | Category/severity/owner mapping (design reference; classifier currently rule-based in code) |
| `kb_articles` | Approved knowledge articles; `review_status` and `risk_level` drive retrieval filtering |
| `ai_runs` | Logs every AI call: type, input, output, status |
| `ticket_predictions` | Stores predictions + human corrections (`actual_category`, `corrected_by_id`) |
| `conversation_summaries` | Stores generated conversation summaries |

Migrations are owned by Zeenat (`packages/database`) — do not create duplicate/isolated tables.

## 7. Known limitations

- Classification is rule/keyword-based (`classify_message()`), not an ML model — confidence scores are currently static per rule, not statistically calibrated against benchmark accuracy.
- `/support/retrieve` does not yet support semantic/embedding search (`kb_article_chunks.vector_embedding` exists in schema but is not queried yet) — it is a direct filtered SQL query on tenant/product/review_status.
- No explicit timeout-handling branch for downstream service calls (service is currently self-contained, no external AI API calls).
- UI screens (Support Inbox, Ticket Detail, Knowledge Base, Automation Center, Client Room) are not yet wired to these endpoints — integration is handled by Zeenat as platform lead, consuming this API.

## 8. Testing / Evaluation

- 105-case benchmark dataset: `NW_Vishaqa_Benchmark_Dataset.xlsx`
- Automated evaluation script: `run_benchmark.py` (runs live API calls, compares against expected labels)
- Evaluation report: `Vishaqa_Evaluation_Report.xlsx`
- Baseline accuracy 89.5% → 94.3% after classifier keyword-matching fix (word-boundary + multi-word combo matching)
- Accuracy improved further to 98.1% after fixing a guardrail priority-ordering bug: Hosting/Website "down" rules (priority 44/45) were matching before the Production Outage guardrail (priority 50), causing critical outage messages to incorrectly return `human_required: false`. Fixed by raising rule priorities to 55/56 in the shared migration (coordinated with Zeenat).
- Tenant isolation manually verified on `/support/predictions/correct` and `/support/retrieve` (wrong tenant_id / draft article correctly excluded)

## 9. Handover notes

| Item | Detail |
|---|---|
| Service entry point | `apps/vishaqa-service/main.py` |
| Run command | `python -m uvicorn apps.vishaqa-service.main:app --port 8001 --reload` |
| Owner | Vishaqa |
| Depends on | `packages/database` (models, session) — maintained by Zeenat |
| GitHub repo | `github.com/zeenatyousef/NW-digital-ops-hub` |
| Test tenant (local) | `d5de8b4d-b089-4d4e-9283-fd952f8df783` |
| To extend classifier | Edit `classify_message()` — add new word combos to the relevant `*_combos` list, or add a new product block following the existing pattern |
| To add KB filtering fields | Coordinate with Zeenat (migration owner) before adding columns to `kb_articles` |
