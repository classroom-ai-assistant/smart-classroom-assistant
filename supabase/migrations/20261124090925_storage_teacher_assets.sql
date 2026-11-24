-- =====================================================================
-- 0008 — Private storage bucket for teacher files
-- The browser uploads directly with the teacher's own session (approved
-- exception to decision أ, files only); no service key is involved.
-- Path convention: <teacher_id>/<uuid>.<ext>
-- =====================================================================

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
  'teacher-assets',
  'teacher-assets',
  false,  -- private: files are read through short-lived signed URLs
  52428800,
  array['image/png', 'image/jpeg', 'image/webp', 'image/gif', 'application/pdf', 'video/mp4', 'video/webm']
)
on conflict (id) do nothing;

-- A teacher can only read, add, replace or delete objects in her own folder.
create policy teacher_assets_select_own on storage.objects
  for select to authenticated
  using (bucket_id = 'teacher-assets' and (storage.foldername(name))[1] = (select auth.uid())::text);

create policy teacher_assets_insert_own on storage.objects
  for insert to authenticated
  with check (bucket_id = 'teacher-assets' and (storage.foldername(name))[1] = (select auth.uid())::text);

create policy teacher_assets_update_own on storage.objects
  for update to authenticated
  using (bucket_id = 'teacher-assets' and (storage.foldername(name))[1] = (select auth.uid())::text)
  with check (bucket_id = 'teacher-assets' and (storage.foldername(name))[1] = (select auth.uid())::text);

create policy teacher_assets_delete_own on storage.objects
  for delete to authenticated
  using (bucket_id = 'teacher-assets' and (storage.foldername(name))[1] = (select auth.uid())::text);
