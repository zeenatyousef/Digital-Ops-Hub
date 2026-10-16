# End-to-End Regression Evidence (Task Doc §8, "End-to-end regression" row)

Required cases: "Client request to publish; support issue to closure; DM to task."
All flows below tested through the real gateway (`http://127.0.0.1:8000`) with a real
authenticated user (`tenant_admin`, tenant `esha-dev-tenant`), not called directly against
individual services — this proves the actual integrated build, not just isolated modules.

---

## Flow 1: Client request → publish — PASS, fully evidenced

**Path tested:** `POST /api/campaigns` → `POST /api/campaigns/{id}/submit` →
`POST /api/campaigns/{id}/approve` → `POST /api/campaigns/{id}/schedule` →
`GET /api/publishing/jobs`

**Date:** 2026-08-27
**Tenant/client:** `esha-dev-tenant` / `bebop` (`f840ec8e-e2e2-498a-bbb5-a99bd54d67c9`)
**Campaign ID:** `e8708b3c-53a3-43d3-bc38-9c368b3729f5`
**Publishing job ID:** `b12ad66a-b17c-4f92-b35f-081b1938d7ea`

| Step | Call | Result |
|---|---|---|
| 1. Create | `POST /api/campaigns` | `status: draft`, ContentVersion v1 created (`status: pending`) |
| 2. Submit | `POST /api/campaigns/{id}/submit` | `status: draft → pending_approval` |
| 3. Approve | `POST /api/campaigns/{id}/approve` | `status: pending_approval → approved`, ContentVersion `status: approved` |
| 4. Schedule | `POST /api/campaigns/{id}/schedule` | Real `PublishingJob` created, `status: queued`, idempotency key `pub-e8708b3c-...-202608271141` |
| 5. Verify | `GET /api/publishing/jobs` | Same job now shows `status: completed`, real `completed_at` timestamp — confirms an actual background worker processed the queue, not a static field |

**Business rule verified:** the schedule endpoint correctly rejects scheduling before
approval (`if campaign.status != "approved": raise HTTPException(400, ...)`), matching the
doc's "No false published status in analytics" requirement — a campaign cannot reach
"scheduled"/"queued"/"completed" without genuinely passing through `approved` first.

**Conclusion:** this flow is real, integrated, and correctly enforces its own business rules.
No gaps found.

---

## Flow 2: Support issue → closure — PASS, fully evidenced

**Updated 2026-08-28.** Previously blocked (see superseded note below) — unblocked by
Zeenat's commit `01e3566`, which added client-room lifecycle endpoints to `messaging.py`.
Tested through the real gateway (`http://127.0.0.1:8000`), authenticated as `tenant_admin`.

| Step | Call | Result |
|---|---|---|
| 1. Create support room | `POST /api/client-rooms` (`client_id: f840ec8e-e2e2-498a-bbb5-a99bd54d67c9`) | Room `0239aabf-866b-4217-82cc-6ee52ef90976` created, `status: active` |
| 2. Log the issue | `POST /api/client-rooms/{id}/messages` | Message `bd4a506e-0133-4df1-b6d9-72935fa2c4b6` created, `visibility: external` (correctly respected) |
| 3. Confirm open state | `GET /api/client-rooms` | `status: active` confirmed |
| 4. Close the ticket | `PATCH /api/client-rooms/{id}/status` (`{"status": "closed"}`) | `status: closed` returned |
| 5. Confirm persisted | `GET /api/client-rooms` | `status: closed` confirmed on independent re-fetch |

Real IDs throughout, state transition independently re-verified rather than trusting the
PATCH response alone.

## Flow 3: DM → task — PASS, fully evidenced

**Updated 2026-08-28.** Previously blocked (`WorkitemConvertRequest.target_type` only
accepted `defect`/`test_case`) — unblocked by the same commit `01e3566`, which added
`"task"` as a valid `target_type`.

| Step | Call | Result |
|---|---|---|
| 1. Create conversation | `POST /api/conversations` | Conversation `1bb8fe29-2489-591c-b43e-dec9a851e963` |
| 2. Send DM | `POST /api/conversations/{id}/messages` | Message `00b373c4-fab8-445e-ace7-7be8e76a57c3` created (`visibility: internal` — confirmed by design; see `evidence/smoke_checklist.md` note) |
| 3. Convert to task | `POST /api/messages/{id}/convert` (`{"target_type": "task", "severity": "medium"}`) | `status: converted, target_type: task, target_id: e5ca3086-c492-4072-903f-a7544eab4877` |

**Implementation note:** `target_type: "task"` shares the same code path as `"defect"` —
it creates a row in the `Defect` table, not a separate `Task` model; no distinct Task
entity exists in the codebase. This satisfies the requirement functionally (a trackable
work item is created from the message) but is named explicitly here rather than implying
a dedicated task system exists.

---

**§8 summary: 3/3 required E2E flows tested and passing** (Flow 1 confirmed 2026-08-27;
Flows 2 and 3 unblocked and confirmed 2026-08-28 following Zeenat's `01e3566`).

<details>
<summary>Superseded note (2026-08-27) — kept for record</summary>

Previously, Flows 2 and 3 were untestable: no ticket/task router existed in
`core_gateway`, and `convert`'s `target_type` didn't support `"task"`. This was logged as
a scope gap, not a defect, and flagged to the team. See git history for the original
full note. Resolved by commit `01e3566`.

</details>