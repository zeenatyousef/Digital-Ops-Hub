# NW Digital Operations Hub — API Specification

**Owner:** Zeenat Yousef (Full-Stack, Integration and Deployment Lead)
**Base URL (local dev):** `http://127.0.0.1:8000`
**Last updated:** September 29, 2026

This document covers every endpoint on the Core Gateway, including the ones that proxy through to Vishaqa, Asma, and Esha's services. For endpoints owned directly by those services (not through the gateway), see their own READMEs.

---

## 1. Conventions Used in This Document

- All request/response bodies are JSON unless noted otherwise.
- All protected endpoints require a bearer token: `Authorization: Bearer <access_token>`.
- All protected endpoints are tenant-scoped automatically from the token — `tenant_id` is never trusted from the request body.
- Timestamps are returned as naive UTC ISO-8601 strings (e.g. `"2026-09-29T14:30:00.123456"`). They do **not** carry a `Z` or offset suffix — treat them as UTC when parsing on the client.
- `{id}` style path segments are UUIDs unless stated otherwise.
- Roles referenced below: `super_admin`, `tenant_admin`, `designer`, `client_rep`.

### Standard Error Shape

```json
{ "detail": "Human-readable error message" }
```

| Status | Meaning |
|---|---|
| 400 | Bad request — invalid input, duplicate value, or business-rule violation |
| 401 | Missing, invalid, or expired bearer token |
| 403 | Authenticated, but the role doesn't have permission for this action |
| 404 | Resource not found (or not visible to this tenant) |
| 422 | Request body failed schema validation (malformed JSON, missing required field) |
| 500 | Unhandled server/database error |
| 502 | A downstream AI service (Vishaqa/Asma/Esha) is unreachable or returned an error |

---

## 2. Authentication

### `POST /api/auth/login`
Form-encoded (not JSON): `username`, `password`.

**Sample request (form data):**
```
username=atif@nationalwireless.com
password=password
```

**Sample response — 200:**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}
```

**Errors:** `401` invalid credentials or inactive user. Returns `429` if login rate limit (5 failed attempts per min per IP+email) is exceeded.

### `POST /api/auth/logout`
Denylists the current JWT access token via its `jti` claim until token expiration.

**Sample response — 200:**
```json
{ "detail": "Successfully logged out" }
```

### `POST /api/auth/refresh`
Exchanges a valid, unexpired access token for a fresh token.

**Sample response — 200:**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}
```

### `GET /api/auth/me`
Returns the current authenticated user's profile.

**Sample response — 200:**
```json
{
  "id": "00000000-0000-0000-0000-00000000000c",
  "tenant_id": "00000000-0000-0000-0000-00000000000a",
  "email": "atif@nationalwireless.com",
  "full_name": "Atif Zaheer",
  "role": "super_admin",
  "is_active": true,
  "phone_number": null,
  "created_at": "2026-07-01T09:00:00.000000"
}
```

### `POST /api/admin/users`
Roles: `super_admin`, `tenant_admin`. Admin user creation for the caller's tenant (`tenant_id` resolved from JWT token).

**Sample request:**
```json
{
  "email": "designer.new@nationalwireless.com",
  "role": "designer",
  "password": "Password123!",
  "full_name": "New Designer User"
}
```
**Sample response — 201:** `UserRead` object (`id`, `email`, `role`, `is_active: true`, etc.).

### `PATCH /api/users/{user_id}/disable`
Roles: `super_admin`, `tenant_admin`. Deactivates user account (`is_active: false`). User is blocked from logging in.
**Errors:** `400` if admin attempts to disable their own account; `404` for cross-tenant user ID; `403` for non-admin roles. Logs audit event `user.disabled`.

### `PATCH /api/users/{user_id}/enable`
Roles: `super_admin`, `tenant_admin`. Re-activates user account (`is_active: true`). Logs audit event `user.enabled`.

---

## 3. Clients

### `GET /api/clients`
Roles: all authenticated roles.

**Sample response — 200:**
```json
[
  {
    "id": "7b535287-e562-4e84-9bc7-886f67915ec2",
    "tenant_id": "00000000-0000-0000-0000-00000000000a",
    "company_name": "Bebop Staples Mill",
    "industry": "Food & Beverage",
    "contact_email": "contact@bebop.example.com",
    "created_at": "2026-08-01T10:00:00.000000"
  }
]
```

### `POST /api/clients`
Roles: `super_admin`, `tenant_admin`.

