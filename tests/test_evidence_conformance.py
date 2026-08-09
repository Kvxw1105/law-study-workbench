"""Phase 5: Evidence Integrity adversarial tests (Schema 4 contract).

Attacks the evidence contract: version/hash binding, review invalidation,
history snapshot immutability, hard/possible conflicts, and the error-repair
resolution gates. All experiments use temp/synthetic data only.
"""
from __future__ import annotations

import io

from fastapi.testclient import TestClient

from tests.support import make_pdf

from app.config import Settings
from app.main import create_app

LAW_BODY = (
    "无权代理未经被代理人追认的，对被代理人不发生效力。"
    "善意相对人有权在被代理人追认前撤销。"
    "相对人可以催告被代理人自收到通知之日起三十日内予以追认。"
)


def import_unit(client: TestClient, text: str = LAW_BODY) -> dict:
    # import an ascii placeholder, then patch the exact law body so the unit
    # body matches the answer text byte-for-byte (PDF parsing may split lines)
    response = client.post(
        "/api/sources/import?wait=true",
        files={"file": ("evidence.pdf", io.BytesIO(make_pdf("Unrelated placeholder for parsing.")), "application/pdf")},
    )
    assert response.status_code == 200, response.text
    source = response.json()["source"]
    unit = client.get(f"/api/sources/{source['id']}/units").json()[0]
    patched = client.patch(f"/api/units/{unit['id']}", json={"body": text})
    assert patched.status_code == 200, patched.text
    return patched.json()


def unit_with_review(client: TestClient, unit_id: str) -> dict:
    """Unit as seen in the library list view (includes review/mastery JOIN)."""
    unit = client.get(f"/api/units/{unit_id}").json()
    units = client.get(f"/api/sources/{unit['source_id']}/units").json()
    return next(u for u in units if u["id"] == unit_id)


def approve_unit(client: TestClient, unit_id: str) -> None:
    response = client.patch(f"/api/units/{unit_id}", json={"status": "approved"})
    assert response.status_code == 200, response.text


def submit(client: TestClient, unit_id: str, answer: str, *, approve: bool = True) -> dict:
    if approve:
        approve_unit(client, unit_id)
    session = client.post(f"/api/units/{unit_id}/sessions", json={"approve_unit": False}).json()["session"]
    submitted = client.post(
        f"/api/sessions/{session['id']}/attempts",
        json={"answer_text": answer, "confidence": 80, "elapsed_ms": 10_000},
    )
    assert submitted.status_code == 200, submitted.text
    return submitted.json()


def open_error(client: TestClient, unit_id: str) -> dict:
    errors = client.get(f"/api/errors?unit_id={unit_id}&status=open").json()
    assert errors, "expected an open error record"
    return errors[0]


def _attempts(client: TestClient) -> list[dict]:
    return client.get("/api/export").json()["tables"]["attempts"]


def test_title_change_keeps_review_and_history(client: TestClient):
    unit = import_unit(client)
    submit(client, unit["id"], LAW_BODY)
    before = _attempts(client)
    assert before

    renamed = client.patch(f"/api/units/{unit['id']}", json={"title": "新的标题（仅改名）"})
    assert renamed.status_code == 200, renamed.text
    after = client.get(f"/api/units/{unit['id']}").json()
    # title change must not create a new evidence version
    assert after["version"] == unit["version"]
    after_attempts = _attempts(client)
    assert len(after_attempts) == len(before)
    # review/mastery survives a pure title change
    assert unit_with_review(client, unit["id"])["mastery_status"] != "新卡"


def test_body_change_invalidates_review_but_keeps_history_snapshot(client: TestClient):
    unit = import_unit(client)
    first = submit(client, unit["id"], unit["body"])
    assert first["review"]["mastery_status"] in ("不稳定", "基本稳定", "稳定")

    changed = client.patch(
        f"/api/units/{unit['id']}",
        json={"body": LAW_BODY + "新增一条限定：相对人也可以先催告。",
              "objective_type": "记忆 + 应用"},
    )
    assert changed.status_code == 200, changed.text
    updated = client.get(f"/api/units/{unit['id']}").json()
    assert updated["version"] == unit["version"] + 1

    # history attempts keep their original snapshot, never rewritten
    snapshots = _attempts(client)
    assert len(snapshots) == 1
    assert snapshots[0]["unit_body_hash"] != updated["body_hash"]
    assert snapshots[0]["unit_version"] == unit["version"]

    # old mastery must not carry across the version boundary (library view: None)
    refreshed = unit_with_review(client, unit["id"])
    assert refreshed["mastery_status"] is None
    assert refreshed.get("review_state") is None


