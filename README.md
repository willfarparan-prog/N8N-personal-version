# FlowForge

A self-hosted, n8n-style visual workflow builder — no subscription. Runs on Vercel (Python serverless functions + static frontend, no build step) with Supabase as the database. Built for general automation (webhooks, schedules, HTTP calls) with first-class nodes for fal.ai image generation and LoRA training.

## Stack

- **Frontend:** plain HTML/CSS/JS in `public/`, no build step. Canvas editor uses [LiteGraph.js](https://github.com/jagenjo/litegraph.js) via CDN (same library ComfyUI's node canvas is built on).
- **Backend:** Vercel Python serverless functions in `api/`.
- **Database:** Supabase Postgres (`workflows`, `executions`, `execution_logs`, `generated_assets`, `oauth_connections` tables) + Supabase Storage (`generated-assets` bucket) for generated images/model files.
- **Scheduling:** Supabase `pg_cron` + `pg_net` call the Vercel cron endpoints every minute (Vercel Hobby's built-in Cron Jobs are daily-only, which is too coarse for polling async training jobs or firing schedule-triggers).
- **Auth:** single shared password (`APP_PASSWORD` env var) + signed cookie. No multi-user system — this is a personal tool.
- **AI providers:** fal.ai for image generation / LoRA training; OpenRouter (DeepSeek by default) for an optional LLM-prompt node.

## Node types (v1)

Triggers: Manual Run, Webhook, Schedule.
Actions: HTTP Request, Supabase Insert/Query, fal.ai Generate Image, fal.ai Train LoRA (async, polled), LLM Prompt (OpenRouter), Delay, Condition, Set/Transform, Google Drive Upload, Search Drive, Create Drive Folder.

## Creative graph studio and Capsules

The workflow editor is a creative graph studio: the node library includes a starter
image-concept recipe, related nodes can be framed into saved visual stages, and each
node setting can be exposed deliberately. The **Capsule** inspector turns those
exposed controls into a focused operator page at `/capsule.html?id=<workflow-id>`.

Running a Capsule applies its fields as **one-run overrides**. It never changes the
saved graph, and the API accepts overrides only for controls that were exposed by the
designer in that graph's Capsule configuration.

## Environment variables (set in Vercel project settings)

- `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` — service-role key, server-side only, bypasses RLS.
- `APP_PASSWORD` — the shared login password.
- `COOKIE_SECRET` — random string used to sign the session cookie.
- `FAL_KEY` — fal.ai API key.
- `OPENROUTER_API_KEY` — OpenRouter API key (used by the LLM Prompt node).
- `CRON_SECRET` — shared secret checked by `/api/cron/*` routes, passed by Supabase pg_net's scheduled HTTP calls.
- `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` — credentials for a **Web application** OAuth client in Google Cloud. Keep the secret server-side; never put either in `public/` files.
- `GOOGLE_OAUTH_REDIRECT_URI` — exact callback URL registered in Google Cloud: `https://flowforge-pi.vercel.app/api/integrations/google/callback`.
- `GOOGLE_TOKEN_ENCRYPTION_KEY` — a Fernet key used only by the server to encrypt Google refresh tokens before saving them in Supabase.

## Google Drive connection setup

1. In your Google Cloud project, enable the **Google Drive API** and create an OAuth 2.0 client of type **Web application**.
2. Register `https://flowforge-pi.vercel.app/api/integrations/google/callback` as an authorized redirect URI. Add a Vercel preview callback only when you specifically need preview testing.
3. Add the four `GOOGLE_*` variables above in Vercel, redeploy, then open **Integrations** in FlowForge and choose **Connect Google Drive**.

FlowForge requests the per-file `drive.file` scope. That permits files created by
FlowForge or explicitly shared/opened with it, rather than unrestricted
access to every file in your Drive. Refresh tokens are encrypted in the private
`oauth_connections` table; browser roles have no access to that table.

## Local development

No Node is required or used anywhere in this project. To preview the static frontend only:

```bash
cd public && python3 -m http.server 8000
```

API routes can't be run locally without the Vercel Python runtime; iterate via preview deployments instead.

## Flow Forge Studio V2 rollout

Apply `supabase/migrations/202608060001_flowforge_v2_foundation.sql` through the
project's additive Supabase migration workflow before enabling V2 APIs. It creates
the private buckets, queue RPC, publication ledger, and V2 tables used by the
server routes.

Set these server-only environment variables before a preview deployment:

- `OPENROUTER_WEBHOOK_SECRET`
- `DESTINATION_WEBHOOK_SIGNING_SECRET`
- `BRAND_ANALYSIS_MODEL`
- `FLOWFORGE_PUBLIC_BASE_URL`
- `FLOWFORGE_STUDIO_V2`, `FLOWFORGE_PROVIDER_NODES_V2`, `FLOWFORGE_DESTINATIONS_V2`
- `FLOWFORGE_PUBLISH_ENABLED`, `FLOWFORGE_BATCH_ENABLED`

Before production, verify: a 50-row batch at concurrency three; fal signed
callbacks and polling fallback; public rate/budget limits; a revoked and rotated
publication token; seven-day cleanup preserving persistent assets; and both themes
at 375, 768, 1024, and 1440px.
