-- =====================================================================
-- 0002 — Tables, constraints and indexes
-- No table or column holds child identity or audio (BRL-07, BRL-08,
-- DR-07, DR-08). Every child table carries teacher_id plus a composite
-- foreign key (x_id, teacher_id) so a row can never point at another
-- teacher's lesson, activity, schedule item or session (BRL-03).
-- =====================================================================

-- ---------------------------------------------------------------------
-- teachers — profile row; email and password live in auth.users
-- (FR-001, FR-004, AUTH-02). Created by trigger on sign-up (0003).
-- ---------------------------------------------------------------------
create table public.teachers (
  id            uuid primary key references auth.users (id) on delete cascade,
  display_name  text not null
                check (char_length(btrim(display_name)) between 1 and 100),
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

-- ---------------------------------------------------------------------
-- teacher_settings — inferred table for FR-044, FR-087, AUTH-09, FR-086.
-- Defaults are provisional until the voice PoC (D-06); the CHECK ranges
-- are safety bounds only.
-- ---------------------------------------------------------------------
create table public.teacher_settings (
  teacher_id                  uuid primary key
                              references public.teachers (id) on delete cascade,
  voice_volume                smallint not null default 80
                              check (voice_volume between 0 and 100),
  speech_rate                 numeric(3, 2) not null default 1.00
                              check (speech_rate between 0.50 and 1.50),
  answer_wait_seconds         smallint not null default 8
                              check (answer_wait_seconds between 3 and 30),
  no_answer_action            public.no_answer_action not null default 'repeat',
  kids_mode_pin_hash          text,  -- hash only, never the PIN itself
  default_alert_lead_minutes  smallint not null default 5
                              check (default_alert_lead_minutes between 0 and 60),
  privacy_notice_accepted_at  timestamptz,
  created_at                  timestamptz not null default now(),
  updated_at                  timestamptz not null default now()
);

-- ---------------------------------------------------------------------
-- lessons (FR-005 to FR-015). Draft/ready status is NOT stored; it is
-- derived by public.lesson_is_ready() so it can never drift (BRL-12).
-- ---------------------------------------------------------------------
create table public.lessons (
  id                     uuid primary key default gen_random_uuid(),
  teacher_id             uuid not null references public.teachers (id) on delete cascade,
  title                  text not null
                         check (char_length(btrim(title)) between 1 and 150),
  topic                  text not null
                         check (char_length(btrim(topic)) between 1 and 200),
  age_group              public.age_group not null,
  copied_from_lesson_id  uuid,  -- FR-013 provenance; cleared if the source is deleted
  created_at             timestamptz not null default now(),
  updated_at             timestamptz not null default now(),
  constraint lessons_id_teacher_key unique (id, teacher_id),
  constraint lessons_copied_from_fkey
    foreign key (copied_from_lesson_id, teacher_id)
    references public.lessons (id, teacher_id)
    on delete set null (copied_from_lesson_id)
);

create index lessons_teacher_updated_idx
  on public.lessons (teacher_id, updated_at desc);
create index lessons_title_trgm_idx
  on public.lessons using gin (title extensions.gin_trgm_ops);
create index lessons_copied_from_idx
  on public.lessons (copied_from_lesson_id)
  where copied_from_lesson_id is not null;

-- ---------------------------------------------------------------------
-- activities (FR-008, FR-020 to FR-023, FR-030).
-- order_index NULL = not placed in the lesson (e.g. an AI suggestion
-- still awaiting the teacher). An approved activity must be placed.
-- ---------------------------------------------------------------------
create table public.activities (
  id               uuid primary key default gen_random_uuid(),
  lesson_id        uuid not null,
  teacher_id       uuid not null references public.teachers (id) on delete cascade,
  type             public.activity_type not null,
  title            text not null
                   check (char_length(btrim(title)) between 1 and 150),
  content          jsonb not null
                   check (jsonb_typeof(content) = 'object'),
  approval_status  public.approval_status not null default 'proposed',
  origin           public.content_origin not null,
  approved_at      timestamptz,
  order_index      integer check (order_index >= 0),
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  constraint activities_id_teacher_key unique (id, teacher_id),
  constraint activities_lesson_fkey
    foreign key (lesson_id, teacher_id)
    references public.lessons (id, teacher_id)
    on delete cascade,
  -- Deferrable so a reorder can swap positions inside one transaction (FR-009).
  constraint activities_lesson_order_key
    unique (lesson_id, order_index) deferrable initially immediate,
  constraint activities_approved_at_consistent
    check ((approval_status = 'approved') = (approved_at is not null)),
  constraint activities_approved_is_placed
    check (approval_status <> 'approved' or order_index is not null)
);

create index activities_teacher_idx on public.activities (teacher_id);

-- ---------------------------------------------------------------------
-- schedule_items (FR-055 to FR-064). Duration is derived from start/end
-- (FR-056). Overlaps are allowed after teacher confirmation (BRL-14),
-- so the overlap warning lives in the API, not here.
-- ---------------------------------------------------------------------
create table public.schedule_items (
  id                  uuid primary key default gen_random_uuid(),
  teacher_id          uuid not null references public.teachers (id) on delete cascade,
  lesson_id           uuid,  -- optional link (FR-057)
  title               text not null
                      check (char_length(btrim(title)) between 1 and 150),
  date                date not null,
  start_time          time not null,  -- kindergarten local time, no time zone
  end_time            time not null,
  alert_lead_minutes  smallint check (alert_lead_minutes between 0 and 60),
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),
  constraint schedule_items_id_teacher_key unique (id, teacher_id),
  constraint schedule_items_end_after_start check (end_time > start_time),  -- DR-06
  constraint schedule_items_lesson_fkey
    foreign key (lesson_id, teacher_id)
    references public.lessons (id, teacher_id)
    on delete set null (lesson_id)  -- DR-10
);