def test_active_session_blocks_objective_change(client: TestClient):
    unit = import_unit(client)
    approve_unit(client, unit["id"])
    session = client.post(f"/api/units/{unit['id']}/sessions", json={"approve_unit": False}).json()["session"]
    blocked = client.patch(f"/api/units/{unit['id']}", json={"objective_type": "记忆"})
    assert blocked.status_code == 409
    assert "未完成闭卷" in blocked.json()["detail"]
    client.post(f"/api/sessions/{session['id']}/cancel")


def test_hard_conflict_affects_score_mastery_due_and_error(client: TestClient):
    unit = import_unit(client)
    bad = (
        "无权代理未经被代理人追认的，对被代理人发生效力。"
        "善意相对人无权在被代理人追认前撤销。"
        "相对人可以催告被代理人自收到通知之日起三十日内予以追认。"
    )
    result = submit(client, unit["id"], bad)
    assert result["provider_score"] > 70
    assert result["score"] <= 45
    assert result["evidence_verdict"]["status"] == "blocked_critical"
    assert result["review"]["mastery_status"] == "需立即修复"
    assert result["review"]["interval_days"] == 0  # due immediately
    error = open_error(client, unit["id"])
    assert error["error_type"] == "critical_legal_conflict"
    assert error["status"] == "open"


def test_resolve_without_repair_session_rejected(client: TestClient):
    unit = import_unit(client)
    bad = LAW_BODY.replace("不发生效力", "发生效力").replace("有权", "无权")
    submit(client, unit["id"], bad)
    error = open_error(client, unit["id"])
    response = client.post(f"/api/errors/{error['id']}/resolve")
    assert response.status_code == 409
    assert "无提示闭卷" in response.json()["detail"] or "修复" in response.json()["detail"]


def test_repair_retest_with_hint_cannot_resolve(client: TestClient):
    unit = import_unit(client)
    bad = LAW_BODY.replace("不发生效力", "发生效力").replace("有权", "无权")
    submit(client, unit["id"], bad)
    error = open_error(client, unit["id"])
    repair = client.post(f"/api/errors/{error['id']}/repair")
    assert repair.status_code == 200, repair.text
    session_id = repair.json()["session"]["id"]

    # use a hint, then answer correctly: hint retest must NOT satisfy the gate
    hinted = client.post(f"/api/sessions/{session_id}/hint", json={"level": 1})
    assert hinted.status_code == 200
    submitted = client.post(
        f"/api/sessions/{session_id}/attempts",
        json={"answer_text": unit["body"], "confidence": 85, "elapsed_ms": 20_000},
    )
    assert submitted.status_code == 200, submitted.text

    error_after = client.get(f"/api/errors?status=repairing&unit_id={unit['id']}").json()[0]
    assert error_after["can_resolve"] is False
    assert error_after["retest_attempt_id"] is None  # hint retests are excluded
    response = client.post(f"/api/errors/{error['id']}/resolve")
    assert response.status_code == 409


def test_repair_retest_below_70_cannot_resolve(client: TestClient):
    unit = import_unit(client)
    bad = LAW_BODY.replace("不发生效力", "发生效力").replace("有权", "无权")
    submit(client, unit["id"], bad)
    error = open_error(client, unit["id"])
    repair = client.post(f"/api/errors/{error['id']}/repair")
    session_id = repair.json()["session"]["id"]
    submitted = client.post(
        f"/api/sessions/{session_id}/attempts",
        json={"answer_text": "完全不相关的内容。", "confidence": 30, "elapsed_ms": 5_000},
    )
    assert submitted.status_code == 200
    error_after = client.get(f"/api/errors?status=repairing&unit_id={unit['id']}").json()[0]
    assert error_after["can_resolve"] is False
    assert error_after["retest_score"] is not None and error_after["retest_score"] < 70
    assert client.post(f"/api/errors/{error['id']}/resolve").status_code == 409


