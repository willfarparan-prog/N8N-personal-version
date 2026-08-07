-- registry of trained LoRA models so they can be reused by name across workflow runs, closing the loop opened by the existing async `action/fal_train_lora` node
create table if not exists public.trained_loras (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  trigger_word text not null default '',
  base_model text not null default 'flux',
  weights_url text,
  status text not null default 'training' check (status in ('training', 'ready', 'failed')),
  thumbnail_url text,
  source_execution_id uuid references public.executions(id) on delete set null,
  training_input jsonb not null default '{}'::jsonb,
  error text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.trained_loras enable row level security;
