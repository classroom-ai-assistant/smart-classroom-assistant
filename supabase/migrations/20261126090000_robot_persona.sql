-- Robot persona and automatic narration (approved 2026-11-26).
--
-- Each teacher names her robot and picks its character and voice in the
-- settings; she can change them any time. The robot then writes its own
-- words for every slide. `speech_auto` tells apart words the robot wrote
-- (may be rewritten when the deck changes) from words the teacher wrote
-- herself (never overwritten unless she asks).
--
-- Nothing here is about children: these are the teacher's own choices.

alter table public.teacher_settings
  add column robot_name  text not null default 'روبو'
             check (char_length(btrim(robot_name)) between 1 and 30),
  add column robot_style text not null default 'playful'
             check (robot_style in ('storyteller', 'playful', 'calm')),
  add column robot_voice text not null default 'Puck'
             check (robot_voice in ('Puck', 'Kore', 'Leda', 'Achird', 'Sulafat', 'Zephyr'));

-- Column-level grants: the teacher may update only these columns.
grant update (robot_name, robot_style, robot_voice) on public.teacher_settings to authenticated;

alter table public.slides
  add column speech_auto boolean not null default false;
