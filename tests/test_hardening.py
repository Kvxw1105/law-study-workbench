from __future__ import annotations

import io

import fitz
from fastapi.testclient import TestClient

from app.services.method_packs import evaluate_method_pack, select_method_pack
from app.services.retrieval import grade_cloze
from app.services.scorer import LocalEvidenceScorer, ScoreRequest


def make_pdf(text: str) -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_textbox(fitz.Rect(45, 55, 545, 780), text, fontsize=11)
    payload = document.tobytes()
    document.close()
    return payload


def import_unit(client: TestClient, text: str) -> tuple[dict, dict]:
    source = client.post(
        "/api/sources/import?wait=true",
        files={"file": ("hardening.pdf", io.BytesIO(make_pdf(text)), "application/pdf")},
    ).json()["source"]
    units = client.get(f"/api/sources/{source['id']}/units").json()
    assert units
    return source, units[0]


def test_cloze_critical_token_gate_rejects_polarity_number_and_qualifier_conflicts():
    cases = [
        ("应当", "不应当"),
        ("可以", "不可以"),
        ("三十日", "六十日"),
        ("恶意第三人", "善意第三人"),
        ("代理人", "被代理人"),
    ]
    for response, expected in cases:
        grade = grade_cloze(response, expected)
        assert grade.correct is False
        assert grade.rating == "again"
        assert grade.score <= 45
        assert grade.critical_mismatches
        assert "关键" in grade.note


def _law_request(answer: str) -> ScoreRequest:
    source = (
        "无权代理未经被代理人追认的，对被代理人不发生效力。"
        "善意相对人有权在被代理人追认前撤销。"
        "相对人可以催告被代理人自收到通知之日起三十日内予以追认。"
    )
    return ScoreRequest(
        unit_title="无权代理的效力与相对人保护",
        source_text=source,
        page_start=10,
        page_end=10,
        answer_text=answer,
        confidence=80,
        hint_level=0,
        previous_errors=[],
    )


def test_method_pack_flags_reversed_legal_effect_even_with_high_overlap():
    request = _law_request(
        "无权代理未经被代理人追认的，对被代理人发生效力。"
        "善意相对人无权在追认前撤销。相对人可以催告三十日内追认。"
    )
    result = evaluate_method_pack(
        selection=select_method_pack("精确复现型"),
        request=request,
        base_feedback=LocalEvidenceScorer().score(request),
    )
    by_id = {item["id"]: item for item in result["dimension_results"]}
    assert by_id["legal_effect"]["status"] == "critical_conflict"
    assert by_id["legal_effect"]["score"] <= 35
    assert by_id["legal_effect"]["critical_conflicts"]


def test_method_pack_does_not_call_keyword_pile_strong_core_answer():
    request = _law_request("代理权 被代理人 追认 效力 相对人 催告 三十日 善意 撤销 通知 条件")
    result = evaluate_method_pack(
        selection=select_method_pack("精确复现型"),
        request=request,
        base_feedback=LocalEvidenceScorer().score(request),
    )
    by_id = {item["id"]: item for item in result["dimension_results"]}
    assert by_id["core_question"]["status"] != "strong"
    assert by_id["core_question"]["structure_warning"] is True


