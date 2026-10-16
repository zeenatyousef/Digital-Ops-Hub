# esha-service API Specification

Base URL (local dev): `http://localhost:8003`
All request/response bodies are JSON. All endpoints are tenant-scoped internally; tenant
identity and permission enforcement happen upstream at the core/gateway API per §2.3 of the
task doc — this service does not implement its own auth.

---

## `GET /health`

Liveness check.

**Response `200`**
```json
{ "status": "ok", "service": "esha-service", "tenants_in_db": 3 }
```

---

## `POST /quality/hashtags/suggest`

> **Naming note:** the task doc (§5) lists a single `POST /quality/hashtags`. That's
> implemented here as two endpoints — `suggest` (recommend + score, read-only) and `save`
> (persist a signature) — because they're different operations with different request/
> response shapes and side effects; a single combined endpoint would need a mode flag to
> distinguish "just evaluate this" from "commit this as a reusable signature." Both are
> filtered by client/location/platform/banned/duplicate per §5's minimum rules.

Returns recommended tags for a client/platform plus warnings on the tags submitted.

**Request**
```json
{
  "tags": ["#BebopStaplesMill", "#f4f", "#love", "#love"],
  "client": "bebop",
  "platform": "instagram"
}
```

**Response `200`**
```json
{
  "recommended_tags": ["#BebopStaplesMill", "#RichmondEats", "#RVAFood", "#HalalFoodRVA"],
  "warnings": [
    { "type": "banned", "tag": "#f4f", "message": "'#f4f' is on the banned list." },
    { "type": "duplicate", "tag": "#love", "message": "'#love' was submitted more than once." }
  ],
  "quality_score": 60
}
```

**Scoring:** starts at 100; −30 per banned tag, −10 per duplicate, −20 if >40% of submitted
tags are generic/high-volume (spam risk). Floors at 0.

**Errors:** `422` on missing/malformed fields (standard FastAPI/Pydantic validation).

---

## `POST /quality/hashtags/save`

Saves a new, versioned hashtag set for a client/platform. Previous versions are kept
(deactivated, not deleted).

**Request**
```json
{
  "client": "bebop",
  "platform": "instagram",
  "category": "brand",
  "tags": ["#BebopStaplesMill", "#RichmondEats", "#RVAFood"]
}
```
`category` is one of `brand | local | campaign | industry` (defaults to `brand`).

**Response `200`**
```json
{
  "hashtag_set_id": "6f2a1e3d-...",
  "version": 2,
  "saved_tags": ["#BebopStaplesMill", "#RichmondEats", "#RVAFood"]
}
```

**Errors:** `422` on missing/malformed fields.

---

## `POST /quality/content`

Scores a caption for clarity, CTA strength, brand-rule compliance, and duplicate risk.

**Request**
```json
{
  "caption": "Visit us today, this deal is 100% risk-free and guaranteed!",
  "client": "bebop"
}
```

**Response `200`**
```json
{
  "score": 47,
  "label": "Needs Work",
  "brand_match": 30,
  "clarity": 100,
  "cta_strength": 100,
  "duplicate_risk": "Low",
  "issues": [
    { "severity": "critical", "location": "whole caption", "message": "Prohibited phrase used: '100% risk-free'." },
    { "severity": "critical", "location": "whole caption", "message": "Prohibited phrase used: 'guaranteed'." }
  ]
}
```

**Checks performed:** sentence length (>30 words → clarity penalty), CTA-word presence,
prohibited-phrase matches, excessive word repetition (3+ occurrences, stopwords/CTA words
excluded), email in caption not matching the client's registered `contact_email`, phone
numbers detected (flagged for manual check, not auto-verified — see README limitations).
`duplicate_risk` reuses the same similarity logic as `/quality/similarity` against the
client's last 50 content-quality runs.

**Overall score** = `0.3×clarity + 0.3×cta_strength + 0.4×brand_match`, rounded.

**Errors:** `422` on missing/malformed fields.

---

## `POST /quality/similarity`

Checks a caption against a client's recent content for near-duplicates.

**Request**
```json
{
  "caption": "Visit us today for our biggest sale of the year!",
  "client": "bebop",
  "threshold": 0.85
}
```
`threshold` is optional, default `0.85`.

**Response `200`**
```json
{
  "is_near_duplicate": true,
  "similarity_score": 0.91,
  "source_ids": ["a1b2c3d4-..."]
}
```
`similarity_score` is a word-overlap ratio (0.0–1.0) against the closest match among the
client's last 50 content-quality runs. `source_ids` is empty when no duplicate is found.

**Errors:** `422` on missing/malformed fields.

---

## `POST /analytics/event`

Idempotent ingestion of a normalized operational event.

