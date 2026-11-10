-- =====================================================================
-- 0001 — Extensions and enum types
-- Phase 1 design: https://claude.ai/artifact/RjaL3gLHhLgQoa2yT5rPBv
-- Enum values are stored in English; the UI shows Arabic labels.
-- =====================================================================

-- Trigram search on lesson titles (FR-014).
create extension if not exists pg_trgm with schema extensions;

-- D-08: ages 3 to 6. Values provisional (Phase 1, decision 1).
create type public.age_group as enum ('age_3_4', 'age_4_5', 'age_5_6', 'mixed_3_6');

-- FR-008 / DR-03
create type public.activity_type as enum ('story', 'qa_dialogue', 'interactive');

-- FR-023
create type public.approval_status as enum ('proposed', 'approved', 'rejected');
create type public.content_origin as enum ('manual', 'ai');

-- FR-076 to FR-078
create type public.run_mode as enum ('teacher_device', 'class_screen', 'robot');

-- FR-074
create type public.session_state as enum ('running', 'paused', 'ended');

-- FR-044
create type public.no_answer_action as enum ('repeat', 'encourage', 'skip');

-- FR-073: operational events only, never speech content (DR-12).
create type public.session_event_type as enum (
  'started', 'paused', 'resumed', 'ended',
  'ai_stopped', 'ai_resumed', 'activity_changed',
  'intervention_alert', 'schedule_alert', 'error'
);
