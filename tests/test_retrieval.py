from __future__ import annotations

import io
from datetime import UTC, datetime

import fitz
from fastapi.testclient import TestClient

from app.services.retrieval import generate_retrieval_items, grade_cloze, retrieval_review_plan


SOURCE_TEXT = (
    "善意取得应当具备下列条件：处分人为无处分权人；受让人在受让该财产时是善意；"
    "以合理价格转让；依法应当登记的已经登记，不需要登记的已经交付。"
    "受让人取得所有权后，原所有权人有权向无处分权人请求损害赔偿。"
)


def make_chinese_pdf() -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_textbox(fitz.Rect(50, 60, 540, 760), SOURCE_TEXT, fontsize=12, fontname="china-s")
    payload = document.tobytes()
    document.close()
    return payload


def import_unit(client: TestClient) -> dict:
    response = client.post(
        "/api/sources/import?wait=true",
        files={"file": ("civil-law-cn.pdf", io.BytesIO(make_chinese_pdf()), "application/pdf")},
    )
    assert response.status_code == 200, response.text
    source = response.json()["source"]
    units = client.get(f"/api/sources/{source['id']}/units").json()
    assert units
    return units[0]


def test_local_generation_and_cloze_grading():
    drafts = generate_retrieval_items(
        title="善意取得的构成要件",
        body=SOURCE_TEXT,
        item_types=["flashcard", "cloze"],
        max_per_type=3,
    )
    assert any(item.item_type == "flashcard" for item in drafts)
    clozes = [item for item in drafts if item.item_type == "cloze"]
    assert clozes
    assert "____" in clozes[0].prompt

    exact = grade_cloze(clozes[0].answer, clozes[0].answer)
    wrong = grade_cloze("完全无关的答案", clozes[0].answer)
    assert exact.score == 100
    assert exact.correct is True
    assert wrong.score < exact.score

    plan = retrieval_review_plan("again", now=datetime(2026, 8, 6, tzinfo=UTC))
    assert plan.interval_minutes == 10
    assert plan.mastery_status == "学习中"


def test_generate_reveal_review_and_persist(client: TestClient):
    unit = import_unit(client)
    generated = client.post(
        f"/api/units/{unit['id']}/retrieval-items/generate",
        json={"item_types": ["flashcard", "cloze"], "max_per_type": 3},
    )
    assert generated.status_code == 200, generated.text
    payload = generated.json()
    assert payload["created"] >= 2
    assert {item["item_type"] for item in payload["items"]} == {"flashcard", "cloze"}

    repeated = client.post(
        f"/api/units/{unit['id']}/retrieval-items/generate",
        json={"item_types": ["flashcard", "cloze"], "max_per_type": 3},
    ).json()
    assert repeated["created"] == 0
    assert repeated["reused"] >= 2

    due = client.get("/api/retrieval-items?due_only=true").json()
    assert due
    assert all("answer" not in item for item in due)

    flashcard = next(item for item in due if item["item_type"] == "flashcard")
    forged_reveal = client.post(
        f"/api/retrieval-items/{flashcard['id']}/attempts",
        json={"rating": "good", "elapsed_ms": 1200, "revealed_answer": True},
    )
    assert forged_reveal.status_code == 422

    blocked = client.post(
        f"/api/retrieval-items/{flashcard['id']}/attempts",
        json={"rating": "good", "elapsed_ms": 1200, "revealed_answer": False},
    )
    assert blocked.status_code == 422

    reveal = client.post(f"/api/retrieval-items/{flashcard['id']}/reveal")
    assert reveal.status_code == 200
    assert reveal.json()["answer"]

    flash_result = client.post(
        f"/api/retrieval-items/{flashcard['id']}/attempts",
        json={"rating": "good", "elapsed_ms": 1200, "revealed_answer": True},
    )
    assert flash_result.status_code == 200, flash_result.text
    assert flash_result.json()["review"]["interval_minutes"] >= 3 * 24 * 60

    repeated_without_new_reveal = client.post(
        f"/api/retrieval-items/{flashcard['id']}/attempts",
        json={"rating": "good", "elapsed_ms": 300, "revealed_answer": True},
    )
    assert repeated_without_new_reveal.status_code == 422

    cloze = next(item for item in due if item["item_type"] == "cloze")
    full_cloze = client.get(f"/api/retrieval-items/{cloze['id']}?include_answer=true").json()
    cloze_result = client.post(
        f"/api/retrieval-items/{cloze['id']}/attempts",
        json={"response_text": full_cloze["answer"], "elapsed_ms": 900},
    )
    assert cloze_result.status_code == 200, cloze_result.text
    assert cloze_result.json()["score"] == 100
    assert cloze_result.json()["correct"] is True

    summary = client.get("/api/retrieval/summary").json()
    assert summary["total"] == len(payload["items"])
    assert summary["attempts"] == 2
    assert summary["reviewed_today"] == 2

    exported = client.get("/api/export")
    assert exported.status_code == 200
    export_payload = exported.json()
    assert "retrieval_items" in export_payload["tables"]
    assert len(export_payload["tables"]["retrieval_attempts"]) == 2


