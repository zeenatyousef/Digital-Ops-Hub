# Defect Log — System QA Evidence (Task Doc §2.5)

Coordinated with Zeenat. Format follows §9: owner, severity, steps, expected, actual,
screenshot/log, retest result. A Critical/High defect is not closed until it retests
clean on the integrated build (§10, non-negotiable rule).

---

## DEF-001

| Field | Value |
|---|---|
| **Title** | `/support/classify` returns 500 for a well-formed but unseeded `tenant_id` |
| **Module / Owner** | Vishaqa — AI Support Intelligence Service (`apps/vishaqa-service/main.py`) |
| **Found by** | Esha, during independent AI-evaluation benchmarking (§2.4) |
| **Date found** | 2026-08-24 |
| **Severity** | High — endpoint is unusable for any tenant not currently present in the DB, with no graceful failure |
| **Status** | Closed — fixed in Viqasha's commit `1360600`, retested 2026-08-27 with 8/8 real responses (see retest section below) |

**Steps to reproduce**
1. POST to `/support/classify` with a syntactically valid UUID as `tenant_id` that does not
   exist as a row in the shared `tenants` table (e.g. the README's own test tenant,
   `d5de8b4d-b089-4d4e-9283-fd952f8df783`, if it is not currently seeded on the running instance).
2. Include any valid `message` string.

**Expected result**
Either a successful classification with DB logging skipped, or a clean 4xx response —
per the README, "invalid UUIDs are handled gracefully (no crash; empty/default result returned)."

**Actual result**
`500 Internal Server Error`. All 9 of Esha's benchmark cases against this endpoint failed
with this error (see `evidence/ai_evaluation_report.json`, generated 2026-08-24).

**Root cause (from code review)**
```python
try:
    tenant_uuid = uuid.UUID(ticket.tenant_id)
except ValueError:
    return result
```
This only catches a malformed UUID **string**. It does not check whether the UUID
corresponds to an existing `tenants` row. `tenant_id` is a foreign key on both
`ai_runs` and `ticket_predictions`, so the subsequent `db.add()` / `db.commit()`
raises an unhandled `IntegrityError` (FK violation), which FastAPI surfaces as a 500.
The same gap exists in `suggest_reply_endpoint` and `escalation_endpoint`.

**Evidence**
- `evidence/ai_evaluation_report.json` — 9/9 Viqasha cases failing with this error
- Raw response body (once captured via updated `viqasha_predict_fn` error handling)

**Suggested fix**
Wrap the AI-run/prediction logging block in try/except so a logging failure doesn't
fail the whole classify response; or verify the tenant exists before attempting the insert.

**Retest result — 2026-08-25 (partial, via workaround)**
Confirmed on the current shared DB (`nw-digital-ops-db` / `nw_digital_ops_hub`) that the
originally-referenced test tenant (`d5de8b4d-b089-4d4e-9283-fd952f8df783`, from Viqasha's
own README) is **not seeded**:This confirms the root cause: the FK violation fires for any tenant_id not in this table,
exactly as described above.

