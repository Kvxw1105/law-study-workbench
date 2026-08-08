from __future__ import annotations

import io
import json
import sqlite3

import fitz
from fastapi.testclient import TestClient

from app.services.method_packs import evaluate_method_pack, select_method_pack
from app.services.scorer import LocalEvidenceScorer, ScoreRequest


def make_law_pdf() -> bytes:
    document = fitz.open()
    page = document.new_page()
    text = (
        "Acquisition in good faith requires the following conditions. "
        "The transferor lacks authority to dispose. The transferee acts in good faith, "
        "pays a reasonable price, and completes registration or delivery. "
        "However, the rule does not apply to lost property. "
        "After the transferee acquires ownership, the original owner may claim damages "
        "from the unauthorized disposer."
    )
    page.insert_textbox(fitz.Rect(50, 60, 540, 760), text, fontsize=12)
    payload = document.tobytes()
    document.close()
    return payload


def import_unit(client: TestClient) -> dict:
    source = client.post(
        "/api/sources/import?wait=true",
        files={"file": ("method-pack.pdf", io.BytesIO(make_law_pdf()), "application/pdf")},
    ).json()["source"]
    return client.get(f"/api/sources/{source['id']}/units").json()[0]


def test_method_pack_selection_is_deterministic_and_complete():
    expected_profiles = {
        "精确复现型": "precision_recall",
        "辨析型": "distinction",
        "适用型": "application",
        "理解解释型": "explanation",
        "表达型": "subjective_expression",
        "综合型": "balanced_recall",
        "未知类型": "balanced_recall",
    }
    expected_dimensions = {
        "core_question",
        "rule_elements",
        "exceptions_boundaries",
        "legal_effect",
        "terminology_expression",
    }

    for objective_type, profile in expected_profiles.items():
        first = select_method_pack(objective_type)
        second = select_method_pack(objective_type)
        assert first == second
        assert first["id"] == "law_full_recall_v1"
        assert first["version"] == "0.3.0"
        assert first["focus_profile"] == profile
        assert {item["id"] for item in first["training_dimensions"]} == expected_dimensions
        assert first["generated_flags"]["source_answer_hidden"] is True
        assert first["generated_flags"]["formal_legal_grade"] is False


def test_method_pack_diagnostics_are_source_bounded():
    source = (
        "善意取得应当具备下列条件：处分人为无处分权人；受让人在受让时为善意；"
        "以合理价格转让；依法应当登记的已经登记，不需要登记的已经交付。"
        "但是，遗失物不适用善意取得。受让人取得所有权后，原所有权人有权向"
        "无处分权人请求损害赔偿。"
    )
    answer = (
        "善意取得要求处分人无处分权，受让人善意并支付合理价格，完成登记或者交付。"
        "遗失物不适用。符合条件后受让人取得所有权，原权利人可以请求损害赔偿。"
    )
    request = ScoreRequest(
        unit_title="善意取得的构成要件与法律效果",
        source_text=source,
        page_start=12,
        page_end=13,
        answer_text=answer,
        confidence=80,
        hint_level=0,
        previous_errors=[],
    )
    base_feedback = LocalEvidenceScorer().score(request)
    result = evaluate_method_pack(
        selection=select_method_pack("精确复现型"),
        request=request,
        base_feedback=base_feedback,
    )

    assert result["method_pack"]["runtime_status"] == "completed"
    assert result["generated_flags"]["source_bounded"] is True
    assert result["generated_flags"]["external_knowledge_used"] is False
    assert result["generated_flags"]["formal_legal_grade"] is False
    assert len(result["dimension_results"]) == 5

    by_id = {item["id"]: item for item in result["dimension_results"]}
    assert by_id["rule_elements"]["status"] in {"strong", "partial"}
    assert by_id["exceptions_boundaries"]["status"] in {"strong", "partial"}
    assert by_id["legal_effect"]["status"] in {"strong", "partial"}

    for dimension in result["dimension_results"]:
        for ref in dimension["source_refs"]:
            assert ref["text"] in source
            assert ref["page_start"] == 12
            assert ref["page_end"] == 13


