"""Activity content validation (no database)."""

import pytest
from pydantic import TypeAdapter, ValidationError

from app.modules.activities.schemas import CONTENT_ADAPTERS, ActivityCreate, ActivityType

create = TypeAdapter(ActivityCreate)


def test_story_with_optional_questions():
    a = create.validate_python(
        {
            "type": "story",
            "title": " الفراشة الملونة ",
            "content": {"segments": [{"text": "كان يا ما كان"}, {"text": "طارت الفراشة", "question": "وين طارت؟"}]},
        }
    )
    assert a.title == "الفراشة الملونة"
    assert a.content.segments[1].question == "وين طارت؟"


def test_qa_dialogue_defaults():
    a = create.validate_python(
        {"type": "qa_dialogue", "title": "الألوان", "content": {"questions": [{"question": "وش لون الموز؟"}]}}
    )
    q = a.content.questions[0]
    assert q.expected_answers == [] and q.hint is None and q.simpler_question is None


@pytest.mark.parametrize(
    "payload",
    [
        {"type": "story", "title": "x", "content": {"segments": []}},
        {"type": "story", "title": "x", "content": {"segments": [{"text": "  "}]}},
        {"type": "story", "title": "", "content": {"segments": [{"text": "a"}]}},
        {"type": "qa_dialogue", "title": "x", "content": {"segments": [{"text": "a"}]}},
        {"type": "interactive", "title": "x", "content": {"instructions": "a", "steps": []}},
        {"type": "song", "title": "x", "content": {}},
        {"type": "story", "title": "x", "content": {"segments": [{"text": "a", "child_name": "سارة"}]}},
    ],
)
def test_invalid_activity_is_rejected(payload):
    with pytest.raises(ValidationError):
        create.validate_python(payload)


def test_content_adapter_per_type():
    ok = {"instructions": "نلعب", "steps": [{"text": "قفوا"}]}
    CONTENT_ADAPTERS[ActivityType.interactive].validate_python(ok)
    with pytest.raises(ValidationError):
        CONTENT_ADAPTERS[ActivityType.story].validate_python(ok)
