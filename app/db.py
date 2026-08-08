from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator


SCHEMA_SQL = """
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_profile (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    exam_name TEXT NOT NULL DEFAULT '法学考研',
    exam_date TEXT,
    daily_minutes INTEGER NOT NULL DEFAULT 90,
    preferences_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_documents (
    id TEXT PRIMARY KEY,
    original_name TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    content_hash TEXT NOT NULL UNIQUE,
    file_size INTEGER NOT NULL,
    status TEXT NOT NULL,
    page_count INTEGER NOT NULL DEFAULT 0,
    processed_pages INTEGER NOT NULL DEFAULT 0,
    quality_json TEXT NOT NULL DEFAULT '{}',
    parser_version TEXT NOT NULL,
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_pages (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES source_documents(id) ON DELETE CASCADE,
    page_number INTEGER NOT NULL,
    text TEXT NOT NULL,
    text_hash TEXT NOT NULL,
    quality_status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(source_id, page_number)
);

CREATE TABLE IF NOT EXISTS knowledge_units (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES source_documents(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    body_hash TEXT NOT NULL DEFAULT '',
    source_basis_text TEXT NOT NULL DEFAULT '',
    source_basis_hash TEXT NOT NULL DEFAULT '',
    source_basis_status TEXT NOT NULL DEFAULT 'captured',
    page_start INTEGER NOT NULL,
    page_end INTEGER NOT NULL,
    objective_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS knowledge_unit_versions (
    id TEXT PRIMARY KEY,
    knowledge_unit_id TEXT NOT NULL REFERENCES knowledge_units(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    body_hash TEXT NOT NULL,
    source_basis_text TEXT NOT NULL DEFAULT '',
    source_basis_hash TEXT NOT NULL DEFAULT '',
    source_basis_status TEXT NOT NULL DEFAULT 'captured',
    page_start INTEGER NOT NULL,
    page_end INTEGER NOT NULL,
    objective_type TEXT NOT NULL,
    snapshot_status TEXT NOT NULL DEFAULT 'captured',
    created_at TEXT NOT NULL,
    UNIQUE(knowledge_unit_id, version)
);

CREATE TABLE IF NOT EXISTS study_sessions (
    id TEXT PRIMARY KEY,
    knowledge_unit_id TEXT NOT NULL REFERENCES knowledge_units(id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    hint_level INTEGER NOT NULL DEFAULT 0,
    draft_text TEXT NOT NULL DEFAULT '',
    draft_confidence INTEGER NOT NULL DEFAULT 70,
    draft_updated_at TEXT,
    unit_version INTEGER,
    unit_body_hash TEXT NOT NULL DEFAULT '',
    unit_snapshot_json TEXT NOT NULL DEFAULT '{}',
    snapshot_status TEXT NOT NULL DEFAULT 'captured',
    started_at TEXT NOT NULL,
    last_activity_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS attempts (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES study_sessions(id) ON DELETE CASCADE,
    knowledge_unit_id TEXT NOT NULL REFERENCES knowledge_units(id) ON DELETE CASCADE,
    unit_version INTEGER,
    unit_body_hash TEXT NOT NULL DEFAULT '',
    unit_snapshot_status TEXT NOT NULL DEFAULT 'captured',
    answer_text TEXT NOT NULL,
    confidence INTEGER NOT NULL,
    elapsed_ms INTEGER NOT NULL,
    hint_level INTEGER NOT NULL,
    score REAL NOT NULL,
    evidence_weight REAL NOT NULL,
    feedback_json TEXT NOT NULL,
    provider TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS error_records (
    id TEXT PRIMARY KEY,
    attempt_id TEXT NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
    knowledge_unit_id TEXT NOT NULL REFERENCES knowledge_units(id) ON DELETE CASCADE,
    error_type TEXT NOT NULL,
    detail TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL,
    resolved_at TEXT
);

CREATE TABLE IF NOT EXISTS review_states (
    knowledge_unit_id TEXT PRIMARY KEY REFERENCES knowledge_units(id) ON DELETE CASCADE,
    knowledge_unit_version INTEGER,
    unit_body_hash TEXT NOT NULL DEFAULT '',
    mastery_status TEXT NOT NULL,
    due_at TEXT NOT NULL,
    interval_days INTEGER NOT NULL,
    last_score REAL NOT NULL,
    last_attempt_id TEXT NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS retrieval_items (
    id TEXT PRIMARY KEY,
    knowledge_unit_id TEXT NOT NULL REFERENCES knowledge_units(id) ON DELETE CASCADE,
    item_type TEXT NOT NULL CHECK (item_type IN ('flashcard', 'cloze')),
    prompt TEXT NOT NULL,
    answer TEXT NOT NULL,
    cloze_text TEXT,
    source_excerpt TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    generation_method TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(knowledge_unit_id, content_hash)
);

CREATE TABLE IF NOT EXISTS retrieval_attempts (
    id TEXT PRIMARY KEY,
    retrieval_item_id TEXT NOT NULL REFERENCES retrieval_items(id) ON DELETE CASCADE,
    knowledge_unit_id TEXT NOT NULL REFERENCES knowledge_units(id) ON DELETE CASCADE,
    item_version INTEGER NOT NULL DEFAULT 1,
    item_type_snapshot TEXT NOT NULL DEFAULT '',
    prompt_snapshot TEXT NOT NULL DEFAULT '',
    answer_snapshot TEXT NOT NULL DEFAULT '',
    cloze_text_snapshot TEXT,
    source_excerpt_snapshot TEXT NOT NULL DEFAULT '',
    content_hash_snapshot TEXT NOT NULL DEFAULT '',
    snapshot_status TEXT NOT NULL DEFAULT 'captured',
    response_text TEXT NOT NULL DEFAULT '',
    rating TEXT NOT NULL CHECK (rating IN ('again', 'hard', 'good', 'easy')),
    score REAL NOT NULL,
    elapsed_ms INTEGER NOT NULL,
    revealed_answer INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS retrieval_review_states (
    retrieval_item_id TEXT PRIMARY KEY REFERENCES retrieval_items(id) ON DELETE CASCADE,
    mastery_status TEXT NOT NULL,
    due_at TEXT NOT NULL,
    interval_minutes INTEGER NOT NULL DEFAULT 0,
    streak INTEGER NOT NULL DEFAULT 0,
    lapses INTEGER NOT NULL DEFAULT 0,
    last_score REAL NOT NULL DEFAULT 0,
    last_rating TEXT NOT NULL DEFAULT 'new',
    last_attempt_id TEXT REFERENCES retrieval_attempts(id) ON DELETE SET NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS study_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS provider_runs (
    id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    task_type TEXT NOT NULL,
    input_chars INTEGER NOT NULL,
    output_chars INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    error_message TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sources_status ON source_documents(status);
CREATE INDEX IF NOT EXISTS idx_units_source ON knowledge_units(source_id);
CREATE INDEX IF NOT EXISTS idx_unit_versions_unit ON knowledge_unit_versions(knowledge_unit_id, version DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_status ON study_sessions(status);
CREATE INDEX IF NOT EXISTS idx_attempts_unit ON attempts(knowledge_unit_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_errors_unit ON error_records(knowledge_unit_id, status);
CREATE INDEX IF NOT EXISTS idx_reviews_due ON review_states(due_at);
CREATE INDEX IF NOT EXISTS idx_retrieval_items_unit ON retrieval_items(knowledge_unit_id, status, item_type);
CREATE INDEX IF NOT EXISTS idx_retrieval_attempts_item ON retrieval_attempts(retrieval_item_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_retrieval_reviews_due ON retrieval_review_states(due_at);
CREATE INDEX IF NOT EXISTS idx_events_created ON study_events(created_at DESC);
"""


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _text_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _version_id(unit_id: str, version: int) -> str:
    return f"{unit_id}:v{version}"


