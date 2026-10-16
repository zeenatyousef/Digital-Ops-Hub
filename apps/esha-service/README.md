# esha-service

Hashtag intelligence, content-quality scoring, similarity detection, and analytics/reporting
for NW Digital Operations Hub V3. Owned by Esha per the Final Task Assignment (§2.1–2.5).

This service does **not** own its own database. It reads/writes the shared Postgres instance
via `packages.database.models` (Zeenat's schema) — no isolated tables, per §6 of the task doc.

## What this service does

- `/quality/hashtags/suggest`, `/quality/hashtags/save` — versioned hashtag signatures per
  client/platform, with duplicate/banned/spam-risk detection and a quality score.
- `/quality/content` — scores a caption on clarity, CTA strength, brand-rule compliance
  (prohibited wording, repetition, wrong contact detail) and duplicate risk.
- `/quality/similarity` — near-duplicate detection against a client's recent content, using
  word-overlap ratio with a configurable threshold.
- `/analytics/event` — idempotent ingestion of normalized operational events.
- `/analytics/dashboard` — role/client/date-filtered event summary.
- `/analytics/monthly-report` — per-client monthly dataset with data-completeness flags.
- `/analytics/client-summary`, `/analytics/client-health` — per-client reach/engagement,
  ticket-resolution, and health-score signals, read from real `AnalyticsEvent` data. Live and
  wired into the frontend's Analytics screen (see DEF-013 in `evidence/defect_log.md`); all
  three real clients (bebop, samvix, abc-traders) confirmed rendering correctly as of the
  2026-09-18 retest (DEF-015).
- `/analytics/workload` — team workload metrics, built against the real `Defect` table
  (confirmed with Zeenat — no service actually emits task-lifecycle events; see DEF-008 in
  `evidence/defect_log.md`). Completed/blocked/overdue/in_progress buckets are mutually
  exclusive and always sum to `total_tasks`. `client` filtering is not possible on this data
  source (`Defect` has no `client_id`) and is reported explicitly via a `limitations` field.
  Live totals reconfirmed against the frontend's "Live Defect Workload" card as of the
  2026-09-18 retest (DEF-016).
- `/analytics/scheduler-consistency` — flags a campaign as inconsistent if marked
  `"published"` with no `PublishingJob` that actually `"completed"`. Built against the real
  `Campaign`/`PublishingJob` tables (confirmed with Zeenat — the scheduler never emits
  `post.scheduled`/`post.published`/`post.failed` events; original assumption was wrong,
  rebuilt against real data). Historical false-positive flags traced to test-suite pollution,
  not a scheduler bug — see DEF-011 in `evidence/defect_log.md`.
- `/quality/ai-evaluation/summary` — serves the latest benchmark/correction counts (Asma and
  Viqasha modules) for the Support/AI panel, reading from `evidence/`.

## Setup

### Requirements
- Python 3.12
- The shared Postgres instance (via Docker Compose at the repo root) running and migrated
  with Zeenat's current `packages/database/models.py`
- This service lives at `apps/esha-service/` inside the monorepo — it imports
  `packages.database.session` / `packages.database.models` via a relative `sys.path.append`,
  so it must stay at that path depth (two levels under the repo root) to resolve imports.

### Install
```bash
cd apps/esha-service
python -m venv venv
source venv/bin/activate
pip install fastapi uvicorn sqlalchemy pydantic requests pytest pytest-html
```

### Run
```bash
# from apps/esha-service, with the shared Postgres container up
python -m seed_data          # loads Bebop, Samvix, FBR, ABC Traders test data
uvicorn main:app --reload --port 8003
```

### Test
```bash
pytest test_main.py --html=test_report.html --self-contained-html
```

### Environment variables

| Variable | Purpose | Default |
|---|---|---|
| `DATABASE_URL` | Shared Postgres connection string, read by `packages.database.session` | set in repo-root `.env` — not owned by this service |
| `VIQASHA_API_URL` | Base URL for Viqasha's support-classification service, used only by the AI-evaluation benchmark scripts | `http://localhost:8001` |

This service has no env vars of its own beyond what the shared `packages.database.session`
module requires — it reuses the monorepo's DB connection.

## Known limitations

- **API naming vs. task doc.** The task doc (§5) lists a single `POST /quality/hashtags`.
  This service implements it as two endpoints — `POST /quality/hashtags/suggest` and
  `POST /quality/hashtags/save` — since suggesting/scoring and persisting a signature are
  different operations with different request/response shapes. See `API_SPEC.md` for the
  full split. Both satisfy §5's filtering rules (client/location/platform/banned/duplicate).
- **DEF-001 — closed.** The Viqasha AI-evaluation benchmark (`vishaqa_benchmark.py`)
  originally called `/support/classify` with a hardcoded test tenant ID that was not seeded
  on every environment, which caused a 500 (unhandled FK violation on Viqasha's side — see
  `evidence/defect_log.md`). Viqasha fixed this in commit `1360600` (DB logging now wrapped
  in try/except so a failed log no longer breaks the response); retested 2026-08-27 against
  the original unseeded tenant ID with 8/8 real classification responses and zero 500s.
  **Status: Closed.**
- **Dev-tenant fallback.** `get_or_create_dev_tenant()` auto-creates an `esha-dev-tenant`
  row if none is supplied. This is a local/testing convenience — in production, tenant
  context should come from the gateway/core API per §2.3 of the task doc, not be inferred
  here. Marked `TODO(Esha)` in `main.py`.
- **Role→event-type mapping is a first pass.** `ROLE_EVENT_PREFIXES` in `main.py` is not yet
  confirmed against the final product role list; tenant/permission enforcement itself is
  handled upstream by the core API, not by this service.
- **Phone numbers in captions are flagged, not verified.** `check_wrong_contact_detail()`
  can verify a caption's email against the client's registered `contact_email`, but there is
  no canonical phone field on `Client` yet, so phone numbers are only flagged for manual
  review, not validated.
- **Missing platform data is reported as `"unavailable"`, never `0`.** Applies to
  `/analytics/monthly-report`'s `completeness` field, per the task doc's non-negotiable rule
  in §10.
- **`profitability_pct` has no confirmed data source.** §2.3 and §4 deliverable 3 both
  require profitability alongside SLA/workload/client health, but nothing in the shared
  schema (`Client`, `Campaign`, `AnalyticsEvent`, `PublishingJob`) carries cost, spend, or
  revenue data as of this build. `GET /analytics/client-summary` now reports it as `null`
  in `unavailable_fields` (never `0`, per §10) pending confirmation from Zeenat/management
  on where this data should come from — see `TODO(Esha)` above `ClientSummaryResponse` in
  `main.py`.
- **`sla_compliance_pct` has no confirmed data source.** `GET /analytics/client-health`
  reports this as `null` in `unavailable_signals` for every client — same root cause as
  `/analytics/workload`'s client-filtering gap (`Defect` has no `client_id` in the shared
  schema). Its component defaults to a neutral 70 in the `health_score` weighting
  (engagement 40% / SLA 30% / resolution 30%, confirmed by Zeenat) until this is resolved.
  Not a defect — see DEF-015 in `evidence/defect_log.md`.