**Request**
```json
{
  "event_type": "post.published",
  "object_type": "post",
  "object_id": "d290f1ee-6c54-4b01-90e6-d701748f0851",
  "event_key": "post-published-d290f1ee-2026-08-25",
  "client": "bebop",
  "metrics": { "reach": 1200, "engagement": 45 },
  "source": "scheduler-service"
}
```
`object_id` should be a UUID; non-UUID values are still accepted and preserved in
`event_data` rather than dropped. `event_key` is the idempotency key — replays with the
same key return the original event, not a duplicate row.

**Response `200` — first ingestion**
```json
{ "accepted": true, "duplicate": false, "event_id": "7c9e6679-..." }
```

**Response `200` — replay of the same `event_key`**
```json
{ "accepted": true, "duplicate": true, "event_id": "7c9e6679-..." }
```

**Errors:** `422` on missing/malformed fields.

---

## `GET /analytics/dashboard`

Role/client/date-filtered event summary.

**Query parameters** (all optional)

| Param | Type | Notes |
|---|---|---|
| `client` | string | Filters to one client |
| `date_from` | date (`YYYY-MM-DD`) | Inclusive |
| `date_to` | date (`YYYY-MM-DD`) | Inclusive |
| `role` | string | One of `marketing`, `support`, `management` |

**Example:** `GET /analytics/dashboard?client=bebop&role=marketing&date_from=2026-08-01`

**Response `200`**
```json
{
  "total_events": 14,
  "by_type": { "post.published": 9, "campaign.started": 5 },
  "filters_applied": { "client": "bebop", "date_from": "2026-08-01", "date_to": null, "role": "marketing" }
}
```
`role=marketing` restricts to event types prefixed `post.`/`campaign.`; `support` restricts
to `ticket.`; `management` sees everything (no restriction). This is data-level filtering
within this service's own tables — tenant/permission enforcement itself is the core API's
responsibility (§5).

**Errors:** `400` if `role` is not one of the known values.

---

## `GET /analytics/monthly-report`

Per-client monthly dataset with completeness flags.

**Query parameters** (both required)

| Param | Type | Notes |
|---|---|---|
| `client` | string | |
| `month` | string | `YYYY-MM` format |

**Example:** `GET /analytics/monthly-report?client=bebop&month=2026-08`

**Response `200`**
```json
{
  "client": "bebop",
  "period": "2026-08",
  "dataset": { "total_events": 14 },
  "completeness": { "instagram": "unavailable", "facebook": "unavailable" }
}
```
Per §10 (non-negotiable), missing platform data is always reported as `"unavailable"`,
never as `0`.

**Errors:** `400` if `month` is not `YYYY-MM` or the month value is outside 01–12.

---

## `GET /analytics/client-summary`

Client performance summary — reach, engagement, leads, profitability, and ticket
resolution, aggregated from real `analytics_events`. Powers the Analytics screen's
top-row cards and Client Performance chart (Assignment §2.3 / §3).

> **Frontend status:** gateway-verified (DEF-010, closed) but not yet consumed by any
> frontend screen — tracked as an open follow-up in `HANDOVER.md`/`section12_walkthrough.md`,
> not a defect.

**Query parameters** (all optional)

| Param | Type | Notes |
|---|---|---|
| `client` | string | filters to one client |
| `date_from` | date | `YYYY-MM-DD` |
| `date_to` | date | `YYYY-MM-DD` |

**Example:** `GET /analytics/client-summary?client=bebop&date_from=2026-08-01`

**Response `200`**
```json
{
  "total_reach": 1200,
  "engagement_rate_pct": 6.8,
  "leads": null,
  "profitability_pct": null,
  "avg_ticket_resolution_hours": 3.2,
  "client_performance": [{"client": "bebop", "reach": 1200}],
  "filters_applied": {"client": "bebop", "date_from": "2026-08-01", "date_to": null},
  "unavailable_fields": ["leads", "profitability_pct"],
  "data_source": "analytics_events.metrics + ticket.opened/ticket.closed pairs"
}
```
Per §10 (non-negotiable), any field with no confirmed real data source is returned as
`null` and listed in `unavailable_fields` — never reported as `0`. `leads` has no service
emitting a `lead.*` event yet. `profitability_pct` has no confirmed source in the shared
schema (no cost/spend/revenue field on `Client`, `Campaign`, or `AnalyticsEvent` as of this
build) — required by §2.3/§4 deliverable 3 but pending confirmation from Zeenat on where
that data should come from. `client_performance` previously included spurious reach
attributed to no client, traced to marker/tenant-check writes (DEF-009, closed) — that
noise is now excluded while genuinely unmatched events are still correctly bucketed under
`"unknown"`.