**Sample request:**
```json
{
  "company_name": "Samvix Retail",
  "industry": "Retail",
  "contact_email": "ops@samvix.example.com"
}
```

**Sample response — 201:** same shape as above.
**Errors:** `400` duplicate `contact_email` within the tenant.

### `PATCH /api/clients/{client_id}`
Roles: `super_admin`, `tenant_admin`. Partial update — any subset of `company_name`, `industry`, `contact_email`.

### `DELETE /api/clients/{client_id}`
Roles: `super_admin`, `tenant_admin`. Returns `204 No Content`.

### `GET /api/clients/{client_id}` — Client 360
Roles: all authenticated roles. Returns the client plus its linked campaigns and team members (users whose `client_id` matches).

**Sample response — 200:**
```json
{
  "id": "7b535287-e562-4e84-9bc7-886f67915ec2",
  "company_name": "Bebop Staples Mill",
  "industry": "Food & Beverage",
  "contact_email": "contact@bebop.example.com",
  "created_at": "2026-08-01T10:00:00.000000",
  "campaigns": [
    { "id": "c1a2...", "name": "Weekend Fusion Deal", "status": "approved", "created_at": "..." }
  ],
  "team_members": []
}
```
`team_members` is commonly empty — `client_rep` users are not auto-linked to a client on creation; it must be set explicitly via the `User.client_id` field.

**Errors:** `404` client not found in this tenant.

---

## 4. Client Rooms

### `POST /api/client-rooms`
Roles: `super_admin`, `tenant_admin`, `designer`.
```json
{ "client_id": "7b535287-e562-4e84-9bc7-886f67915ec2" }
```
**Response — 201:** `{ "id": "...", "client_id": "...", "tenant_id": "...", "status": "active", "created_at": "..." }`

### `GET /api/client-rooms`
Roles: all authenticated roles.

### `PATCH /api/client-rooms/{client_room_id}/status`
Roles: `super_admin`, `tenant_admin`, `designer`.
```json
{ "status": "closed" }
```
Posts an automatic system message into the room announcing the status change.

### `GET /api/client-rooms/{client_room_id}/messages`
Roles: all authenticated roles. `client_rep` only ever sees `visibility: "external"` messages — internal notes are filtered out server-side, not just hidden in the UI.

### `POST /api/client-rooms/{client_room_id}/messages`
Roles: all authenticated roles (but `client_rep` is rejected with `403` if they try to send `visibility: "internal"`).

**Sample request:**
```json
{
  "content": "The poster draft looks great, approved!",
  "content_type": "text",
  "visibility": "external",
  "parent_message_id": null,
  "mentioned_user_ids": [],
  "attachments": []
}
```

**Sample response — 201:**
```json
{
  "id": "msg-uuid",
  "client_room_id": "room-uuid",
  "conversation_id": null,
  "sender_id": "user-uuid",
  "sender_role": "designer",
  "content": "The poster draft looks great, approved!",
  "content_type": "text",
  "visibility": "external",
  "parent_message_id": null,
  "read_at": null,
  "created_at": "2026-09-29T10:00:00.000000",
  "mentions": [],
  "attachments": []
}
```

### `POST /api/client-rooms/{client_room_id}/read`
Roles: all authenticated roles. Marks unread messages (not sent by the caller) as read. For `client_rep`, only `visibility: "external"` messages are marked — internal notes they can't see are never touched.

**Response — 200:** `{ "marked_read": 3 }`

---

## 5. Team Messenger & Personal Direct Chat (Conversations)

Both the shared internal channel and 1:1 DMs use the same `conversations` mechanism — a DM is just a conversation with exactly one other participant.

### `POST /api/conversations`
Roles: `super_admin`, `tenant_admin`, `designer` (client reps cannot start internal DMs).
```json
{ "participant_ids": ["teammate-user-id"] }
```
**Response — 201:** `{ "id": "deterministic-conversation-uuid", "created_at": "..." }`
**Errors:** `400` if a participant is invalid or is a `client_rep`.

### `GET /api/conversations/{conversation_id}/messages`
Roles: participants only. `403` if the caller isn't a member of this conversation.

### `POST /api/conversations/{conversation_id}/messages`
Same body shape as Client Room messages (see above), minus `visibility` (DMs/Team Messenger are always `internal`).

### `POST /api/conversations/{conversation_id}/read`
Marks all unread messages in the conversation (not sent by the caller) as read.
**Response — 200:** `{ "marked_read": 1 }`