- **DEF-011 — fixed (2026-09-16).** Test helpers in `test_main.py` (`_make_campaign`,
  `_make_defect`) previously wrote directly to the shared dev database with no teardown,
  producing 34 false "published" campaigns that `/analytics/scheduler-consistency` correctly
  flagged as inconsistent — a test-pollution bug, not a scheduler defect. Fixed via an
  autouse pytest cleanup fixture; historical rows removable via
  `investigate_def011_campaign_pollution.py --delete --confirm`. See
  `evidence/defect_log.md` for the full root-cause investigation.
- **DEF-014 — fixed (2026-09-17).** The same class of test-pollution bug as DEF-011
  affected `/analytics/client-health`: several tests wrote throwaway `Client`/
  `AnalyticsEvent` rows under fixed keys with no cleanup, which then appeared as real
  clients once the frontend was wired live. Fixed by extending the same cleanup fixture to
  match and remove known test-only client names. **Status: Closed.**
- **DEF-015 — closed, not a code defect (2026-09-18).** The Client Health screen appeared
  to show only one client during a retest; root cause was PowerShell's `curl` alias
  (`Invoke-WebRequest`) truncating output, not an application bug. All three real clients
  confirmed rendering correctly. See `evidence/defect_log.md`.

This service has no other known critical or high-severity open defects as of 2026-09-18.
See `evidence/defect_log.md` for the full defect history and `evidence/section12_walkthrough.md`
for acceptance-checklist status.

## Evidence

See `evidence/` for defect log, AI-evaluation reports (Asma and Viqasha, separate files),
and UI screenshots from the integrated build.