---

## `GET /analytics/client-health`

Per-client health signal (Assignment §2.3 / §3 Client Health Signals panel). Each
client's `health_score` (0–100) is computed only from signals with a confirmed real
source; missing signals are never padded with a fake value.

> **Frontend status:** wired into the live Analytics screen via `refreshAllData()`
> (DEF-013, closed). Live retest on 2026-09-18 confirmed all three real clients (bebop,
> samvix, abc-traders) render correctly — an initial retest appeared to show only one
> client, which was traced to a PowerShell `curl`-alias truncation artifact in the retest
> tooling, not an application bug (DEF-015, closed, no code change). Test-only client
> names (e.g. `esha-health-test`) previously leaked into this response and rendered as
> real clients on the live screen — fixed via test-fixture cleanup (DEF-014, closed).

**Query parameters** (all optional): `date_from`, `date_to` (`YYYY-MM-DD`)

**Response `200`**
```json
{
  "clients": [{
    "client": "bebop",
    "health_score": 92,
    "status": "healthy",
    "avg_ticket_resolution_hours": 3.2,
    "engagement_rate_pct": 6.8,
    "sla_compliance_pct": null,
    "unavailable_signals": ["sla_compliance_pct"]
  }],
  "filters_applied": {"date_from": null, "date_to": null},
  "data_source": "analytics_events (metrics + ticket.opened/ticket.closed pairs)",
  "limitations": [
    "sla_compliance_pct has no confirmed data source — Defect has no client_id...",
    "health_score currently reflects engagement only where available..."
  ]
}
```
`status` is `"healthy"` (score ≥ 70), `"at_risk"` (≥ 40), `"critical"` (< 40), or
`"unavailable"` (no signal computable at all). `sla_compliance_pct` is always `null`
today — see `limitations` and `HANDOVER.md` for why. `health_score` weighting is
engagement 40% / SLA 30% / resolution 30% (confirmed by Zeenat); a missing signal's
component defaults to a neutral 70 rather than being dropped from the average.

---

## `GET /quality/ai-evaluation/summary`

Serves the latest benchmark/correction counts for the Support/AI panel, sourced from the
most recently written evaluation report each benchmark script produces. This service does
not run the benchmarks itself — `asma_benchmark.py` and `vishaqa_benchmark.py` remain the
source of truth; this endpoint just exposes their last output via a real API instead of
leaving it as a standalone JSON file, per the task doc's completion rule that a
disconnected script/output is not itself a completed deliverable.

> **Frontend status:** gateway-verified (DEF-010, closed) but not yet consumed by any
> frontend screen — tracked as an open follow-up, not a defect.

**No request parameters.**

**Response `200`**
```json
{
  "modules": [
    {
      "module": "asma",
      "available": true,
      "total_cases": 7,
      "passed": 7,
      "failed": 0,
      "pass_rate": 1.0,
      "corrections_logged": 0,
      "rule_version": "ai-eval-v1.0",
      "generated_at": "2026-08-27T06:26:14.861817+00:00",
      "error": null
    },
    {
      "module": "viqasha",
      "available": true,
      "total_cases": 8,
      "passed": 8,
      "failed": 0,
      "pass_rate": 1.0,
      "corrections_logged": 0,
      "rule_version": "ai-eval-v1.0",
      "generated_at": "2026-08-27T12:26:04.789144+00:00",
      "error": null
    }
  ]
}
```
If a module's report file is missing or unreadable (e.g. the benchmark hasn't been run
yet in this environment), that module comes back with `available: false` and an `error`
message instead of failing the whole request — the panel can still render partial data.

**Errors:** none expected under normal operation; always returns `200` with per-module
availability, so the Support/AI panel doesn't need special error handling.

---

## `GET /analytics/workload`

Team Workload metrics (Assignment §4 deliverable 9). Built directly against the real
`Defect` table (`packages.database.models.Defect`), the shared task/defect data source
Zeenat confirmed. `due_date` (DateTime, nullable) and `is_blocked` (Boolean, default
`False`) were added to `Defect` specifically to support this endpoint's overdue/blocked
metrics (migration `67c7b363204b_add_due_date_and_is_blocked_to_defect`).

> **Confirmed with Zeenat (2026-08-31):** live task/defect data lives in `defects`, not
> `analytics_events`. An earlier version of this endpoint assumed
> `object_type="task"` analytics events existed — that assumption was confirmed wrong
> and this endpoint was rebuilt against the real table.