def test_unit_split_and_merge_preserve_history_and_stale_cards(client: TestClient):
    text = (
        "First section. Unauthorized agency does not bind the principal without ratification. "
        "The counterparty may demand ratification. Second section. Apparent agency protects reasonable reliance "
        "when the counterparty has grounds to believe authority exists."
    )
    _, unit = import_unit(client, text)
    session = client.post(f"/api/units/{unit['id']}/sessions", json={"approve_unit": True}).json()["session"]
    submitted = client.post(
        f"/api/sessions/{session['id']}/attempts",
        json={"answer_text": "Unauthorized agency does not bind the principal without ratification.", "confidence": 60, "elapsed_ms": 1000},
    )
    assert submitted.status_code == 200
    created_card = client.post(
        f"/api/units/{unit['id']}/retrieval-items",
        json={
            "item_type": "flashcard",
            "prompt": "What is the effect of unauthorized agency before ratification?",
            "answer": "It does not bind the principal.",
            "source_excerpt": unit["body"],
        },
    )
    assert created_card.status_code == 200, created_card.text

    # A no-op save/approval must not invalidate cards or create a fake new version.
    before_noop = client.get(f"/api/units/{unit['id']}").json()
    noop = client.patch(
        f"/api/units/{unit['id']}",
        json={
            "title": before_noop["title"],
            "body": before_noop["body"],
            "objective_type": before_noop["objective_type"],
            "status": before_noop["status"],
        },
    )
    assert noop.status_code == 200
    assert noop.json()["version"] == before_noop["version"]
    active_cards = client.get(f"/api/units/{unit['id']}/retrieval-items?include_answer=true").json()
    assert active_cards and all(item["status"] == "active" for item in active_cards)

    # Splitting from the review dialog must honor unsaved text currently in the textarea.
    edited_body = unit["body"].replace("Second section.", "Second section revised.")
    split_at = edited_body.index("Second section revised")
    split = client.post(
        f"/api/units/{unit['id']}/split",
        json={
            "split_at": split_at,
            "body": edited_body,
            "left_title": "Unauthorized agency",
            "right_title": "Apparent agency",
        },
    )
    assert split.status_code == 200, split.text
    payload = split.json()
    assert payload["archived_unit_id"] == unit["id"]
    assert len(payload["units"]) == 2
    assert "Second section revised" in payload["units"][1]["body"]

    old = client.get(f"/api/units/{unit['id']}").json()
    assert old["status"] == "archived"
    old_cards = client.get(f"/api/units/{unit['id']}/retrieval-items?include_answer=true").json()
    assert old_cards and all(item["status"] == "stale" for item in old_cards)
    stored_session = client.get(f"/api/sessions/{session['id']}").json()
    assert stored_session["attempt"]["id"] == submitted.json()["id"]

    # Archived parents remain readable as history, but must disappear from current study queues
    # and may not silently re-enter learning through direct API calls.
    with client.app.state.db.connect() as conn:
        conn.execute("UPDATE review_states SET due_at='2000-01-01T00:00:00+00:00' WHERE knowledge_unit_id=?", (unit["id"],))
    today = client.get("/api/today").json()
    assert unit["id"] not in {item["id"] for item in today["due"]}
    model = client.get("/api/learning-model").json()
    assert sum(int(item["count"]) for item in model["mastery"]) == 0
    assert client.post(f"/api/units/{unit['id']}/sessions", json={"approve_unit": True}).status_code == 409
    assert client.post(
        f"/api/units/{unit['id']}/retrieval-items/generate",
        json={"item_types": ["flashcard"], "max_per_type": 1},
    ).status_code == 409
    assert client.post(
        f"/api/units/{unit['id']}/retrieval-items",
        json={"item_type": "flashcard", "prompt": "Archived?", "answer": "No"},
    ).status_code == 409

    merged = client.post(
        f"/api/units/{payload['units'][0]['id']}/merge",
        json={"other_unit_id": payload["units"][1]["id"], "title": "Agency doctrines"},
    )
    assert merged.status_code == 200, merged.text
    merged_payload = merged.json()
    assert merged_payload["unit"]["title"] == "Agency doctrines"
    assert "Unauthorized agency" in merged_payload["unit"]["body"]
    assert "Apparent agency" in merged_payload["unit"]["body"]


def test_error_repair_requires_later_unhinted_retest_before_resolve(client: TestClient):
    _, unit = import_unit(
        client,
        "A valid transfer requires good faith, reasonable value, and delivery or registration. Lost property is generally excluded from this rule.",
    )
    first_session = client.post(f"/api/units/{unit['id']}/sessions", json={"approve_unit": True}).json()["session"]
    first = client.post(
        f"/api/sessions/{first_session['id']}/attempts",
        json={"answer_text": "不知道", "confidence": 90, "elapsed_ms": 500},
    )
    assert first.status_code == 200
    errors = client.get(f"/api/errors?unit_id={unit['id']}&status=open").json()
    assert errors
    error = errors[0]

    premature = client.post(f"/api/errors/{error['id']}/resolve")
    assert premature.status_code == 409

    repair = client.post(f"/api/errors/{error['id']}/repair")
    assert repair.status_code == 200, repair.text
    repair_session = repair.json()["session"]
    assert repair.json()["error"]["status"] == "repairing"

    second = client.post(
        f"/api/sessions/{repair_session['id']}/attempts",
        json={
            "answer_text": "A valid transfer requires good faith, reasonable value, and delivery or registration; lost property is generally excluded from this rule.",
            "confidence": 70,
            "elapsed_ms": 1200,
        },
    )
    assert second.status_code == 200

    resolvable = client.get(f"/api/errors?unit_id={unit['id']}&status=repairing").json()
    target = next(item for item in resolvable if item["id"] == error["id"])
    assert target["can_resolve"] is True
    assert target["retest_attempt_id"] == second.json()["id"]

    resolved = client.post(f"/api/errors/{error['id']}/resolve")
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["status"] == "resolved"
    assert resolved.json()["resolved_at"]