### `GET /api/messages/{message_id}/thread`
Roles: all authenticated roles. Returns `[parent_message, ...replies]`, ordered oldest-first. Works for Client Room, Team Messenger, and DM messages alike.

### `POST /api/messages/{message_id}/convert`
Converts a message into a Defect/Task or a Test Case.
```json
{ "target_type": "defect", "severity": "medium", "owner_id": null }
```
**Response — 201:** `{ "status": "converted", "target_type": "defect", "target_id": "new-uuid" }`
### `PATCH /api/messages/{message_id}`
Roles: original sender only (admin access blocked for DMs unless caller is the sender). Edits message content and updates `edited_at` timestamp. Logs audit event `message_edited` with previous content in diff.

**Sample request:**
```json
{ "content": "Updated message text after edit" }
```
**Sample response — 200:** `MessageRead` object with updated `content` and populated `edited_at`.
**Errors:** `403` if caller is not the message sender. `404` if message not found in caller's tenant.

### `DELETE /api/messages/{message_id}`
Roles: original sender only (admin access blocked for DMs unless caller is the sender). Soft-deletes message by setting `deleted_at` timestamp. Read endpoints return `"[deleted]"` for deleted messages. Logs audit event `message_deleted`.

**Sample response — 200:** `MessageRead` object with `deleted_at` timestamp.
**Errors:** `403` if caller is not the message sender. `404` if message not found in caller's tenant.

---

## 6. QA Defects

### `GET /api/defects`
Roles: `super_admin`, `tenant_admin`, `designer`.

**Sample response — 200:**
```json
[
  {
    "id": "defect-uuid",
    "tenant_id": "00000000-0000-0000-0000-00000000000a",
    "test_run_id": null,
    "owner_id": "00000000-0000-0000-0000-00000000000e",
    "severity": "medium",
    "steps_to_reproduce": "Message context:\nCheckout error on mobile viewport",
    "expected": "Resolved operational flow",
    "actual": "Incorrect operational state",
    "screenshot_url": null,
    "status": "open",
    "due_date": "2026-10-15T18:00:00.000000",
    "is_blocked": false,
    "created_at": "2026-09-29T10:00:00.000000"
  }
]
```

### `PATCH /api/defects/{defect_id}/status`
```json
{ "status": "investigating" }
```
Status cycles `open → investigating → resolved → open` in the UI, but the endpoint accepts any valid status string directly.

---

## 7. Campaigns & Calendar

### `POST /api/campaigns`
Roles: all authenticated roles that can reach the Campaign Builder.
```json
{ "name": "August Back-to-School Fusion", "client_id": "7b535287-e562-4e84-9bc7-886f67915ec2" }
```
Optional fields: platform, language, caption, cta, hashtags_reference, scheduled_publish_at
**Response — 201:** campaign object, `status: "draft"`.
**Errors:** `400` if `client_id` is missing or doesn't belong to this tenant.

### `POST /api/campaigns/{campaign_id}/submit`
Transitions `draft → pending_approval`. No request body.

### `POST /api/campaigns/{campaign_id}/calendar`
Persists an approved/scheduled campaign into the calendar as a `CalendarItem`. No request body — pulls `scheduled_publish_at` and `name` from the campaign itself.
**Response — 201:** `{ "status": "persisted", "calendar_item_id": "...", "scheduled_time": "..." }`

### `GET /api/calendar`
Roles: all authenticated roles.
```json
[
  {
    "id": "...", "campaign_brief_id": null,
    "scheduled_time": "2026-09-29T18:30:00.000000",
    "content_draft": "Campaign: August Back-to-School Fusion",
    "platform": "Multi-channel", "objective": "Campaign persist workflow",
    "status": "scheduled", "owner": "Atif Zaheer"
  }
]
```

### `POST /api/calendar` (manual post scheduling — query params, not JSON body)
Roles: `super_admin`, `tenant_admin`, `designer`.
```
POST /api/calendar?scheduled_time=2026-10-01T18:00:00Z&platform=Instagram&content_draft=Weekend+promo&objective=Brand+Awareness
```
**Errors:** `403` if caller role isn't allowed.

### `POST /api/marketing/brief` (proxied to Asma)
```json
{
  "client_id": "...", "tenant_id": "...",
  "brand_profile_id": "brand-profile-uuid",
  "source_message_ids": [],
  "raw_text": "30% discount on 5G packages for new subscribers in Richmond area"
}
```
**Response — 200:** structured brief with `objective`, `audience`, `location`, `offer`, `dates`, `deliverables`, `platforms`, `assets` (each with `value`/`confidence`), plus `missing_fields`.
**Errors:** `404` (wrapped as `502` by the gateway) if `brand_profile_id` doesn't exist. `502` if Asma is offline.

