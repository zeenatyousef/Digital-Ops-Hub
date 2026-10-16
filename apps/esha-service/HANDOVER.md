# Handover Notes — esha-service

Owner: Esha (Hashtag, Analytics, AI Quality and Test Evidence Lead)
Module: `apps/esha-service/` in the shared monorepo

## Files and what they do

| File | Purpose |
|---|---|
| `main.py` | The FastAPI service — hashtags suggest/save, content quality, similarity, event ingestion, dashboard, monthly report, client summary, client health, team workload, and scheduler consistency. |
| `seed_data.py` | Loads hashtag sets for the 4 required test clients (Bebop, Samvix, FBR, ABC Traders) into the shared DB, plus sample analytics events for client-summary/client-health. Run once after migrations, before demoing. |
| `test_main.py` | 42 pytest cases covering hashtags, content quality, similarity, event idempotency, dashboard/report filtering, team workload, scheduler consistency, and client summary/health. Includes an autouse cleanup fixture (`_cleanup_test_fixture_rows`) that removes test-created `Campaign`/`Defect` rows (DEF-011) and test-only `Client`/`AnalyticsEvent` rows (DEF-014) after every test. Run with `pytest test_main.py --html=test_report.html`. |
| `test_report.html` | Latest generated pytest-html run — regenerate before any handover/demo, don't hand over a stale one. |
| `ai_evaluation_updated.py` | Shared benchmark framework (`BenchmarkCase`, `evaluate_case`, `run_benchmark_suite`, `record_correction`, `write_evaluation_report`) used by both AI-evaluation scripts below. Schema-agnostic by design — don't need to touch this when adding new cases. |
| `asma_benchmark.py` | Independent benchmark suite for Asma's 6 marketing endpoints (7 cases). Writes `evidence/asma_evaluation_report.json`. |
| `vishaqa_benchmark.py` | Independent benchmark suite for Viqasha's `/support/classify` (8 cases). Writes `evidence/vishaqa_evaluation_report.json`. **Currently targets a manually-confirmed seeded tenant ID as a workaround for DEF-001 — see `evidence/defect_log.md` before changing `VIQASHA_TEST_TENANT_ID`.** |
| `evidence/defect_log.md` | All defects found during independent QA, in the §9 format (owner, severity, steps, expected/actual, evidence, retest result). Now includes DEF-011 through DEF-016. |
| `evidence/*.png` | Screenshots from the integrated staging build for each required completion-evidence item in §3 of the task doc. |
| `evidence/smoke_checklist.md` | Production smoke checklist (§8/§12) — login, dashboard, message, ticket, campaign, schedule, report, plus DEF-007/scheduler/workload retests added later. Currently 10/10 PASS (2 defects found along the way — DEF-005, DEF-008 — both fixed and retested; see the file for current item list). |
| `evidence/section12_walkthrough.md` | Line-by-line §12 final acceptance checklist status, including the tenant-isolation scope-boundary note and the 2026-09-18 frontend live-integration retest (DEF-015, DEF-016). |
| `gateway_smoke_test_5_endpoints.py` | Standalone script (self-registers a test user, no real credentials needed) that verifies `client-summary`, `client-health`, `workload`, `scheduler-consistency`, and `ai-evaluation/summary` through the real gateway vs. directly against esha-service. Rerun after any `proxy.py` change to these routes — last run 5/5 PASS after DEF-010 closed. |
| `investigate_def011_campaign_pollution.py` | One-off investigation/cleanup script for DEF-011 — supports `--delete --confirm` to remove the 34 historical test-pollution `Campaign` rows from the shared dev DB. |
| `README.md` | Setup, run, test instructions and known limitations. |
| `API_SPEC.md` | Full request/response/error reference for all endpoints. |

## Services this module depends on

| Service | What's needed from it | Owner |
|---|---|---|
| Shared Postgres + `packages.database.models` | Tenant, Client, HashtagSet, HashtagItem, QualityRun, AnalyticsEvent, ReportSnapshot, Defect, Campaign, PublishingJob tables. This service does not own or migrate its own schema. | Zeenat |
| Viqasha's support service (`/support/classify`) | Target of the AI-evaluation benchmark in `vishaqa_benchmark.py`. | Viqasha |
| Asma's marketing endpoints | Target of the AI-evaluation benchmark in `asma_benchmark.py`. | Asma |
| Frontend (`apps/web/src/app/page.tsx`) | `refreshAllData()` now polls `/analytics/client-health`, `/analytics/scheduler-consistency`, and `/analytics/workload` every 5s and renders the real response shapes (see DEF-013). `client-summary` and `ai-evaluation/summary` are not yet consumed by any screen. | Zeenat |

