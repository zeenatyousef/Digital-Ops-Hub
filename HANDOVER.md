# NW Digital Operations Hub — Handover Documentation

**Prepared by:** Zeenat Yousef (Full-Stack, Integration & Deployment Lead)
**Date:** September 26, 2026
**Status:** Core platform feature-complete and integration-tested (67/67 automated tests passing). Deployment parked.

This document is a supplement to `README.md` — it covers everything a new developer or reviewer needs that isn't already in the setup guide: the full environment variable list, known gaps, and fragile areas to be aware of before extending or deploying this codebase.

---

## 1. What This Project Is

A shared multi-tenant operations platform for National Wireless, built by four contributors (Zeenat, Vishaqa, Asma, Esha), each owning a FastAPI microservice behind a common gateway. See `README.md` for the monorepo layout and local setup steps, and `ARCHITECTURE.md` for the system diagram and database ERD.

**Zeenat's ownership (this handover covers):** platform backbone (auth, tenancy, integration, deployment) plus the Clients, Client Rooms, Team Messenger, Personal Direct Chat, Campaigns/Approvals, Poster/Media, and Scheduler/Settings screens.

---

## 2. Environment Variables — Complete Reference

`.env.example` in the repo root is the starting template, but it is **missing two keys that are required for the app to run correctly** (see the warning in section 3). The full list of variables actually read by the code:

| Variable | Used In | Default If Missing | Purpose |
|---|---|---|---|
| `DATABASE_URL` | `packages/database/session.py`, `alembic/env.py` | `postgresql://nw_admin:nw_sec_password_2026_rotated@localhost:5432/nw_digital_ops_hub` | Main Postgres connection string (SQLAlchemy + Alembic). |
| `ENCRYPTION_KEY` | `apps/core_gateway/token_encryption.py` | **None — raises an error if missing/invalid** | Fernet key used to encrypt/decrypt social account access tokens at rest. |
| `JWT_SECRET` | `apps/core_gateway/security.py` | `"super_secret_jwt_token_2026_zeenat_yousef_lead"` (insecure fallback) | Signs and verifies user auth bearer tokens. |
| `JWT_ALGORITHM` | `apps/core_gateway/security.py` | `"HS256"` | JWT signing algorithm. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `apps/core_gateway/security.py` | `60` | JWT access token lifetime. |
| `VISHAQA_API_URL` | `apps/core_gateway/proxy.py` | `http://localhost:8001` | Base URL the gateway proxies to for Vishaqa's Support Intelligence service. |
| `ASMA_API_URL` | `apps/core_gateway/proxy.py` | `http://localhost:8002` | Base URL the gateway proxies to for Asma's Marketing/Social AI service. |
| `ESHA_API_URL` | `apps/core_gateway/proxy.py`, `esha_client.py` | `http://localhost:8003` | Base URL the gateway proxies to for Esha's Analytics/QA service. |
| `GROQ_API_KEY` | `groq_client.py` (Asma service) | **None** | External Groq Cloud LLM key used for AI-generated marketing captions/ideas. |
| `MOCK_MODE` | `groq_client.py` (Asma service) | `"false"` | When `"true"`, bypasses the Groq API and returns local offline template fallbacks instead. |
| `REDIS_URL` | `.env` (consumed by Celery/queue setup) | `redis://localhost:6379/0` | Background task queue and caching for publishing jobs. |
| `PORT` | `main.py` (gateway, Asma) | Gateway: `8000`, Asma: `8002` | Service port binding. |
| `HOST` | `main.py` (gateway, Asma) | `"0.0.0.0"` | Network interface binding. |
| `GATEWAY_BASE`, `DIRECT_BASE`, `GW_USER`, `GW_PASS` | `gateway_smoke_test_5_endpoints.py` | — | Overrides used only by the Esha smoke-test script; not needed for normal running. |