create index schedule_items_teacher_day_idx
  on public.schedule_items (teacher_id, date, start_time);
create index schedule_items_lesson_idx
  on public.schedule_items (lesson_id) where lesson_id is not null;

-- ---------------------------------------------------------------------
-- sessions (FR-065 to FR-075). One non-ended session per teacher (A-04).
-- resume_position holds positions only (segment/step numbers), no text.
-- ---------------------------------------------------------------------
create table public.sessions (
  id                   uuid primary key default gen_random_uuid(),
  teacher_id           uuid not null references public.teachers (id) on delete cascade,
  lesson_id            uuid,
  schedule_item_id     uuid,
  run_mode             public.run_mode not null,
  state                public.session_state not null default 'running',
  ai_enabled           boolean not null default true,
  current_activity_id  uuid,
  resume_position      jsonb
                       check (resume_position is null or jsonb_typeof(resume_position) = 'object'),
  started_at           timestamptz not null default now(),
  ended_at             timestamptz,
  created_at           timestamptz not null default now(),
  updated_at           timestamptz not null default now(),
  constraint sessions_id_teacher_key unique (id, teacher_id),
  constraint sessions_ended_consistent
    check ((state = 'ended') = (ended_at is not null)),
  constraint sessions_end_after_start
    check (ended_at is null or ended_at >= started_at),
  constraint sessions_lesson_fkey
    foreign key (lesson_id, teacher_id)
    references public.lessons (id, teacher_id)
    on delete set null (lesson_id),
  constraint sessions_schedule_item_fkey
    foreign key (schedule_item_id, teacher_id)
    references public.schedule_items (id, teacher_id)
    on delete set null (schedule_item_id),
  constraint sessions_current_activity_fkey
    foreign key (current_activity_id, teacher_id)
    references public.activities (id, teacher_id)
    on delete set null (current_activity_id)
);

create unique index sessions_one_active_per_teacher
  on public.sessions (teacher_id) where state <> 'ended';
create index sessions_lesson_idx
  on public.sessions (lesson_id) where lesson_id is not null;
create index sessions_schedule_item_idx
  on public.sessions (schedule_item_id) where schedule_item_id is not null;
create index sessions_current_activity_idx
  on public.sessions (current_activity_id) where current_activity_id is not null;

-- ---------------------------------------------------------------------
-- session_events (FR-073, NFR-024). Append-only log with no free-text
-- column: code accepts only ERR-nn / T-nn so no child speech can be
-- written here (DR-12).
-- ---------------------------------------------------------------------
create table public.session_events (
  id           bigint generated always as identity primary key,
  session_id   uuid not null,
  teacher_id   uuid not null references public.teachers (id) on delete cascade,
  event_type   public.session_event_type not null,
  code         text check (code is null or code ~ '^(ERR|T)-[0-9]{2}$'),
  occurred_at  timestamptz not null default now(),
  constraint session_events_session_fkey
    foreign key (session_id, teacher_id)
    references public.sessions (id, teacher_id)
    on delete cascade
);

create index session_events_session_time_idx
  on public.session_events (session_id, occurred_at);
create index session_events_occurred_idx
  on public.session_events (occurred_at);  -- retention sweep (DR-13)
