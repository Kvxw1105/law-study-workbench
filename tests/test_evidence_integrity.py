from __future__ import annotations

import io
import json
import sqlite3
from pathlib import Path

import fitz
from fastapi.testclient import TestClient

from app.db import Database
from app.services.legal_signals import detect_clause_conflicts, detect_mismatch_details, looks_like_keyword_pile
from app.services.retrieval import grade_cloze


def make_pdf(text: str) -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_textbox(fitz.Rect(45, 55, 545, 780), text, fontsize=11)
    payload = document.tobytes()
    document.close()
    return payload


def import_ascii_unit(client: TestClient, text: str | None = None) -> tuple[dict, dict]:
    text = text or (
        "Unauthorized agency does not bind the principal without ratification. "
        "A good-faith counterparty may revoke before ratification. "
        "The counterparty may request ratification within thirty days."
    )
    response = client.post(
        "/api/sources/import?wait=true",
        files={"file": ("evidence-integrity.pdf", io.BytesIO(make_pdf(text)), "application/pdf")},
    )
    assert response.status_code == 200, response.text
    source = response.json()["source"]
    units = client.get(f"/api/sources/{source['id']}/units").json()
    assert units
    return source, units[0]


def approve_unit(client: TestClient, unit_id: str) -> dict:
    response = client.patch(f"/api/units/{unit_id}", json={"status": "approved"})
    assert response.status_code == 200, response.text
    return response.json()


def test_draft_unit_requires_explicit_approval_before_session(client: TestClient):
    _, unit = import_ascii_unit(client)
    assert unit["status"] == "draft"
    blocked = client.post(f"/api/units/{unit['id']}/sessions", json={"approve_unit": False})
    assert blocked.status_code == 409
    started = client.post(f"/api/units/{unit['id']}/sessions", json={"approve_unit": True})
    assert started.status_code == 200, started.text
    assert client.get(f"/api/units/{unit['id']}").json()["status"] == "approved"


def test_learning_target_provenance_distinguishes_source_exact_from_edited_text(client: TestClient):
    _, unit = import_ascii_unit(client)
    approve_unit(client, unit["id"])
    exact_session = client.post(f"/api/units/{unit['id']}/sessions", json={"approve_unit": False}).json()["session"]
    assert exact_session["method_pack"]["generated_flags"]["learning_target_provenance"] == "source_exact"
    assert exact_session["method_pack"]["generated_flags"]["source_exact"] is True
    client.post(f"/api/sessions/{exact_session['id']}/cancel")

    changed = client.patch(
        f"/api/units/{unit['id']}",
        json={"body": unit["body"] + " A learner-added explanation changes this target."},
    )
    assert changed.status_code == 200, changed.text
    approve_unit(client, unit["id"])
    edited_session = client.post(f"/api/units/{unit['id']}/sessions", json={"approve_unit": False}).json()["session"]
    flags = edited_session["method_pack"]["generated_flags"]
    assert flags["learning_target_provenance"] == "edited_learning_text"
    assert flags["source_exact"] is False
    assert flags["source_bounded"] is False
    assert flags["learning_target_bounded"] is True


def test_hard_conflict_controls_effective_score_review_and_errors(client: TestClient):
    _, unit = import_ascii_unit(client)
    law_body = (
        "无权代理未经被代理人追认的，对被代理人不发生效力。"
        "善意相对人有权在被代理人追认前撤销。"
        "相对人可以催告被代理人自收到通知之日起三十日内予以追认。"
    )
    edited = client.patch(f"/api/units/{unit['id']}", json={"body": law_body})
    assert edited.status_code == 200, edited.text
    assert edited.json()["status"] == "draft"
    approve_unit(client, unit["id"])

    session = client.post(f"/api/units/{unit['id']}/sessions", json={"approve_unit": False}).json()["session"]
    submitted = client.post(
        f"/api/sessions/{session['id']}/attempts",
        json={
            "answer_text": (
                "无权代理未经被代理人追认的，对被代理人发生效力。"
                "善意相对人无权在被代理人追认前撤销。"
                "相对人可以催告被代理人自收到通知之日起三十日内予以追认。"
            ),
            "confidence": 90,
            "elapsed_ms": 12_000,
        },
    )
    assert submitted.status_code == 200, submitted.text
    result = submitted.json()
    assert result["provider_score"] > 70
    assert result["score"] <= 45
    assert result["evidence_verdict"]["status"] == "blocked_critical"
    assert result["review"]["mastery_status"] == "需立即修复"
    assert result["review"]["interval_days"] == 0

    errors = client.get(f"/api/errors?unit_id={unit['id']}&status=open").json()
    assert any(item["error_type"] == "critical_legal_conflict" for item in errors)
    current_units = client.get(f"/api/sources/{unit['source_id']}/units").json()
    current = next(item for item in current_units if item["id"] == unit["id"])
    assert current["mastery_status"] == "需立即修复"


