-- Flow Forge V2 foundation. Apply through the Supabase migration workflow.
-- This migration is additive and deliberately does not touch unrelated tables.

create table if not exists public.workflow_jobs (
  id uuid primary key default gen_random_uuid(),
  job_type text not null,
  execution_id uuid not null references public.executions(id) on delete cascade,
  batch_item_id uuid,
  payload_json jsonb not null default '{}'::jsonb,
  status text not null default 'queued' check (status in ('queued', 'running', 'success', 'failed', 'canceled')),
  available_at timestamptz not null default now(),
  lease_expires_at timestamptz,
  attempts integer not null default 0 check (attempts >= 0),
  max_attempts integer not null default 3 check (max_attempts between 1 and 3),
  idempotency_key text not null unique,
  last_error text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  completed_at timestamptz
);

alter table public.executions
  add column if not exists publication_id uuid,
  add column if not exists batch_run_id uuid,
  add column if not exists batch_item_id uuid,
  add column if not exists graph_snapshot jsonb,
  add column if not exists estimated_cost_usd numeric(12, 6) not null default 0,
  add column if not exists actual_cost_usd numeric(12, 6) not null default 0,
  add column if not exists cancel_requested_at timestamptz;

alter table public.execution_logs
  add column if not exists input_json jsonb,
  add column if not exists artifacts_json jsonb not null default '[]'::jsonb,
  add column if not exists usage_json jsonb not null default '{}'::jsonb,
  add column if not exists external_ref jsonb,
  add column if not exists attempt integer not null default 1;

alter table public.generated_assets
  add column if not exists mime_type text,
  add column if not exists size_bytes bigint,
  add column if not exists metadata_json jsonb not null default '{}'::jsonb,
  add column if not exists expires_at timestamptz,
  add column if not exists is_persistent boolean not null default false;

create table if not exists public.provider_models (
  id uuid primary key default gen_random_uuid(),
  provider text not null check (provider in ('openrouter', 'fal')),
  model_slug text not null,
  modality text not null,
  capabilities_json jsonb not null default '{}'::jsonb,
  raw_json jsonb not null default '{}'::jsonb,
  fetched_at timestamptz not null default now(),
  expires_at timestamptz not null,
  unique (provider, model_slug)
);

