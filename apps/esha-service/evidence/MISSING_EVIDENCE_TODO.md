# Screenshot / evidence capture checklist — Team Workload, Scheduler, Support/AI panel

**STATUS UPDATE 2026-09-17: DEF-013 is fixed and confirmed live.** Zeenat wired the
frontend to real endpoints. Real UI screenshots are now possible and should REPLACE the
direct-API captures below. See DEF-013 and DEF-014 in `defect_log.md` for the full story.

**Scheduler — done.** Confirmed live: `Published: 34`, `Failed: 0`,
`Inconsistent (False Published): 0`, matching the API exactly after DEF-011's 34 stale
rows were deleted. Real screenshot captured — replace
`scheduler_consistency_api_response.png` with a real UI capture named
`scheduler_consistency_screen.png`.

**Analytics — needs DEF-014 fix confirmed first.** Before re-capturing, run `pytest`
(picks up the new cleanup fixture), then reload the Analytics screen and confirm the fake
"esha-summary-test" / "esha-health-*" client cards are gone before screenshotting — don't
capture this screen while polluted test data is still visible.

**Team Workload — needs a check.** Confirm the "Live Defect Workload" card shows all 4
buckets (`completed`/`overdue`/`blocked`/`in_progress`) summing to `total_tasks`, not just
3 of the 4 — Zeenat's message didn't mention `in_progress` explicitly.

**Support/AI panel — not yet confirmed wired.** DEF-013's fix covered client-health,
scheduler-consistency, and workload specifically — check whether
`/quality/ai-evaluation/summary` was included too, or still needs its own screenshot via
the direct-API method.

---

## Original direct-API captures (superseded where a real UI screenshot now exists)
`team_workload_api_response.png`, `scheduler_consistency_api_response.png`,
`support_ai_panel_api_response.png` — kept as a fallback/history record. Replace each with
a real UI screenshot as it's confirmed working, and delete the corresponding `_api_response`
file once its real replacement is in place.

