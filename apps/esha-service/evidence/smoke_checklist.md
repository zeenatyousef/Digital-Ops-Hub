# Production Smoke Checklist — esha-service (Task Doc §8 / §12)

Tested through the real gateway (`http://127.0.0.1:8000`), authenticated as `tenant_admin`,
tenant `esha-dev-tenant`. Not tested against individual services directly — this proves the
actual integrated build.

**Date:** 2026-08-27 (message-visibility follow-up resolved 2026-08-28; Scheduler and Team
Workload retests added 2026-08-31 and 2026-09-01; live frontend retest added 2026-09-18)
**Tester:** Esha

| # | Item | Endpoint / Action | Result |
|---|---|---|---|
| 1 | Login | `POST /api/auth/login` | **PASS** — real JWT issued |
| 2 | Dashboard | `GET /api/analytics/dashboard` | **PASS** — real data returned (`total_events: 28`, breakdown by type, e.g. `post.published: 15`, `ticket.opened: 13`) |
| 3 | Message | `POST /api/conversations` + `POST /api/conversations/{id}/messages` | **PASS** — real conversation and message created. See note below on visibility. |
| 4 | Ticket | `POST /api/client-rooms` → `POST /api/client-rooms/{id}/messages` → `PATCH /api/client-rooms/{id}/status` | **PASS** — full lifecycle tested 2026-08-28: room created (`0239aabf-...`), issue logged, status transitioned `active → closed`, persistence confirmed on re-fetch. See `e2e_test_evidence.md` Flow 2 for full detail. Unblocked by gateway commit `01e3566`. |
| 5 | Campaign | `POST /api/campaigns` → submit → approve | **PASS** — full lifecycle, `draft → pending_approval → approved` |
| 6 | Schedule | `POST /api/campaigns/{id}/schedule` → `GET /api/publishing/jobs` | **PASS** — real `PublishingJob` created, later confirmed `status: completed` with real timestamp |
| 7 | Report | `GET /api/analytics/monthly-report?client=bebop&month=2026-08` | **PASS when called with required params.** Without `client`/`month`, the gateway silently returns a fallback (`service_version: v1.0-fallback`) instead of an error — root-caused to the gateway's proxy layer only forwarding `tenant_id`, not the incoming query string. Logged as **DEF-005** (fixed by Zeenat, commit `01e3566`, retested 2026-08-28). Direct calls to `esha-service` (port 8003) work correctly with the same params. |
| 8 | DEF-007 tenant retest | Login as real Super Admin via `apps/web` → Analytics screen | **PASS** (2026-08-31) — real non-empty data shown (Campaign Coverage: 2, Pending Approvals: 0, Avg SLA: 15 min). Direct DB query confirmed all real clients under canonical tenant `00000000-...00a`. See `defect_log.md` DEF-007 for full evidence. |
| 9 | Scheduler consistency | `GET /analytics/scheduler-consistency` | **PASS** — rebuilt against real `Campaign`/`PublishingJob` tables (Zeenat-confirmed data source, replacing earlier wrong `analytics_events` assumption). 42/42 automated tests passing, including seeded-row tests for this endpoint. **2026-09-18 live retest:** `total_published: 34`, `inconsistent_count: 0`, confirming the endpoint through the real frontend (`refreshAllData()`, wired per DEF-013) once the 34 historical test-pollution rows (DEF-011 — traced to `_make_campaign` in `test_main.py` writing to the shared dev DB with no teardown, not a scheduler defect) were deleted. |
| 10 | Team Workload | `GET /analytics/workload` | **PASS** (2026-09-01) — rebuilt against the real `Defect` table (Zeenat-confirmed data source, replacing earlier wrong `analytics_events` assumption; `due_date`/`is_blocked` fields added specifically to unblock this). Completed/overdue/blocked/in_progress buckets are mutually exclusive and always sum to `total_tasks`, proving the doc's evidence requirement ("Metrics match underlying tasks"). 37/37 automated tests passing at the time, including seeded-row tests for this endpoint and its severity/client-filter behavior. See `defect_log.md` DEF-008 for full retest evidence. **2026-09-18 live retest (DEF-016):** `65 completed + 65 overdue + 33 blocked + 34 in_progress = 197`, matching `total_tasks` exactly and matching the live "Team Workload" screen once wired (DEF-013). |
| 11 | Client Health | `GET /analytics/client-health` | **PASS** (2026-09-18, added to this checklist after DEF-013 wired the screen live). All three real clients (bebop, samvix, abc-traders) confirmed rendering with correct health_score/status/engagement/resolution data. An initial retest appeared to show only one client — traced to PowerShell's `curl` alias truncating output, not an application bug (DEF-015, closed, no code change). `sla_compliance_pct` is `null` for all three by documented design (no `client_id` on defect data in the shared schema). |
| 12 | Frontend live integration | Full app (`apps/web`, `http://localhost:3000`) with all 3 services running concurrently | **PASS** (2026-09-16/17, DEF-013). `refreshAllData()` now polls `/analytics/client-health`, `/analytics/scheduler-consistency`, and `/analytics/workload` every 5s and renders real response shapes — Scheduler and Team Workload screens confirmed showing live numbers matching direct API calls exactly (items 9–11 above). `client-summary` and `ai-evaluation/summary` remain gateway-verified only, with no frontend screen consuming them yet — not a defect, just unbuilt UI. |

**Overall: 12/12 PASS. 2 original smoke-test defects (DEF-005, DEF-008) fixed and retested;
one Critical frontend-integration gap (DEF-013) found and fixed after this checklist was
first run, then confirmed live along with two test-pollution defects (DEF-011, DEF-014)
that were surfaced only once the frontend went live — see `evidence/defect_log.md` for the
full DEF-001–016 history.**

---

## Notes

### Message visibility mismatch — investigated, not a defect
Sent `visibility: "external"` on a DM/conversation message; response came back
`visibility: "internal"`. Traced to `apps/core_gateway/routers/messaging.py:225`,
`send_conversation_message()`:

```python
visibility="internal", # DMs are always internal
```

This is a deliberate, hardcoded rule — all conversation/DM messages are stored internal
regardless of what the request body specifies. Confirmed this is isolated to the DM path;
`send_room_message()` (client-room messaging, same file, lines 62–88) correctly respects
`message_in.visibility` from the request and even enforces it by role (`client_rep` can only
send `external`).

No defect logged. Minor API-clarity note: the `MessageCreate.visibility` field being silently
ignored on the DM path could confuse a future caller — worth a docstring note or removing the
field from that request shape — but not blocking.

### Ticket item — re-verified 2026-08-28
A report came in that tickets/tasks endpoints had been implemented and were ready for E2E
testing. Verified before testing (not taken at face value): `git pull origin main` showed
"Already up to date"; `Select-String` against `core_gateway/main.py` for `include_router`
still showed only the same 5 routers; `Get-ChildItem` for `*ticket*` / `*task*` in
`routers/` returned nothing. Gap remains open — flagged back to the team.

### Items 9–12 added retroactively (2026-09-18)
Items 9 and 10 were part of the original 2026-08-27/2026-09-01 checklist runs; items 11 and
12 were added once the frontend was actually wired to these endpoints (DEF-013, 2026-09-16).
Before that fix, the Scheduler and Team Workload numbers in items 9–10 were verified only by
calling the endpoint directly — not through the running app a demo would actually show. The
2026-09-18 entries close that gap by confirming the same numbers appear on the live screens,
not just in a raw API response.</document_content></document>