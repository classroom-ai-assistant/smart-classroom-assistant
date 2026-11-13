-- =====================================================================
-- Phase 1 schema checks — run against a dev database only.
--
-- Everything happens inside one DO block that ends by RAISING the
-- summary as an exception, so the whole run is rolled back: no test
-- user, lesson or event survives. The "error" you see is the report.
--
-- Test data is fictional (@example.com). No real teacher or child data.
-- =====================================================================
do $test$
declare
  a  uuid := gen_random_uuid();   -- teacher A
  b  uuid := gen_random_uuid();   -- teacher B
  la uuid; la2 uuid; lb uuid; act uuid; sched uuid; sa uuid;
  n  int;
  st text;
  total  int := 0;
  passed int := 0;
  fails  text[] := '{}';
begin
  -- ------------------------------------------------------------------
  -- Setup as owner: two auth users -> sign-up trigger fires
  -- ------------------------------------------------------------------
  insert into auth.users (instance_id, id, aud, role, email, encrypted_password,
                          raw_app_meta_data, raw_user_meta_data, created_at, updated_at)
  values
    ('00000000-0000-0000-0000-000000000000', a, 'authenticated', 'authenticated',
     'test-a@example.com', '', '{}', '{"display_name": "تجريبية أ"}', now(), now()),
    ('00000000-0000-0000-0000-000000000000', b, 'authenticated', 'authenticated',
     'test-b@example.com', '', '{}', '{}', now(), now());

  -- T01 sign-up creates profile + settings, with display_name fallback
  total := total + 1;
  select count(*) into n
  from public.teachers t join public.teacher_settings s on s.teacher_id = t.id
  where t.id in (a, b);
  if n = 2
     and (select display_name from public.teachers where id = a) = 'تجريبية أ'
     and (select display_name from public.teachers where id = b) = 'test-b' then
    passed := passed + 1;
  else
    fails := fails || 'T01 sign-up trigger';
  end if;

  insert into public.lessons (teacher_id, title, topic, age_group)
    values (a, 'الألوان', 'الألوان الأساسية', 'age_4_5') returning id into la;
  insert into public.lessons (teacher_id, title, topic, age_group)
    values (a, 'الحيوانات', 'حيوانات المزرعة', 'age_3_4') returning id into la2;
  insert into public.lessons (teacher_id, title, topic, age_group)
    values (b, 'الأرقام', 'العد إلى عشرة', 'age_5_6') returning id into lb;
  insert into public.activities (lesson_id, teacher_id, type, title, content,
                                 approval_status, origin, approved_at, order_index)
    values (la, a, 'qa_dialogue', 'أسئلة الألوان', '{"questions": []}',
            'approved', 'manual', now(), 0) returning id into act;
  insert into public.schedule_items (teacher_id, lesson_id, title, date, start_time, end_time)
    values (a, la, 'حلقة الصباح', '2026-11-11', '08:00', '08:30') returning id into sched;

  -- ------------------------------------------------------------------
  -- Act as teacher A (authenticated + JWT sub) — RLS now applies
  -- ------------------------------------------------------------------
  perform set_config('request.jwt.claims',
                     json_build_object('sub', a, 'role', 'authenticated')::text, true);
  execute 'set local role authenticated';

  -- T02 A sees only her own lessons
  total := total + 1;
  select count(*) into n from public.lessons;
  if n = 2 then passed := passed + 1; else fails := fails || ('T02 A saw ' || n || ' lessons'); end if;

  -- T03 A cannot read B's lesson by id
  total := total + 1;
  select count(*) into n from public.lessons where id = lb;
  if n = 0 then passed := passed + 1; else fails := fails || 'T03 read other teacher lesson'; end if;

  -- T04 A cannot update B's lesson
  total := total + 1;
  update public.lessons set title = 'مخترق' where id = lb;
  get diagnostics n = row_count;
  if n = 0 then passed := passed + 1; else fails := fails || 'T04 updated other teacher lesson'; end if;

  -- T05 A cannot delete B's lesson
  total := total + 1;
  delete from public.lessons where id = lb;
  get diagnostics n = row_count;
  if n = 0 then passed := passed + 1; else fails := fails || 'T05 deleted other teacher lesson'; end if;

  -- T06 A cannot attach an activity to B's lesson under her own id (composite FK)
  total := total + 1;
  begin
    insert into public.activities (lesson_id, teacher_id, type, title, content, origin)
      values (lb, a, 'story', 'دخيل', '{}', 'manual');
    fails := fails || 'T06 cross-teacher activity accepted';
  exception
    when foreign_key_violation then passed := passed + 1;
    when others then fails := fails || ('T06 unexpected ' || sqlstate);
  end;

  -- T07 A cannot insert a row claiming to be B (RLS with check)
  total := total + 1;
  begin
    insert into public.activities (lesson_id, teacher_id, type, title, content, origin)
      values (lb, b, 'story', 'دخيل', '{}', 'manual');
    fails := fails || 'T07 impersonated insert accepted';
  exception
    when insufficient_privilege then passed := passed + 1;
    when others then fails := fails || ('T07 unexpected ' || sqlstate);
  end;

  -- T08 derived status: la has an approved activity, la2 has none
  total := total + 1;
  if (select status from public.lessons_with_status where id = la) = 'ready'
     and (select status from public.lessons_with_status where id = la2) = 'draft' then
    passed := passed + 1;
  else
    fails := fails || 'T08 derived lesson status';
  end if;

  -- T09 a placed unapproved activity makes the lesson draft (BRL-12) ...
  total := total + 1;
  insert into public.activities (lesson_id, teacher_id, type, title, content, origin, order_index)
    values (la, a, 'story', 'قصة مقترحة', '{"segments": []}', 'ai', 1);
  st := (select status from public.lessons_with_status where id = la);
  delete from public.activities where lesson_id = la and order_index = 1;
  -- ... but an unplaced suggestion (order_index NULL) does not
  insert into public.activities (lesson_id, teacher_id, type, title, content, origin)
    values (la, a, 'story', 'اقتراح معلّق', '{"segments": []}', 'ai');
  if st = 'draft' and (select status from public.lessons_with_status where id = la) = 'ready' then
    passed := passed + 1;
  else
    fails := fails || 'T09 placed vs unplaced suggestion';
  end if;

  -- T10 an approved activity must have approved_at and a position
  total := total + 1;
  begin
    insert into public.activities (lesson_id, teacher_id, type, title, content,
                                   approval_status, origin)
      values (la, a, 'story', 'بلا ترتيب', '{}', 'approved', 'manual');
    fails := fails || 'T10 approved activity without position/approved_at accepted';
  exception
    when check_violation then passed := passed + 1;
    when others then fails := fails || ('T10 unexpected ' || sqlstate);
  end;

  -- T11 schedule end before start is rejected (DR-06)
  total := total + 1;
  begin
    insert into public.schedule_items (teacher_id, title, date, start_time, end_time)
      values (a, 'خطأ', '2026-11-11', '09:00', '08:00');
    fails := fails || 'T11 end before start accepted';
  exception
    when check_violation then passed := passed + 1;
    when others then fails := fails || ('T11 unexpected ' || sqlstate);
  end;

  -- T12 a session cannot start from a draft lesson (FR-065, ERR-10)
  total := total + 1;
  begin
    insert into public.sessions (teacher_id, lesson_id, run_mode) values (a, la2, 'robot');
    fails := fails || 'T12 session on draft lesson accepted';
  exception
    when check_violation then passed := passed + 1;
    when others then fails := fails || ('T12 unexpected ' || sqlstate);
  end;

  -- T13 one active session per teacher (A-04)
  total := total + 1;
  insert into public.sessions (teacher_id, lesson_id, schedule_item_id, run_mode, current_activity_id)
    values (a, la, sched, 'class_screen', act) returning id into sa;
  begin
    insert into public.sessions (teacher_id, lesson_id, run_mode) values (a, la, 'robot');
    fails := fails || 'T13 second active session accepted';
  exception
    when unique_violation then passed := passed + 1;
    when others then fails := fails || ('T13 unexpected ' || sqlstate);
  end;

  -- T14 event codes accept ERR-nn / T-nn only, never free text (DR-12)
  total := total + 1;
  insert into public.session_events (session_id, teacher_id, event_type, code)
    values (sa, a, 'error', 'ERR-02');
  begin
    insert into public.session_events (session_id, teacher_id, event_type, code)
      values (sa, a, 'error', 'الطفل قال كذا');
    fails := fails || 'T14 free-text event code accepted';
  exception
    when check_violation then passed := passed + 1;
    when others then fails := fails || ('T14 unexpected ' || sqlstate);
  end;

  -- T15 session events are append-only for the teacher
  total := total + 1;
  begin
    update public.session_events set code = 'ERR-03' where session_id = sa;
    get diagnostics n = row_count;
    if n = 0 then passed := passed + 1; else fails := fails || 'T15 event row was updated'; end if;
  exception
    when insufficient_privilege then passed := passed + 1;  -- no UPDATE grant: expected
    when others then fails := fails || ('T15 unexpected ' || sqlstate);
  end;

  -- T16 column-level grant: A may rename herself but not change her id
  total := total + 1;
  update public.teachers set display_name = 'أ' where id = a;
  begin
    update public.teachers set id = gen_random_uuid() where id = a;
    fails := fails || 'T16 teacher id was writable';
  exception
    when insufficient_privilege then passed := passed + 1;
    when others then fails := fails || ('T16 unexpected ' || sqlstate);
  end;

  -- T17 deleting a lesson cascades to activities and unlinks schedule/session (DR-10)
  total := total + 1;
  delete from public.lessons where id = la;
  if not exists (select 1 from public.activities where lesson_id = la)
     and (select lesson_id from public.schedule_items where id = sched) is null
     and (select lesson_id from public.sessions where id = sa) is null
     and (select current_activity_id from public.sessions where id = sa) is null then
    passed := passed + 1;
  else
    fails := fails || 'T17 lesson delete cascade/unlink';
  end if;

  -- ------------------------------------------------------------------
  -- Anonymous role sees nothing
  -- ------------------------------------------------------------------
  execute 'reset role';
  execute 'set local role anon';
  total := total + 1;
  begin
    select count(*) into n from public.lessons;
    fails := fails || 'T18 anon could read lessons';
  exception
    when insufficient_privilege then passed := passed + 1;
    when others then fails := fails || ('T18 unexpected ' || sqlstate);
  end;
  execute 'reset role';

  -- ------------------------------------------------------------------
  -- Back as owner: account deletion and structural checks
  -- ------------------------------------------------------------------
  -- T19 deleting the auth user removes every row of that teacher (FR-085)
  total := total + 1;
  delete from auth.users where id = a;
  if not exists (select 1 from public.teachers where id = a)
     and not exists (select 1 from public.teacher_settings where teacher_id = a)
     and not exists (select 1 from public.lessons where teacher_id = a)
     and not exists (select 1 from public.activities where teacher_id = a)
     and not exists (select 1 from public.schedule_items where teacher_id = a)
     and not exists (select 1 from public.sessions where teacher_id = a)
     and not exists (select 1 from public.session_events where teacher_id = a) then
    passed := passed + 1;
  else
    fails := fails || 'T19 account deletion left rows';
  end if;

  -- T20 RLS is enabled on all seven tables
  total := total + 1;
  select count(*) into n from pg_class c join pg_namespace s on s.oid = c.relnamespace
  where s.nspname = 'public' and c.relkind = 'r' and c.relrowsecurity
    and c.relname in ('teachers', 'teacher_settings', 'lessons', 'activities',
                      'schedule_items', 'sessions', 'session_events');
  if n = 7 then passed := passed + 1; else fails := fails || ('T20 RLS on ' || n || '/7 tables'); end if;

  -- T21 anon has no privilege on any table or view in public
  total := total + 1;
  select count(*) into n from pg_class c join pg_namespace s on s.oid = c.relnamespace
  where s.nspname = 'public' and c.relkind in ('r', 'v')
    and (has_table_privilege('anon', c.oid, 'select')
         or has_table_privilege('anon', c.oid, 'insert')
         or has_table_privilege('anon', c.oid, 'update')
         or has_table_privilege('anon', c.oid, 'delete'));
  if n = 0 then passed := passed + 1; else fails := fails || ('T21 anon has privileges on ' || n || ' relations'); end if;

  -- T22 client roles cannot call the sign-up trigger function directly
  total := total + 1;
  if not has_function_privilege('authenticated', 'public.handle_new_teacher()', 'execute')
     and not has_function_privilege('anon', 'public.handle_new_teacher()', 'execute') then
    passed := passed + 1;
  else
    fails := fails || 'T22 handle_new_teacher executable by clients';
  end if;

  -- T23 no column suggests child identity, audio or transcripts (DR-07, DR-08)
  total := total + 1;
  select count(*) into n from information_schema.columns
  where table_schema = 'public'
    and column_name ~* '(child|student|pupil|audio|recording|transcript|photo|image)';
  if n = 0 then passed := passed + 1; else fails := fails || ('T23 suspicious columns: ' || n); end if;

  -- ------------------------------------------------------------------
  -- Report and roll everything back
  -- ------------------------------------------------------------------
  raise exception 'SCHEMA CHECKS: % / % passed. Failures: %',
    passed, total,
    coalesce(nullif(array_to_string(fails, ' | '), ''), 'none');
end
$test$;