def test_retrieval_state_survives_restart(settings):
    from app.main import create_app

    first = create_app(settings)
    with TestClient(first) as client:
        unit = import_unit(client)
        items = client.post(
            f"/api/units/{unit['id']}/retrieval-items/generate",
            json={"item_types": ["flashcard"], "max_per_type": 2},
        ).json()["items"]
        item = items[0]
        client.post(f"/api/retrieval-items/{item['id']}/reveal")
        result = client.post(
            f"/api/retrieval-items/{item['id']}/attempts",
            json={"rating": "hard", "elapsed_ms": 500, "revealed_answer": True},
        ).json()
        due_at = result["review"]["due_at"]

    second = create_app(settings)
    with TestClient(second) as client:
        restored = client.get(f"/api/retrieval-items/{item['id']}?include_answer=true").json()
        assert restored["last_rating"] == "hard"
        assert restored["due_at"] == due_at
        assert restored["attempt_count"] == 1


def test_schema_v1_database_migrates_without_losing_learning_content(tmp_path):
    import sqlite3

    from app.db import Database

    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        PRAGMA foreign_keys = ON;
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO meta(key, value) VALUES('schema_version', '1');
        CREATE TABLE user_profile (
            id INTEGER PRIMARY KEY CHECK (id = 1), exam_name TEXT NOT NULL DEFAULT '法学考研', exam_date TEXT,
            daily_minutes INTEGER NOT NULL DEFAULT 90, preferences_json TEXT NOT NULL DEFAULT '{}', updated_at TEXT NOT NULL
        );
        INSERT INTO user_profile(id, exam_name, daily_minutes, updated_at) VALUES(1, '法学考研', 120, '2026-08-05T00:00:00+00:00');
        CREATE TABLE source_documents (
            id TEXT PRIMARY KEY, original_name TEXT NOT NULL, stored_path TEXT NOT NULL, content_hash TEXT NOT NULL UNIQUE,
            file_size INTEGER NOT NULL, status TEXT NOT NULL, page_count INTEGER NOT NULL DEFAULT 0,
            processed_pages INTEGER NOT NULL DEFAULT 0, quality_json TEXT NOT NULL DEFAULT '{}', parser_version TEXT NOT NULL,
            error_message TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE knowledge_units (
            id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES source_documents(id) ON DELETE CASCADE,
            title TEXT NOT NULL, body TEXT NOT NULL, page_start INTEGER NOT NULL, page_end INTEGER NOT NULL,
            objective_type TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'draft', version INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE study_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT NOT NULL, entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL, payload_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
        );
        INSERT INTO source_documents(
            id, original_name, stored_path, content_hash, file_size, status, page_count, processed_pages,
            parser_version, created_at, updated_at
        ) VALUES('source-old', '旧教材.pdf', '/local/old.pdf', 'hash-old', 123, 'ready', 1, 1, 'pymupdf-1',
                 '2026-08-05T00:00:00+00:00', '2026-08-05T00:00:00+00:00');
        INSERT INTO knowledge_units(
            id, source_id, title, body, page_start, page_end, objective_type, status, created_at, updated_at
        ) VALUES('unit-old', 'source-old', '旧知识单元', '这是一段应当被保留的旧知识内容。', 1, 1, '精确复现型', 'approved',
                 '2026-08-05T00:00:00+00:00', '2026-08-05T00:00:00+00:00');
        """
    )
    conn.commit()
    conn.close()

    Database(db_path, schema_version=3).initialize()

    conn = sqlite3.connect(db_path)
    assert conn.execute("SELECT title FROM knowledge_units WHERE id='unit-old'").fetchone()[0] == "旧知识单元"
    assert conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == "3"
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"retrieval_items", "retrieval_attempts", "retrieval_review_states"}.issubset(tables)
    retrieval_attempt_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(retrieval_attempts)").fetchall()
    }
    assert {
        "item_version",
        "prompt_snapshot",
        "answer_snapshot",
        "source_excerpt_snapshot",
        "snapshot_status",
    }.issubset(retrieval_attempt_columns)
    migration = conn.execute("SELECT payload_json FROM study_events WHERE event_type='schema_migrated'").fetchone()
    assert migration is not None
    conn.close()


def test_schema_v2_retrieval_attempts_are_preserved_with_explicit_backfill_provenance(tmp_path):
    import sqlite3

    from app.db import Database

    db_path = tmp_path / "schema-v2.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        PRAGMA foreign_keys = ON;
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO meta(key, value) VALUES('schema_version', '2');
        CREATE TABLE source_documents (
            id TEXT PRIMARY KEY, original_name TEXT NOT NULL, stored_path TEXT NOT NULL,
            content_hash TEXT NOT NULL UNIQUE, file_size INTEGER NOT NULL, status TEXT NOT NULL,
            page_count INTEGER NOT NULL DEFAULT 0, processed_pages INTEGER NOT NULL DEFAULT 0,
            quality_json TEXT NOT NULL DEFAULT '{}', parser_version TEXT NOT NULL, error_message TEXT,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE knowledge_units (
            id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES source_documents(id) ON DELETE CASCADE,
            title TEXT NOT NULL, body TEXT NOT NULL, page_start INTEGER NOT NULL, page_end INTEGER NOT NULL,
            objective_type TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'draft', version INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE retrieval_items (
            id TEXT PRIMARY KEY, knowledge_unit_id TEXT NOT NULL REFERENCES knowledge_units(id) ON DELETE CASCADE,
            item_type TEXT NOT NULL, prompt TEXT NOT NULL, answer TEXT NOT NULL, cloze_text TEXT,
            source_excerpt TEXT NOT NULL, content_hash TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active',
            generation_method TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            UNIQUE(knowledge_unit_id, content_hash)
        );
        CREATE TABLE retrieval_attempts (
            id TEXT PRIMARY KEY,
            retrieval_item_id TEXT NOT NULL REFERENCES retrieval_items(id) ON DELETE CASCADE,
            knowledge_unit_id TEXT NOT NULL REFERENCES knowledge_units(id) ON DELETE CASCADE,
            response_text TEXT NOT NULL DEFAULT '', rating TEXT NOT NULL, score REAL NOT NULL,
            elapsed_ms INTEGER NOT NULL, revealed_answer INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
        );
        INSERT INTO source_documents(
            id, original_name, stored_path, content_hash, file_size, status, page_count, processed_pages,
            parser_version, created_at, updated_at
        ) VALUES('source-v2', '教材.pdf', '/local/book.pdf', 'source-hash-v2', 100, 'ready', 1, 1,
                 'pymupdf-1', '2026-08-05T00:00:00+00:00', '2026-08-05T00:00:00+00:00');
        INSERT INTO knowledge_units(
            id, source_id, title, body, page_start, page_end, objective_type, status, version, created_at, updated_at
        ) VALUES('unit-v2', 'source-v2', '善意取得', '善意取得制度用于保护交易安全。', 1, 1,
                 '精确复现型', 'approved', 1, '2026-08-05T00:00:00+00:00', '2026-08-05T00:00:00+00:00');
        INSERT INTO retrieval_items(
            id, knowledge_unit_id, item_type, prompt, answer, source_excerpt, content_hash, status,
            generation_method, version, created_at, updated_at
        ) VALUES('card-v2', 'unit-v2', 'flashcard', '核心价值？', '交易安全。',
                 '善意取得制度用于保护交易安全。', 'card-hash-v2', 'active', 'manual_v1', 2,
                 '2026-08-05T00:00:00+00:00', '2026-08-05T00:00:00+00:00');
        INSERT INTO retrieval_attempts(
            id, retrieval_item_id, knowledge_unit_id, response_text, rating, score, elapsed_ms,
            revealed_answer, created_at
        ) VALUES('attempt-v2', 'card-v2', 'unit-v2', '', 'good', 85, 800, 1,
                 '2026-08-05T00:05:00+00:00');
        """
    )
    conn.commit()
    conn.close()

    Database(db_path, schema_version=3).initialize()

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    attempt = conn.execute("SELECT * FROM retrieval_attempts WHERE id='attempt-v2'").fetchone()
    schema_version = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
    conn.close()

    assert schema_version == "3"
    assert attempt["item_version"] == 2
    assert attempt["prompt_snapshot"] == "核心价值？"
    assert attempt["answer_snapshot"] == "交易安全。"
    assert attempt["content_hash_snapshot"] == "card-hash-v2"
    assert attempt["snapshot_status"] == "backfilled_current"


