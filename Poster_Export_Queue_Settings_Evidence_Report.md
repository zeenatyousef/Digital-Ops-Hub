# Poster Export & Queue Settings — QA Evidence Report

**NW Digital Operations Hub | Section 8 Testing Responsibilities**
**Module Owner:** Zeenat Yousef (Full-Stack, Integration & Deployment Lead)
**Test Result:** ✅ 19 / 19 PASSED
**Automated Suites:** `test_media_assets_suite.py`, `test_social_accounts_suite.py`

---

## 1. Scope

This report documents automated test evidence for two backend modules that had no prior automated coverage:

| Module | Router File | Endpoints Covered |
|---|---|---|
| Poster Export (Media Assets) | `apps/core_gateway/routers/media_assets.py` | `POST /api/media-assets`, `GET /api/media-assets`, `POST /api/media-assets/{id}/approve` |
| Queue Settings (Social Accounts) | `apps/core_gateway/routers/social_accounts.py` | `POST /api/social-accounts`, `GET /api/social-accounts`, `DELETE /api/social-accounts/{id}`, `POST /api/publishing/jobs/{id}/manual-handoff` |

---

## 2. Poster Export (Media Assets) — 10/10 Passed

| # | Scenario | Expected Result | Status |
|---|---|---|:---:|
| 1 | Create first media asset for a campaign | `version_number=1`, `status=pending_review`, `is_locked=False` | ✅ PASS |
| 2 | Upload a second poster for the same campaign | `version_number` auto-increments to 2 | ✅ PASS |
| 3 | Upload a poster for a different/unrelated campaign | `version_number` resets and starts at 1 | ✅ PASS |
| 4 | List all media assets for the tenant | Returns all created assets across campaigns | ✅ PASS |
| 5 | List media assets filtered by `campaign_id` | Returns only the 2 assets for that campaign (v1, v2) | ✅ PASS |
| 6 | Approve a pending media asset | `status=approved`, `is_locked=True`, `reviewed_by_id` set | ✅ PASS |
| 7 | Approve a media asset that does not exist | 404 Not Found | ✅ PASS |
| 8 | `client_rep` attempts to create a media asset | 403 Forbidden (creation restricted to admin/designer) | ✅ PASS |
| 9 | `client_rep` approves a media asset | 200 OK — approval is allowed for `client_rep` | ✅ PASS |
| 10 | Unauthenticated request to list media assets | 401/403 rejected | ✅ PASS |

**Key behaviors verified:**
- Version numbering is scoped per campaign, not global.
- Approval is a one-way gate: once approved, the asset is locked and cannot be re-edited without further backend support.
- Role separation is enforced: only admins/designers can upload; both admins and clients can approve (client sign-off use case).

---

## 3. Queue Settings (Social Accounts) — 9/9 Passed

| # | Scenario | Expected Result | Status |
|---|---|---|:---:|
| 1 | Connect a new social account with a raw access token | 201 Created; token encrypted at rest, never returned in the response | ✅ PASS |
| 2 | List connected social accounts for the tenant | Returns the connected account(s) | ✅ PASS |
| 3 | Disconnect a connected social account | 204 No Content; account no longer appears in list | ✅ PASS |
| 4 | Disconnect a social account that does not exist | 404 Not Found | ✅ PASS |
| 5 | Manual handoff on a failed publishing job | `status` becomes `manual_handoff` with a human-review note | ✅ PASS |
| 6 | Manual handoff on a publishing job that does not exist | 404 Not Found | ✅ PASS |
| 7 | `designer` attempts to connect a social account | 403 Forbidden (connect restricted to admin roles) | ✅ PASS |
| 8 | `designer` lists accounts (allowed) then attempts disconnect (blocked) | List succeeds (200); disconnect rejected (403) | ✅ PASS |
| 9 | Unauthenticated request to list social accounts | 401/403 rejected | ✅ PASS |

**Key behaviors verified:**
- Access tokens are stored via `Fernet` symmetric encryption (`token_encryption.py`) — the raw token is confirmed absent from both the API response and the encrypted DB column, and successfully decrypts back to the original value.
- The manual handoff endpoint correctly pulls a failed job out of the automated retry queue and flags it for a human to complete, without deleting any job history.
- Only `super_admin`/`tenant_admin` roles can connect or disconnect accounts; `designer` has read-only access.

---

## 4. Defects Found

None. All 19 test cases passed against the implementation as built. One test-harness issue was found and corrected during development (a raw string UUID needed explicit casting to `uuid.UUID` before an ORM lookup in the test file itself — not an application defect).

---

## 5. Evidence Storage

In addition to this report, the same 19 cases are recorded in the shared database evidence tables (`test_cases` / `test_runs`), consistent with the QA process already used for Vishaqa's support-intelligence benchmark. This was done via `generate_media_social_evidence.py`, run once against the live database after the automated suites passed.

---

## 6. How to Reproduce

```bash
# 1. Run the automated test suites
python -m pytest test_media_assets_suite.py test_social_accounts_suite.py -v

# 2. Record the evidence in the shared database (test_cases / test_runs)
python generate_media_social_evidence.py
```

**Report generated:** September 26, 2026