def test_session_freezes_and_persists_method_pack_snapshot(client: TestClient, settings):
    unit = import_unit(client)
    started = client.post(
        f"/api/units/{unit['id']}/sessions",
        json={"approve_unit": True},
    )
    assert started.status_code == 200, started.text
    session = started.json()["session"]
    frozen_pack = session["method_pack"]
    assert frozen_pack["id"] == "law_full_recall_v1"
    assert frozen_pack["version"] == "0.3.0"

    changed = client.patch(
        f"/api/units/{unit['id']}",
        json={"objective_type": "表达型"},
    )
    # The learning objective is part of the evidence contract. It cannot change
    # inside an active recall event.
    assert changed.status_code == 409, changed.text

    renamed = client.patch(
        f"/api/units/{unit['id']}",
        json={"title": "Display-only renamed unit"},
    )
    assert renamed.status_code == 200, renamed.text

    active = client.get("/api/sessions/active").json()
    assert active["objective_type"] == frozen_pack["objective_type"]
    assert active["title"] != "Display-only renamed unit"
    assert active["unit_version_drift"] is False
    assert client.get(f"/api/units/{unit['id']}").json()["title"] == "Display-only renamed unit"
    assert active["method_pack"]["focus_profile"] == frozen_pack["focus_profile"]
    assert active["method_pack"]["selection_reason"] == frozen_pack["selection_reason"]

    submitted = client.post(
        f"/api/sessions/{session['id']}/attempts",
        json={
            "answer_text": (
                "The transferor lacks authority. The transferee acts in good faith, pays a reasonable price, "
                "and completes registration or delivery. The rule does not apply to lost property. "
                "The transferee acquires ownership and the original owner may claim damages."
            ),
            "confidence": 82,
            "elapsed_ms": 52_000,
        },
    )
    assert submitted.status_code == 200, submitted.text
    result = submitted.json()
    assert result["method_pack"]["id"] == frozen_pack["id"]
    assert result["method_pack"]["version"] == frozen_pack["version"]
    assert result["method_pack"]["focus_profile"] == frozen_pack["focus_profile"]
    assert len(result["dimension_results"]) == 5
    assert result["feedback"]["method_pack"] == result["method_pack"]
    assert result["feedback"]["dimension_results"] == result["dimension_results"]

    stored_session = client.get(f"/api/sessions/{session['id']}").json()
    assert stored_session["attempt"]["feedback"]["method_pack"]["version"] == "0.3.0"
    assert len(stored_session["attempt"]["feedback"]["dimension_results"]) == 5

    with sqlite3.connect(settings.db_path) as conn:
        conn.row_factory = sqlite3.Row
        attempt_row = conn.execute(
            "SELECT feedback_json FROM attempts WHERE session_id=?",
            (session["id"],),
        ).fetchone()
        feedback_json = json.loads(attempt_row["feedback_json"])
        assert feedback_json["method_pack"]["focus_profile"] == frozen_pack["focus_profile"]
        events = conn.execute(
            "SELECT event_type, payload_json FROM study_events "
            "WHERE (entity_type='study_session' AND entity_id=?) OR "
            "(entity_type='attempt' AND entity_id=?) ORDER BY id",
            (session["id"], result["id"]),
        ).fetchall()
    event_types = [row["event_type"] for row in events]
    assert "method_pack_selected" in event_types
    assert "method_pack_evaluated" in event_types
    evaluated = next(json.loads(row["payload_json"]) for row in events if row["event_type"] == "method_pack_evaluated")
    assert evaluated["method_pack"]["version"] == "0.3.0"
    assert len(evaluated["dimension_results"]) == 5


def test_method_pack_failure_degrades_without_blocking_submission(client: TestClient, monkeypatch):
    unit = import_unit(client)
    session = client.post(
        f"/api/units/{unit['id']}/sessions",
        json={"approve_unit": True},
    ).json()["session"]

    def fail_method_pack(**_kwargs):
        raise RuntimeError("forced method-pack failure")

    monkeypatch.setattr("app.main.evaluate_method_pack", fail_method_pack)
    response = client.post(
        f"/api/sessions/{session['id']}/attempts",
        json={
            "answer_text": "The transferor lacks authority and the transferee acts in good faith.",
            "confidence": 60,
            "elapsed_ms": 20_000,
        },
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["provider"] == "local_evidence_v1"
    assert result["method_pack"]["runtime_status"] == "degraded"
    assert "方法包诊断失败" in result["feedback"]["warning"]
    assert {item["status"] for item in result["dimension_results"]} == {"unavailable"}


def test_legacy_active_session_without_method_event_is_compatible(client: TestClient, settings):
    from uuid import uuid4

    from app.db import utc_now

    unit = import_unit(client)
    session_id = str(uuid4())
    now = utc_now()
    with sqlite3.connect(settings.db_path) as conn:
        conn.execute(
            "INSERT INTO study_sessions(id, knowledge_unit_id, status, started_at, last_activity_at) "
            "VALUES(?, ?, 'active', ?, ?)",
            (session_id, unit["id"], now, now),
        )

    active = client.get("/api/sessions/active")
    assert active.status_code == 200, active.text
    assert active.json()["id"] == session_id
    assert active.json()["method_pack"]["id"] == "law_full_recall_v1"

    resumed = client.post(
        f"/api/units/{unit['id']}/sessions",
        json={"approve_unit": True},
    )
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["resumed"] is True
    assert resumed.json()["session"]["method_pack"]["version"] == "0.3.0"

    with sqlite3.connect(settings.db_path) as conn:
        event_count = conn.execute(
            "SELECT COUNT(*) FROM study_events "
            "WHERE event_type='method_pack_selected' AND entity_type='study_session' AND entity_id=?",
            (session_id,),
        ).fetchone()[0]
    assert event_count == 1