**Known naming inconsistency:** Esha's benchmark scripts (`vishaqa_benchmark.py`, `ai_evaluation_updated.py`) use `VIQASHA_API_URL`, while the core gateway proxy and `.env` use `VISHAQA_API_URL`. These are two different variable names pointing at the same service — worth unifying in a future cleanup so a typo doesn't silently break the benchmark script.

---

## 3. ⚠️ Setting Up `.env` — Don't Just Copy `.env.example`

`.env.example` is missing two variables that exist in the working `.env` used during development. **A fresh clone will not fully work without adding these manually:**

```ini
ENCRYPTION_KEY=<a-valid-32-byte-base64-fernet-key>
GROQ_API_KEY=<your-groq-cloud-api-key>
```

Without `ENCRYPTION_KEY`, connecting a social account (Queue Settings) will throw a Fernet error. Without `GROQ_API_KEY`, Asma's AI caption generation will fail unless `MOCK_MODE=true` is also set.

An updated `.env.example` with both keys included (as empty placeholders) is provided alongside this document — use that going forward instead of the current one in the repo.

---

## 4. Known Limitations & Fragile Areas

These are things that work today but are not production-hardened, or are intentionally simplified for this phase of the project. Anyone picking up this codebase should know about them before extending or deploying it.

1. **Attachments and posters are not on real object storage.** `ARCHITECTURE.md` diagrams S3/MinIO, but `MessageAttachment` and `MediaAsset` currently store either base64 Data URLs or mock URL strings directly as text in the database. This works for demos and small files but will not scale — a real upload service (S3, Cloudinary, etc.) should replace this before production use.

2. **Deployment is parked.** Config templates exist for Railway, Render, and Netlify (`railway.json`, `render.yaml`, `netlify.toml`), but none are actively deployed. The team currently runs everything locally via `docker-compose` (Postgres + Redis). Railway was tried and abandoned due to settings-save reliability issues; a Hugging Face Spaces shared-deployment plan was discussed but never started.

3. **Tests run against SQLite, production runs on Postgres.** The automated suites (`test_*_suite.py`) spin up temporary SQLite databases (`temp_test_*.db`) for speed and isolation. This is standard practice, but be aware that any Postgres-specific behavior (e.g., certain constraint or JSON handling edge cases) won't be caught by these tests. A handful of one-off SQL fix scripts in the repo root (`fix_pos_printing_form.sql`, `fix_pos_receipts.sql`, `fix_taxonomy_combos.sql`) were needed as manual patches during setup — check whether these still need to be run on a fresh Postgres instance.

4. **Social media publishing is simulated.** `PublishingJob` moves through `queued → processing → completed`/`manual_handoff`, but there is no real integration with Meta Graph API, LinkedIn, or TikTok. The queue logic marks jobs "complete" once the internal handoff logic passes — actual posting to a live platform is not implemented.

5. **JWT secret has an insecure silent fallback.** If `JWT_SECRET` is missing from `.env`, the app does not fail — it silently falls back to a hardcoded string (`"super_secret_jwt_token_2026_zeenat_yousef_lead"`). This is fine for local dev but must be changed to a hard failure before any real deployment, so a missing secret can never go unnoticed.

6. **Some Esha analytics metrics are intentionally "unavailable."** Complex metrics like lead scoring, profitability, and SLA compliance return an explicit "unavailable" status because the underlying data pipeline doesn't exist yet (documented in `apps/esha-service/main.py`). This is by design, not a bug — don't mistake it for a broken endpoint.

7. **Media asset approval is a one-way lock.** Once a poster is approved (`status=approved`, `is_locked=True`), there is no API endpoint to un-approve or revert it — only a direct database update can undo this. If revision-after-approval turns out to be a real workflow need, a new endpoint should be added.

8. **Message attachments have no size limit enforced server-side.** Since attachments are base64-encoded before sending, very large files will produce very large `TEXT` column values. There's currently no client- or server-side size cap — worth adding if this goes further than internal testing.

