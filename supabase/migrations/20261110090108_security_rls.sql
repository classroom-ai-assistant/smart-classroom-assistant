-- =====================================================================
-- 0004 — Row Level Security, grants and least privilege
-- Every policy is "own rows only" via (select auth.uid()). The anon role
-- gets nothing. FastAPI is expected to run requests as `authenticated`
-- with the teacher's verified JWT claims so these policies apply
-- (Phase 1, decision 4).
-- =====================================================================

-- ---------------------------------------------------------------------
-- Stop Supabase's default auto-grants to anon/authenticated on future
-- objects in public. Every grant from here on is explicit.
-- ---------------------------------------------------------------------
alter default privileges for role postgres in schema public
  revoke all on tables from anon, authenticated;
alter default privileges for role postgres in schema public
  revoke all on sequences from anon, authenticated;
alter default privileges for role postgres in schema public
  revoke execute on functions from anon, authenticated, public;

-- Remove whatever the defaults already granted on the objects from 0002/0003.
revoke all on all tables    in schema public from anon, authenticated;
revoke all on all sequences in schema public from anon, authenticated;
revoke execute on all functions in schema public from anon, authenticated, public;

-- ---------------------------------------------------------------------
-- Enable RLS on every table
-- ---------------------------------------------------------------------
alter table public.teachers         enable row level security;
alter table public.teacher_settings enable row level security;
alter table public.lessons          enable row level security;
alter table public.activities       enable row level security;
alter table public.schedule_items   enable row level security;
alter table public.sessions         enable row level security;
alter table public.session_events   enable row level security;

-- ---------------------------------------------------------------------
-- Grants for authenticated (column-level where only some fields change)
-- ---------------------------------------------------------------------
grant select on public.teachers to authenticated;
grant update (display_name) on public.teachers to authenticated;

grant select on public.teacher_settings to authenticated;
grant update (
  voice_volume, speech_rate, answer_wait_seconds, no_answer_action,
  kids_mode_pin_hash, default_alert_lead_minutes, privacy_notice_accepted_at
) on public.teacher_settings to authenticated;

grant select, insert, update, delete on public.lessons        to authenticated;
grant select, insert, update, delete on public.activities     to authenticated;
grant select, insert, update, delete on public.schedule_items to authenticated;
grant select, insert, update         on public.sessions       to authenticated;
grant select, insert                 on public.session_events to authenticated;

grant execute on function public.lesson_is_ready(uuid) to authenticated;

-- ---------------------------------------------------------------------
-- Policies
-- ---------------------------------------------------------------------
-- teachers: read and rename own profile; rows are created by the
-- sign-up trigger and removed only by deleting the auth user.
create policy teachers_select_own on public.teachers
  for select to authenticated
  using (id = (select auth.uid()));
create policy teachers_update_own on public.teachers
  for update to authenticated
  using (id = (select auth.uid()))
  with check (id = (select auth.uid()));

-- teacher_settings
create policy teacher_settings_select_own on public.teacher_settings
  for select to authenticated
  using (teacher_id = (select auth.uid()));
create policy teacher_settings_update_own on public.teacher_settings
  for update to authenticated
  using (teacher_id = (select auth.uid()))
  with check (teacher_id = (select auth.uid()));

-- lessons, activities, schedule_items: full CRUD on own rows
create policy lessons_select_own on public.lessons
  for select to authenticated using (teacher_id = (select auth.uid()));
create policy lessons_insert_own on public.lessons
  for insert to authenticated with check (teacher_id = (select auth.uid()));
create policy lessons_update_own on public.lessons
  for update to authenticated
  using (teacher_id = (select auth.uid()))
  with check (teacher_id = (select auth.uid()));
create policy lessons_delete_own on public.lessons
  for delete to authenticated using (teacher_id = (select auth.uid()));

create policy activities_select_own on public.activities
  for select to authenticated using (teacher_id = (select auth.uid()));
create policy activities_insert_own on public.activities
  for insert to authenticated with check (teacher_id = (select auth.uid()));
create policy activities_update_own on public.activities
  for update to authenticated
  using (teacher_id = (select auth.uid()))
  with check (teacher_id = (select auth.uid()));
create policy activities_delete_own on public.activities
  for delete to authenticated using (teacher_id = (select auth.uid()));

create policy schedule_items_select_own on public.schedule_items
  for select to authenticated using (teacher_id = (select auth.uid()));
create policy schedule_items_insert_own on public.schedule_items
  for insert to authenticated with check (teacher_id = (select auth.uid()));
create policy schedule_items_update_own on public.schedule_items
  for update to authenticated
  using (teacher_id = (select auth.uid()))
  with check (teacher_id = (select auth.uid()));
create policy schedule_items_delete_own on public.schedule_items
  for delete to authenticated using (teacher_id = (select auth.uid()));

-- sessions: no delete from clients (history removed with the account)
create policy sessions_select_own on public.sessions
  for select to authenticated using (teacher_id = (select auth.uid()));
create policy sessions_insert_own on public.sessions
  for insert to authenticated with check (teacher_id = (select auth.uid()));
create policy sessions_update_own on public.sessions
  for update to authenticated
  using (teacher_id = (select auth.uid()))
  with check (teacher_id = (select auth.uid()));

-- session_events: append-only from clients
create policy session_events_select_own on public.session_events
  for select to authenticated using (teacher_id = (select auth.uid()));
create policy session_events_insert_own on public.session_events
  for insert to authenticated with check (teacher_id = (select auth.uid()));
