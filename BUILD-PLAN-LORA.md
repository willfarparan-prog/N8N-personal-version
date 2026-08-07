# Build Plan — Close the LoRA Loop in FlowForge

_Last updated: 2026-08-06_

## What's already here (don't rebuild)

FlowForge is a Supabase-backed, Vercel-Python workflow engine with a LiteGraph
canvas frontend. fal.ai is already wired:

- `api/_lib/nodes/fal_train_lora.py` — submits a training job, returns
  `pending_external` with `request_id` / `status_url` / `response_url`.
- `api/cron/poll_jobs.py` — every minute, checks fal status; on `COMPLETED` it
  fetches the response and `resume_execution(...)` continues the paused run.
- `api/_lib/nodes/fal_generate_image.py` — synchronous image gen; overrides
  `prompt` from an upstream input.
- Frontend palette (`public/workflow.html`) has **Train LoRA** and **Generate
  Image** nodes.

## The real gaps (what "integrate correctly" means)

1. **No model registry.** A finished LoRA's weights URL only exists inside that one
   execution's outputs/logs. It can't be reused by name in a later workflow.
2. **Generate Image can't consume a LoRA.** No `loras:[{path,scale}]`, no trigger
   word, no picker — you'd have to hand-edit raw JSON and know the URL.
3. **Train LoRA writes nothing durable.** No name, no trigger word captured as a
   first-class record; output is ephemeral.
4. **No dashboard surface.** Nowhere shows "your brand models," their training
   status, or lets you pick one.

## The fix — five changes

### 1. DB: `trained_loras` registry (additive migration)
New migration file under `supabase/migrations/`, applied through the project's
additive workflow (see V2 foundation migration for the pattern).

```
trained_loras (
  id uuid pk, name text, trigger_word text,
  base_model text default 'flux',              -- inference endpoint family
  weights_url text,                            -- fal diffusers_lora_file url
  status text check in ('training','ready','failed') default 'training',
  thumbnail_url text,
  source_execution_id uuid references executions(id),
  training_input jsonb default '{}', error text,
  created_at timestamptz default now(), updated_at timestamptz default now()
)
```
RLS: browser role reads `ready` rows; service role writes. (Note: this project
currently has RLS **disabled** on 10 existing tables — flagged separately; new
table should ship with RLS on + explicit policies so we don't widen the hole.)

### 2. Train LoRA node → register on submit
`fal_train_lora.py`: add a `name` config field; on successful submit, insert a
`trained_loras` row (`status='training'`, `source_execution_id`, `trigger_word`
from input, `training_input`). Return its id in `external_ref` so the poller can
find it.

### 3. Poller → complete the registry row
`poll_jobs.py`: when a `fal` job completes **and** its `external_ref` carries a
`trained_lora_id`, extract the weights URL from `result_json`
(`diffusers_lora_file.url` / `safetensors`) and update the row to
`status='ready', weights_url=...`. On unexpected/failed status → `status='failed'`
with the error. (Keep the existing resume-execution behavior intact.)

### 4. Generate Image node → consume a LoRA
`fal_generate_image.py`: accept `lora_id` (resolve `weights_url` + `trigger_word`
from `trained_loras`) **or** a direct `lora_url`, plus `lora_scale` (default 1.0).
When set: switch the endpoint default to a LoRA-capable one (`fal-ai/flux-lora`),
inject `loras=[{"path": weights_url, "scale": lora_scale}]`, and prepend the
trigger word to the prompt if not already present. No LoRA set → behaves exactly
as today.

### 5. API + dashboards
- **`api/models.py`** — `GET` list / `GET ?id=` / `PATCH` (rename, edit trigger) /
  `DELETE`. Service-role reads registry; auth via existing session cookie.
- **`public/models.html`** (+ nav link from `index.html`) — **Brand Models**
  library: cards with status pill (`training` / `ready` / `failed`), trigger word,
  thumbnail, source execution link, and a copy-id / "use in workflow" affordance.
- **`workflow.html`** — Generate Image node gains a **Model** picker field
  (dropdown populated from `/api/models` ready rows) + a **LoRA scale** range;
  Train LoRA node gains a **Name** field.
- **Capsule** (`capsule.html`) — add a `lora_select` exposable control type so an
  operator page can pick a brand model as a one-run override.

## Phasing (each phase is DeepSeek-sized)

- **P1 — Registry backend.** Migration + `fal_train_lora` register + `poll_jobs`
  complete. _Milestone: train once → a `ready` row appears with weights_url._
- **P2 — Consume in Generate.** `fal_generate_image` LoRA support + `api/models.py`.
  _Milestone: generate an on-brand image by lora_id, headless._
- **P3 — Dashboards.** `models.html` + nav + node picker fields + Capsule control.
- **P4 — Polish.** Thumbnail capture (first render → `thumbnail_url`), failure
  surfacing, delete cascades, and the RLS hardening pass on legacy tables.

## Orchestration
Planner (Claude) writes each file's contract; `deepseek-coder` → `deepseek_call.py`
→ `deepseek/deepseek-v3.2` implements one file at a time; planner reviews, merges,
and verifies against fal's real response shape. Python 3.9-compatible where the
runtime demands it, though `api/_lib/nodes/*` already use 3.10+ unions on Vercel.

## Gates before touching live infra
- **Supabase migration** runs against the shared, in-use project
  (`bmmwvxgxmesmgnrncoaj`) — needs an explicit go; it's additive (new table only).
- **`FAL_KEY`** already present in `.env.local` / Vercel — training will bill fal.
- Verification is via **preview deploy**, not local (API needs Vercel runtime).
