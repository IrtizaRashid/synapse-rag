-- Lock down backend-owned tables and RPCs.
-- Run in Supabase SQL Editor after schema.sql, rag_vector.sql, and chatbots.sql.
--
-- The app backend uses the service-role key for these resources. Public clients
-- should never read or write them directly with the anon key.

alter table if exists public.auth_users enable row level security;
alter table if exists public.auth_otp_codes enable row level security;
alter table if exists public.auth_sessions enable row level security;
alter table if exists public.chatbots enable row level security;
alter table if exists public.rag_chunks enable row level security;

revoke all on table public.auth_users from anon, authenticated;
revoke all on table public.auth_otp_codes from anon, authenticated;
revoke all on table public.auth_sessions from anon, authenticated;
revoke all on table public.chatbots from anon, authenticated;
revoke all on table public.rag_chunks from anon, authenticated;

grant all on table public.auth_users to service_role;
grant all on table public.auth_otp_codes to service_role;
grant all on table public.auth_sessions to service_role;
grant all on table public.chatbots to service_role;
grant all on table public.rag_chunks to service_role;

drop policy if exists chatbots_select_own on public.chatbots;
drop policy if exists chatbots_insert on public.chatbots;
drop policy if exists chatbots_update_own on public.chatbots;
drop policy if exists chatbots_delete_own on public.chatbots;

revoke execute on function public.search_chunks(vector(768), int, text[], bigint) from anon, authenticated;
revoke execute on function public.list_rag_sources(bigint) from anon, authenticated;
revoke execute on function public.search_chunks(vector(768), int, text[], bigint) from public;
revoke execute on function public.list_rag_sources(bigint) from public;
revoke execute on function public.handle_new_auth_user() from public, anon, authenticated;

grant execute on function public.search_chunks(vector(768), int, text[], bigint) to service_role;
grant execute on function public.list_rag_sources(bigint) to service_role;

alter function public.search_chunks(vector(768), int, text[], bigint) set search_path = public;
alter function public.list_rag_sources(bigint) set search_path = public;