def test_conflict_detector_catches_appended_contradiction():
    source = "无权代理未经被代理人追认的，对被代理人不发生效力。"
    answer = "无权代理未经被代理人追认的，对被代理人不发生效力。另据此，对被代理人发生效力。"
    conflicts = detect_clause_conflicts(source, answer)
    assert any(item.severity == "hard" for item in conflicts)


def test_conflict_detector_binds_roles_and_numbers_and_softens_scoped_negation():
    role = detect_clause_conflicts("债务人应当向债权人履行债务。", "债权人应当向债务人履行债务。")
    assert any(item.severity == "hard" and "主体关系" in "".join(item.mismatches) for item in role)

    number = detect_clause_conflicts(
        "相对人应当在三十日内通知，并在六十日内起诉。",
        "相对人应当在六十日内通知，并在三十日内起诉。",
    )
    assert any(item.severity == "hard" and "数字关系" in "".join(item.mismatches) for item in number)

    scoped = detect_mismatch_details("合同依法有效。", "合同并非无效。")
    assert not any(item.severity == "hard" for item in scoped)
    assert any(item.severity == "possible" for item in scoped)

    short_rule = detect_clause_conflicts("合同无效。", "合同有效。")
    assert any(item.severity == "hard" for item in short_rule)


def test_keyword_pile_and_cloze_relation_swap_are_blocked():
    assert looks_like_keyword_pile("代理权、被代理人、追认、效力、相对人、催告、三十日、善意、撤销、通知、条件")
    grade = grade_cloze("六十日内通知，三十日内起诉", "三十日内通知，六十日内起诉")
    assert grade.correct is False
    assert grade.rating == "again"
    assert grade.score <= 45
    assert grade.critical_mismatches


def test_body_edit_invalidates_current_mastery_and_history_keeps_snapshot(client: TestClient):
    _, unit = import_ascii_unit(client)
    approve_unit(client, unit["id"])
    original = client.get(f"/api/units/{unit['id']}").json()
    original_body = original["body"]
    original_hash = original["body_hash"]
    original_basis = original["source_basis_text"]

    session = client.post(f"/api/units/{unit['id']}/sessions", json={"approve_unit": False}).json()["session"]
    attempt = client.post(
        f"/api/sessions/{session['id']}/attempts",
        json={"answer_text": original_body, "confidence": 80, "elapsed_ms": 8_000},
    )
    assert attempt.status_code == 200, attempt.text
    assert attempt.json()["score"] >= 0

    before = client.get(f"/api/sources/{unit['source_id']}/units").json()
    assert next(item for item in before if item["id"] == unit["id"])["mastery_status"] is not None

    new_body = "A materially different rule now governs a different legal question and requires a fresh recall attempt."
    changed = client.patch(f"/api/units/{unit['id']}", json={"body": new_body})
    assert changed.status_code == 200, changed.text
    changed_unit = changed.json()
    assert changed_unit["status"] == "draft"
    assert changed_unit["version"] == original["version"] + 1
    assert changed_unit["body_hash"] != original_hash
    assert changed_unit["source_basis_text"] == original_basis

    after = client.get(f"/api/sources/{unit['source_id']}/units").json()
    current = next(item for item in after if item["id"] == unit["id"])
    assert current["mastery_status"] is None
    today = client.get("/api/today").json()
    assert any(item["id"] == unit["id"] for item in today["suggested"])

    historical = client.get(f"/api/sessions/{session['id']}").json()
    assert historical["body"] == original_body
    assert historical["unit_body_hash"] == original_hash
    assert historical["unit_version_drift"] is True
    assert historical["attempt"]["unit_body_hash"] == original_hash