> **Frontend status:** wired into the live Team Workload screen via `refreshAllData()`
> (DEF-013, closed). Live retest on 2026-09-18 (DEF-016) confirmed bucket totals
> (`65 completed + 65 overdue + 33 blocked + 34 in_progress = 197`) sum exactly to
> `total_tasks` and match the rendered "Live Defect Workload" card. Some historical
> totals included accumulated test-fixture defects from `_make_defect` in `test_main.py`,
> which lacked teardown (DEF-011, fixed) — figures above reflect the post-cleanup count.

**Bucketing** (mutually exclusive — buckets always sum to `total_tasks`, which is what
proves the doc's evidence requirement, "metrics match underlying tasks"):

| Bucket | Rule |
|---|---|
| `completed` | `status == "closed"` |
| `blocked` | not completed, `is_blocked == True` |
| `overdue` | not completed, not blocked, `due_date` set and in the past |
| `in_progress` | everything else |

**Query parameters** (all optional)

| Param | Type | Notes |
|---|---|---|
| `client` | string | **Not applied.** `Defect` has no `client_id` in the shared schema, so per-client workload isn't possible on this data source. Accepted for API-shape compatibility only; `filters_applied.client` always returns `null`, and a note is added to `limitations` so this is visible rather than silently ignored. |
| `severity` | string | `critical` / `high` / `medium` / `low` |

**Example:** `GET /analytics/workload?severity=critical`

**Response `200`**
```json
{
  "client": null,
  "total_tasks": 12,
  "completed": 7,
  "overdue": 2,
  "blocked": 1,
  "in_progress": 2,
  "completion_rate": 0.5833,
  "filters_applied": { "client": null, "severity": null },
  "data_source": "defects (packages.database.models.Defect)",
  "limitations": []
}
```
Evidence requirement per §4: "Metrics match underlying tasks" — proven by
`test_workload_metrics_match_underlying_tasks` (asserts the four buckets sum exactly to
`total_tasks`) and `test_workload_closed_defect_not_double_counted_as_blocked_or_overdue`
in `test_main.py`, and reconfirmed live per the DEF-016 retest note above.

---

## `GET /analytics/scheduler-consistency`

Scheduler event consistency check (Assignment §4 deliverable 7). Built directly against
`Campaign.status` and `PublishingJob.status` — the real tables the scheduler writes to.

> **Confirmed with Zeenat (2026-08-31):** the scheduler does not emit `analytics_events`;
> it writes directly to `Campaign.status` (`draft` → `pending_approval` → `approved` →
> `scheduled` → `published`) and `PublishingJob.status` (`queued` → `processing` →
> `completed`/`failed`), joined by `campaign_id`. An earlier version of this endpoint
> assumed `post.scheduled/published/failed` analytics events existed — that assumption
> was confirmed wrong and this endpoint was rebuilt against the real tables.

> **Frontend status:** wired into the live Scheduler screen via `refreshAllData()`
> (DEF-013, closed). Live retest on 2026-09-18 confirmed `total_published: 34`,
> `inconsistent_count: 0`, matching the rendered screen exactly. Historical
> `inconsistent_count` figures (up to 34 false positives) were traced not to a scheduler
> bug but to `_make_campaign` in `test_main.py` writing directly to the shared dev DB
> with no teardown (DEF-011, fixed via an autouse pytest cleanup fixture). A separate,
> genuine `scheduler.py` status-transition bug was found and fixed by Zeenat along the
> way (commit `13c062c`) — real, but unrelated to those 34 rows.

**Query parameters** (all optional)

| Param | Type | Notes |
|---|---|---|
| `client` | string | Filters to one client |
| `date_from` | date (`YYYY-MM-DD`) | Inclusive, filters on `Campaign.created_at` |
| `date_to` | date (`YYYY-MM-DD`) | Inclusive, filters on `Campaign.created_at` |

**Example:** `GET /analytics/scheduler-consistency?client=bebop`

**Response `200`**
```json
{
  "client": "bebop",
  "total_scheduled": 10,
  "total_published": 9,
  "total_failed": 1,
  "inconsistent_count": 0,
  "inconsistent_campaign_ids": [],
  "filters_applied": { "client": "bebop", "date_from": null, "date_to": null }
}
```
`inconsistent_campaign_ids` lists any campaign whose `status` is `"published"` but has
**no** `PublishingJob` with `status="completed"` backing it — either no job ever
completed, or the only job(s) that ran ended in `"failed"`. That mismatch is exactly a
false "published" status reaching analytics. `total_failed` counts campaigns with at
least one failed publishing job, regardless of the campaign's own status. Evidence
requirement per §4: "No false published status in analytics" — proven by
`test_scheduler_consistency_flags_false_published_no_completed_job` and
`test_scheduler_consistency_clean_published_not_flagged` in `test_main.py`, and
reconfirmed live per the DEF-011/DEF-013 retest notes above.