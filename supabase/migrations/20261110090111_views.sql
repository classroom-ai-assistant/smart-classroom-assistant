-- =====================================================================
-- 0005 — Views
-- security_invoker = true so RLS on lessons/activities applies to the
-- caller; without it the view would run as its owner and bypass RLS.
-- =====================================================================

create view public.lessons_with_status
with (security_invoker = true)
as
select
  l.id,
  l.teacher_id,
  l.title,
  l.topic,
  l.age_group,
  l.copied_from_lesson_id,
  l.created_at,
  l.updated_at,
  case when public.lesson_is_ready(l.id) then 'ready' else 'draft' end as status
from public.lessons l;

comment on view public.lessons_with_status is
  'Lessons with derived draft/ready status (FR-015, BRL-12). Status is never stored.';

grant select on public.lessons_with_status to authenticated;