9. **Messaging is REST/polling-based, not WebSocket.** The task assignment calls for "Messaging WebSocket/REST" with typing/presence events. This implementation uses REST endpoints with periodic polling (`refreshAllData`) instead of a WebSocket connection. Messages are sent, saved, and retrieved correctly, but delivery isn't instant — a recipient sees a new message on their next poll cycle, not the moment it's sent. There is no typing indicator and no live presence/online status. This was a deliberate scope decision made late in the project: implementing WebSockets correctly (connection management, per-room/per-conversation broadcast, auth over WebSocket, reconnect handling, and re-testing tenant isolation on the new transport) was judged too large and too risky to add under time pressure without destabilizing the messaging features that were already working and tested. If this project continues, this should be the next major piece of work on the messaging module.

10. **Screenshots/Recording from Staging Environment:** Deployment to remote cloud staging is currently parked (the team runs everything locally via `docker-compose`). Remote staging video recordings/screenshots are deferred until cloud deployment resumes. Local test evidence, automated suite reports (67/67 passing), HTML test logs, and database QA trails (`test_cases`/`test_runs`) are generated and stored in `evidence/` as local proof of functionality.

---

## 5. What's Fully Working (as of this handover)

- Full authentication, multi-tenant isolation, and role-based access control (verified in `test_security_suite.py`, `test_auth_tenancy.py`).
- Clients CRUD, Client Rooms, Campaign approval workflow (draft → pending_approval → approved → scheduled → published).
- Team Messenger, Client Room chat, and Personal Direct Chat — each with **reply/threading, @mentions, and file attachments** (see `test_messaging_suite.py` and manual verification).
- Poster Export (Media Assets) API — versioning, approve/lock workflow (`test_media_assets_suite.py`, 10/10 passing).
- Queue Settings (Social Accounts) API — encrypted token storage, connect/disconnect, manual handoff for failed publishing jobs (`test_social_accounts_suite.py`, 9/9 passing).
- Integration proxy to Vishaqa, Asma, and Esha services, with fallback handling when those services are offline (`test_proxy.py`).
- Full integration test suite: **67/67 automated tests passing** (58 pytest + 9 Esha unit tests) as of the last full run.
- QA evidence trail recorded in the shared `test_cases`/`test_runs` tables for both new modules, plus a standalone evidence report (`Poster_Export_Queue_Settings_Evidence_Report.md`).

### Handover Deliverables Status Summary

| Item / Deliverable | Status | Details / Location |
|---|---|---|
| Core Gateway & API Specs | ✅ Complete | Updated `docs/API_SPECIFICATION.md` |
| Auth & Multi-tenancy | ✅ Complete | Verified in `test_security_suite.py` |
| Messaging (Team Messenger, DM, Voice Notes, Read Receipts) | ✅ Complete | `apps/core_gateway/routers/messaging.py` & DTOs |
| Poster Export & Media Assets | ✅ Complete | `Poster_Export_Queue_Settings_Evidence_Report.md` |
| Queue Settings & Encrypted Social Accounts | ✅ Complete | `apps/core_gateway/routers/social_accounts.py` |
| Microservices Proxy Integration | ✅ Complete | Gateway proxy to Vishaqa, Asma & Esha |
| Automated Test Suites & Evidence Trail | ✅ Complete | 67/67 tests passing (`evidence/`) |
| Screenshots / Recording from Staging | ⏸️ Parked | Cloud deployment parked; local docker-compose evidence logged in `evidence/` |

---

## 6. Suggested Next Steps (Beyond This Handover)

- Replace base64 attachment storage with a real object storage service.
- Decide on and execute an actual deployment target (the Hugging Face Spaces plan is the most recent discussion point).
- Harden the JWT secret fallback into a hard failure.
- Unify the `VISHAQA_API_URL` / `VIQASHA_API_URL` naming inconsistency.
- Add an un-approve/revert endpoint for media assets if the workflow requires it.
- Add real social platform publishing integrations if this moves past internal use.