def test_legal_repair_resolves(client: TestClient):
    unit = import_unit(client)
    bad = LAW_BODY.replace("不发生效力", "发生效力").replace("有权", "无权")
    submit(client, unit["id"], bad)
    error = open_error(client, unit["id"])
    repair = client.post(f"/api/errors/{error['id']}/repair")
    assert repair.status_code == 200, repair.text
    session_id = repair.json()["session"]["id"]
    submitted = client.post(
        f"/api/sessions/{session_id}/attempts",
        json={"answer_text": unit["body"], "confidence": 90, "elapsed_ms": 25_000},
    )
    assert submitted.status_code == 200, submitted.text
    error_after = client.get(f"/api/errors?status=repairing&unit_id={unit['id']}").json()[0]
    assert error_after["can_resolve"] is True
    assert error_after["retest_score"] >= 70
    assert error_after["retest_evidence_weight"] >= 0.99
    assert error_after["retest_verdict_status"] == "accepted"

    resolved = client.post(f"/api/errors/{error['id']}/resolve")
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "resolved"
    assert resolved.json()["resolved_at"]


def test_resolved_error_cannot_repair_again(client: TestClient):
    unit = import_unit(client)
    bad = LAW_BODY.replace("不发生效力", "发生效力").replace("有权", "无权")
    submit(client, unit["id"], bad)
    error = open_error(client, unit["id"])
    repair = client.post(f"/api/errors/{error['id']}/repair")
    session_id = repair.json()["session"]["id"]
    client.post(
        f"/api/sessions/{session_id}/attempts",
        json={"answer_text": unit["body"], "confidence": 90, "elapsed_ms": 25_000},
    )
    assert client.post(f"/api/errors/{error['id']}/resolve").status_code == 200
    # resolved errors must reject new repair tasks
    again = client.post(f"/api/errors/{error['id']}/repair")
    assert again.status_code == 409
    assert "已经解决" in again.json()["detail"]


def test_superseded_error_binds_old_version_and_cannot_repair(client: TestClient):
    unit = import_unit(client)
    bad = LAW_BODY.replace("不发生效力", "发生效力").replace("有权", "无权")
    submit(client, unit["id"], bad)
    error = open_error(client, unit["id"])

    # material changes after the evidence -> error binds the old version
    changed = client.patch(f"/api/units/{unit['id']}", json={"body": LAW_BODY + "新增条款："})
    assert changed.status_code == 200
    repair = client.post(f"/api/errors/{error['id']}/repair")
    assert repair.status_code == 409
    assert "旧版" in repair.json()["detail"] or "当前版本" in repair.json()["detail"]


def test_error_of_archived_unit_cannot_repair(client: TestClient):
    unit = import_unit(client)
    bad = LAW_BODY.replace("不发生效力", "发生效力").replace("有权", "无权")
    submit(client, unit["id"], bad)
    error = open_error(client, unit["id"])
    archived = client.patch(f"/api/units/{unit['id']}", json={"status": "archived"})
    assert archived.status_code == 200
    repair = client.post(f"/api/errors/{error['id']}/repair")
    assert repair.status_code == 409
    assert "归档" in repair.json()["detail"]


def test_restart_preserves_review_and_error_states(settings: Settings):
    first = TestClient(create_app(settings))
    with first:
        unit = import_unit(first)
        bad = LAW_BODY.replace("不发生效力", "发生效力").replace("有权", "无权")
        submit(first, unit["id"], bad)
        error = open_error(first, unit["id"])
        assert error["status"] == "open"
    second = TestClient(create_app(settings))
    with second:
        unit_after = unit_with_review(second, unit["id"])
        assert unit_after["mastery_status"] == "需立即修复"
        errors = second.get(f"/api/errors?status=open&unit_id={unit['id']}").json()
        assert any(e["id"] == error["id"] for e in errors)
        # historical attempt survived restart with its snapshot
        attempts = second.get("/api/export").json()["tables"]["attempts"]
        assert any(a["id"] == error["attempt_id"] for a in attempts)


def test_attempt_snapshot_never_rewritten_after_restart_and_edit(client: TestClient):
    unit = import_unit(client)
    submit(client, unit["id"], LAW_BODY)
    snap_before = _attempts(client)[0]
    # material edit, then restart-like new app on the same home is covered by
    # other tests; here assert the stored snapshot is immutable at API level
    changed = client.patch(f"/api/units/{unit['id']}", json={"body": LAW_BODY + "新条款。"})
    assert changed.status_code == 200
    snap_after = _attempts(client)[0]
    assert snap_after["id"] == snap_before["id"]
    assert snap_after["unit_body_hash"] == snap_before["unit_body_hash"]
    assert snap_after["answer_text"] == snap_before["answer_text"]