def test_objective_change_creates_new_evidence_version_but_title_change_does_not(client: TestClient):
    _, unit = import_ascii_unit(client)
    approve_unit(client, unit["id"])
    current = client.get(f"/api/units/{unit['id']}").json()
    base_version = current["version"]

    renamed = client.patch(f"/api/units/{unit['id']}", json={"title": "Renamed display label"})
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["version"] == base_version

    session = client.post(f"/api/units/{unit['id']}/sessions", json={"approve_unit": False}).json()["session"]
    submitted = client.post(
        f"/api/sessions/{session['id']}/attempts",
        json={"answer_text": current["body"], "confidence": 75, "elapsed_ms": 5_000},
    )
    assert submitted.status_code == 200, submitted.text
    listed = client.get(f"/api/sources/{unit['source_id']}/units").json()
    assert next(item for item in listed if item["id"] == unit["id"])["mastery_status"] is not None

    objective = client.patch(f"/api/units/{unit['id']}", json={"objective_type": "表达型"})
    assert objective.status_code == 200, objective.text
    assert objective.json()["version"] == base_version + 1
    assert objective.json()["status"] == "draft"
    listed = client.get(f"/api/sources/{unit['source_id']}/units").json()
    assert next(item for item in listed if item["id"] == unit["id"])["mastery_status"] is None
    today = client.get("/api/today").json()
    assert any(item["id"] == unit["id"] for item in today["suggested"])


def test_active_session_blocks_body_mutation(client: TestClient):
    _, unit = import_ascii_unit(client)
    approve_unit(client, unit["id"])
    started = client.post(f"/api/units/{unit['id']}/sessions", json={"approve_unit": False}).json()["session"]
    blocked = client.patch(
        f"/api/units/{unit['id']}",
        json={"body": "A new body that must not replace material inside an active evidence event."},
    )
    assert blocked.status_code == 409
    active = client.get("/api/sessions/active").json()
    assert active["id"] == started["id"]
    assert active["unit_version_drift"] is False


def test_low_quality_repair_retest_cannot_be_resolved(client: TestClient):
    _, unit = import_ascii_unit(client)
    approve_unit(client, unit["id"])
    first_session = client.post(f"/api/units/{unit['id']}/sessions", json={"approve_unit": False}).json()["session"]
    first = client.post(
        f"/api/sessions/{first_session['id']}/attempts",
        json={"answer_text": "unknown", "confidence": 90, "elapsed_ms": 500},
    )
    assert first.status_code == 200
    error = client.get(f"/api/errors?unit_id={unit['id']}&status=open").json()[0]
    repair = client.post(f"/api/errors/{error['id']}/repair")
    assert repair.status_code == 200, repair.text
    repair_session = repair.json()["session"]
    retest = client.post(
        f"/api/sessions/{repair_session['id']}/attempts",
        json={"answer_text": "still unknown", "confidence": 30, "elapsed_ms": 600},
    )
    assert retest.status_code == 200
    current = next(
        item
        for item in client.get(f"/api/errors?unit_id={unit['id']}&status=repairing").json()
        if item["id"] == error["id"]
    )
    assert current["can_resolve"] is False
    assert "不能关闭" in current["resolution_gate_reason"] or "70 分" in current["resolution_gate_reason"]
    resolved = client.post(f"/api/errors/{error['id']}/resolve")
    assert resolved.status_code == 409


