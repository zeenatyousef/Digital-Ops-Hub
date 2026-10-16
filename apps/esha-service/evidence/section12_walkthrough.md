# §12 Individual Acceptance Checklist — Walkthrough Notes

Line-by-line status against the task doc's final acceptance checklist, with evidence pointers.

| Item | Status | Evidence |
|---|---|---|
| All assigned endpoints and screens are integrated | **Done** | 12 real endpoints exist in `main.py`, all 12 now gateway-verified. Original 7 confirmed per DEF-004. Remaining 5 (`client-summary`, `client-health`, `workload`, `scheduler-consistency`, `ai-evaluation/summary`) were confirmed missing gateway routes 2026-09-02 (DEF-010) and closed same day after Zeenat added the routes (`proxy.py`, commit `f7e01ef`) and Esha independently retested on the merged branch: `gateway_smoke_test_5_endpoints.py` → 5/5 PASS, `pytest test_main.py` → 41/41. Frontend integration confirmed live for the remaining screens: `refreshAllData()` in `page.tsx` now polls `client-health`, `scheduler-consistency`, and `workload` every 5s (wired by Zeenat, 2026-09-15). Retested 2026-09-18 with all three services running concurrently — DEF-015 (Client Health) and DEF-016 (Workload) both closed with live data confirmed rendering correctly on their respective screens. `client-summary` and `ai-evaluation/summary` remain gateway-verified only, with no frontend consumer built yet — tracked as an open follow-up, not a defect (see note below). |
| No Critical or High defect remains in assigned scope | **Done** | DEF-010 (High) closed 2026-09-02, retested 5/5 PASS on the integrated build. DEF-003 (Asma's, Low severity, non-blocking) is the only defect open outside this module's scope. |
| Tenant and role tests pass | Role: Done. Tenant: see note below | `test_main.py::test_dashboard_role_filter_marketing_excludes_tickets`, `::test_dashboard_unknown_role_rejected` |
| Error and offline/fallback behaviour is implemented | Done | Fallback pattern implemented; the one case where it masked a real error as success (DEF-005 — gateway dropped query params) is fixed and retested — see `defect_log.md` |
| Documentation is complete and another team member can run the module | Done | `README.md`, `API_SPEC.md`, `HANDOVER.md` |
| Management has accepted the demonstration | Pending | Live step, not verifiable from the repo |

---

## Endpoint count and gateway-verification gap (updated 2026-09-02)

This checklist previously stated "All 6 endpoints DB-integrated, tested via gateway" — a
count taken before `client-summary`, `client-health`, `workload`, `scheduler-consistency`,
and `ai-evaluation/summary` were added. `main.py` currently exposes 12 real endpoints
(13 including `/health`):

`/quality/hashtags/suggest`, `/quality/hashtags/save`, `/quality/content`,
`/quality/similarity`, `/analytics/event`, `/analytics/dashboard`,
`/analytics/client-summary`, `/analytics/client-health`, `/quality/ai-evaluation/summary`,
`/analytics/monthly-report`, `/analytics/workload`, `/analytics/scheduler-consistency`

Of those 12, only the original 7 have gateway-level verification on record (DEF-004: a real
auth'd request through `core_gateway` reached esha-service and wrote to the shared DB;
DEF-005: `monthly-report`'s query-parameter forwarding bug found and fixed specifically at
the gateway layer — proof the gateway path was actually exercised, not assumed).

The remaining 5 endpoints — including both `client-summary` and `client-health` — have
automated test coverage (`test_main.py`, 41/41 passing as of 2026-09-02) that proves they
work correctly when called directly against esha-service. That is not the same claim as
"tested via gateway," and this doc should not imply otherwise. DEF-005 is a direct
precedent for why this distinction matters: a bug existed specifically in gateway
forwarding logic that no amount of direct-to-esha-service testing could have caught.

**Update — 2026-09-02, resolved from "unverified" to "confirmed defect":** ran the same
gateway-level smoke test DEF-004 used (real auth token via self-registered `tenant_admin`
user, real requests through `core_gateway`) against all 5 remaining endpoints using
`gateway_smoke_test_5_endpoints.py`. Result: all 5 returned `404` through the gateway —
the routes were never added to `proxy.py`. Logged as **DEF-010** (same shape and root
cause as DEF-004: `proxy.py` wasn't updated when these 5 endpoints were built after
DEF-004 closed). This is no longer an open question for the final report — it's a
confirmed, named defect owned by Zeenat, blocking this checklist item until fixed and
retested.

---

## Frontend live-integration retest (2026-09-18)

Following DEF-010's gateway-route fix, the frontend was wired to consume 3 of the
5 previously gateway-only endpoints (`client-health`, `scheduler-consistency`,
`workload`) via `refreshAllData()` polling every 5s. Retested live with all three
services running concurrently (esha-service :8003, core_gateway :8000, web :3000):

- **DEF-015 (Client Health)** — closed. All three clients (bebop, samvix,
  abc-traders) render with correct health_score, status, and metrics.
  `sla_compliance_pct` is `null` for all three by design — no `client_id` on
  defect data in the shared schema (same constraint as workload, below);
  pending Zeenat confirmation. Component defaults to a neutral 70 in the
  health_score weighting (engagement 40% / SLA 30% / resolution 30%) in the
  meantime. Not a defect — documented limitation.
- **DEF-016 (Workload)** — closed. Live totals (65 completed + 65 overdue +
  33 blocked + 34 other = 197) match the endpoint's total exactly, confirming
  the backend was correct all along and the frontend now surfaces all four
  buckets.
- **DEF-011 (Scheduler consistency)** — Zeenat's root-cause fix in
  `scheduler.py` (only mark a campaign `"published"` once all its jobs
  complete) confirmed via live retest: `total_published: 34`,
  `inconsistent_count: 0` — matches this log's existing DEF-011 closure notes.

**Open follow-up (not blocking):** `client-summary` and `ai-evaluation/summary`
remain gateway-verified (DEF-010) but have no frontend screen consuming them
yet. This is unbuilt UI, not a defect, and is tracked here so it isn't silently
dropped from the final report.

---

## Tenant isolation — gateway-owned boundary, not independently testable here

Every endpoint in `main.py` resolves tenant identity via `get_or_create_dev_tenant()`; no
request DTO accepts `tenant_id`. Internal filtering (`AnalyticsEvent.tenant_id == tenant.id`,
`HashtagSet.tenant_id == tenant.id`, etc.) is correct wherever it's used, but this service has
no live code path to prove end-to-end tenant isolation, because it's never given a second
tenant to filter against — there's nothing in any request that could carry a different
tenant's identity in the first place.

This matches the existing `TODO(Esha)` in `main.py` and the "Dev-tenant fallback" limitation
already documented in `README.md`. Per §2.3 of the task doc, tenant context is meant to come
from the gateway/core API, not be inferred here. Real tenant enforcement — verifying that
tenant A's JWT genuinely can't retrieve tenant B's hashtag sets, events, or reports through
the gateway — is Zeenat's side of this boundary and isn't wired or testable from this module
yet.

**Recommendation for the final report:** name this explicitly to management as a shared
responsibility item (same treatment as the tickets/tasks gap in `e2e_test_evidence.md`)
rather than marking this checklist row "done" or omitting it silently.