-- =====================================================================
-- 0003 — Functions and triggers
-- All functions pin search_path to '' and use schema-qualified names.
-- =====================================================================

-- ---------------------------------------------------------------------
-- updated_at maintenance
-- ---------------------------------------------------------------------
create function public.set_updated_at()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

create trigger teachers_set_updated_at
  before update on public.teachers
  for each row execute function public.set_updated_at();
create trigger teacher_settings_set_updated_at
  before update on public.teacher_settings
  for each row execute function public.set_updated_at();
create trigger lessons_set_updated_at
  before update on public.lessons
  for each row execute function public.set_updated_at();
create trigger activities_set_updated_at
  before update on public.activities
  for each row execute function public.set_updated_at();
create trigger schedule_items_set_updated_at
  before update on public.schedule_items
  for each row execute function public.set_updated_at();
create trigger sessions_set_updated_at
  before update on public.sessions
  for each row execute function public.set_updated_at();

-- ---------------------------------------------------------------------
-- Sign-up: create the teacher profile and default settings (D-02,
-- self-registration). SECURITY DEFINER because it runs on auth.users;
-- execute is revoked from client roles in 0004.
-- ---------------------------------------------------------------------
create function public.handle_new_teacher()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_name text;
begin
  v_name := left(
    coalesce(
      nullif(btrim(new.raw_user_meta_data ->> 'display_name'), ''),
      nullif(split_part(coalesce(new.email, ''), '@', 1), ''),
      'معلمة'
    ),
    100
  );

  insert into public.teachers (id, display_name) values (new.id, v_name);
  insert into public.teacher_settings (teacher_id) values (new.id);
  return new;
end;
$$;

create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_teacher();

-- ---------------------------------------------------------------------
-- Lesson readiness — the single source of truth for draft/ready
-- (FR-015, BRL-12): at least one approved activity, and every activity
-- placed in the lesson is approved. Runs as the caller, so RLS applies.
-- ---------------------------------------------------------------------
create function public.lesson_is_ready(p_lesson_id uuid)
returns boolean
language sql
stable
set search_path = ''
as $$
  select
    exists (
      select 1 from public.activities a
      where a.lesson_id = p_lesson_id and a.approval_status = 'approved'
    )
    and not exists (
      select 1 from public.activities a
      where a.lesson_id = p_lesson_id
        and a.order_index is not null
        and a.approval_status <> 'approved'
    );
$$;

-- ---------------------------------------------------------------------
-- A session can only start from a ready lesson (FR-065, BRL-01, ERR-10).
-- Defence in depth: the API checks first; this guards against a bug.
-- ---------------------------------------------------------------------
create function public.ensure_session_lesson_ready()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if new.lesson_id is not null and not public.lesson_is_ready(new.lesson_id) then
    raise exception 'lesson % is not ready: it has no approved activities or has unapproved ones', new.lesson_id
      using errcode = 'check_violation', hint = 'ERR-10';
  end if;
  return new;
end;
$$;

create trigger sessions_require_ready_lesson
  before insert on public.sessions
  for each row execute function public.ensure_session_lesson_ready();