To unblock evaluation evidence without waiting on a code fix, `vishaqa_benchmark.py` (see
that file's module docstring) now targets `6598b5c2-a9ef-4fd8-b984-7f7edfac4dc4`, a tenant
confirmed to exist. Re-run against this tenant: **all 8 cases returned real classification
responses — zero 500s.** This confirms the crash is specifically tied to the missing-tenant
FK violation described above, not a broader service issue.

**This defect is NOT closed by the workaround.** The underlying bug — a syntactically valid
but unseeded `tenant_id` should fail gracefully (4xx), not crash the request — is unchanged
and still reproducible with any tenant ID absent from the `tenants` table. Status remains
**Open** until Viqasha ships the graceful-failure fix described above and it's retested with
an intentionally unseeded tenant.

**Retest result — final, 2026-08-27**
Viqasha fixed this in commit `1360600` — wrapped DB logging (AIRun/TicketPrediction) in
try/except across classify, summarize, suggest-reply, and escalation, so a failed log no
longer breaks the response.

Retested `vishaqa_benchmark.py` against the exact tenant this defect originally referenced
(`d5de8b4d-b089-4d4e-9283-fd952f8df783`, still absent from the current shared DB) after
pulling her fix and restarting the service. **Result: 8/8 real classification responses,
zero `_error` / zero 500s.** Confirmed via full terminal output, same day.

**Status: Closed.** The classifier still produces some incorrect classifications for this
tenant (4/8 — see DEF-002), but that's a separate, pre-existing accuracy issue, not a crash.
This defect was specifically about graceful failure on an unseeded tenant, and that's now
verified fixed.

---

## DEF-002 — Guardrail keyword matching fails on natural, non-literal phrasing

| Field | Detail |
|---|---|
| **Owner** | Viqasha |
| **Found by** | Esha, during independent AI-evaluation benchmarking (§2.4) |
| **Date found** | 2026-08-25, root cause confirmed 2026-08-27 |
| **Severity** | Medium — guardrail categories exist and work for expected phrasing, but silently fail to trigger for natural real-world phrasing of the same scenario |
| **Status** | Closed — Viqasha updated classifier logic; retested 2026-08-27, 8/8 pass |

**Steps to reproduce**
POST to `/support/classify` with each of the following messages (using tenant `6598b5c2-a9ef-4fd8-b984-7f7edfac4dc4`, since `d5de8b4d-...` is not present on the shared DB — see DEF-001):

1. `"Someone I don't recognize logged into my account and changed my settings."`
2. `"I noticed I was billed for two subscriptions this month."`
3. `"The receipts at the front counter are not printing anymore."`
4. `"Can you please remove all our old customer records from the system permanently?"`

**Expected**
Each message describes a genuine Security / Financial / POS / Destructive Action scenario and should route to the matching guardrail category with `human_required: true` (per the assignment's non-negotiable rule that these categories must never auto-resolve).

**Actual**
All 4 fell through to the fallback:
```json
{"product": "Unclassified", "category": "Needs manual review", "severity": "Medium", "owner_team": "General Support", "confidence": 0.4, "human_required": true}
```

**Root cause (confirmed by reading `classify_message()` in `vishaqa-service/main.py`)**
Each failure traces to a specific, exact gap in the keyword-combo lists, not a systemic bug:

| Case | Message uses | Combo list checked | Gap |
|---|---|---|---|
| 1 | "logged into my account" | `security_combos` | No combo covers "logged in" without the literal word "access" (closest: `["login", "access"]`) |
| 2 | "billed for two subscriptions" | `financial_combos` | List has `refund`, `charge`/`charged`, `overcharged`, `reimburse` — no entry for "billed" |
| 3 | "receipts... not printing" | POS check | `has_word(text, "receipt")` checks the **singular** form only; message uses the plural "receipts" |
| 4 | "remove all our old customer records" | `destructive_combos` | `["remove", "all", "data"]` requires the literal word "data"; message says "records" instead |

This is the same underlying pattern as her own logged defects TC-042 (`"down"` matching inside `"downloads"`) and TC-051 (POS `"print"` keyword ambiguity) — confirmed independently from a different angle: word-literal matching rather than semantic/synonym-aware matching.

**Comparison to self-reported guardrail evidence**
Viqasha's own QA report (27 Aug 2026) reports 48/48 (100%) guardrail pass rate. Those 48 cases are phrased using the literal trigger words (e.g. "hacked," "breach," "delete," "wipe," "refund," "billing dispute"). The 4 cases here test the *same guardrail categories* with natural, non-literal phrasing and fail — indicating the 100% figure reflects testing against expected vocabulary, not independent testing of generalization, which is what §2.4 specifically asks for.

**Suggested fix**
- Make `has_word` (or wherever plural/singular is checked) plural-aware, or normalize word endings before matching.
- Add synonym coverage to `financial_combos` (e.g. "billed") and `destructive_combos` (e.g. "records", "account", "info") and `security_combos` (e.g. "logged in" alone, without requiring "access").

**Retest result — final, 2026-08-27**
Re-ran all 8 independent benchmark cases against Viqasha's updated `/support/classify`
(commit range `a33f135..b229844`, `apps/vishaqa-service/main.py` updated). Result:
**8/8 passed**, `pass_rate: 1.0`, `corrections_logged: 0`.

All 4 previously-failing cases now classify correctly with real confidence scores instead
of falling to the `Unclassified` fallback:
- viqasha-01 (security/account breach) → `Security`, confidence 0.9
- viqasha-02 (billing dispute) → `Financial`, confidence 0.93
- viqasha-04 (POS printing regression) → `POS`, confidence 0.82 — confirms the earlier
  regression is genuinely fixed, not just working around this specific phrasing
- viqasha-07 (data deletion request) → `Destructive Action`, confidence 0.89,
  `human_required: True` — the safety concern raised in the original defect (destructive
  action not being flagged for human review) is resolved

viqasha-06 remains `Unclassified` at confidence 0.4 — this is expected and correct, as this
case was deliberately designed to test the low-confidence fallback path, not a real category.

Full evidence in `evidence/vishaqa_evaluation_report.json`.

**Status: Closed.**

---

## DEF-003

| Field | Value |
|---|---|
| **Title** | `POST /marketing/brief` intermittently 500s with `pydantic_core.ValidationError: confidence — Input should be a valid number [type=float_type, input_value=None]` |
| **Module / Owner** | Asma — Marketing Intelligence Service (`apps/asma-service/main.py`, `generate_campaign_brief()` / `build_field()`) |
| **Found by** | Esha, running `asma_benchmark.py` fixture setup |
| **Date found** | 2026-08-27 |
| **Severity** | Low — did not reproduce on immediate retry; not currently blocking, but a genuine unhandled crash path worth fixing |
| **Status** | Open — reported to Asma for awareness, not currently blocking |

**Steps to reproduce**
Not reliably reproducible. Ran `python asma_benchmark.py` against her live service 3 times in
one session: call #1–3 to `/marketing/brief` succeeded (200 OK); after her `--reload` picked
up an unrelated file change and restarted her process, the next call to the same endpoint
with the same fixture payload 500'd. Two subsequent immediate retries both succeeded (200 OK,
7/7 benchmark cases passed each time).

**Expected result**
`POST /marketing/brief` returns 200 consistently for the same valid payload.

**Actual result (one occurrence)**Traceback shows this originates in `build_field("offer")` inside `generate_campaign_brief()`
(`apps/asma-service/main.py`), constructing a `FieldConfidence` model with `confidence=None`.

**Evidence**
Full server-side traceback captured from her `uvicorn` terminal output, same session,
2026-08-27. Not saved as a file — captured in this conversation's history; can be reproduced
again and screenshotted properly if Asma wants to investigate.

**Suggested fix**
Whatever computes the confidence score for the "offer" field of a campaign brief appears to
sometimes return `None` instead of a float — possibly for an edge case in the underlying
brief content, or a transient issue right after a hot-reload. Worth adding a default/fallback
confidence value or input validation before constructing `FieldConfidence`, so a bad score
degrades gracefully instead of 500ing the whole request.

**Retest result**
Not applicable — not currently blocking Esha's own deliverables since it self-resolved on
retry both times observed. Logged for Asma's awareness per §9's evidence-based defect
process; not treated as a blocker for this submission.

---

## DEF-004 — Gateway has no working route to Esha's real endpoints

| Field | Detail |
|---|---|
| **Owner** | Zeenat (core_gateway) |
| **Found by** | Esha, while bringing all 4 services up together for the first time for the smoke checklist |
| **Date found** | 2026-08-27 |
| **Severity** | High — every one of Esha's endpoints is currently unreachable through the gateway, which blocks the smoke checklist and any UI screen that goes through core_gateway rather than calling esha-service directly |
| **Status** | Closed — Zeenat wired all 7 routes with RBAC + fallback; retested end-to-end by Esha 2026-08-27 |

**Steps to reproduce**
Compare `apps/core_gateway/routers/proxy.py` against `apps/esha-service/main.py`'s real routes.

**Expected**
A gateway route per real Esha endpoint — `/quality/hashtags/suggest`, `/quality/hashtags/save`,
`/quality/content`, `/quality/similarity`, `/analytics/event`, `/analytics/dashboard`,
`/analytics/monthly-report` — matching the pattern already used for Asma (6 routes) and
Viqasha (6 routes).

**Actual**
Only one route exists: `POST /qa/analyze`, forwarding to `ESHA_API_URL + "/qa/analyze"` —
an endpoint that doesn't exist on esha-service. Its fallback response shape (`score`,
`checks[]`, `issues[]`) resembles a single content-quality check, not any of the 7 real
endpoints. RBAC (tenant check, role check) and an offline-fallback pattern are already
correctly built in — this looks like a stub written before the real API was finalized,
not abandoned work.

**Suggested fix**
Replace the single `/qa/analyze` route with 7 routes mirroring Asma's/Viqasha's pattern in
the same file, each forwarding to its matching real path on `ESHA_API_URL`.

**Retest result — final, 2026-08-27**
Confirmed all 7 routes exist under the gateway's `/api` prefix (discovered via
`APIRouter(prefix="/api", ...)` in `proxy.py`), with real auth/RBAC enforced
(`get_current_tenant` + `RoleChecker`). Registered a real test user against the
`esha-dev-tenant`, logged in via `/api/auth/login`, and called
`POST /api/quality/hashtags/save` through the gateway (port 8000) with a valid bearer
token. **Result: 200 OK, real response** — `hashtag_set_id`, correctly incremented
`version: 16` (proving it hit the real, same database esha-service uses directly on
port 8003), and the submitted tags echoed back correctly. Full request/response chain
verified: client → gateway auth → RBAC → forward to esha-service → database write →
response back through gateway.