def test_v3_migration_backfills_snapshots_and_invalidates_unprovable_mastery(tmp_path: Path):
    db_path = tmp_path / "legacy-v3.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        PRAGMA foreign_keys=OFF;
        CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO meta(key, value) VALUES('schema_version', '3');
        CREATE TABLE source_documents(
          id TEXT PRIMARY KEY, original_name TEXT NOT NULL, stored_path TEXT NOT NULL,
          content_hash TEXT NOT NULL UNIQUE, file_size INTEGER NOT NULL, status TEXT NOT NULL,
          page_count INTEGER NOT NULL DEFAULT 0, processed_pages INTEGER NOT NULL DEFAULT 0,
          quality_json TEXT NOT NULL DEFAULT '{}', parser_version TEXT NOT NULL,
          error_message TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE source_pages(
          id TEXT PRIMARY KEY, source_id TEXT NOT NULL, page_number INTEGER NOT NULL,
          text TEXT NOT NULL, text_hash TEXT NOT NULL, quality_status TEXT NOT NULL,
          created_at TEXT NOT NULL, UNIQUE(source_id, page_number)
        );
        CREATE TABLE knowledge_units(
          id TEXT PRIMARY KEY, source_id TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL,
          page_start INTEGER NOT NULL, page_end INTEGER NOT NULL, objective_type TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'draft', version INTEGER NOT NULL DEFAULT 1,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE study_sessions(
          id TEXT PRIMARY KEY, knowledge_unit_id TEXT NOT NULL, status TEXT NOT NULL,
          hint_level INTEGER NOT NULL DEFAULT 0, draft_text TEXT NOT NULL DEFAULT '',
          draft_confidence INTEGER NOT NULL DEFAULT 70, draft_updated_at TEXT,
          started_at TEXT NOT NULL, last_activity_at TEXT NOT NULL, completed_at TEXT
        );
        CREATE TABLE attempts(
          id TEXT PRIMARY KEY, session_id TEXT NOT NULL, knowledge_unit_id TEXT NOT NULL,
          answer_text TEXT NOT NULL, confidence INTEGER NOT NULL, elapsed_ms INTEGER NOT NULL,
          hint_level INTEGER NOT NULL, score REAL NOT NULL, evidence_weight REAL NOT NULL,
          feedback_json TEXT NOT NULL, provider TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE review_states(
          knowledge_unit_id TEXT PRIMARY KEY, mastery_status TEXT NOT NULL, due_at TEXT NOT NULL,
          interval_days INTEGER NOT NULL, last_score REAL NOT NULL, last_attempt_id TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        INSERT INTO source_documents VALUES(
          's1','legacy.pdf','/tmp/legacy.pdf','doc-hash',100,'ready',1,1,'{}','pymupdf-1',NULL,
          '2026-01-01T00:00:00+00:00','2026-01-01T00:00:00+00:00'
        );
        INSERT INTO source_pages VALUES('p1','s1',1,'Old source text','page-hash','ok','2026-01-01T00:00:00+00:00');
        INSERT INTO knowledge_units VALUES(
          'u1','s1','Legacy unit','Edited current body',1,1,'综合型','approved',2,
          '2026-01-01T00:00:00+00:00','2026-01-03T00:00:00+00:00'
        );
        INSERT INTO study_sessions VALUES(
          'ss1','u1','completed',0,'',70,NULL,
          '2026-01-01T01:00:00+00:00','2026-01-01T01:10:00+00:00','2026-01-01T01:10:00+00:00'
        );
        INSERT INTO attempts VALUES(
          'a1','ss1','u1','Old answer',80,1000,0,90,1.0,'{}','local_evidence_v1','2026-01-01T01:10:00+00:00'
        );
        INSERT INTO review_states VALUES(
          'u1','基本稳定','2026-01-08T00:00:00+00:00',7,90,'a1','2026-01-01T01:10:00+00:00'
        );
        """
    )
    conn.commit()
    conn.close()

    Database(db_path, schema_version=4).initialize()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    assert conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == "4"
    unit = conn.execute("SELECT * FROM knowledge_units WHERE id='u1'").fetchone()
    assert unit["body_hash"]
    assert unit["source_basis_text"] == "Edited current body"
    version = conn.execute("SELECT * FROM knowledge_unit_versions WHERE knowledge_unit_id='u1'").fetchone()
    assert version is not None
    assert version["snapshot_status"] == "legacy_backfilled_current"
    session = conn.execute("SELECT * FROM study_sessions WHERE id='ss1'").fetchone()
    assert session["snapshot_status"] == "legacy_backfilled_current"
    snapshot = json.loads(session["unit_snapshot_json"])
    assert snapshot["body"] == "Edited current body"
    attempt = conn.execute("SELECT * FROM attempts WHERE id='a1'").fetchone()
    assert attempt["unit_body_hash"] == session["unit_body_hash"]
    # v3 cannot prove that this old mastery belonged to the body edited on Jan 3.
    assert conn.execute("SELECT * FROM review_states WHERE knowledge_unit_id='u1'").fetchone() is None
    conn.close()
