# Esha Module — Schema Requirements (v2, matching task assignment exactly)

This replaces the simplified version currently in `models.py`. Goal: proper typed columns instead of JSON-blob text fields, plus the 3 missing test/QA tables.

---

## 1. Fix: `hashtag_sets` (currently too simplified)

**Currently has:** `id`, `tenant_id`, `name`, `created_at`

**Needs to become:**

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | (already exists) |
| `tenant_id` | UUID FK → tenants | (already exists) |
| `client_id` | UUID FK → clients, nullable | **NEW** — null = industry-wide set |
| `name` | String(255) | (already exists) |
| `category` | String(50) | **NEW** — "brand" \| "local" \| "campaign" \| "industry" |
| `platform` | String(50) | **NEW** — "instagram" \| "facebook" \| "twitter" \| "linkedin" \| "tiktok" |
| `version` | Integer, default=1 | **NEW** |
| `is_active` | Boolean, default=True | **NEW** |
| `created_at` | DateTime | (already exists) |

## 2. Fix: `hashtag_items` (currently too simplified)

**Currently has:** `id`, `hashtag_set_id`, `tag`, `created_at`

**Needs to become:**

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | (already exists) |
| `hashtag_set_id` | UUID FK → hashtag_sets | (already exists) |
| `tag` | String(255) | (already exists) |
| `exclusions` | Text, nullable | **NEW** — JSON array of tags banned in combination with this one |
| `performance_score` | Float, nullable | **NEW** |
| `created_at` | DateTime | (already exists) |

## 3. Fix: `quality_runs` (currently too simplified)

**Currently has:** `id`, `tenant_id`, `content`, `run_type`, `score`, `results`, `created_at`

**Needs to become:**

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | (already exists) |
| `tenant_id` | UUID FK → tenants | (already exists) |
| `content_version_id` | UUID FK → content_versions, nullable | **NEW** — links to Asma's content table |
| `input_version` | String(255), nullable | **NEW** — hash/version of content checked |
| `run_type` | String(100) | (already exists — "hashtags" \| "content" \| "similarity") |
| `checks` | Text (JSON) | **NEW** — per-check breakdown, separate from `results` |
| `issues` | Text (JSON) | **NEW** — array of {severity, location, message} |
| `score` | Float | (already exists) |
| `rule_version` | String(50), nullable | **NEW** — version of rubric used |
| `reviewer_id` | UUID FK → users, nullable | **NEW** — if a human reviewed/overrode |
| `created_at` | DateTime | (already exists) |

*(`content` and `results` can stay as-is for backward compatibility, or be removed if you're okay re-pointing my code — let me know which you'd prefer.)*

## 4. Fix: `analytics_events` (currently too simplified)

**Currently has:** `id`, `tenant_id`, `event_type`, `event_data`, `idempotency_key`, `created_at`

**Needs to become:**

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | (already exists) |
| `tenant_id` | UUID FK → tenants | (already exists) |
| `client_id` | UUID FK → clients, nullable | **NEW** |
| `event_type` | String(100) | (already exists) |
| `object_type` | String(100), nullable | **NEW** — e.g. "campaign", "content_version", "ticket" |
| `object_id` | UUID, nullable | **NEW** — polymorphic reference, not a hard FK |
| `metrics` | Text (JSON), nullable | **NEW** — e.g. `{"reach": 1200}` |
| `source` | String(100), nullable | **NEW** — which system emitted it |
| `occurred_at` | DateTime, nullable | **NEW** — when the real-world event happened |
| `idempotency_key` | String(255), unique | (already exists, rename OK to `event_key` if preferred) |
| `created_at` | DateTime | (already exists — acts as `recorded_at`) |

## 5. Fix: `report_snapshots` (currently too simplified)

**Currently has:** `id`, `tenant_id`, `report_type`, `data`, `created_at`

**Needs to become:**

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | (already exists) |
| `tenant_id` | UUID FK → tenants | (already exists) |
| `client_id` | UUID FK → clients | **NEW** |
| `period_start` | Date | **NEW** |
| `period_end` | Date | **NEW** |
| `dataset` | Text (JSON) | (rename `data` → `dataset` if possible) |
| `completeness` | Text (JSON) | **NEW** — e.g. `{"instagram": "complete", "facebook": "unavailable"}` |
| `created_at` | DateTime | (already exists — acts as `generated_at`) |

---

## 6. NEW: `test_cases`

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `tenant_id` | UUID FK → tenants | |
| `scenario` | Text | what's being tested |
| `expected_result` | Text | |
| `test_group` | String(100) | e.g. "hashtags" \| "content_quality" \| "analytics" \| "ai_evaluation" \| "regression" \| "smoke" |
| `created_at` | DateTime | |

## 7. NEW: `test_runs`

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `test_case_id` | UUID FK → test_cases | |
| `actual_result` | Text | |
| `status` | String(50) | "pass" \| "fail" \| "blocked" |
| `evidence_url` | String(500), nullable | link/path to screenshot or log |
| `run_at` | DateTime | |

## 8. NEW: `defects`

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `tenant_id` | UUID FK → tenants | |
| `test_run_id` | UUID FK → test_runs, nullable | |
| `owner_id` | UUID FK → users | |
| `severity` | String(50) | "critical" \| "high" \| "medium" \| "low" |
| `steps_to_reproduce` | Text | |
| `expected` | Text | |
| `actual` | Text | |
| `screenshot_url` | String(500), nullable | |
| `status` | String(50) | "open" \| "retested" \| "closed" |
| `created_at` | DateTime | |

---

## Migration note

This will need a new Alembic migration (similar to `1bfc94ceaa76_add_esha_asma_vishaqa_modules.py`), since it's altering existing tables (adding columns) and creating 3 new ones. Happy to write this myself and open a PR if that's faster for you — just let me know.
