-- =====================================================================
-- 0006 — Covering indexes for the composite foreign keys
-- The Performance Advisor flagged 8 foreign keys without a covering
-- index. Postgres does not index foreign keys automatically; without
-- these, deleting a lesson or a teacher account (cascade / set null)
-- scans whole tables, and the session_events RLS filter on teacher_id
-- has no index. Each composite index lists the FK columns in FK order.
-- Single-column partial indexes they replace are dropped. No data change.
-- =====================================================================

-- lessons.copied_from (copied_from_lesson_id, teacher_id)
drop index if exists public.lessons_copied_from_idx;
create index lessons_copied_from_fk_idx
  on public.lessons (copied_from_lesson_id, teacher_id);

-- activities.lesson (lesson_id, teacher_id)
create index activities_lesson_fk_idx
  on public.activities (lesson_id, teacher_id);

-- schedule_items.lesson (lesson_id, teacher_id)
drop index if exists public.schedule_items_lesson_idx;
create index schedule_items_lesson_fk_idx
  on public.schedule_items (lesson_id, teacher_id);

-- sessions: lesson, schedule item, current activity
drop index if exists public.sessions_lesson_idx;
drop index if exists public.sessions_schedule_item_idx;
drop index if exists public.sessions_current_activity_idx;
create index sessions_lesson_fk_idx
  on public.sessions (lesson_id, teacher_id);
create index sessions_schedule_item_fk_idx
  on public.sessions (schedule_item_id, teacher_id);
create index sessions_current_activity_fk_idx
  on public.sessions (current_activity_id, teacher_id);

-- session_events: (session_id, teacher_id) FK + time order in one index,
-- and teacher_id for the RLS filter and account deletion.
drop index if exists public.session_events_session_time_idx;
create index session_events_session_fk_time_idx
  on public.session_events (session_id, teacher_id, occurred_at);
create index session_events_teacher_idx
  on public.session_events (teacher_id);
