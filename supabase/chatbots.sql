-- Chatbots: named assistants bound to a set of ingested file sources.
create table if not exists public.chatbots (
    id uuid primary key default gen_random_uuid(),
    name text not null,
    description text not null default '',
    sources jsonb not null default '[]',
    owner_id bigint not null default 0,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

alter table public.chatbots enable row level security;

alter table public.chatbots replica identity full;

revoke all on table public.chatbots from anon, authenticated;
grant all on table public.chatbots to service_role;