---

## 8. Publishing Jobs & Scheduler

### `POST /api/publishing/jobs/{job_id}/cancel`
Roles: `super_admin`, `tenant_admin`. Cancels a queued job (`status: "cancelled"`).
**Response — 200:** `{ "id": "job-uuid", "status": "cancelled", "detail": "Job successfully cancelled" }`
**Errors:** `400` if job status is not `queued`. `404` for cross-tenant attempt or non-existent job. Logs audit event `publishing.job.cancelled`.

### `POST /api/publishing/jobs/{job_id}/manual-handoff`
Roles: `super_admin`, `tenant_admin`. Pulls a job out of the automated queue for a human to finish manually. Requires proof (`manual_proof`, `proof_url`, or `proof_note`). Sets `job.manual_proof` and transitions campaign status to `published` once all campaign jobs are complete/manual_handoff.

**Sample request:**
```json
{ "manual_proof": "https://instagram.com/p/manual_post_proof_123" }
```
**Response — 200:**
```json
{
  "id": "job-uuid",
  "status": "manual_handoff",
  "manual_proof": "https://instagram.com/p/manual_post_proof_123",
  "note": "Marked for manual publishing outside the automated queue — a human must complete this post manually."
}
```
**Errors:** `422` if manual proof is missing; `404` if job not found. Logs audit event `publishing.job.manual_handoff`.

> **Rule 3 Enforcement:** Simulated publish ke baad campaign 'published' tab hota hai jab job mein `platform_post_id` ya `manual_proof` ho (Rule 3). No post is marked `published` without platform confirmation (`platform_post_id`) or manual proof (`manual_proof`). The scheduler daemon marks jobs `completed` upon simulated execution, but campaign status remains in its scheduled/approved state until platform confirmation or manual proof is supplied.

---

## 9. Poster Export (Media Assets)

### `POST /api/media-assets`
Roles: `super_admin`, `tenant_admin`, `designer`.
```json
{ "campaign_id": "campaign-uuid", "file_url": "data:image/png;base64,iVBORw0KGgo..." }
```
**Response — 201:** `version_number` auto-increments per campaign (starts at 1 for a new campaign).

### `GET /api/media-assets?campaign_id={id}`
Roles: all authenticated roles. `campaign_id` filter is optional.

### `POST /api/media-assets/{asset_id}/approve`
Roles: `super_admin`, `tenant_admin`, `client_rep`. Sets `status: "approved"`, `is_locked: true`, `reviewed_by_id` to the caller.
**Errors:** `404` asset not found. There is currently no un-approve endpoint — reverting requires a direct database update (see Known Limitations).

---

## 10. Queue Settings (Social Accounts)

### `POST /api/social-accounts`
Roles: `super_admin`, `tenant_admin`.
```json
{ "platform": "instagram", "account_identifier": "nw_official", "access_token": "raw-token-from-oauth-flow" }
```
**Response — 201:** the account record. The raw token is never echoed back — it's encrypted (`Fernet`) before storage and only `access_token_encrypted` exists server-side.

### `GET /api/social-accounts`
Roles: `super_admin`, `tenant_admin`, `designer` (read-only for designer).

### `DELETE /api/social-accounts/{account_id}`
Roles: `super_admin`, `tenant_admin`. Returns `204 No Content`.
**Errors:** `404` account not found. `403` for `designer`.

---

## 11. Analytics (proxied to Esha)

### `GET /api/analytics/client-health`
Per-client health scoring. Returns `{"clients": [], ...}` with an empty array and a `limitations` list when there isn't enough underlying event data yet — this is expected behavior, not an error.

### `GET /api/analytics/client-summary`
Tenant-wide KPI rollup used by the Analytics dashboard cards.
```json
{
  "total_reach": 1654,
  "engagement_rate_pct": 5.74,
  "leads": null,
  "profitability_pct": null,
  "avg_ticket_resolution_hours": null,
  "client_performance": [{ "client": "Acme Wireless Partners", "reach": 1654 }],
  "unavailable_fields": ["leads", "profitability_pct", "avg_ticket_resolution_hours"],
  "data_source": "analytics_events.metrics + ticket.opened/ticket.closed pairs"
}
```
Any field can be `null` with its name listed in `unavailable_fields` when there's no event data to compute it from yet — the frontend renders `—`/"No data yet" rather than a fake number in that case.