**Status: Closed.**

---

## DEF-005 — Gateway drops query parameters when forwarding to /analytics/monthly-report

| Field | Detail |
|---|---|
| **Owner** | Zeenat (core_gateway) |
| **Found by** | Esha, during production smoke checklist |
| **Date found** | 2026-08-27 |
| **Severity** | Medium — the report endpoint is unusable through the gateway; only reachable by calling esha-service directly, bypassing auth/RBAC |
| **Status** | Closed — fixed by Zeenat in commit `01e3566`, retested by Esha 2026-08-28, re-verified against `proxy.py` source 2026-09-03 |

**Steps to reproduce**
1. Call `GET http://127.0.0.1:8003/analytics/monthly-report?client=bebop&month=2026-08` directly against esha-service — returns real data.
2. Call `GET http://127.0.0.1:8000/api/analytics/monthly-report?client=bebop&month=2026-08` through the gateway, same params, valid auth token.

**Expected**
Gateway forwards all relevant query parameters (`client`, `month`) from the incoming request to esha-service, same as it does for `tenant_id`.

**Actual**
Previously, `proxy.py` hardcoded `params = {"tenant_id": str(tenant_id)}` — it never read or forwarded `client`/`month` (or any other) query params from the original request.

**Fix**
Zeenat updated `proxy_analytics_monthly_report` (and all GET proxy handlers in `apps/core_gateway/routers/proxy.py`), commit `01e3566`, to read `params = dict(request.query_params)` and attach `tenant_id`.

**Retest result — final, 2026-08-28**
Retested through the real gateway with a valid auth token:
`GET http://127.0.0.1:8000/api/analytics/monthly-report?client=bebop&month=2026-08` →
returned real data (`client: bebop, period: 2026-08, dataset: {total_events: 1},
completeness: {instagram: unavailable, facebook: unavailable}`), no fallback shape.
Confirmed fix: `proxy.py` now does `params = dict(request.query_params)` before adding
`tenant_id`, forwarding all incoming params instead of only `tenant_id`. Also confirms
compliance with §9's rule that missing platform data shows as `unavailable`, not `0`.

**Re-verification — 2026-09-03**
Confirmed directly in `apps/core_gateway/routers/proxy.py` (lines 466–467) that
`request.query_params` are still captured into `params` and forwarded via `_forward_get`.
Direct call and gateway call continue to receive identical query parameter structures.

**Status: Closed.**

---

## DEF-006 — Similarity/duplicate-risk check flags different clients' captions as duplicates of each other

| Field | Detail |
|---|---|
| **Owner** | Esha (esha-service) |
| **Found by** | Esha, while reviewing `compute_similarity()` scoping ahead of E2E testing |
| **Date found** | 2026-08-28 |
| **Severity** | Medium — `/quality/similarity` and the `duplicate_risk` field in `/quality/content` can produce false positives across unrelated clients, which would incorrectly block or flag legitimate content in the integrated build |
| **Status** | Closed — fixed and retested by Esha 2026-08-28 |

**Steps to reproduce**
1. Log a caption for Client A via `POST /quality/content` (e.g. `client: "bebop"`).
2. Submit the same caption for Client B via `POST /quality/similarity` (e.g. `client: "samvix"`).

**Expected**
Client B's caption should not be flagged as a near-duplicate of Client A's caption — similarity should only be checked against a client's own past content.

**Actual**
`compute_similarity()` filtered past `QualityRun` rows by `tenant_id` only. All clients currently share a single dev tenant (`get_or_create_dev_tenant()`), so any caption logged for one client counted as history for every other client, producing cross-client false positives.

**Root cause**
`QualityRun` has no `client_id` column in the shared schema (`packages.database.models`) yet — client scoping wasn't possible via a direct filter.

**Fix**
`client` is now written into the `checks` JSON column at write time (in both `/quality/content` and `/quality/similarity`), and `compute_similarity()` parses `checks` and only compares against past runs where the stored client matches the request's client. Both call sites now pass `client` through explicitly. Change is isolated to `compute_similarity()` and its two call sites — no other logic touched.

**Retest result — final, 2026-08-28**
Added `test_similarity_no_false_positive_across_different_clients` to `test_main.py`: logs a caption for `bebop`, then submits the identical caption for `samvix` — asserts `is_near_duplicate` is `False`. Full suite re-run via `pytest test_main.py --html=test_report.html --self-contained-html`; all tests pass, including the existing same-client duplicate-detection test (`test_similarity_detects_duplicate`), confirming the fix didn't break true-positive detection.

**Status: Closed.**

---

## DEF-007 — esha-service's dev tenant resolves to a random UUID, not the canonical demo tenant

| Field | Detail |
|---|---|
| **Owner** | Esha (esha-service) — team-wide coordination with Zeenat/Viqasha on canonical tenant_id |
| **Found by** | Esha, investigating a tenant_id drift issue raised by Viqasha on a different screen (Knowledge Base) |
| **Date found** | 2026-08-28 |
| **Severity** | Medium-High — not a code bug, but a data-isolation/demo-readiness risk: if unresolved before the live demo, all of Esha's screens (Content Studio, Analytics, Team data) could appear empty when viewed through the real demo Super Admin login |
| **Status** | **Closed — retest passed.** `get_or_create_dev_tenant()` in `main.py` and `seed_data.py` now resolve by the fixed canonical UUID (`00000000-0000-0000-0000-00000000000a`) instead of by name. Confirmed team-wide (Viqasha independently found the same UUID from the demo Super Admin JWT; Zeenat confirmed the gateway force-injects this tenant_id server-side on every forwarded request). Retest evidence below. |

**Steps to reproduce**
1. Log in as the demo Super Admin (Atif Zaheer) through the real UI — JWT carries `tenant_id: 00000000-0000-0000-0000-00000000000a`.
2. Query any esha-service-owned data (hashtag sets, quality runs, analytics events) — all of it was created under `esha-service`'s own auto-generated dev tenant.
3. Confirmed via direct DB query that this does not match the demo Super Admin's `00000000-...00a`, nor either of the two other tenant_ids Viqasha found in play (`d5de8b4d-...`, `6598b5c2-...`) — a fourth distinct ID.

**Expected**
All test/demo data across the team resolves to one agreed canonical tenant_id, matching what the real demo login produces.

**Actual**
`get_or_create_dev_tenant()` in `main.py` looks up a `Tenant` row **by name** (`"esha-dev-tenant"`), not by a fixed UUID, and creates one if missing. This means every fresh database gets its own randomly-generated tenant UUID — deterministic per database, but arbitrary across different databases/environments. Confirmed matches the existing `TODO(Esha)` comment: `"replace with real tenant_id from the gateway once wired up."`

