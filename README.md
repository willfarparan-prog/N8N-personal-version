# FlowForge

A self-hosted, n8n-style visual workflow builder — no subscription. Runs on Vercel (Python serverless functions + static frontend, no build step) with Supabase as the database. Built for general automation (webhooks, schedules, HTTP calls) with first-class nodes for fal.ai image generation and LoRA training.

## Stack

- **Frontend:** plain HTML/CSS/JS in `public/`, no build step. Canvas editor uses [LiteGraph.js](https://github.com/jagenjo/litegraph.js) via CDN (same library ComfyUI's node canvas is built on).
- **Backend:** Vercel Python serverless functions in `api/`.
- **Database:** Supabase Postgres (`workflows`, `executions`, `execution_logs`, `generated_assets` tables) + Supabase Storage (`generated-assets` bucket) for generated images/model files.
- **Scheduling:** Supabase `pg_cron` + `pg_net` call the Vercel cron endpoints every minute (Vercel Hobby's built-in Cron Jobs are daily-only, which is too coarse for polling async training jobs or firing schedule-triggers).
- **Auth:** single shared password (`APP_PASSWORD` env var) + signed cookie. No multi-user system — this is a personal tool.
- **AI providers:** fal.ai for image generation / LoRA training; OpenRouter (DeepSeek by default) for an optional LLM-prompt node.

## Node types (v1)

Triggers: Manual Run, Webhook, Schedule.
Actions: HTTP Request, Supabase Insert/Query, fal.ai Generate Image, fal.ai Train LoRA (async, polled), LLM Prompt (OpenRouter), Delay, Condition, Set/Transform.

## Environment variables (set in Vercel project settings)

- `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` — service-role key, server-side only, bypasses RLS.
- `APP_PASSWORD` — the shared login password.
- `COOKIE_SECRET` — random string used to sign the session cookie.
- `FAL_KEY` — fal.ai API key.
- `OPENROUTER_API_KEY` — OpenRouter API key (used by the LLM Prompt node).
- `CRON_SECRET` — shared secret checked by `/api/cron/*` routes, passed by Supabase pg_net's scheduled HTTP calls.

## Local development

No Node is required or used anywhere in this project. To preview the static frontend only:

```bash
cd public && python3 -m http.server 8000
```

API routes can't be run locally without the Vercel Python runtime; iterate via preview deployments instead.
