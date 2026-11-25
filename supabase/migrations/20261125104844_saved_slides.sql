-- =====================================================================
-- 0010 — "مكتبتي" for slides: a slide the teacher keeps to reuse in
-- other lessons (lesson editor step 2). Same idea as saved_pages, which
-- stays for older activity-based lessons.
-- =====================================================================

create table public.saved_slides (
  id          uuid primary key default gen_random_uuid(),
  teacher_id  uuid not null references public.teachers (id) on delete cascade,
  title       text not null check (char_length(btrim(title)) between 1 and 150),
  layout      jsonb not null
              check (jsonb_typeof(layout) = 'object' and pg_column_size(layout) <= 262144),
  speech      text check (char_length(speech) <= 2000),
  question    jsonb check (question is null
                           or (jsonb_typeof(question) = 'object' and pg_column_size(question) <= 16384)),
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);
create index saved_slides_teacher_updated_idx on public.saved_slides (teacher_id, updated_at desc);

create trigger saved_slides_set_updated_at
  before update on public.saved_slides
  for each row execute function public.set_updated_at();

alter table public.saved_slides enable row level security;
grant select, insert, update, delete on public.saved_slides to authenticated;

create policy saved_slides_select_own on public.saved_slides
  for select to authenticated using (teacher_id = (select auth.uid()));
create policy saved_slides_insert_own on public.saved_slides
  for insert to authenticated with check (teacher_id = (select auth.uid()));
create policy saved_slides_update_own on public.saved_slides
  for update to authenticated
  using (teacher_id = (select auth.uid()))
  with check (teacher_id = (select auth.uid()));
create policy saved_slides_delete_own on public.saved_slides
  for delete to authenticated using (teacher_id = (select auth.uid()));
