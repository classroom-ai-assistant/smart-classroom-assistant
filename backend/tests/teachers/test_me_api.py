"""/api/v1/me endpoints (FR-001 to FR-004, FR-044, FR-086, FR-087, AUTH-09)."""

from uuid import uuid4

import pytest

from app.modules.teachers.pin import verify_pin


def test_get_me_returns_profile_and_settings(client, auth_headers, teacher_id):
    response = client.get("/api/v1/me", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(teacher_id)
    assert body["display_name"] == "معلمة تجريبية"
    assert body["email"] == "teacher@example.com"
    assert body["settings"]["voice_volume"] == 80
    assert body["settings"]["speech_rate"] == 1.0
    assert body["settings"]["has_kids_mode_pin"] is False


def test_response_never_contains_the_pin_hash(client, auth_headers):
    client.put("/api/v1/me/kids-mode-pin", headers=auth_headers, json={"pin": "4821"})
    text = client.get("/api/v1/me", headers=auth_headers).text
    assert "pin_hash" not in text
    assert "scrypt" not in text


def test_get_me_for_missing_profile_is_404_in_arabic(client, make_token):
    response = client.get("/api/v1/me", headers={"Authorization": f"Bearer {make_token(uuid4())}"})
    assert response.status_code == 404
    assert "ملف المعلمة" in response.json()["error"]["message"]


def test_teacher_only_ever_sees_her_own_profile(client, make_token, fake_repo):
    a, b = uuid4(), uuid4()
    fake_repo.add_teacher(a, "أ")
    fake_repo.add_teacher(b, "ب")
    body = client.get("/api/v1/me", headers={"Authorization": f"Bearer {make_token(a)}"}).json()
    assert body["id"] == str(a)
    assert body["display_name"] == "أ"


def test_update_display_name_trims_spaces(client, auth_headers, fake_repo, teacher_id):
    response = client.patch("/api/v1/me", headers=auth_headers, json={"display_name": "  أ. نورة  "})
    assert response.status_code == 200
    assert response.json()["display_name"] == "أ. نورة"
    assert fake_repo.rows[teacher_id]["display_name"] == "أ. نورة"


@pytest.mark.parametrize("name", ["", "   ", "ن" * 101])
def test_invalid_display_name_is_422_naming_the_field(client, auth_headers, name):
    response = client.patch("/api/v1/me", headers=auth_headers, json={"display_name": name})
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_failed"
    assert error["details"][0]["field"] == "display_name"


def test_unknown_fields_are_rejected(client, auth_headers):
    response = client.patch("/api/v1/me", headers=auth_headers, json={"display_name": "س", "id": str(uuid4())})
    assert response.status_code == 422


def test_validation_error_does_not_echo_input(client, auth_headers):
    secret_looking = "ن" * 101
    response = client.patch("/api/v1/me", headers=auth_headers, json={"display_name": secret_looking})
    assert secret_looking not in response.text


def test_partial_settings_update(client, auth_headers, fake_repo, teacher_id):
    response = client.patch(
        "/api/v1/me/settings",
        headers=auth_headers,
        json={"voice_volume": 60, "no_answer_action": "encourage"},
    )
    assert response.status_code == 200
    settings = response.json()["settings"]
    assert settings["voice_volume"] == 60
    assert settings["no_answer_action"] == "encourage"
    assert settings["answer_wait_seconds"] == 8  # untouched


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"voice_volume": 101},
        {"voice_volume": -1},
        {"speech_rate": 2.0},
        {"answer_wait_seconds": 2},
        {"default_alert_lead_minutes": 61},
        {"no_answer_action": "shout"},
        {"voice_volume": None},
        {"privacy_notice_accepted": False},
        {"kids_mode_pin_hash": "x"},
    ],
)
def test_invalid_settings_are_rejected(client, auth_headers, payload):
    response = client.patch("/api/v1/me/settings", headers=auth_headers, json=payload)
    assert response.status_code == 422


def test_accepting_privacy_notice_records_the_time(client, auth_headers):
    response = client.patch("/api/v1/me/settings", headers=auth_headers, json={"privacy_notice_accepted": True})
    assert response.status_code == 200
    assert response.json()["settings"]["privacy_notice_accepted_at"] is not None


def test_set_kids_mode_pin_stores_a_verifiable_hash(client, auth_headers, fake_repo, teacher_id):
    response = client.put("/api/v1/me/kids-mode-pin", headers=auth_headers, json={"pin": "4821"})
    assert response.status_code == 200
    assert response.json()["settings"]["has_kids_mode_pin"] is True

    stored = fake_repo.rows[teacher_id]["kids_mode_pin_hash"]
    assert stored != "4821"
    assert verify_pin("4821", stored)
    assert not verify_pin("0000", stored)


@pytest.mark.parametrize("pin", ["123", "1234567", "12a4", "", "١٢٣٤"])
def test_invalid_pin_is_rejected(client, auth_headers, pin):
    response = client.put("/api/v1/me/kids-mode-pin", headers=auth_headers, json={"pin": pin})
    assert response.status_code == 422


def test_all_me_endpoints_require_a_token(client):
    assert client.get("/api/v1/me").status_code == 401
    assert client.patch("/api/v1/me", json={"display_name": "x"}).status_code == 401
    assert client.patch("/api/v1/me/settings", json={"voice_volume": 50}).status_code == 401
    assert client.put("/api/v1/me/kids-mode-pin", json={"pin": "1234"}).status_code == 401
