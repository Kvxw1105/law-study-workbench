from __future__ import annotations

import io
from pathlib import Path

import fitz
from fastapi.testclient import TestClient

from app.main import create_app


def make_pdf() -> bytes:
    document = fitz.open()
    page = document.new_page()
    text = (
        "Acquisition in good faith requires several conditions. "
        "The transferor lacks authority to dispose. The transferee acts in good faith, "
        "pays a reasonable price, and completes registration or delivery. "
        "The original owner may claim damages from the unauthorized disposer.\n\n"
        "The time for judging good faith is the time of registration or delivery."
    )
    page.insert_textbox(fitz.Rect(50, 60, 540, 760), text, fontsize=12)
    payload = document.tobytes()
    document.close()
    return payload


def test_complete_local_learning_loop(client: TestClient):
    pdf = make_pdf()
    response = client.post(
        "/api/sources/import?wait=true",
        files={"file": ("civil-law.pdf", io.BytesIO(pdf), "application/pdf")},
    )
    assert response.status_code == 200, response.text
    source = response.json()["source"]
    assert source["status"] == "ready"

    units = client.get(f"/api/sources/{source['id']}/units").json()
    assert units
    unit = units[0]

    started = client.post(
        f"/api/units/{unit['id']}/sessions",
        json={"approve_unit": True},
    ).json()
    session_id = started["session"]["id"]

    active = client.get("/api/sessions/active").json()
    assert active["id"] == session_id

    attempt = client.post(
        f"/api/sessions/{session_id}/attempts",
        json={
            "answer_text": "The transferor lacks authority. The transferee is in good faith, pays a reasonable price, and completes registration or delivery.",
            "confidence": 80,
            "elapsed_ms": 42_000,
        },
    )
    assert attempt.status_code == 200, attempt.text
    result = attempt.json()
    assert 0 <= result["score"] <= 100
    assert result["review"]["due_at"]
    assert result["feedback"]["evidence"]

    assert client.get("/api/sessions/active").json() is None
    model = client.get("/api/learning-model").json()
    assert model["metrics"]["attempts"] == 1

    export_response = client.get("/api/export")
    assert export_response.status_code == 200
    assert export_response.headers["content-type"].startswith("application/json")


def test_session_survives_app_restart(settings):
    pdf = make_pdf()
    first_app = create_app(settings)
    with TestClient(first_app) as first:
        source = first.post(
            "/api/sources/import?wait=true",
            files={"file": ("restart.pdf", io.BytesIO(pdf), "application/pdf")},
        ).json()["source"]
        unit = first.get(f"/api/sources/{source['id']}/units").json()[0]
        session = first.post(
            f"/api/units/{unit['id']}/sessions",
            json={"approve_unit": True},
        ).json()["session"]

    second_app = create_app(settings)
    with TestClient(second_app) as second:
        active = second.get("/api/sessions/active").json()
        assert active["id"] == session["id"]
        resumed = second.post(
            f"/api/units/{unit['id']}/sessions",
            json={"approve_unit": True},
        ).json()
        assert resumed["resumed"] is True
        assert resumed["session"]["id"] == session["id"]


def test_rejects_fake_pdf_and_deduplicates_real_pdf(client: TestClient):
    bad = client.post(
        "/api/sources/import?wait=true",
        files={"file": ("fake.pdf", io.BytesIO(b"not a pdf"), "application/pdf")},
    )
    assert bad.status_code == 415

    pdf = make_pdf()
    first = client.post(
        "/api/sources/import?wait=true",
        files={"file": ("same.pdf", io.BytesIO(pdf), "application/pdf")},
    ).json()
    second = client.post(
        "/api/sources/import?wait=true",
        files={"file": ("copy.pdf", io.BytesIO(pdf), "application/pdf")},
    ).json()
    assert first["deduplicated"] is False
    assert second["deduplicated"] is True
    assert len(client.get("/api/sources").json()) == 1


def test_draft_persists_and_second_active_session_is_blocked(settings):
    pdf = make_pdf()
    app = create_app(settings)
    with TestClient(app) as client:
        source = client.post(
            "/api/sources/import?wait=true",
            files={"file": ("one.pdf", io.BytesIO(pdf), "application/pdf")},
        ).json()["source"]
        unit = client.get(f"/api/sources/{source['id']}/units").json()[0]
        session = client.post(
            f"/api/units/{unit['id']}/sessions",
            json={"approve_unit": True},
        ).json()["session"]
        saved = client.put(
            f"/api/sessions/{session['id']}/draft",
            json={"text": "draft answer", "confidence": 66},
        )
        assert saved.status_code == 200

        second_pdf = make_pdf() + b"\n% second distinct file"
        source2 = client.post(
            "/api/sources/import?wait=true",
            files={"file": ("two.pdf", io.BytesIO(second_pdf), "application/pdf")},
        ).json()["source"]
        # Appending after EOF keeps the PDF readable and produces a distinct content hash.
        unit2 = client.get(f"/api/sources/{source2['id']}/units").json()[0]
        blocked = client.post(
            f"/api/units/{unit2['id']}/sessions",
            json={"approve_unit": True},
        )
        assert blocked.status_code == 409

    restarted = create_app(settings)
    with TestClient(restarted) as client:
        active = client.get("/api/sessions/active").json()
        assert active["draft_text"] == "draft answer"
        assert active["draft_confidence"] == 66
        cancelled = client.post(f"/api/sessions/{active['id']}/cancel")
        assert cancelled.status_code == 200
        assert client.get("/api/sessions/active").json() is None