### `GET /api/analytics/scheduler-consistency`
### `GET /api/analytics/workload`
Both proxied directly to Esha; see Esha's own docs for response shape.

### `GET /api/analytics/monthly-report`
Generates a monthly rollup, flags any missing data sources explicitly rather than guessing.

---

## 12. Support (proxied to Vishaqa)

### `POST /api/support/classify`
```json
{ "tenant_id": "...", "message": "FBR invoices completely blocked" }
```
**Response — 200:** `{ "product": "Production Outage", "severity": "Critical", "human_required": true }`

### `POST /api/support/retrieve`
Vector search over the knowledge base.
```json
{ "query": "FBR invoice timeout", "top_k": 5 }
```

### `POST /api/support/suggest-reply`
Drafts a reply from retrieved KB articles; `human_required: true` with `proposed_reply: null` when no articles were found — it never invents an answer.

### `POST /api/support/summarize`
Summarizes a client-room conversation.

### `POST /api/support/escalation`
```json
{ "tenant_id": "...", "ticket_message": "...", "severity": "Critical" }
```
**Response — 200:** `{ "severity": "Critical", "escalation_required": true }`

### `GET /api/support/health`
Simple liveness check for the Vishaqa service.

### `POST /api/kb-articles`
Roles: `super_admin`, `tenant_admin`. Creates a Knowledge Base article in `draft` status for the caller's tenant (`tenant_id` resolved from JWT token).

**Sample request:**
```json
{
  "title": "FBR Invoice Timeout Troubleshooting",
  "content": "Check gateway connection and restart Oracle listener daemon.",
  "product": "FBR Digital Invoicing",
  "risk_level": "medium"
}
```

**Sample response — 201:**
```json
{
  "id": "7b535287-e562-4e84-9bc7-886f67915ec2",
  "tenant_id": "00000000-0000-0000-0000-00000000000a",
  "title": "FBR Invoice Timeout Troubleshooting",
  "content": "Check gateway connection and restart Oracle listener daemon.",
  "review_status": "draft",
  "product": "FBR Digital Invoicing",
  "risk_level": "medium",
  "created_at": "2026-09-29T10:00:00.000000"
}
```
**Errors:** `403` forbidden for non-admin roles (`designer`, `client_rep`). `422` schema validation error.

### `GET /api/kb-articles`
Roles: all authenticated roles. Returns articles for the tenant. Optional query param: `review_status` (`draft` / `approved`).

### `POST /api/kb-articles/{article_id}/approve`
Roles: `super_admin`, `tenant_admin`. Transitions article status `draft → approved`, indexing it for RAG auto-guidance retrieval.

**Sample response — 200:**
```json
{
  "id": "7b535287-e562-4e84-9bc7-886f67915ec2",
  "tenant_id": "00000000-0000-0000-0000-00000000000a",
  "title": "FBR Invoice Timeout Troubleshooting",
  "content": "Check gateway connection and restart Oracle listener daemon.",
  "review_status": "approved",
  "product": "FBR Digital Invoicing",
  "risk_level": "medium",
  "created_at": "2026-09-29T10:00:00.000000"
}
```
**Errors:** `404` article not found or cross-tenant attempt. `403` forbidden for non-admin roles (`designer`, `client_rep`).

---

## 13. Audit Log

### `GET /api/audit-events`
Roles: `super_admin`, `tenant_admin`. Append-only log — every sensitive action (message sent, status changed, approval granted, etc.) is recorded here automatically by the relevant endpoint.

```json
[
  {
    "id": "...", "user_id": "...", "action_name": "persist_campaign_to_calendar",
    "entity_name": "CalendarItem", "entity_id": "...", "diff_data": null,
    "created_at": "2026-09-29T10:00:00.000000"
  }
]
```

---

## 14. Dev/Test Utility

### `POST /api/seed`
**Not for production use.** Seeds a demo tenant, users, and sample data into whatever database `DATABASE_URL` currently points at. Used exclusively by the automated test suites to get a clean, known starting state.

---

## 15. Known Gaps in This Spec

- **WebSocket / Typing Indicators / Presence:** No WebSocket endpoints exist yet. All messaging uses REST APIs with client-side polling. Future WebSocket implementation should cover real-time typing indicators, user presence states, and instant message notifications.
- **Base64 (Non-Signed) Media:** Poster exports and legacy asset uploads currently accept Base64 data URIs alongside standard HTTP file URLs; full pre-signed cloud media URLs are supported via `/api/media/upload`.