## Open items at handover

- **Tenant isolation — cannot be independently verified from this module. Named
  explicitly here per §12 of the task doc ("Tenant and role tests pass"), same treatment
  as the DM→task scope note in `e2e_test_evidence.md`.** Role-based tests pass
  (`test_dashboard_role_filter_marketing_excludes_tickets`,
  `test_dashboard_unknown_role_rejected`). Tenant-based tests do not, and cannot, because
  no request DTO in `main.py` ever accepts a second `tenant_id` to filter against — every
  endpoint resolves tenant identity via `get_or_create_dev_tenant()` alone. This is not a
  bug in esha-service; it's a real architectural boundary. Verifying that tenant A's JWT
  genuinely cannot retrieve tenant B's hashtag sets, events, or reports is Zeenat's side
  of the gateway/core-API boundary per §2.3 of the task doc, and isn't wired or testable
  from esha-service as it stands. **This item in §12's acceptance checklist should not be
  marked "done" without an explicit gateway-level tenant test from Zeenat** — see
  `evidence/section12_walkthrough.md` for the full technical explanation.
- **DEF-001 — CLOSED.** `/support/classify` previously 500'd on any syntactically valid
  but unseeded `tenant_id` (unhandled FK violation). Viqasha fixed this in commit
  `1360600` (wrapped DB logging in try/except across classify, summarize, suggest-reply,
  and escalation). Retested against the exact originally-reported unseeded tenant ID —
  8/8 real classification responses, zero 500s. `vishaqa_benchmark.py` still targets a
  manually-confirmed seeded tenant ID as a historical workaround from when this was open;
  no longer required for correctness, but left as-is unless there's a reason to change
  `VIQASHA_TEST_TENANT_ID`. See `evidence/defect_log.md` for full retest evidence.
- **Role→event-type mapping** (`ROLE_EVENT_PREFIXES` in `main.py`) is a first pass, not yet
  confirmed against the final product role list — flagged inline as `TODO(Esha)`.
- **Dev-tenant auto-creation** (`get_or_create_dev_tenant`) is a local-dev convenience —
  see the tenant-isolation item at the top of this section for the full scope-boundary
  explanation; this line is kept only as the pointer to the `TODO` inline in `main.py`.
- **DEF-007 — CLOSED (2026-08-31, retest passed).**
  `get_or_create_dev_tenant()` previously looked up the dev tenant **by name**, so every
  fresh database auto-generated its own random tenant UUID, disconnected from the real demo
  Super Admin's tenant. Fixed in `main.py` and `seed_data.py` to resolve by a fixed canonical
  UUID (`00000000-0000-0000-0000-00000000000a`) instead — team-confirmed (Viqasha
  independently identified the same ID from the demo Super Admin JWT; gateway force-injects
  it from the JWT server-side). Retest: logged in as real Super Admin through `apps/web`;
  Analytics screen showed real non-empty data; direct DB query confirmed all real clients
  (`bebop`, `samvix`, `abc-traders`, `Acme Wireless Partners`) sit under the canonical
  tenant. See `evidence/defect_log.md` for full retest evidence.
- **Content Studio "Select Client Profile" dropdown appears empty for Super Admin —
  NOT a DEF-007 recurrence, separate gap in Asma's module.** Investigated during the
  DEF-007 retest: the dropdown reads from `BrandProfile`, not `Client`. No `BrandProfile`
  row exists yet for any client under the canonical tenant (only a stale row for an old
  test tenant). Tenant resolution itself is correct — this is missing seed data in
  `BrandProfile`, which is Asma's module per the shared schema. Flagged to
  Asma/Zeenat; not an esha-service defect.
