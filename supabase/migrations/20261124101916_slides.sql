-- =====================================================================
-- 0009 — Slides: a lesson is a deck the teacher builds like PowerPoint
-- (approved by Lama 2026-11-24). Each slide has its visual layout, an
-- optional robot narration (like speaker notes) and an optional question
-- for the children. Older activity-based lessons stay as they are.
-- =====================================================================

create table public.slides (
  id           uuid primary key default gen_random_uuid(),
  lesson_id    uuid not null,
  teacher_id   uuid not null references public.teachers (id) on delete cascade,
  order_index  integer not null check (order_index >= 0),
  layout       jsonb not null default '{"background": "#FAEFE9", "elements": []}'::jsonb
               check (jsonb_typeof(layout) = 'object' and pg_column_size(layout) <= 262144),
  speech       text check (char_length(speech) <= 2000),          -- what the robot says
  question     jsonb check (question is null
                            or (jsonb_typeof(question) = 'object' and pg_column_size(question) <= 16384)),
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now(),
  constraint slides_id_teacher_key unique (id, teacher_id),
  constraint slides_lesson_fkey
    foreign key (lesson_id, teacher_id)
    references public.lessons (id, teacher_id)
    on delete cascade,
  -- Deferrable so insert-in-the-middle and reorder can shift positions.
  constraint slides_lesson_order_key
    unique (lesson_id, order_index) deferrable initially immediate
);

create index slides_lesson_teacher_idx on public.slides (lesson_id, teacher_id);
create index slides_teacher_idx on public.slides (teacher_id);

create trigger slides_set_updated_at
  before update on public.slides
  for each row execute function public.set_updated_at();

alter table public.slides enable row level security;
grant select, insert, update, delete on public.slides to authenticated;

create policy slides_select_own on public.slides
  for select to authenticated using (teacher_id = (select auth.uid()));
create policy slides_insert_own on public.slides
  for insert to authenticated with check (teacher_id = (select auth.uid()));
create policy slides_update_own on public.slides
  for update to authenticated
  using (teacher_id = (select auth.uid()))
  with check (teacher_id = (select auth.uid()));
create policy slides_delete_own on public.slides
  for delete to authenticated using (teacher_id = (select auth.uid()));

-- A lesson is ready when it has at least one slide, or (older lessons)
-- when its placed activities are all approved. Status stays derived (BRL-12).
create or replace function public.lesson_is_ready(p_lesson_id uuid)
returns boolean
language sql
stable
set search_path = ''
as $$
  select
    exists (select 1 from public.slides s where s.lesson_id = p_lesson_id)
    or (
      exists (
        select 1 from public.activities a
        where a.lesson_id = p_lesson_id and a.approval_status = 'approved'
      )
      and not exists (
        select 1 from public.activities a
        where a.lesson_id = p_lesson_id
          and a.order_index is not null
          and a.approval_status <> 'approved'
      )
    );
$$;