create table if not exists public.brand_kits (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  active_version_id uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create table if not exists public.brand_kit_versions (
  id uuid primary key default gen_random_uuid(),
  brand_kit_id uuid not null references public.brand_kits(id) on delete cascade,
  version_number integer not null,
  profile_json jsonb not null default '{}'::jsonb,
  analysis_model text,
  prompt_version text,
  source_asset_ids jsonb not null default '[]'::jsonb,
  cost_usd numeric(12, 6) not null default 0,
  created_at timestamptz not null default now(),
  unique (brand_kit_id, version_number)
);
create table if not exists public.brand_assets (
  id uuid primary key default gen_random_uuid(),
  brand_kit_id uuid not null references public.brand_kits(id) on delete cascade,
  storage_path text not null unique,
  mime_type text not null check (mime_type in ('image/png', 'image/jpeg', 'image/webp')),
  size_bytes bigint not null check (size_bytes > 0 and size_bytes <= 10485760),
  created_at timestamptz not null default now()
);

create table if not exists public.batch_runs (
  id uuid primary key default gen_random_uuid(),
  workflow_id uuid not null references public.workflows(id) on delete cascade,
  graph_snapshot jsonb not null,
  input_storage_path text not null,
  status text not null default 'queued' check (status in ('queued', 'running', 'success', 'partial_success', 'failed', 'cancel_requested', 'canceled')),
  concurrency integer not null default 3 check (concurrency between 1 and 3),
  created_at timestamptz not null default now(),
  finished_at timestamptz
);
create table if not exists public.batch_items (
  id uuid primary key default gen_random_uuid(),
  batch_run_id uuid not null references public.batch_runs(id) on delete cascade,
  row_index integer not null,
  raw_input jsonb not null,
  normalized_input jsonb not null,
  execution_id uuid references public.executions(id),
  status text not null default 'queued' check (status in ('queued', 'running', 'success', 'failed', 'canceled')),
  actual_cost_usd numeric(12, 6) not null default 0,
  output_json jsonb,
  error text,
  created_at timestamptz not null default now(),
  finished_at timestamptz,
  unique (batch_run_id, row_index)
);

create table if not exists public.publications (
  id uuid primary key default gen_random_uuid(),
  workflow_id uuid not null references public.workflows(id) on delete cascade,
  token_hash text not null unique,
  name text not null,
  description text,
  status text not null default 'active' check (status in ('active', 'revoked')),
  allowed_origins jsonb not null default '["self"]'::jsonb,
  runs_per_hour integer check (runs_per_hour is null or runs_per_hour >= 1) default 3,
  daily_cost_limit_usd numeric(12, 6) check (daily_cost_limit_usd is null or daily_cost_limit_usd >= 0) default 3,
  settings_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  revoked_at timestamptz
);
create table if not exists public.publication_runs (
  id uuid primary key default gen_random_uuid(),
  publication_id uuid not null references public.publications(id) on delete cascade,
  execution_id uuid references public.executions(id),
  estimated_cost_usd numeric(12, 6) not null default 0,
  actual_cost_usd numeric(12, 6) not null default 0,
  accepted_at timestamptz not null default now(),
  created_at timestamptz not null default now()
);

alter table public.workflow_jobs enable row level security;
alter table public.provider_models enable row level security;
alter table public.brand_kits enable row level security;
alter table public.brand_kit_versions enable row level security;
alter table public.brand_assets enable row level security;
alter table public.batch_runs enable row level security;
alter table public.batch_items enable row level security;
alter table public.publications enable row level security;
alter table public.publication_runs enable row level security;

create index if not exists workflow_jobs_claim_idx on public.workflow_jobs (status, available_at) where status = 'queued';
create index if not exists workflow_jobs_execution_idx on public.workflow_jobs (execution_id);
create index if not exists executions_publication_idx on public.executions (publication_id);
create index if not exists executions_batch_idx on public.executions (batch_run_id, batch_item_id);
create index if not exists generated_assets_expiration_idx on public.generated_assets (expires_at) where not is_persistent;
create index if not exists provider_models_expiration_idx on public.provider_models (provider, modality, expires_at);
create index if not exists batch_items_run_status_idx on public.batch_items (batch_run_id, status, row_index);
create index if not exists publications_workflow_idx on public.publications (workflow_id, status);
create index if not exists publication_runs_limit_idx on public.publication_runs (publication_id, accepted_at);

create or replace function public.claim_flowforge_jobs(p_limit integer default 3)
returns setof public.workflow_jobs
language plpgsql
security invoker
set search_path = public
as $$
begin
  if p_limit is null or p_limit < 1 or p_limit > 3 then
    raise exception 'p_limit must be between 1 and 3';
  end if;

  return query
  with claimable as (
    select id
    from public.workflow_jobs
    where attempts < max_attempts
      and (
        (status = 'queued' and available_at <= now())
        or (status = 'running' and lease_expires_at < now())
      )
    order by available_at, created_at
    limit p_limit
    for update skip locked
  )
  update public.workflow_jobs jobs
  set status = 'running', attempts = jobs.attempts + 1,
      lease_expires_at = now() + interval '5 minutes', updated_at = now()
  from claimable
  where jobs.id = claimable.id
  returning jobs.*;
end;
$$;

revoke all on function public.claim_flowforge_jobs(integer) from public, anon, authenticated;
grant execute on function public.claim_flowforge_jobs(integer) to service_role;

create or replace function public.accept_flowforge_publication_run(p_publication_id uuid, p_estimated_cost numeric)
returns boolean language plpgsql security invoker set search_path = public as $$
declare p public.publications; hourly_count integer; daily_spend numeric;
begin
  select * into p from public.publications where id = p_publication_id and status = 'active' for update;
  if not found then return false; end if;
  select count(*) into hourly_count from public.publication_runs where publication_id = p.id and accepted_at > now() - interval '1 hour';
  select coalesce(sum(estimated_cost_usd), 0) into daily_spend from public.publication_runs where publication_id = p.id and accepted_at >= date_trunc('day', now());
  if (p.runs_per_hour is not null and hourly_count >= p.runs_per_hour) or (p.daily_cost_limit_usd is not null and daily_spend + p_estimated_cost > p.daily_cost_limit_usd) then return false; end if;
  insert into public.publication_runs(publication_id, estimated_cost_usd) values (p.id, p_estimated_cost);
  return true;
end; $$;
revoke all on function public.accept_flowforge_publication_run(uuid, numeric) from public, anon, authenticated;
grant execute on function public.accept_flowforge_publication_run(uuid, numeric) to service_role;

insert into storage.buckets (id, name, public)
values ('flowforge-assets', 'flowforge-assets', false),
       ('flowforge-brand-assets', 'flowforge-brand-assets', false),
       ('flowforge-batch-inputs', 'flowforge-batch-inputs', false)
on conflict (id) do update set public = false;