- **DEF-008 — Team Workload (Assignment §4, deliverable 9) — CLOSED (2026-09-01,
  retest passed).** Originally assumed task-lifecycle events via `analytics_events`;
  no upstream service actually emits them, so the endpoint would have silently returned
  zero counts against any real deployment. Zeenat confirmed real task/defect data lives
  in the `Defect` table, and her team added `due_date` and `is_blocked` fields to it
  (migration `67c7b363204b_add_due_date_and_is_blocked_to_defect`, commit `6008bcb`)
  specifically so overdue/blocked metrics could be computed honestly instead of reported
  as unavailable. Endpoint (`GET /analytics/workload`) rewritten against `Defect`
  directly with mutually-exclusive completed/blocked/overdue/in_progress buckets that
  always sum to `total_tasks`. Known limitation: `Defect` has no `client_id` anywhere in
  its chain (`Defect → TestRun → TestCase → Tenant`), so per-client filtering isn't
  possible on this data source — the endpoint reports this explicitly via a
  `limitations` field rather than silently ignoring the `client` param. Full retest
  history and root cause in `evidence/defect_log.md` (DEF-008). Retested: 37/37 tests
  passing, including seeded real `Defect` rows and severity/client-filter coverage.
  **2026-09-18: bucket totals reconfirmed live (DEF-016) — `65 completed + 65 overdue +
  33 blocked + 34 in_progress = 197`, matching `total_tasks` exactly, and matching the
  rendered "Live Defect Workload" card once DEF-013 wired the frontend to this
  endpoint.**
- **Scheduler consistency (Assignment §4, deliverable 7) — REBUILT, confirmed
  working.** Originally assumed `post.scheduled`/`post.published`/`post.failed`
  analytics events; Zeenat confirmed the scheduler never emits these — it writes
  directly to `Campaign.status` and `PublishingJob.status`. Endpoint (`GET
  /analytics/scheduler-consistency`) rewritten against these real tables, flags a
  campaign as inconsistent if marked `"published"` with no `PublishingJob` that
  actually `"completed"`. Retested: passing, including against real seeded
  `Campaign`/`PublishingJob` rows. **See DEF-011 below — the 34 rows this endpoint
  flagged as "false published" turned out to be test-suite pollution, not a
  scheduler bug, though Zeenat also found and fixed a real (separate) scheduler
  status-transition bug along the way.**
- **Client summary / client health (Assignment §2.3 / §3 Analytics screen) — BUILT.**
  `GET /analytics/client-summary` and `GET /analytics/client-health` read real
  `AnalyticsEvent.metrics` (reach/engagement) and matched `ticket.opened`/`ticket.closed`
  pairs. Per §10, a field is only ever a computed number when at least one matching event
  actually carried that data — otherwise it's reported as `unavailable`, not `0`.
  `leads` has no confirmed data source yet (no service emits a `lead.*` event or a
  `metrics.leads` field) and reports `unavailable` until confirmed with Asma/Zeenat.
  `client-health`'s `sla_compliance_pct` similarly has no confirmed source, for the same
  reason `Defect` has no `client_id` — see DEF-008's limitation above. `profitability_pct`
  was added 2026-09-02 to `client-summary`, also reporting `unavailable` — §2.3/§4
  deliverable 3 require profitability but no cost/spend/revenue field exists yet on
  `Client`, `Campaign`, or `AnalyticsEvent`; needs the same confirmation from
  Zeenat/management as `leads`. Test coverage for both endpoints (previously a gap —
  neither had a `test_client_summary_*`/`test_client_health_*` function anywhere despite
  being wired into `main.py`) was added 2026-09-02–05; see the DEF-009 entry below for
  the marker/tenant-check exclusion logic specifically. **2026-09-18: all three real
  clients (bebop, samvix, abc-traders) reconfirmed rendering correctly on the live
  Analytics screen once DEF-013 wired the frontend to this endpoint — see DEF-015
  below; the apparent "only one client showing" issue was a retest-tooling artifact,
  not a code defect.**
- **DEF-009 — CLOSED (2026-09-05, merged to `origin/main` as commit `4698973`,
  retested on the integrated build).**
  `GET /analytics/client-summary`'s `client_performance` breakdown previously showed a
  real, non-trivial reach total (~7000+) attributed to no client, traced to `AnalyticsEvent`
  rows with `client_id IS NULL` carrying a `tenant_resolution_marker` event type or a
  `tenant-check-<uuid>` idempotency key — an unidentified process writing directly to the
  shared table. This defect's own scope was the read-side aggregation bug (and a real
  regression from an earlier attempted fix, reverted 2026-09-04 after it silently dropped
  *all* `client_id IS NULL` events, not just marker noise — see `evidence/defect_log.md`
  for the full history). The corrected fix: `get_client_summary()` excludes only events
  matching the marker signature (`idempotency_key` prefixed `tenant-check`, or
  `event_type == "tenant_resolution_marker"`), leaving genuinely unmatched events correctly
  bucketed under `"unknown"`. Two dedicated tests lock this in
  (`test_client_summary_marker_events_excluded_from_client_performance`,
  `test_client_summary_genuine_unmatched_events_still_bucketed_as_unknown`). Retested on
  the merged `main` build per §10: `pytest test_main.py` → 42/42, and
  `gateway_smoke_test_5_endpoints.py` → 5/5 PASS through the real gateway. **Root cause of
  the underlying write path — who/what actually sends `tenant-check`-pattern requests — is
  still unconfirmed** and is not resolved by this closure; it's a separate open
  investigation from the aggregation bug DEF-009 covered. See `evidence/defect_log.md` for
  the full retest record.