def test_updating_unit_content_marks_generated_cards_stale(client: TestClient):
    unit = import_unit(client)
    generated = client.post(
        f"/api/units/{unit['id']}/retrieval-items/generate",
        json={"item_types": ["flashcard", "cloze"], "max_per_type": 2},
    ).json()
    assert generated["created"] >= 2

    updated = client.patch(
        f"/api/units/{unit['id']}",
        json={"body": unit["body"] + " 新增规则：善意判断应当结合受让时点。"},
    )
    assert updated.status_code == 200

    summary = client.get("/api/retrieval/summary").json()
    assert summary["total"] == 0
    all_unit_items = client.get(f"/api/units/{unit['id']}/retrieval-items?include_answer=true").json()
    assert all(item["status"] == "stale" for item in all_unit_items)

    regenerated = client.post(
        f"/api/units/{unit['id']}/retrieval-items/generate",
        json={"item_types": ["flashcard", "cloze"], "max_per_type": 2},
    )
    assert regenerated.status_code == 200, regenerated.text
    regeneration = regenerated.json()
    assert regeneration["reactivated"] >= 1
    assert all(item["status"] == "active" for item in regeneration["items"])
    assert client.get("/api/retrieval/summary").json()["total"] == len(regeneration["items"])


def test_manual_card_edit_and_archive_lifecycle(client: TestClient):
    unit = import_unit(client)
    invalid_cloze = client.post(
        f"/api/units/{unit['id']}/retrieval-items",
        json={
            "item_type": "cloze",
            "prompt": "没有空位的挖空题",
            "answer": "善意",
            "cloze_text": "受让人应当为善意。",
        },
    )
    assert invalid_cloze.status_code == 422

    created = client.post(
        f"/api/units/{unit['id']}/retrieval-items",
        json={
            "item_type": "flashcard",
            "prompt": "善意取得保护的核心价值是什么？",
            "answer": "交易安全。",
            "source_excerpt": "善意取得制度用于保护交易安全。",
        },
    )
    assert created.status_code == 200, created.text
    item = created.json()
    assert item["generation_method"] == "manual_v1"
    assert item["mastery_status"] == "新卡"

    duplicate = client.post(
        f"/api/units/{unit['id']}/retrieval-items",
        json={
            "item_type": "flashcard",
            "prompt": "善意取得保护的核心价值是什么？",
            "answer": "交易安全。",
            "source_excerpt": "善意取得制度用于保护交易安全。",
        },
    )
    assert duplicate.status_code == 409

    edited = client.patch(
        f"/api/retrieval-items/{item['id']}",
        json={"answer": "保护交易安全。"},
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["answer"] == "保护交易安全。"
    assert edited.json()["mastery_status"] == "新卡"

    archived = client.patch(
        f"/api/retrieval-items/{item['id']}",
        json={"status": "archived"},
    )
    assert archived.status_code == 200, archived.text
    assert archived.json()["status"] == "archived"
    assert client.get("/api/retrieval/summary").json()["total"] == 0


def test_attempt_snapshot_survives_later_card_edit(client: TestClient, settings):
    import sqlite3

    unit = import_unit(client)
    created = client.post(
        f"/api/units/{unit['id']}/retrieval-items",
        json={
            "item_type": "flashcard",
            "prompt": "善意取得保护的核心价值是什么？",
            "answer": "交易安全。",
            "source_excerpt": "善意取得制度用于保护交易安全。",
        },
    ).json()

    client.post(f"/api/retrieval-items/{created['id']}/reveal")
    submitted = client.post(
        f"/api/retrieval-items/{created['id']}/attempts",
        json={"rating": "good", "elapsed_ms": 1000, "revealed_answer": True},
    )
    assert submitted.status_code == 200, submitted.text

    edited = client.patch(
        f"/api/retrieval-items/{created['id']}",
        json={"answer": "保护动态交易安全。"},
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["version"] == created["version"] + 1

    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    attempt = conn.execute(
        "SELECT item_version, prompt_snapshot, answer_snapshot, source_excerpt_snapshot, snapshot_status "
        "FROM retrieval_attempts WHERE retrieval_item_id=?",
        (created["id"],),
    ).fetchone()
    conn.close()

    assert attempt["item_version"] == created["version"]
    assert attempt["prompt_snapshot"] == created["prompt"]
    assert attempt["answer_snapshot"] == "交易安全。"
    assert attempt["source_excerpt_snapshot"] == "善意取得制度用于保护交易安全。"
    assert attempt["snapshot_status"] == "captured"


def test_archived_generated_card_is_not_silently_reactivated(client: TestClient):
    unit = import_unit(client)
    first = client.post(
        f"/api/units/{unit['id']}/retrieval-items/generate",
        json={"item_types": ["flashcard"], "max_per_type": 1},
    )
    assert first.status_code == 200, first.text
    item = first.json()["items"][0]
    archived = client.patch(f"/api/retrieval-items/{item['id']}", json={"status": "archived"})
    assert archived.status_code == 200, archived.text

    regenerated = client.post(
        f"/api/units/{unit['id']}/retrieval-items/generate",
        json={"item_types": ["flashcard"], "max_per_type": 1},
    )
    assert regenerated.status_code == 200, regenerated.text
    payload = regenerated.json()
    assert payload["created"] == 0
    assert payload["reactivated"] == 0
    assert payload["skipped_archived"] == 1
    assert payload["items"] == []
    assert client.get("/api/retrieval/summary").json()["total"] == 0