**Suggested fix**
Once the team confirms the canonical tenant_id (Viqasha proposed `00000000-0000-0000-0000-00000000000a`, the Super Admin's real ID), two options:
1. Update existing rows to reassign `Tenant.id` to the canonical UUID (same approach Viqasha used for `kb_articles`).
2. Change `get_or_create_dev_tenant()` to look up/create by the fixed UUID instead of by name — removes the per-database drift risk permanently, not just this one instance.

**Retest — PASSED, 2026-08-31**

1. Migration script (`migrate_tenant_to_canonical.py`) run once locally — confirmed
   canonical tenant present, no orphaned rows found under the old drifted UUID.
2. Logged in as the real demo Super Admin (Atif Zaheer) through the actual gateway UI
   (`apps/web`, `http://localhost:3000`).
3. **Analytics screen** — confirmed showing real, non-empty data: Campaign Coverage: 2,
   Pending Approvals: 0, Avg. SLA Response: 15 min. Not blank, not zero-by-default.
4. **Direct DB query** confirms every real client row (`bebop`, `samvix`, `abc-traders`,
   `Acme Wireless Partners`) sits under `tenant_id: 00000000-0000-0000-0000-00000000000a`
   — the canonical tenant. Only stale leftover row is `AI-Eval Test Client` under an old
   test tenant, which is unrelated pre-existing test data, not a recurrence of the drift.
5. **Content Studio screen** — page loads correctly under Super Admin, but the "Select
   Client Profile" dropdown was empty. Investigated: this dropdown reads from
   `BrandProfile`, not `Client` directly. Confirmed via direct DB query that **no**
   `BrandProfile` row exists for `bebop`/`samvix`/`abc-traders`/`Acme Wireless Partners`
   under the canonical tenant — the only `BrandProfile` row in the DB belongs to the old
   `AI-Eval Test Client` test tenant. This is a **missing-seed-data gap in `BrandProfile`
   (Asma's module, per schema)**, not a tenant-resolution bug — DEF-007's own scope
   (esha-service's tenant resolution) is proven correct by the direct client-table query
   above. Flagged separately to Asma/Zeenat rather than reopening this defect.

**Conclusion:** DEF-007 is closed. Tenant resolution across esha-service's own data is
correct and verified live. The Content Studio dropdown gap is a separate, smaller item
(missing `BrandProfile` seed data, owned by Asma's module) — tracked outside this defect.

---

## DEF-008 — Team Workload endpoint built against a data source that doesn't exist in the real system

| Field | Detail |
|---|---|
| **Owner** | Esha (esha-service) |
| **Found by** | Esha, cross-checking `GET /analytics/workload` against Zeenat's confirmation of where task/defect data actually lives |
| **Date found** | 2026-08-31 |
| **Severity** | Medium — not a crash, but the endpoint would have returned zero counts for every real deployment, silently, since nothing populates the assumed data path |
| **Status** | **Closed — retest passed.** Rebuilt against the real `Defect` table; 37/37 tests passing. |

**Steps to reproduce**
1. Review the original `GET /analytics/workload` implementation: it queried `analytics_events` filtered by `object_type="task"`, reconstructing each task's latest status from event history.
2. Ask: what upstream service actually emits an event with `object_type="task"`? None does — no code path in the gateway or any service posts task-lifecycle events to `/analytics/event`.

**Expected**
Deliverable 9's evidence requirement ("Metrics match underlying tasks") implies the endpoint reads from wherever tasks/defects genuinely live and get updated.

**Actual**
The original implementation was built on an unconfirmed assumption (flagged in its own code comments as pending Zeenat's confirmation). Zeenat subsequently confirmed directly: live task/defect data lives in the shared `defects` table (the `Defect` model), queried via the gateway's `/api/defects` — the gateway does **not** auto-trigger a `POST /analytics/event` on defect status changes; it only writes to a general audit log. The original endpoint would return `total_tasks: 0` for every real defect in the system, silently, in violation of §10's rule against presenting missing analytics as zero performance in spirit (the data isn't "missing" — it's just being read from the wrong table entirely).

Compounding this, `Defect` originally had no `due_date` or `is_blocked` field at all, so even a correct data source couldn't have produced real overdue/blocked metrics — Zeenat added both fields (migration `67c7b363204b_add_due_date_and_is_blocked_to_defect`, commit `6008bcb`) specifically to unblock this rebuild.

**Root cause**
Built against an assumed event-emission contract that was never confirmed with the team before implementation, rather than tracing the real data flow first.

**Fix**
`GET /analytics/workload` now queries `Defect` directly (`tenant_id`-scoped — `Defect` has no `client_id` in the shared schema, confirmed by tracing `Defect → TestRun → TestCase → Tenant`, none of which reference `Client`; this matches deliverable 9's actual wording, which requires completion/overdue/blocker metrics only, not a client breakdown). Bucketing is mutually exclusive so buckets always sum to `total_tasks`, proving the doc's evidence requirement directly:
- `completed` = `status == "closed"`
- `blocked` = not completed AND `is_blocked == True`
- `overdue` = not completed, not blocked, `due_date` set AND `due_date < now`
- `in_progress` = everything else

A defect with no `due_date` is never counted as overdue (nothing to be overdue against) — per §10, it lands in `in_progress`, not silently miscounted either way. The endpoint also reports its `data_source` explicitly and, if a `client` filter is passed, explicitly states in `limitations` that it isn't applied rather than silently ignoring it or pretending to scope data it can't scope.

**Retest result — final, 2026-09-01**
Full suite re-run via `pytest test_main.py --html=test_report.html --self-contained-html`: **37 passed, 0 failed.** New coverage added: `test_workload_completed_matches_closed_defects`, `test_workload_overdue_matches_past_due_date_open_defects`, `test_workload_blocked_matches_is_blocked_flag`, `test_workload_no_due_date_never_counted_as_overdue`, `test_workload_buckets_are_mutually_exclusive_and_sum_to_total`, `test_workload_severity_filter`, `test_workload_client_filter_reported_as_unapplied_not_silently_ignored`, `test_workload_response_reports_its_data_source` — each seeding real `Defect` rows via the shared DB session, the same table the real system writes to, not fabricated events.

**Status: Closed.**

---

## DEF-009 — Unidentified writes to analytics_events with client_id NULL (`tenant_resolution_marker` / `tenant-check`)

| Field | Detail |
|---|---|
| **Owner** | TBD / Zeenat (write-path root cause) + Esha (esha-service read-side fix) |
| **Found by** | Esha, during HANDOVER.md review and repo-wide audit |
| **Date found** | 2026-08-31 (pytest pollution distinguished from this), confirmed ongoing 2026-09-02 |
| **Severity** | Medium — not currently breaking a screen, but an unidentified process has been writing directly to shared production data; the read-side aggregation fix has now landed twice, was reverted once, and is merged and independently retested as of this entry |
| **Status** | **Closed — merged to `origin/main` (commit `4698973`) and independently retested on the integrated build.** Root cause of the underlying write path itself remains unconfirmed and is tracked separately — see "Next step" below. |

**Steps to reproduce**
```sql
SELECT COUNT(*) AS unlinked_marker_count
FROM analytics_events
WHERE client_id IS NULL
  AND (event_type = 'tenant_resolution_marker' OR idempotency_key LIKE 'tenant-check%');
```
```sql
SELECT event_type, source, idempotency_key, COUNT(*) AS count
FROM analytics_events
WHERE client_id IS NULL
GROUP BY event_type, source, idempotency_key;
```

**Expected result**
No `analytics_events` rows should be written with `client_id IS NULL` by any known process; every write should be traceable to a known service/script.

**Actual result**
71 `AnalyticsEvent` rows exist (at time of original discovery) with `client_id IS NULL`, recurring in near-identical batches, containing a `tenant_resolution_marker` string or a `tenant-check-<uuid>` idempotency-key pattern. Confirmed distinct from the separate pytest test-pollution bug (that one used a random `event_key` per test run — already fixed, see HANDOVER.md).

**Root cause**
Unconfirmed. The entire esha-service repository — every branch, every file type, including untracked files — was searched multiple times for whatever writes this string. Nothing was found in tracked code. Something outside this codebase, or an unmerged/unpushed process, appears to be writing to the shared table.

**Verification history — three independent guardrail-claim checks, all negative (2026-09-02)**
Zeenat repeatedly reported adding a filter/guardrail to exclude these events from aggregation, citing an unconfirmed "likely healthcheck" theory. Checked directly each time via `git grep` across `main` and `feature/marketing-and-support-integration`, before and after merging her `f7e01ef` (DEF-010 fix): **no matches, three separate times.** The claimed guardrail was not present in code on any branch checked.

**Zeenat's repro-data reply (2026-09-02) — data received, write-path question unanswered**
Zeenat provided a manual migration of local SQLite rows into a local Postgres container, producing a matching count of 71 with `source: test_runner` / `source: healthcheck`. This answered "what does the data look like" but not "where in application code is the insert" — no commit, file, or line was ever cited at this stage.

**Fourth verification (2026-09-02) — write-path claim did not hold up**
Zeenat claimed a specific file, `scratch/seed_71_markers.py`, as the write path, plus claims of a `defect_log.md` edit and "26 unit tests passing." Checked directly:
- `git log --all --oneline -- scratch/seed_71_markers.py` → **no results, ever, on any branch.**
- `git log --all --oneline -- apps/esha-service/evidence/defect_log.md` → no commits from Zeenat on this file.
- `pytest apps/esha-service/test_main.py -q` → **41 passed**, not 26.

None of the three specific claims held up.

**Independent investigation (2026-09-02)** — using Esha's own existing DB access (`investigate_def009_write_path.py`):
- Current count at that time: 2 rows, not 71, with **timestamps 2 days apart** — inconsistent with a one-time seed script, more consistent with an ongoing/recurring write path.
- `idempotency_key` prefix (`tenant-check-<uuid>`) did **not** match the naming pattern in Zeenat's cited seed script, ruling out that specific script as the source of these particular rows.
- Repo-wide search (all branches, all file types) for `tenant-check` / `tenant_resolution_marker` → only matches were this repo's own documentation of the problem.
- Separately noted 25 additional unrelated `client_id IS NULL` rows (`event_type='task.status_changed'`, `source='test'`) — not yet investigated.

**Two invalid evidence attempts (2026-09-02–03) — both correctly rejected**
1. Query run against `temp.db` (wrong target — a local SQLite DB with 4 seeded events, not the shared dev/staging instance) → returned 0 rows. Not valid evidence.
2. Query run against `temp.db` after Zeenat seeded 71 rows into it specifically to match the expected count → returned 71, but every `created_at` was the same afternoon, seconds apart — synthetic, not organically accumulated. Zeenat acknowledged seeding it herself once asked directly. Rejected as evidence.

A live credential (`nw_admin:nw_password_2026`) was also pasted into chat during this exchange and flagged for rotation; not stored anywhere beyond this note.

**First fix implemented and verified — 2026-09-04 (commit `1b2558f`)**
Zeenat pushed a genuine fix to `origin/main`:
- **Ingest guard** in `ingest_event()` (`apps/esha-service/main.py`, ~lines 441–443): payloads with `event_type == "tenant_resolution_marker"` or `event_key.startswith("tenant-check")` and no `client` are accepted (200, no error) but not persisted as orphaned `client_id IS NULL` rows. Idempotency is preserved — repeat submissions still return `duplicate: True`.
- **Dashboard filter** in `get_client_summary()` (~lines 628–633): excludes `client_id IS NULL` rows from `reach_by_client`.

Independently verified by Esha:
- `pytest test_main.py -v -k "def009"` → the new `test_def009_tenant_check_marker_does_not_create_unlinked_db_row` test **passed**.
- A manual live POST of a synthetic `tenant_resolution_marker` event confirmed the guard behavior.

**Regression found in the same fix**
Full suite run surfaced a real regression: `test_client_summary_unmatched_client_events_bucket_as_unknown` started failing. The `get_client_summary()` filter appeared to exclude **all** `client_id IS NULL` events, not just marker/tenant-check ones — silently removing the legitimate "unknown" bucket for genuinely unmatched events, not just DEF-009 noise. This was flagged back but not yet resolved before the next event (the revert) happened.

**Fix reverted — 2026-09-04 (commits `5f02d6e`, `d2e68ea`)**
Zeenat pushed two commits reverting `1b2558f` in full, restoring `main.py`/`test_main.py` to their pre-fix state (matching commit `ba6ded1`). Confirmed independently:
- `git diff 1b2558f d2e68ea -- apps/esha-service/main.py apps/esha-service/test_main.py` showed the guard and the new test being removed.
- Post-pull, `pytest test_main.py` → **41 passed**, no `test_def009_...` present, matching the pre-fix baseline exactly.

**Collateral damage — defect_log.md itself**
The same `1b2558f` commit that added the fix also overwrote large sections of this file, deleting the DEF-007, DEF-008, and DEF-010 entries entirely and replacing this DEF-009 entry with a much shorter "Closed" version that omitted the full verification history above. The revert commits did not restore `defect_log.md` (their commit messages only reference the code files), so the file had to be manually reconstructed from the pre-damage version. This document is that reconstruction, merged with everything that happened afterward.

**Second fix — 2026-09-05 (branch-local, `esha/hashtag-quality-analytics-service`)**
This time built and verified directly on Esha's branch, addressing the exact regression that sank the first attempt: `get_client_summary()`'s exclusion now gates specifically on the marker signature (`idempotency_key` prefixed `tenant-check`, or `event_type == "tenant_resolution_marker"`) rather than on `client_id IS NULL` alone — so marker/tenant-check noise is excluded from `client_performance` while genuinely unmatched events still land in the `"unknown"` bucket as they should.

Two dedicated tests added to `test_main.py` (§10 "Client Summary" section) to keep these two cases independently provable going forward:
- `test_client_summary_marker_events_excluded_from_client_performance` — confirms a marker event does not add to the "unknown" bucket (before/after delta comparison, avoids test-order coupling).
- `test_client_summary_genuine_unmatched_events_still_bucketed_as_unknown` — confirms a genuine unmatched event still lands in "unknown" with the correct reach delta.

**Test-quality note on the second test above:** it initially used a fixed `event_key` (matching the pattern of other idempotency tests in this file), but unlike those tests — which only assert `>= 1` or non-membership — this one asserts an exact reach delta. A fixed key meant the event was silently deduplicated on any run after the first, producing a false pass with zero actual coverage of the fix. Corrected to a per-run-unique `event_key` (UUID-suffixed) with explicit teardown (deletes the row by `idempotency_key` in a `finally` block after the assertion), so the test proves the fix on every run without adding a new permanent row to the shared dev DB.

**Retest result — branch-local, 2026-09-05**
Full suite: `pytest test_main.py -v` → **42 passed, 0 failed** (up from the 41-test pre-fix baseline — net +1 after the earlier single-test version of the genuine-unmatched case was replaced by the two dedicated tests above). Ran twice in succession to confirm the corrected teardown doesn't leave a stale row that would break a subsequent run.

**Merge to `origin/main` — 2026-09-05, commit `4698973`**
Committed (`main.py`, `test_main.py`, `evidence/defect_log.md`, `HANDOVER.md`) and pushed to `esha/hashtag-quality-analytics-service`, then merged into `main` as a clean fast-forward (`d2e68ea..4698973`, no conflicts) and pushed to `origin/main`.

**Retest on the integrated build — 2026-09-05**
Per §10's "retest on the integrated build" rule and the DEF-010 precedent, retested independently on the merged `main` checkout rather than trusting the branch-local result alone:
- `pytest test_main.py -v` (from the merged `main` checkout) → **42 passed, 0 failed.**
- `python gateway_smoke_test_5_endpoints.py`, run against both `core_gateway` and `esha-service` started fresh from the merged build → **5/5 PASS** — `client-summary`, `client-health`, `workload`, `scheduler-consistency`, `ai-evaluation-summary` all returned gateway responses matching the direct esha-service response exactly. (Getting both services running required correcting two stale port references in the local `.env` — `DATABASE_URL` pointed at 5433 while `docker-compose.yml` maps Postgres to 5434, and `REDIS_URL` pointed at 6379 while Redis is mapped to 6380 — an environment-config issue unrelated to this defect's code fix, noted here only because it blocked the retest, not because it's part of DEF-009 itself.)

**Status: Closed.** The read-side aggregation fix (marker/tenant-check exclusion, genuine-unmatched events still bucketed as "unknown") is now on `origin/main` and independently verified on the integrated build — both the unit-level fix and the gateway-level end-to-end path.

**What remains open, tracked separately from this defect's closure:** root cause of the
underlying write path (who/what actually sends `tenant-check`-pattern requests) is still
unidentified. This fix addresses the read-side aggregation only, not the source of the
writes — the 71 historical rows remain unexplained. If this needs continued tracking,
it should be logged as its own item (e.g. a follow-up defect or an open investigation
note in `HANDOVER.md`) rather than reopening this closed entry, since DEF-009's own
scope (the "unknown"-bucket aggregation bug and its regression) is now fully resolved
and retested.

---

## DEF-010 — Gateway has no routes for the 5 endpoints built after DEF-004 closed

| Field | Detail |
|---|---|
| **Owner** | Zeenat (core_gateway) |
| **Found by** | Esha, running `gateway_smoke_test_5_endpoints.py` to close the gateway-verification gap flagged in `evidence/section12_walkthrough.md` |
| **Date found** | 2026-09-02 |
| **Severity** | High — same class as DEF-004: 5 real, tested endpoints are completely unreachable through the gateway, which means the Analytics screen's Client Performance chart, Client Health Signals panel, Team Workload screen, Scheduler consistency check, and Support/AI evaluation panel (§3 of the task doc) cannot work end-to-end no matter how correct esha-service's own code is |
| **Status** | Closed — retested 5/5 PASS |

**Steps to reproduce**
1. Start `core_gateway` (port 8000) and `esha-service` (port 8003) locally.
2. Run `gateway_smoke_test_5_endpoints.py` (self-registers a `tenant_admin` test user against the canonical tenant, logs in via the real `OAuth2PasswordRequestForm` login flow, then calls all 5 endpoints through both the gateway and directly against esha-service for comparison).

**Expected**
A gateway route per real esha-service endpoint added since DEF-004 closed — `/analytics/client-summary`, `/analytics/client-health`, `/analytics/workload`, `/analytics/scheduler-consistency`, `/quality/ai-evaluation/summary` — matching the pattern DEF-004 already established for the original 7.

**Actual (original finding)**
All 5 gateway calls returned `404`. Login succeeded (proving auth/RBAC itself works fine — this isn't an auth problem), and the same 5 paths called directly against esha-service (port 8003) worked correctly per `test_main.py`'s 41/41 passing suite. The routes simply didn't exist in `apps/core_gateway/routers/proxy.py`.

**Root cause**
Same root cause as DEF-004: `proxy.py`'s route list wasn't updated when these 5 endpoints were added to esha-service after DEF-004 closed on 2026-08-27. DEF-004's fix only covered the 7 endpoints that existed at the time.

**Fix**
Zeenat added the 5 missing routes to `proxy.py` (`/api/analytics/client-summary`, `/api/analytics/client-health`, `/api/analytics/workload`, `/api/analytics/scheduler-consistency`, `/api/quality/ai-evaluation/summary`), pushed as commit `f7e01ef` on `feature/marketing-and-support-integration` / `main` — "Zeenat: Add missing gateway proxy routes for client-summary, workload, scheduler-consistency, and ai-evaluation/summary (Resolves DEF-010)".

**Retest result — CLOSED, 2026-09-02**
Merged `origin/main` (commit `f7e01ef`) into `esha/hashtag-quality-analytics-service` locally (clean merge, no conflicts — touched only `proxy.py` and the frontend, neither of which esha-service owns). Restarted both services fresh from the merged build and reran independently:
-- `pytest test_main.py` → **41/41 passing**
-- `python gateway_smoke_test_5_endpoints.py` → **5/5 PASS** — `client-summary`, `client-health`, `workload`, `scheduler-consistency`, `ai-evaluation-summary` all returned gateway responses matching the direct esha-service response exactly.

Retest was run independently by Esha on the merged branch rather than taken on Zeenat's word alone, per §10's "retest on the integrated build" rule.

## DEF-011 — 34 campaigns marked "published" with a failed job — root cause confirmed: esha-service's own test suite, not the scheduler

| Field | Detail |
|---|---|
| **Owner** | Esha — confirmed root cause is `test_main.py`, not Zeenat's `scheduler.py` |
| **Found by** | Esha, calling `GET /analytics/scheduler-consistency`, confirmed via `investigate_def011_campaign_pollution.py`, root-caused via `git grep -n "campaign.status" -- "*.py"` across the full repo |
| **Date found** | 2026-09-08; root cause confirmed 2026-09-16 |
| **Severity** | Medium (downgraded from High) — same category as DEF-009: test pollution landing in shared dev data, not a production defect |
| **Status** | **Fixed** — `_make_campaign`/`_make_defect` in `test_main.py` now clean up after themselves via an autouse pytest fixture. The 34 historical rows are safe to delete with `investigate_def011_campaign_pollution.py --delete --confirm`. |

**Investigation history (kept for the record — this is a good example of not trusting the first plausible theory)**
1. Initially suspected as manual test-data clutter ("+ New Campaign" clicked repeatedly). Ruled out — investigation script showed a suspiciously uniform pattern (all 34 had exactly one job, status `failed`, zero successes).
2. Escalated to Zeenat as a likely `scheduler.py` status-transition bug. She found and fixed a real (but different) bug: a campaign was marked `published` on the first job success without checking if sibling jobs were still pending — genuinely correct fix, now in `scheduler.py`, but for a different failure mode than the one that produced these 34 rows.
3. Reading the actual diff (`git show 13c062c -- apps/core_gateway/scheduler.py`) showed her fix only runs inside the `job.status == "completed"` branch — it cannot affect a campaign whose only job's status is `failed`, which is what all 34 rows are.
4. `git grep -n "campaign.status" -- "*.py"` across the **entire repo** found only two places that ever set `campaign.status = "published"`, both inside `scheduler.py`, both under Zeenat's fix. No third code path exists.
5. That pointed to `test_main.py:515` — `_make_campaign(status="published", job_statuses=["failed"])`, called by `test_scheduler_consistency_flags_false_published_no_completed_job`. Confirmed: `_make_campaign` used `SessionLocal()` (the shared dev DB, not an isolated test DB), committed permanently, and had no teardown. Every `pytest` run of that one test left a real row behind — 34 rows ≈ 34 test runs over 6 days, all under the "bebop" client used throughout this test file.

**Actual root cause**
`_make_campaign` and `_make_defect` in `test_main.py` wrote directly to the shared dev database with no cleanup — the same class of bug as DEF-009, just in a different table.

**Fix**
Both helpers now append the row ID they create to a module-level list (`_created_campaign_ids`, `_created_defect_ids`). A new autouse pytest fixture (`_cleanup_test_fixture_rows`) deletes every tracked row after each test, pass or fail, so nothing survives past the test that created it. Matches the existing try/finally teardown convention already used elsewhere in this file (`test_client_summary_genuine_unmatched_events_still_bucketed_as_unknown`).

**Note for Zeenat**
Her `scheduler.py` fix is real and correct for its own scenario (job succeeds while siblings are still pending/failed) — it's just unrelated to these 34 rows. No further action needed from her on DEF-011.

**Follow-up**
The same bug in `_make_defect` means the 197 defects behind `/analytics/workload`'s numbers likely include accumulated test fixtures from before this fix, not only genuine QA defects. Worth a fresh look at `GET /analytics/workload` after a full pytest run under the new cleanup to see how much the total drops — that'll show how much of the 197 was test noise versus real defects.

## DEF-012 — Confirmed NOT a defect: `client` query filter works correctly

Investigated as a suspected filter bug (identical results for `?client=bebop` vs. unfiltered call). Read `get_scheduler_consistency` in `main.py`: the filter is applied correctly (`Campaign.client_id == client_row.id`, exact match on `company_name`). The identical results are fully explained by DEF-011 — every published campaign in this tenant currently belongs to the "bebop" client, so filtering to it changes nothing. No code change needed. Logged here only to record that this was checked and ruled out, not to leave it as an open question.

## DEF-013 — Frontend does not call any of esha-service's 13 endpoints

| Field | Detail |
|---|---|
| **Owner** | Zeenat (frontend, `apps/web/src/app/page.tsx`) |
| **Found by** | Esha, reading `page.tsx` in full while trying to capture UI screenshots for Team Workload, Scheduler consistency, and the Support/AI panel |
| **Date found** | 2026-09-08 |
| **Severity** | **Critical** — blocks the task doc's §12 completion rule ("a disconnected API is not a completed assignment... completion requires integrated production behaviour") for a majority of this module's deliverables |
| **Status** | **Fixed and confirmed.** Zeenat wired `refreshAllData()` to call `/analytics/client-health`, `/analytics/scheduler-consistency`, and `/analytics/workload` (commit `13c062c` on `main`, pushed 2026-09-16). Verified live in the running app on 2026-09-17: Scheduler screen shows real `total_scheduled`/`total_published`/`total_failed`/`inconsistent_count` (matched a fresh direct API call exactly — see the math check in this entry's retest note below), and the Publishing Jobs Queue table shows real campaign UUIDs and job statuses. |

**Steps to reproduce**
1. Search `page.tsx` for every `fetch(` / `apiFetch(` call.
2. Compare against the 13 endpoints documented in `API_SPEC.md`.

**Expected**
UI screens for Content Studio/Hashtag Manager, Scheduler, Team Workload, and Analytics call the corresponding esha-service endpoints and render real response data, per the task doc §3 completion-evidence table.

**Actual (as originally found)**
The frontend's `refreshAllData()` only called `/api/campaigns`, `/api/client-rooms`, `/api/defects`, `/api/users`, `/api/brand-profiles`, `/api/audit-events`, `/api/calendar`, and `/api/auth/*`. None of `/analytics/workload`, `/analytics/scheduler-consistency`, `/analytics/client-summary`, `/analytics/client-health`, `/quality/ai-evaluation/summary`, `/quality/content`, `/quality/similarity`, `/quality/hashtags/suggest`, `/quality/hashtags/save`, `/analytics/dashboard`, `/analytics/monthly-report`, or `/analytics/event` were referenced anywhere.

By contrast, **QA Defects and Campaigns were already genuinely wired** and displaying real data from `/api/defects` and `/api/campaigns` — this was never a wholesale frontend failure, it was specific to esha-service's endpoints.

**Retest (2026-09-17)**
Before the fix: `GET /analytics/scheduler-consistency` showed `total_published: 68`. 34 of those were confirmed as DEF-011's test-pollution rows and deleted (see DEF-011 below). After deletion, `68 - 34 = 34` should remain, all clean. Live Scheduler screen now shows exactly `Published: 34`, `Failed: 0`, `Inconsistent (False Published): 0` — matches the arithmetic exactly, confirming both the wiring and the DEF-011 fix are working together correctly. Zeenat's UI even labels the fourth card "DEF-011 tracking."

**Remaining gap**
Content Studio's "AI Quality Score" and a dedicated Hashtag Manager screen are still not wired/present (not covered by this fix, which focused on the three analytics endpoints Zeenat mentioned). Lower priority than the three that were fixed — hashtags and content-quality checks are demonstrable via direct API/Swagger evidence in the meantime.

## DEF-014 — Client-summary/client-health tests leak fake "clients" into the live Analytics screen

| Field | Detail |
|---|---|
| **Owner** | Esha |
| **Found by** | Esha, viewing the live Analytics screen after DEF-013's fix went live — spotted "esha-summary-test" displayed as a real client with a red "critical" health badge |
| **Date found** | 2026-09-17 |
| **Severity** | Medium — same class of bug as DEF-009/DEF-011 (test writes polluting shared data), but more visible/embarrassing than either, since it now renders directly on the Analytics screen a live demo would show to management |
| **Status** | **Fixed** |

**Steps to reproduce (before fix)**
1. Run `pytest test_main.py` at least once.
2. Open the app UI → Analytics screen (now wired per DEF-013).
3. Observe "esha-summary-test" and/or "esha-health-engagement-test" / "esha-health-sla-test" listed as real Client Health Signals cards.

**Root cause**
`test_client_summary_reports_reach_and_engagement_from_events`, `test_client_summary_avg_ticket_resolution_from_ticket_pairs`, `test_client_health_reports_healthy_status_for_strong_engagement`, `test_client_health_sla_compliance_always_unavailable`, and `test_client_health_excludes_events_with_no_client` all post `AnalyticsEvent` rows with **deliberately fixed, non-randomized `event_key` values** (commented "do-not-randomize") under throwaway client names (`esha-summary-test`, `esha-health-engagement-test`, `esha-health-sla-test`). The fixed key was a reasonable attempt to keep repeated pytest runs idempotent and avoid unbounded row growth — but it also meant these rows, and the `Client` rows `get_or_create_client` created for them, were never deleted. `GET /analytics/client-health` has no client filter (by design — it aggregates every client it has ever seen), so these fake clients show up permanently, indistinguishable from real ones, on the live Analytics screen.

**First fix attempt was incomplete — worth recording why.** The first version of this fix matched cleanup by specific known `event_key` values. Retesting against the live API turned up a fourth fake client, `"esha-health-test"` (health_score 74, "healthy"), that survived the fix untouched. Investigation: that name doesn't appear anywhere in current test code except a comment explaining it was **renamed away from** at some point (to `esha-health-engagement-test`/`esha-health-sla-test`, to fix an unrelated key-collision bug) — but the original row created under the old name was never deleted, and no current test recreates or touches it, so a key-based cleanup could never find it. **Fix revised to match by client name instead of event key** — this catches any event under a known test-only client name regardless of what key created it, including orphaned rows from before this fix existed. The lesson: matching cleanup logic to "what the current code creates" misses history; matching to "what shouldn't exist in production" (the client name, which is what actually renders on screen) is more robust.

**Fix**
Extended the same autouse pytest fixture used for DEF-011 (`_cleanup_test_fixture_rows` in `test_main.py`). After every test, it looks up all `Client` rows whose `company_name` is in a known test-only list (`esha-summary-test`, `esha-health-test`, `esha-health-engagement-test`, `esha-health-sla-test`), deletes every `AnalyticsEvent` tied to those client IDs, then deletes the `Client` rows themselves. `tenant-check-fixed-key-do-not-randomize` (DEF-007's marker-exclusion test) is unaffected — it has no client attached and `main.py` already filters it out of every display by design.

**Retest**
Run `pytest test_main.py` (42 passed), then check `GET /analytics/client-health` — none of the four test-only client names should appear in the response. Reload the Analytics screen and confirm no fake client cards remain.

---

## DEF-015 — Client Health screen appeared to show only one client

| Field | Detail |
|---|---|
| **Owner** | Esha (retest process, not application code) |
| **Found by** | Esha, retesting the live Analytics screen after DEF-013's frontend wiring |
| **Date found** | 2026-09-18 |
| **Severity** | N/A — not a defect; logged to record that this was investigated and ruled out |
| **Status** | **Closed.** Confirmed to be a retest-tooling artifact, not a backend or frontend bug. |

**Steps to reproduce (as originally observed)**
`curl http://127.0.0.1:8003/analytics/client-health` in PowerShell appeared to return only one client (bebop).

**Expected**
`/analytics/client-health` returns all three real clients (bebop, samvix, abc-traders).

**Actual (root cause)**
Not a defect. PowerShell's `curl` alias maps to `Invoke-WebRequest`, which truncates `.Content` in its default table view — the endpoint was returning all three clients correctly the entire time. Confirmed by re-running with `(Invoke-RestMethod http://127.0.0.1:8003/analytics/client-health) | ConvertTo-Json -Depth 5`, which bypasses the truncation.

**Fix**
None required — no application code changed.

**Retest result — final, 2026-09-18**
All three clients confirmed rendering with correct data:
- bebop — health_score 83, status healthy, engagement 6.00%, resolution 2.5h
- samvix — health_score 78, status healthy, engagement 3.21%, resolution 1.0h
- abc-traders — health_score 59, status at_risk, engagement 2.11%, resolution 8.0h

`sla_compliance_pct` is `null` for all three — a documented, expected limitation, not part of this defect: no `client_id` exists on defect data in the shared schema (same constraint as DEF-008/workload), pending Zeenat's confirmation before this signal can be added. In the meantime its component defaults to a neutral 70 in the health_score weighting (engagement 40% / SLA 30% / resolution 30%, confirmed by Zeenat).

**Status: Closed.**

---

## DEF-016 — Workload totals not yet confirmed against live data

| Field | Detail |
|---|---|
| **Owner** | Esha |
| **Found by** | Esha, following up on DEF-008's rebuild once the frontend wiring from DEF-013 went live |
| **Date found** | 2026-09-18 |
| **Severity** | Low — verification gap, not a suspected bug; DEF-008 already established the backend logic was correct |
| **Status** | **Closed.** Live retest confirms totals sum correctly and match the UI. |

**Steps to reproduce**
Call `GET /analytics/workload` live (all three services running concurrently) and compare its four bucket totals, and their sum, against the "Live Defect Workload" card on the Team Workload screen.

**Expected**
`completed + overdue + blocked + in_progress == total_tasks`, and the UI card shows the same four numbers.

**Actual**
Confirmed exactly: `65 (completed) + 65 (overdue) + 33 (blocked) + 34 (in_progress) = 197`, matching the endpoint's `total_tasks` exactly, and matching what the "Live Defect Workload" card renders via `refreshAllData()`.

**Fix**
None required — DEF-008's backend rebuild was already correct; this closes the outstanding live-data verification for it.

**Retest result — final, 2026-09-18**
197 confirmed live, both from the raw endpoint and the rendered UI card.

**Status: Closed.**