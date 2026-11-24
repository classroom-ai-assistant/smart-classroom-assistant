-- =====================================================================
-- 0007 — Teacher files (assets) and "مكتبتي" (saved pages)
-- Visual lesson editor, step 1 (approved 2026-11-24).
-- No child identity: teachers are told not to upload photos of children,
-- and nothing here links a file to a child.
-- =====================================================================

create type public.asset_kind as enum ('image', 'pdf', 'video');
create type public.asset_source as enum ('upload', 'library', 'ai');

-- ---------------------------------------------------------------------
-- assets — metadata for files the teacher stored in the private
-- `teacher-assets` bucket (0008). The object path always starts with the
-- owner's id, so storage RLS and this table agree on ownership.
-- ---------------------------------------------------------------------
create table public.assets (
  id            uuid primary key default gen_random_uuid(),
  teacher_id    uuid not null references public.teachers (id) on delete cascade,
  kind          public.asset_kind not null,
  source        public.asset_source not null default 'upload',
  storage_path  text not null unique
                check (split_part(storage_path, '/', 1) = teacher_id::text
                       and char_length(storage_path) <= 300),
  file_name     text not null check (char_length(btrim(file_name)) between 1 and 200),
  mime_type     text not null,
  size_bytes    bigint not null check (size_bytes > 0),
  width         integer check (width > 0),
  height        integer check (height > 0),
  attribution   text check (char_length(attribution) <= 300),  -- credit line for library images
  created_at    timestamptz not null default now(),
  constraint assets_id_teacher_key unique (id, teacher_id),
  -- Type and size limits per kind (Supabase free plan: 50 MB per file).
  constraint assets_kind_mime_size check (
       (kind = 'image' and mime_type in ('image/png', 'image/jpeg', 'image/webp', 'image/gif')
                       and size_bytes <= 10485760)
    or (kind = 'pdf'   and mime_type = 'application/pdf' and size_bytes <= 20971520)
    or (kind = 'video' and mime_type in ('video/mp4', 'video/webm') and size_bytes <= 52428800)
  )
);
create index assets_teacher_created_idx on public.assets (teacher_id, created_at desc);

-- ---------------------------------------------------------------------
-- saved_pages — a page the teacher keeps to reuse in other lessons.
-- `page` holds the page content and its layouts (validated by the API);
-- size-capped so a single row cannot grow without bound.
-- ---------------------------------------------------------------------
create table public.saved_pages (
  id             uuid primary key default gen_random_uuid(),
  teacher_id     uuid not null references public.teachers (id) on delete cascade,
  title          text not null check (char_length(btrim(title)) between 1 and 150),
  activity_type  public.activity_type not null,  -- which kind of section it fits
  page           jsonb not null
                 check (jsonb_typeof(page) = 'object' and pg_column_size(page) <= 262144),
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);
create index saved_pages_teacher_updated_idx on public.saved_pages (teacher_id, updated_at desc);

create trigger saved_pages_set_updated_at
  before update on public.saved_pages
  for each row execute function public.set_updated_at();

-- ---------------------------------------------------------------------
-- Security: own rows only, same pattern as lessons (0004).
-- Assets are immutable after upload (no UPDATE grant).
-- ---------------------------------------------------------------------
alter table public.assets      enable row level security;
alter table public.saved_pages enable row level security;

grant select, insert, delete         on public.assets      to authenticated;
grant select, insert, update, delete on public.saved_pages to authenticated;

create policy assets_select_own on public.assets
  for select to authenticated using (teacher_id = (select auth.uid()));
create policy assets_insert_own on public.assets
  for insert to authenticated with check (teacher_id = (select auth.uid()));
create policy assets_delete_own on public.assets
  for delete to authenticated using (teacher_id = (select auth.uid()));

create policy saved_pages_select_own on public.saved_pages
  for select to authenticated using (teacher_id = (select auth.uid()));
create policy saved_pages_insert_own on public.saved_pages
  for insert to authenticated with check (teacher_id = (select auth.uid()));
create policy saved_pages_update_own on public.saved_pages
  for update to authenticated
  using (teacher_id = (select auth.uid()))
  with check (teacher_id = (select auth.uid()));
create policy saved_pages_delete_own on public.saved_pages
  for delete to authenticated using (teacher_id = (select auth.uid()));
