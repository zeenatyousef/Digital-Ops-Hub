# Prompt Documentation — Campaign, Calendar and Content AI Module

This documents every Groq system prompt used by `apps/asma-service`, why it's
shaped the way it is, and which endpoint uses it. All prompts live in
`apps/asma-service/main.py` as named constants — this doc explains the
*intent* behind each one so a future maintainer doesn't have to reverse
-engineer it.

**Model:** `openai/gpt-oss-120b` (migrated from `llama-3.3-70b-versatile`,
which Groq decommissioned Aug 16 2026 — see `groq_client.py` docstring).
**Mode:** JSON mode forced on for every call (`response_format:
{"type": "json_object"}`) so responses always parse.

---

## 1. `BRIEF_SYSTEM_PROMPT` — used by `POST /marketing/brief`

**Goal:** extract structured campaign fields from raw client text without
inventing anything.

**Key design choices:**
- Every field gets a `confidence` score (0.0–1.0) rather than a flat
  yes/no — lets the UI/reviewer see *how sure* the extraction is, not just
  what it guessed.
- Explicitly instructed: if a field isn't in the text, return `null` and
  list it in `missing_fields` — this is the mechanism that satisfies the
  non-negotiable rule "do not invent client offers, prices, dates,
  addresses, claims."
- Forced JSON shape (exact keys) rather than free-form JSON — makes the
  response directly mappable to `campaign_briefs` columns with no parsing
  guesswork.

**Known limitation:** confidence scores are the model's own self-assessed
certainty, not independently verified — treat them as a *hint* for a human
reviewer, not a hard guarantee.

---

## 2. `CONTENT_SYSTEM_PROMPT` (+ `PLATFORM_CONSTRAINTS`) — used by `POST /marketing/content`

**Goal:** generate genuinely different copy per platform, never the same
caption reused (non-negotiable rule).

**Key design choices:**
- One Groq call *per platform*, each with a different `PLATFORM_CONSTRAINTS`
  string injected describing that platform's tone/length/format norms
  (e.g. LinkedIn = professional/longer, TikTok = very short/trend-aware).
  This is why outputs are structurally different, not just reworded —
  the model is told a different brief each time.
- Brand voice + required/prohibited wording are passed in as context, but
  compliance is **not** left to the model to self-report — see
  `_check_brand_rules()` below.
- Explicit instruction not to invent offers/prices/dates beyond the brief.

**Brand rule checking is NOT done by the AI.** After generation,
`_check_brand_rules()` runs a plain Python substring check against
`brand_profiles.required_wording` / `prohibited_wording` (comma-separated
lists). This was a deliberate choice: brand compliance needs to be
*verifiable* evidence, not a self-reported claim from the same model that
wrote the copy.

---

## 3. `TRANSLATE_SYSTEM_PROMPT` — used by `POST /marketing/translate`

**Goal:** translate approved content while preserving names, prices, dates,
addresses — the specific entities a bad translation would most likely
mangle.

**Key design choices:**
- Explicit instruction to carry over proper nouns/numbers/fixed brand
  phrases *unchanged* rather than translating them.
- Ambiguous terms (idioms, slang, multi-meaning words) go into
  `ambiguous_terms` instead of being silently guessed — this satisfies the
  task requirement "return warning for ambiguous terms."
- **Roman Urdu-specific guidance was added after a real bug:** the model
  initially produced Hindi/Sanskrit-origin vocabulary (e.g. "anand" instead
  of "khushi"/"maza") when asked for Roman Urdu. The prompt now explicitly
  says to use everyday Pakistani Urdu vocabulary and gives contrastive
  examples. This is worth remembering if other target languages show
  similar drift — the fix pattern is "give 2-3 concrete contrastive
  examples in the prompt," not just "be accurate."

**Endpoint-level gate:** only `content_versions` with `status == "approved"`
can be translated (checked before the Groq call, not by the prompt).

---

## 4. `DESIGNER_BRIEF_SYSTEM_PROMPT` — used by `POST /marketing/designer-brief`

**Goal:** produce poster/designer instructions without inventing product
images (non-negotiable rule: "do not replace approved original product
images with AI-generated products").

**Key design choices:**
- Explicit instruction: `visual_direction` should describe mood/composition
  /color guidance, **not** name a specific stock image or invented product
  photo. This keeps the model in "describe a direction for a human
  designer" mode rather than "hallucinate a specific image."
- `approved_media_ids` are supplied by the caller and passed through as
  `asset_references` — the model never generates or chooses image IDs
  itself.
- `logo_qr_rules` has a hardcoded fallback string
  ("Do not move, resize, recolor, or otherwise alter the approved logo
  lock-up.") if the model doesn't return one — this endpoint explicitly
  "does not control logo lock" per the task assignment, so a safe default
  matters more than a creative one here.

**Known limitation:** `approved_media_ids` aren't validated against a real
assets/media table (none exists in the shared schema yet) — they're taken
as given. Flagged to Zeenat as an open schema gap.

---

## 5. `REVISE_SYSTEM_PROMPT` — used by `POST /marketing/revise`

**Goal:** apply exactly the reviewer's requested change, nothing else
(task requirement: "Specific reviewer change applied without unrelated
changes").

**Key design choices:**
- Prompt explicitly says: apply ONLY the requested change, do not rewrite
  or "improve" anything else, keep everything else exactly as it was.
- **The diff shown to the reviewer is computed in code (`difflib`), not
  self-reported by the model.** This was a deliberate trust boundary: an
  AI narrating "here's what I changed" is not verifiable evidence; a
  word-level diff computed independently of the model's own claim is.

**Endpoint behavior:** always creates a new `content_versions` row
(incremented `version_number`); never touches the source row — satisfies
"never overwrite an approved version."

---

## General patterns used across all prompts

1. **JSON-only, no prose, no markdown fences** — every prompt ends with
   this instruction, and the API call forces `response_format:
   json_object`, so parsing never has to strip markdown fences.
2. **"Do not invent X"** appears in every prompt that touches client-facing
   facts (offers, prices, dates, claims) — this is the direct prompt-level
   enforcement of the task's non-negotiable rules, backstopped by
   code-level checks where verifiability matters (brand rules, diffs).
3. **Verifiable evidence over self-report** — anywhere the task assignment
   asks for "evidence" (brand compliance, version diffs), the check is done
   in Python against the model's output, not asked of the model itself.