def _snapshot_payload(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    data = dict(row)
    return {
        "knowledge_unit_id": data["id"],
        "source_id": data["source_id"],
        "version": int(data.get("version") or 1),
        "title": data["title"],
        "body": data["body"],
        "body_hash": data.get("body_hash") or _text_hash(data["body"]),
        "source_basis_text": data.get("source_basis_text") or "",
        "source_basis_hash": data.get("source_basis_hash") or "",
        "source_basis_status": data.get("source_basis_status") or "legacy_backfilled_current",
        "page_start": int(data["page_start"]),
        "page_end": int(data["page_end"]),
        "objective_type": data["objective_type"],
    }


class Database:
    def __init__(self, path: Path, schema_version: int = 4) -> None:
        self.path = path
        self.schema_version = schema_version

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            has_meta = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='meta'").fetchone()
            previous = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone() if has_meta else None
            conn.executescript(SCHEMA_SQL)

            unit_columns = {row[1] for row in conn.execute("PRAGMA table_info(knowledge_units)").fetchall()}
            unit_migrations = {
                "body_hash": "TEXT NOT NULL DEFAULT ''",
                "source_basis_text": "TEXT NOT NULL DEFAULT ''",
                "source_basis_hash": "TEXT NOT NULL DEFAULT ''",
                "source_basis_status": "TEXT NOT NULL DEFAULT 'legacy_backfilled_current'",
            }
            for column, definition in unit_migrations.items():
                if column not in unit_columns:
                    conn.execute(f"ALTER TABLE knowledge_units ADD COLUMN {column} {definition}")

            unit_rows = conn.execute("SELECT * FROM knowledge_units").fetchall()
            for unit in unit_rows:
                body_hash = unit["body_hash"] or _text_hash(unit["body"])
                source_basis_text = unit["source_basis_text"] or unit["body"]
                source_basis_hash = unit["source_basis_hash"] or _text_hash(source_basis_text)
                source_basis_status = unit["source_basis_status"] or "legacy_backfilled_current"
                conn.execute(
                    "UPDATE knowledge_units SET body_hash=?, source_basis_text=?, source_basis_hash=?, source_basis_status=? WHERE id=?",
                    (body_hash, source_basis_text, source_basis_hash, source_basis_status, unit["id"]),
                )
                refreshed = conn.execute("SELECT * FROM knowledge_units WHERE id=?", (unit["id"],)).fetchone()
                snapshot = _snapshot_payload(refreshed)
                conn.execute(
                    "INSERT OR IGNORE INTO knowledge_unit_versions("
                    "id, knowledge_unit_id, version, title, body, body_hash, source_basis_text, source_basis_hash, "
                    "source_basis_status, page_start, page_end, objective_type, snapshot_status, created_at"
                    ") VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        _version_id(unit["id"], int(unit["version"])),
                        unit["id"],
                        int(unit["version"]),
                        snapshot["title"],
                        snapshot["body"],
                        snapshot["body_hash"],
                        snapshot["source_basis_text"],
                        snapshot["source_basis_hash"],
                        snapshot["source_basis_status"],
                        snapshot["page_start"],
                        snapshot["page_end"],
                        snapshot["objective_type"],
                        "legacy_backfilled_current" if previous and previous[0] != str(self.schema_version) else "captured",
                        unit["updated_at"] or unit["created_at"] or utc_now(),
                    ),
                )

            session_columns = {row[1] for row in conn.execute("PRAGMA table_info(study_sessions)").fetchall()}
            session_migrations = {
                "draft_text": "TEXT NOT NULL DEFAULT ''",
                "draft_confidence": "INTEGER NOT NULL DEFAULT 70",
                "draft_updated_at": "TEXT",
                "unit_version": "INTEGER",
                "unit_body_hash": "TEXT NOT NULL DEFAULT ''",
                "unit_snapshot_json": "TEXT NOT NULL DEFAULT '{}'",
                "snapshot_status": "TEXT NOT NULL DEFAULT 'legacy_backfilled_current'",
            }
            for column, definition in session_migrations.items():
                if column not in session_columns:
                    conn.execute(f"ALTER TABLE study_sessions ADD COLUMN {column} {definition}")

            legacy_sessions = conn.execute(
                "SELECT id AS session_id, knowledge_unit_id, unit_snapshot_json FROM study_sessions"
            ).fetchall()
            for row in legacy_sessions:
                if row["unit_snapshot_json"] and row["unit_snapshot_json"] != "{}":
                    continue
                # Historical v3 sessions had no material snapshot. Keep the limitation explicit.
                unit = conn.execute("SELECT * FROM knowledge_units WHERE id=?", (row["knowledge_unit_id"],)).fetchone()
                snapshot = _snapshot_payload(unit)
                snapshot["source_anchor"] = {"page_start": snapshot["page_start"], "page_end": snapshot["page_end"], "page_hashes": []}
                conn.execute(
                    "UPDATE study_sessions SET unit_version=?, unit_body_hash=?, unit_snapshot_json=?, snapshot_status='legacy_backfilled_current' WHERE id=?",
                    (snapshot["version"], snapshot["body_hash"], json.dumps(snapshot, ensure_ascii=False), row["session_id"]),
                )

            attempt_columns = {row[1] for row in conn.execute("PRAGMA table_info(attempts)").fetchall()}
            attempt_migrations = {
                "unit_version": "INTEGER",
                "unit_body_hash": "TEXT NOT NULL DEFAULT ''",
                "unit_snapshot_status": "TEXT NOT NULL DEFAULT 'legacy_backfilled_current'",
            }
            for column, definition in attempt_migrations.items():
                if column not in attempt_columns:
                    conn.execute(f"ALTER TABLE attempts ADD COLUMN {column} {definition}")
            conn.execute(
                "UPDATE attempts SET "
                "unit_version=COALESCE(unit_version, (SELECT unit_version FROM study_sessions WHERE study_sessions.id=attempts.session_id)), "
                "unit_body_hash=CASE WHEN unit_body_hash='' THEN COALESCE((SELECT unit_body_hash FROM study_sessions WHERE study_sessions.id=attempts.session_id), '') ELSE unit_body_hash END, "
                "unit_snapshot_status=CASE WHEN unit_snapshot_status='' OR unit_snapshot_status='captured' THEN COALESCE((SELECT snapshot_status FROM study_sessions WHERE study_sessions.id=attempts.session_id), 'legacy_backfilled_current') ELSE unit_snapshot_status END "
                "WHERE unit_version IS NULL OR unit_body_hash=''"
            )

            review_columns = {row[1] for row in conn.execute("PRAGMA table_info(review_states)").fetchall()}
            review_migrations = {
                "knowledge_unit_version": "INTEGER",
                "unit_body_hash": "TEXT NOT NULL DEFAULT ''",
            }
            for column, definition in review_migrations.items():
                if column not in review_columns:
                    conn.execute(f"ALTER TABLE review_states ADD COLUMN {column} {definition}")

            invalidated_reviews = 0
            reviews = conn.execute(
                "SELECT r.knowledge_unit_id, r.last_attempt_id, a.created_at AS attempt_created_at, "
                "u.version, u.body_hash, u.updated_at FROM review_states r "
                "JOIN knowledge_units u ON u.id=r.knowledge_unit_id "
                "JOIN attempts a ON a.id=r.last_attempt_id"
            ).fetchall()
            for review in reviews:
                # If the unit changed after the evidence was produced, v3 cannot prove that
                # the review state belongs to the current body. Prefer losing a dashboard badge
                # over carrying false mastery into the new material version.
                if review["attempt_created_at"] < review["updated_at"]:
                    conn.execute("DELETE FROM review_states WHERE knowledge_unit_id=?", (review["knowledge_unit_id"],))
                    invalidated_reviews += 1
                    continue
                conn.execute(
                    "UPDATE review_states SET knowledge_unit_version=?, unit_body_hash=? WHERE knowledge_unit_id=?",
                    (review["version"], review["body_hash"], review["knowledge_unit_id"]),
                )

            retrieval_attempt_columns = {
                row[1] for row in conn.execute("PRAGMA table_info(retrieval_attempts)").fetchall()
            }
            retrieval_attempt_migrations = {
                "item_version": "INTEGER NOT NULL DEFAULT 1",
                "item_type_snapshot": "TEXT NOT NULL DEFAULT ''",
                "prompt_snapshot": "TEXT NOT NULL DEFAULT ''",
                "answer_snapshot": "TEXT NOT NULL DEFAULT ''",
                "cloze_text_snapshot": "TEXT",
                "source_excerpt_snapshot": "TEXT NOT NULL DEFAULT ''",
                "content_hash_snapshot": "TEXT NOT NULL DEFAULT ''",
                "snapshot_status": "TEXT NOT NULL DEFAULT 'captured'",
            }
            added_retrieval_snapshot_columns = False
            for column, definition in retrieval_attempt_migrations.items():
                if column not in retrieval_attempt_columns:
                    conn.execute(f"ALTER TABLE retrieval_attempts ADD COLUMN {column} {definition}")
                    added_retrieval_snapshot_columns = True

            if added_retrieval_snapshot_columns:
                conn.execute(
                    "UPDATE retrieval_attempts SET "
                    "item_version=COALESCE((SELECT version FROM retrieval_items WHERE id=retrieval_item_id), 1), "
                    "item_type_snapshot=COALESCE((SELECT item_type FROM retrieval_items WHERE id=retrieval_item_id), ''), "
                    "prompt_snapshot=COALESCE((SELECT prompt FROM retrieval_items WHERE id=retrieval_item_id), ''), "
                    "answer_snapshot=COALESCE((SELECT answer FROM retrieval_items WHERE id=retrieval_item_id), ''), "
                    "cloze_text_snapshot=(SELECT cloze_text FROM retrieval_items WHERE id=retrieval_item_id), "
                    "source_excerpt_snapshot=COALESCE((SELECT source_excerpt FROM retrieval_items WHERE id=retrieval_item_id), ''), "
                    "content_hash_snapshot=COALESCE((SELECT content_hash FROM retrieval_items WHERE id=retrieval_item_id), ''), "
                    "snapshot_status='backfilled_current'"
                )

            conn.execute(
                "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(self.schema_version),),
            )
            conn.execute(
                "INSERT OR IGNORE INTO user_profile(id, updated_at) VALUES(1, ?)",
                (utc_now(),),
            )
            if previous and previous[0] != str(self.schema_version):
                conn.execute(
                    "INSERT INTO study_events(event_type, entity_type, entity_id, payload_json, created_at) "
                    "VALUES('schema_migrated', 'database', 'workbench', ?, ?)",
                    (
                        json.dumps(
                            {
                                "from": previous[0],
                                "to": self.schema_version,
                                "review_states_invalidated": invalidated_reviews,
                                "full_recall_snapshot_note": "legacy sessions were backfilled from the then-current unit and are labeled legacy_backfilled_current",
                            },
                            ensure_ascii=False,
                        ),
                        utc_now(),
                    ),
                )

    def event(
        self,
        event_type: str,
        entity_type: str,
        entity_id: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO study_events(event_type, entity_type, entity_id, payload_json, created_at) "
                "VALUES(?, ?, ?, ?, ?)",
                (event_type, entity_type, entity_id, json.dumps(payload or {}, ensure_ascii=False), utc_now()),
            )


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]