- **DEF-010 — CLOSED (2026-09-02).** `client-summary`, `client-health`, `workload`,
  `scheduler-consistency`, and `quality/ai-evaluation/summary` all returned `404` through
  `core_gateway` — found via `gateway_smoke_test_5_endpoints.py`. Same root cause and shape
  as DEF-004: `proxy.py` wasn't updated when these 5 endpoints were added after DEF-004
  closed. Zeenat added the 5 routes to `proxy.py` (commit `f7e01ef` on `main`/
  `feature/marketing-and-support-integration`). Esha merged `origin/main` into
  `esha/hashtag-quality-analytics-service` locally and independently retested on the
  merged build: `pytest test_main.py` → 41/41, `gateway_smoke_test_5_endpoints.py` → 5/5
  PASS.
- **DEF-011 — FIXED (2026-09-16).** 34 campaigns showed as "published" with no
  completed `PublishingJob`, flagged by `/analytics/scheduler-consistency`. Root-caused
  (not to Zeenat's `scheduler.py`, initially suspected) to `test_main.py`'s own
  `_make_campaign`/`_make_defect` helpers, which wrote directly to the shared dev DB via
  `SessionLocal()` with no teardown — every `pytest` run of one specific test left a real
  row behind. Fixed with an autouse pytest fixture (`_cleanup_test_fixture_rows`) that
  deletes every row these helpers create, pass or fail. The 34 historical rows are
  removable via `investigate_def011_campaign_pollution.py --delete --confirm`. Zeenat's
  `scheduler.py` fix (found while investigating this) is real and correct for its own,
  different failure mode — no further action needed from her on DEF-011 itself. See
  `evidence/defect_log.md` for the full investigation history.
- **DEF-012 — confirmed NOT a defect.** The `client` filter on
  `/analytics/scheduler-consistency` works correctly; identical filtered/unfiltered
  results were fully explained by DEF-011 (every published campaign belonged to
  "bebop"). No code change made — logged only to record it was checked.
- **DEF-013 — FIXED and CONFIRMED (2026-09-16/17).** The frontend (`page.tsx`) never
  called any of esha-service's 13 endpoints — `refreshAllData()` only touched
  `/api/campaigns`, `/api/defects`, and similar core-gateway resources. Blocked the task
  doc's §12 completion rule for most of this module's screens. Zeenat wired
  `refreshAllData()` to call `/analytics/client-health`, `/analytics/scheduler-consistency`,
  and `/analytics/workload` (commit `13c062c`). Verified live: Scheduler screen numbers
  matched a fresh direct API call exactly after DEF-011's pollution rows were deleted
  (`Published: 34`, `Failed: 0`, `Inconsistent: 0`). **Remaining gap:** Content Studio's
  AI Quality Score and a dedicated Hashtag Manager screen are still unwired — lower
  priority, demonstrable via direct API/Swagger in the meantime. `client-summary` and
  `ai-evaluation/summary` also remain unwired to any screen (see the dependency table
  above) — not a defect, just unbuilt UI.
- **DEF-014 — FIXED (2026-09-17).** Once DEF-013 wired the Analytics screen live,
  throwaway test clients (`esha-summary-test`, `esha-health-test`,
  `esha-health-engagement-test`, `esha-health-sla-test`) started appearing as real
  entries with health-score badges, because several `client-summary`/`client-health`
  tests wrote `AnalyticsEvent`/`Client` rows under fixed, non-randomized keys with no
  cleanup. Fix extends the same autouse fixture used for DEF-011, this time matching by
  known test-only `Client.company_name` values (more robust than matching by event key,
  since a renamed test client's orphaned row wouldn't be caught by a key-based match —
  see `evidence/defect_log.md` for why the first fix attempt missed one). Retested: 42
  tests passing, no test-only client names appear in `/analytics/client-health`.
- **DEF-015 — CLOSED, not a code defect (2026-09-18).** During the DEF-013/DEF-014
  live retest, the Client Health screen appeared to show only one client (bebop).
  Root cause: PowerShell's `curl` alias (`Invoke-WebRequest`) truncates `.Content` in
  its default table view — the endpoint was returning all three real clients (bebop,
  samvix, abc-traders) correctly the entire time. Confirmed with
  `(Invoke-RestMethod ...) | ConvertTo-Json -Depth 5`. No application code changed.
  `sla_compliance_pct` remains `null`/`unavailable` for all three, as already documented
  under DEF-008's limitation above.
- **DEF-016 — CLOSED (2026-09-18).** Live confirmation that
  `/analytics/workload`'s four bucket totals sum correctly and match the frontend's
  "Live Defect Workload" card, now that DEF-013 wired it live. Confirmed: `65 + 65 + 33
  + 34 = 197`, matching `total_tasks` exactly and matching the rendered card. No code
  change required — this closes out the live-data verification for DEF-008's rebuild.

## Maintenance notes for whoever picks this up next

- **`datetime.utcnow()` deprecation — fixed 2026-09-05.** All 5 call sites (`main.py`,
  `test_main.py`) replaced with `datetime.now(timezone.utc).replace(tzinfo=None)`, which
  is the drop-in equivalent that still returns a naive UTC datetime — required because
  every naive datetime column this compares against (`Defect.due_date`,
  `PublishingJob.scheduled_at`, etc.) is naive in the shared schema, so switching to an
  aware datetime without the `.replace(tzinfo=None)` would raise on comparison. `pytest`
  previously logged 44 deprecation warnings from this; confirmed clean (42 passed, 0
  warnings) after the fix.

- Any change to `packages.database.models` field names on Zeenat's side will break this
  service silently at the ORM layer (no compile-time check) — rerun `test_main.py` after
  any shared-schema migration.
- `RULE_VERSION` (`main.py`) should be bumped any time scoring/check logic changes, since
  `QualityRun.rule_version` is used to distinguish historical runs scored under different
  rules.
- New AI-evaluation cases for either Asma or Viqasha should follow the existing
  `asma_benchmark.py` / `vishaqa_benchmark.py` pattern: independent phrasing (don't copy
  their internal keyword lists), a case-specific `match_fn` where the response shape needs
  bespoke comparison, and a written `description` explaining what each case is probing.
- **`/analytics/event` idempotency is keyed globally by `event_key` alone — not scoped per
  tenant or client.** Once a key is written to a persistent (non-reset) DB, re-posting it
  with different `client`/`metrics` is a silent no-op: `ingest_event()` returns the
  pre-existing row unchanged (see the `existing = db.query(...).first()` short-circuit
  before `get_or_create_client()` even runs). This bit `test_main.py` three times now —
  the original `test-event-`/`test-dash-`/etc. random-key pollution
  (`cleanup_test_pollution_events.py` cleans that up); two `client-health` tests that
  reused the same client name with distinct-but-previously-used fixed keys, silently
  aggregating one test's data into another's assertions instead of failing loudly; and
  DEF-009's genuine-unmatched retest, where an exact-delta assertion (not just `>= 1` or
  non-membership like the other fixed-key tests) meant a fixed key silently deduplicated
  after the first run and stopped proving anything. **When adding a fixed-key test
  fixture, always use a client name + event_key combination that has never been used
  anywhere else in this file — and if the test asserts an exact value or delta rather than
  a threshold/membership check, use a per-run-unique key with explicit teardown instead of
  a fixed key.** Don't assume changing one half of the pair is enough to isolate a test
  from stale data in a shared, non-reset local DB.
- **Any helper in `test_main.py` that writes directly to the shared dev DB
  (`_make_campaign`, `_make_defect`, or any future equivalent) must register its created
  row IDs with the autouse `_cleanup_test_fixture_rows` fixture.** DEF-011 and DEF-014
  were both instances of the same root cause (a test helper writing to shared,
  non-isolated data with no teardown) in different tables — assume any new fixture helper
  needs the same treatment rather than adding its own one-off cleanup.