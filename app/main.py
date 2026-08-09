from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import sqlite3
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import Settings
from app.db import Database, row_to_dict, rows_to_dicts, utc_now
from app.schemas import (
    AttemptCreate,
    DraftUpdate,
    HintRequest,
    RetrievalAttemptCreate,
    RetrievalGenerateRequest,
    RetrievalItemCreate,
    RetrievalItemUpdate,
    PortableStudyEventsImport,
    StartSessionRequest,
    UnitMergeRequest,
    UnitSplitRequest,
    UnitUpdate,
    UserProfileUpdate,
)
from app.services.importer import process_source
from app.services.evidence_integrity import (
    capture_session_snapshot,
    derive_evidence_verdict,
    insert_unit_version,
    locate_page_range,
    parse_snapshot,
    text_hash,
)
from app.services.method_packs import (
    degraded_method_pack_snapshot,
    evaluate_method_pack,
    select_method_pack,
)
from app.services.scheduler import due_at_after, review_plan
from app.services.retrieval import (
    generate_retrieval_items,
    grade_cloze,
    retrieval_content_hash,
    retrieval_review_plan,
    score_for_rating,
)
from app.services.study_protocol import (
    STUDY_EVENTS_PROTOCOL,
    STUDY_PACK_PROTOCOL,
    build_study_pack,
    validate_event_time,
)
from app.services.scorer import (
    LocalEvidenceScorer,
    ScoreRequest,
    evidence_weight,
    new_provider_run_id,
    provider_from_settings,
)


def _json_field(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def _session_material(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    data = dict(row)
    snapshot = parse_snapshot(data.get("unit_snapshot_json"))
    if snapshot:
        return snapshot
    # Legacy safety fallback. New v0.7 sessions always capture an exact snapshot.
    return {
        "knowledge_unit_id": data.get("knowledge_unit_id") or data.get("unit_id"),
        "version": int(data.get("unit_version") or data.get("current_unit_version") or 1),
        "title": data.get("title") or data.get("current_title") or "",
        "body": data.get("body") or data.get("current_body") or "",
        "body_hash": data.get("unit_body_hash") or text_hash(data.get("body") or data.get("current_body") or ""),
        "page_start": int(data.get("page_start") or data.get("current_page_start") or 1),
        "page_end": int(data.get("page_end") or data.get("current_page_end") or 1),
        "objective_type": data.get("objective_type") or data.get("current_objective_type") or "综合型",
        "source_basis_text": data.get("source_basis_text") or "",
        "source_basis_hash": data.get("source_basis_hash") or "",
        "source_basis_status": data.get("source_basis_status") or "unknown",
        "source_anchor": {},
    }




def _learning_target_flags(material: dict[str, Any]) -> dict[str, Any]:
    body_hash = material.get("body_hash") or text_hash(material.get("body") or "")
    source_hash = material.get("source_basis_hash") or ""
    source_status = material.get("source_basis_status") or "unknown"
    if source_hash and source_hash == body_hash:
        provenance = "source_exact"
        source_exact = True
    elif source_hash:
        provenance = "edited_learning_text"
        source_exact = False
    elif source_status == "legacy_backfilled_current":
        provenance = "legacy_unverified"
        source_exact = False
    else:
        provenance = "source_basis_pending"
        source_exact = False
    return {
        "learning_target_bounded": True,
        "learning_target_provenance": provenance,
        "source_exact": source_exact,
        "source_bounded": source_exact,
        "source_basis_status": source_status,
    }


def _annotate_method_pack_target(method_pack: dict[str, Any], material: dict[str, Any]) -> dict[str, Any]:
    annotated = {**method_pack}
    annotated["generated_flags"] = {
        **(method_pack.get("generated_flags") or {}),
        **_learning_target_flags(material),
    }
    return annotated

def _record_current_unit_version(conn: sqlite3.Connection, unit_id: str, *, created_at: str, snapshot_status: str = "captured") -> None:
    unit = conn.execute("SELECT * FROM knowledge_units WHERE id=?", (unit_id,)).fetchone()
    if unit is not None:
        insert_unit_version(conn, unit, snapshot_status=snapshot_status, created_at=created_at)


def _hydrate_source(row: dict[str, Any]) -> dict[str, Any]:
    row["quality"] = _json_field(row.pop("quality_json", "{}"), {})
    row["progress"] = (
        round((row["processed_pages"] / row["page_count"]) * 100)
        if row["page_count"]
        else (100 if row["status"] == "ready" else 0)
    )
    return row


def _hydrate_attempt(row: dict[str, Any]) -> dict[str, Any]:
    row["feedback"] = _json_field(row.pop("feedback_json", "{}"), {})
    return row


def _method_pack_selection(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    objective_type: str | None,
) -> tuple[dict[str, Any], bool]:
    event = conn.execute(
        "SELECT payload_json FROM study_events "
        "WHERE event_type='method_pack_selected' AND entity_type='study_session' AND entity_id=? "
        "ORDER BY id DESC LIMIT 1",
        (session_id,),
    ).fetchone()
    if event is not None:
        payload = _json_field(event["payload_json"], {})
        stored = payload.get("method_pack", payload) if isinstance(payload, dict) else {}
        if isinstance(stored, dict) and stored.get("id") and stored.get("version"):
            return stored, True
    return select_method_pack(objective_type), False


def _hydrate_session(conn: sqlite3.Connection, row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    material = _session_material(result)
    result["unit_snapshot"] = material
    result["unit_version"] = material.get("version")
    result["unit_body_hash"] = material.get("body_hash", "")
    result["title"] = material.get("title", result.get("title", ""))
    result["body"] = material.get("body", result.get("body", ""))
    result["page_start"] = material.get("page_start", result.get("page_start"))
    result["page_end"] = material.get("page_end", result.get("page_end"))
    result["objective_type"] = material.get("objective_type", result.get("objective_type", "综合型"))
    current_hash = result.get("current_unit_body_hash") or result.get("current_body_hash") or ""
    current_version = result.get("current_unit_version")
    result["unit_version_drift"] = bool(
        (current_hash and current_hash != material.get("body_hash"))
        or (current_version is not None and int(current_version) != int(material.get("version") or current_version))
    )
    selection, _ = _method_pack_selection(
        conn,
        session_id=result["id"],
        objective_type=result.get("objective_type"),
    )
    result["method_pack"] = _annotate_method_pack_target(selection, material)
    return result


def _hydrate_retrieval_item(row: dict[str, Any], *, include_answer: bool = False) -> dict[str, Any]:
    row["revealed"] = include_answer
    row["is_new"] = not row.get("last_attempt_id")
    if not include_answer:
        row.pop("answer", None)
        row.pop("source_excerpt", None)
    return row


def _has_fresh_retrieval_reveal(
    conn: sqlite3.Connection,
    *,
    item_id: str,
    item_updated_at: str,
) -> bool:
    latest_reveal = conn.execute(
        "SELECT created_at FROM study_events "
        "WHERE event_type='retrieval_answer_revealed' AND entity_type='retrieval_item' AND entity_id=? "
        "ORDER BY id DESC LIMIT 1",
        (item_id,),
    ).fetchone()
    if latest_reveal is None:
        return False
    latest_attempt = conn.execute(
        "SELECT created_at FROM retrieval_attempts WHERE retrieval_item_id=? ORDER BY created_at DESC LIMIT 1",
        (item_id,),
    ).fetchone()
    cutoff = item_updated_at
    if latest_attempt is not None and latest_attempt["created_at"] > cutoff:
        cutoff = latest_attempt["created_at"]
    return latest_reveal["created_at"] > cutoff


RETRIEVAL_SELECT = (
    "SELECT ri.*, u.title AS unit_title, u.page_start, u.page_end, u.source_id, u.status AS unit_status, "
    "s.original_name, rr.mastery_status, rr.due_at, rr.interval_minutes, rr.streak, rr.lapses, "
    "rr.last_score, rr.last_rating, rr.last_attempt_id, "
    "(SELECT COUNT(*) FROM retrieval_attempts ra WHERE ra.retrieval_item_id=ri.id) AS attempt_count "
    "FROM retrieval_items ri JOIN knowledge_units u ON u.id=ri.knowledge_unit_id "
    "JOIN source_documents s ON s.id=u.source_id "
    "LEFT JOIN retrieval_review_states rr ON rr.retrieval_item_id=ri.id "
)


def _persist_retrieval_attempt(
    conn: sqlite3.Connection,
    *,
    row: sqlite3.Row | dict[str, Any],
    attempt_id: str,
    response_text: str,
    rating: str,
    score: float,
    elapsed_ms: int,
    revealed_answer: bool,
    created_at: str,
    plan_now: datetime,
    snapshot_status: str,
):
    plan = retrieval_review_plan(
        rating,
        prior_interval_minutes=int(row["interval_minutes"] or 0),
        prior_streak=int(row["streak"] or 0),
        prior_lapses=int(row["lapses"] or 0),
        now=plan_now,
    )
    conn.execute(
        "INSERT INTO retrieval_attempts(id, retrieval_item_id, knowledge_unit_id, item_version, "
        "item_type_snapshot, prompt_snapshot, answer_snapshot, cloze_text_snapshot, source_excerpt_snapshot, "
        "content_hash_snapshot, snapshot_status, response_text, rating, score, elapsed_ms, revealed_answer, created_at) "
        "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            attempt_id,
            row["id"],
            row["knowledge_unit_id"],
            row["version"],
            row["item_type"],
            row["prompt"],
            row["answer"],
            row["cloze_text"],
            row["source_excerpt"],
            row["content_hash"],
            snapshot_status,
            response_text,
            rating,
            score,
            elapsed_ms,
            1 if revealed_answer else 0,
            created_at,
        ),
    )
    conn.execute(
        "INSERT INTO retrieval_review_states(retrieval_item_id, mastery_status, due_at, interval_minutes, streak, "
        "lapses, last_score, last_rating, last_attempt_id, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(retrieval_item_id) DO UPDATE SET mastery_status=excluded.mastery_status, due_at=excluded.due_at, "
        "interval_minutes=excluded.interval_minutes, streak=excluded.streak, lapses=excluded.lapses, "
        "last_score=excluded.last_score, last_rating=excluded.last_rating, last_attempt_id=excluded.last_attempt_id, "
        "updated_at=excluded.updated_at",
        (
            row["id"],
            plan.mastery_status,
            plan.due_at,
            plan.interval_minutes,
            plan.streak,
            plan.lapses,
            score,
            rating,
            attempt_id,
            utc_now(),
        ),
    )
    return plan


def _mark_retrieval_stale(conn: sqlite3.Connection, unit_ids: list[str], now: str) -> int:
    if not unit_ids:
        return 0
    placeholders = ",".join("?" for _ in unit_ids)
    cursor = conn.execute(
        f"UPDATE retrieval_items SET status='stale', updated_at=? "
        f"WHERE knowledge_unit_id IN ({placeholders}) AND status='active'",
        (now, *unit_ids),
    )
    return cursor.rowcount


def _assert_units_not_in_active_session(conn: sqlite3.Connection, unit_ids: list[str]) -> None:
    if not unit_ids:
        return
    placeholders = ",".join("?" for _ in unit_ids)
    row = conn.execute(
        f"SELECT ss.id, u.title FROM study_sessions ss JOIN knowledge_units u ON u.id=ss.knowledge_unit_id "
        f"WHERE ss.status='active' AND ss.knowledge_unit_id IN ({placeholders}) LIMIT 1",
        tuple(unit_ids),
    ).fetchone()
    if row is not None:
        raise HTTPException(status_code=409, detail=f"知识单元“{row['title']}”存在未完成闭卷，请先结束本轮再调整结构")


def _hydrate_error_record(conn: sqlite3.Connection, row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    repair_event = conn.execute(
        "SELECT id, created_at, payload_json FROM study_events "
        "WHERE event_type='error_repair_started' AND entity_type='error_record' AND entity_id=? "
        "ORDER BY id DESC LIMIT 1",
        (result["id"],),
    ).fetchone()
    result["repair_started_at"] = repair_event["created_at"] if repair_event else None
    result["repair_session_id"] = None
    if repair_event:
        payload = _json_field(repair_event["payload_json"], {})
        result["repair_session_id"] = payload.get("session_id") if isinstance(payload, dict) else None
    retest = None
    if repair_event is not None and result["repair_session_id"]:
        retest = conn.execute(
            "SELECT id, score, evidence_weight, hint_level, feedback_json, unit_body_hash, created_at FROM attempts "
            "WHERE session_id=? AND knowledge_unit_id=? AND created_at>? AND hint_level=0 ORDER BY created_at DESC LIMIT 1",
            (result["repair_session_id"], result["knowledge_unit_id"], repair_event["created_at"]),
        ).fetchone()
    verdict_status = None
    retest_acceptable = False
    gate_reason = "请先启动修复并完成新的无提示闭卷。"
    if retest:
        feedback = _json_field(retest["feedback_json"], {})
        verdict = feedback.get("evidence_verdict") if isinstance(feedback, dict) else {}
        verdict_status = verdict.get("status") if isinstance(verdict, dict) else None
        retest_acceptable = (
            float(retest["score"]) >= 70
            and float(retest["evidence_weight"]) >= 0.99
            and verdict_status == "accepted"
        )
        if retest_acceptable:
            gate_reason = "新的无提示闭卷达到当前证据门槛，等待人工确认是否真正修复。"
        elif verdict_status in {"blocked_critical", "blocked_structure", "needs_verification"}:
            gate_reason = "新的复测仍存在关键冲突、结构阻断或待核验项，不能关闭错因。"
        else:
            gate_reason = "新的无提示复测尚未达到 70 分有效证据门槛，继续保持修复中。"
    result["can_resolve"] = result.get("status") == "repairing" and retest_acceptable
    result["resolution_gate_reason"] = gate_reason
    result["retest_attempt_id"] = retest["id"] if retest else None
    result["retest_score"] = float(retest["score"]) if retest else None
    result["retest_evidence_weight"] = float(retest["evidence_weight"]) if retest else None
    result["retest_verdict_status"] = verdict_status
    result["retest_created_at"] = retest["created_at"] if retest else None
    return result


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    settings.ensure_directories()
    db = Database(settings.db_path, settings.schema_version)
    db.initialize()

    async def resume_pending() -> None:
        with db.connect() as conn:
            pending = conn.execute(
                "SELECT id, stored_path FROM source_documents WHERE status IN ('queued', 'parsing')"
            ).fetchall()
        for row in pending:
            asyncio.create_task(asyncio.to_thread(process_source, db, row["id"], Path(row["stored_path"])))

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await resume_pending()
        yield

    app = FastAPI(title="法学语义学习工作台", version="0.8.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.db = db

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "version": "0.8.0",
            "storage": "local",
            "ai_provider": settings.ai_provider,
        }

    @app.get("/api/app-info")
    def app_info() -> dict[str, Any]:
        with db.connect() as conn:
            profile = row_to_dict(conn.execute("SELECT * FROM user_profile WHERE id=1").fetchone())
            source_count = conn.execute("SELECT COUNT(*) AS count FROM source_documents").fetchone()["count"]
            unit_count = conn.execute("SELECT COUNT(*) AS count FROM knowledge_units WHERE status!='archived'").fetchone()["count"]
            retrieval_item_count = conn.execute(
                "SELECT COUNT(*) AS count FROM retrieval_items WHERE status='active'"
            ).fetchone()["count"]
        if profile:
            profile["preferences"] = _json_field(profile.pop("preferences_json", "{}"), {})
        return {
            "product": "法学语义学习工作台",
            "version": "0.8.0",
            "profile": profile,
            "source_count": source_count,
            "unit_count": unit_count,
            "retrieval_item_count": retrieval_item_count,
            "provider": {
                "mode": settings.ai_provider,
                "configured": settings.ai_provider == "local"
                or bool(settings.ai_base_url and settings.ai_api_key and settings.ai_model),
                "sends_to_cloud": settings.ai_provider != "local",
            },
        }

    @app.put("/api/profile")
    def update_profile(payload: UserProfileUpdate) -> dict[str, Any]:
        now = utc_now()
        with db.connect() as conn:
            conn.execute(
                "UPDATE user_profile SET exam_name=?, exam_date=?, daily_minutes=?, updated_at=? WHERE id=1",
                (payload.exam_name, payload.exam_date, payload.daily_minutes, now),
            )
            profile = dict(conn.execute("SELECT * FROM user_profile WHERE id=1").fetchone())
        db.event("profile_updated", "user_profile", "1", payload.model_dump())
        profile["preferences"] = _json_field(profile.pop("preferences_json", "{}"), {})
        return profile

    @app.post("/api/sources/import")
    async def import_source(
        background_tasks: BackgroundTasks,
        file: UploadFile = File(...),
        wait: bool = Query(default=False),
    ) -> dict[str, Any]:
        filename = file.filename or "教材.pdf"
        if not filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=415, detail="当前原型只支持 PDF 教材")
        temp_path = settings.library_dir / f".upload-{uuid4()}.tmp"
        digest = hashlib.sha256()
        size = 0
        first_bytes = b""
        try:
            with temp_path.open("wb") as target:
                while chunk := await file.read(1024 * 1024):
                    if not first_bytes:
                        first_bytes = chunk[:8]
                    size += len(chunk)
                    if size > settings.max_upload_bytes:
                        raise HTTPException(status_code=413, detail="文件超过本地导入大小上限")
                    digest.update(chunk)
                    target.write(chunk)
        finally:
            await file.close()
        if not first_bytes.startswith(b"%PDF-"):
            temp_path.unlink(missing_ok=True)
            raise HTTPException(status_code=415, detail="文件扩展名为 PDF，但内容不是有效 PDF")
        content_hash = digest.hexdigest()
        with db.connect() as conn:
            existing = conn.execute(
                "SELECT * FROM source_documents WHERE content_hash=?", (content_hash,)
            ).fetchone()
        if existing:
            temp_path.unlink(missing_ok=True)
            return {"deduplicated": True, "source": _hydrate_source(dict(existing))}

        source_id = str(uuid4())
        stored_path = settings.library_dir / f"{source_id}.pdf"
        temp_path.replace(stored_path)
        now = utc_now()
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO source_documents(id, original_name, stored_path, content_hash, file_size, status, parser_version, created_at, updated_at) "
                "VALUES(?, ?, ?, ?, ?, 'queued', ?, ?, ?)",
                (source_id, filename, str(stored_path), content_hash, size, settings.parser_version, now, now),
            )
        db.event("source_imported", "source_document", source_id, {"filename": filename, "size": size})
        if wait:
            await asyncio.to_thread(process_source, db, source_id, stored_path)
        else:
            background_tasks.add_task(process_source, db, source_id, stored_path)
        with db.connect() as conn:
            source = dict(conn.execute("SELECT * FROM source_documents WHERE id=?", (source_id,)).fetchone())
        return {"deduplicated": False, "source": _hydrate_source(source)}

    @app.get("/api/sources")
    def list_sources() -> list[dict[str, Any]]:
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT s.*, (SELECT COUNT(*) FROM knowledge_units u WHERE u.source_id=s.id AND u.status!='archived') AS unit_count "
                "FROM source_documents s ORDER BY s.created_at DESC"
            ).fetchall()
        return [_hydrate_source(dict(row)) for row in rows]

    @app.get("/api/sources/{source_id}")
    def get_source(source_id: str) -> dict[str, Any]:
        with db.connect() as conn:
            row = conn.execute("SELECT * FROM source_documents WHERE id=?", (source_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="教材不存在")
        return _hydrate_source(dict(row))

    @app.get("/api/sources/{source_id}/units")
    def list_units(source_id: str, include_archived: bool = Query(default=False)) -> list[dict[str, Any]]:
        with db.connect() as conn:
            source = conn.execute("SELECT id FROM source_documents WHERE id=?", (source_id,)).fetchone()
            if source is None:
                raise HTTPException(status_code=404, detail="教材不存在")
            archived_clause = "" if include_archived else " AND u.status!='archived'"
            rows = conn.execute(
                "SELECT u.*, r.mastery_status, r.due_at, r.last_score, "
                "(SELECT COUNT(*) FROM retrieval_items ri WHERE ri.knowledge_unit_id=u.id AND ri.status='active') AS retrieval_count, "
                "(SELECT COUNT(*) FROM retrieval_items ri WHERE ri.knowledge_unit_id=u.id AND ri.status='active' AND ri.item_type='flashcard') AS flashcard_count, "
                "(SELECT COUNT(*) FROM retrieval_items ri WHERE ri.knowledge_unit_id=u.id AND ri.status='active' AND ri.item_type='cloze') AS cloze_count "
                "FROM knowledge_units u LEFT JOIN review_states r ON r.knowledge_unit_id=u.id AND r.unit_body_hash=u.body_hash AND r.knowledge_unit_version=u.version "
                "WHERE u.source_id=?" + archived_clause + " ORDER BY u.page_start, u.created_at",
                (source_id,),
            ).fetchall()
        return rows_to_dicts(rows)

    @app.get("/api/units/{unit_id}")
    def get_unit(unit_id: str) -> dict[str, Any]:
        with db.connect() as conn:
            row = conn.execute(
                "SELECT u.*, s.original_name FROM knowledge_units u "
                "JOIN source_documents s ON s.id=u.source_id WHERE u.id=?",
                (unit_id,),
            ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="知识单元不存在")
        return dict(row)

    @app.patch("/api/units/{unit_id}")
    def update_unit(unit_id: str, payload: UnitUpdate) -> dict[str, Any]:
        requested = payload.model_dump(exclude_none=True)
        if not requested:
            return get_unit(unit_id)
        allowed = {"title", "body", "status", "objective_type"}
        now = utc_now()
        stale_count = 0
        review_invalidated = False
        errors_superseded = 0
        with db.connect() as conn:
            existing = conn.execute("SELECT * FROM knowledge_units WHERE id=?", (unit_id,)).fetchone()
            if existing is None:
                raise HTTPException(status_code=404, detail="知识单元不存在")
            if existing["status"] == "archived":
                raise HTTPException(status_code=409, detail="归档知识单元只保留历史证据，不能继续编辑")
            changes = {
                key: value
                for key, value in requested.items()
                if key in allowed and existing[key] != value
            }
            if not changes:
                return dict(existing)
            body_changed = "body" in changes
            evidence_version_changed = any(field in changes for field in {"body", "objective_type"})
            if evidence_version_changed:
                _assert_units_not_in_active_session(conn, [unit_id])
                # Body or learning-objective changes create a new evidence contract.
                # They must be re-reviewed before the next full-recall attempt can claim current mastery.
                changes["status"] = "draft"
            if body_changed:
                changes["body_hash"] = text_hash(changes["body"])
            if changes.get("status") == "archived":
                _assert_units_not_in_active_session(conn, [unit_id])

            fields = list(changes)
            values = [changes[key] for key in fields]
            sql = ", ".join(f"{field}=?" for field in fields)
            version_sql = ", version=version+1" if evidence_version_changed else ""
            conn.execute(
                f"UPDATE knowledge_units SET {sql}{version_sql}, updated_at=? WHERE id=?",
                (*values, now, unit_id),
            )
            if body_changed or changes.get("status") == "archived":
                stale_count = _mark_retrieval_stale(conn, [unit_id], now)
            if evidence_version_changed:
                review_invalidated = conn.execute(
                    "DELETE FROM review_states WHERE knowledge_unit_id=?",
                    (unit_id,),
                ).rowcount > 0
                errors_superseded = conn.execute(
                    "UPDATE error_records SET status='superseded', resolved_at=? "
                    "WHERE knowledge_unit_id=? AND status IN ('open', 'repairing')",
                    (now, unit_id),
                ).rowcount
                _record_current_unit_version(conn, unit_id, created_at=now)

        db.event(
            "knowledge_unit_updated",
            "knowledge_unit",
            unit_id,
            {
                **changes,
                "retrieval_items_marked_stale": stale_count,
                "review_state_invalidated": review_invalidated,
                "errors_superseded": errors_superseded,
                "evidence_version_changed": evidence_version_changed,
            },
        )
        return get_unit(unit_id)

    @app.post("/api/units/{unit_id}/split")
    def split_unit(unit_id: str, payload: UnitSplitRequest) -> dict[str, Any]:
        now = utc_now()
        with db.connect() as conn:
            existing = conn.execute("SELECT * FROM knowledge_units WHERE id=?", (unit_id,)).fetchone()
            if existing is None:
                raise HTTPException(status_code=404, detail="知识单元不存在")
            if existing["status"] == "archived":
                raise HTTPException(status_code=409, detail="归档知识单元不能再次拆分")
            _assert_units_not_in_active_session(conn, [unit_id])
            body = payload.body if payload.body is not None else existing["body"]
            if payload.split_at <= 0 or payload.split_at >= len(body):
                raise HTTPException(status_code=422, detail="拆分位置必须位于知识单元正文内部")
            left_body = body[: payload.split_at].strip()
            right_body = body[payload.split_at :].strip()
            if len(left_body) < 20 or len(right_body) < 20:
                raise HTTPException(status_code=422, detail="拆分后每个知识单元至少保留 20 个字符")
            left_id, right_id = str(uuid4()), str(uuid4())
            left_title = payload.left_title or f"{existing['title']}（上）"
            right_title = payload.right_title or f"{existing['title']}（下）"
            left_type = payload.left_objective_type or existing["objective_type"]
            right_type = payload.right_objective_type or existing["objective_type"]
            stale_count = _mark_retrieval_stale(conn, [unit_id], now)
            conn.execute(
                "UPDATE knowledge_units SET status='archived', updated_at=? WHERE id=?",
                (now, unit_id),
            )

            source_aligned = body == existing["source_basis_text"] and bool(existing["source_basis_text"])
            children = []
            right_created_at = (datetime.fromisoformat(now) + timedelta(microseconds=1)).isoformat()
            specs = (
                (left_id, left_title, left_body, left_type, now),
                (right_id, right_title, right_body, right_type, right_created_at),
            )
            for new_id, title, new_body, objective_type, created_at in specs:
                if source_aligned:
                    page_start, page_end, anchor_status = locate_page_range(
                        conn,
                        source_id=existing["source_id"],
                        text=new_body,
                        fallback_start=existing["page_start"],
                        fallback_end=existing["page_end"],
                    )
                    source_basis_text = new_body
                    source_basis_hash = text_hash(new_body)
                    source_basis_status = anchor_status
                else:
                    page_start, page_end = existing["page_start"], existing["page_end"]
                    source_basis_text = ""
                    source_basis_hash = ""
                    source_basis_status = "source_anchor_pending"
                conn.execute(
                    "INSERT INTO knowledge_units(id, source_id, title, body, body_hash, source_basis_text, source_basis_hash, source_basis_status, "
                    "page_start, page_end, objective_type, status, version, created_at, updated_at) "
                    "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', 1, ?, ?)",
                    (
                        new_id,
                        existing["source_id"],
                        title,
                        new_body,
                        text_hash(new_body),
                        source_basis_text,
                        source_basis_hash,
                        source_basis_status,
                        page_start,
                        page_end,
                        objective_type,
                        created_at,
                        now,
                    ),
                )
                _record_current_unit_version(conn, new_id, created_at=created_at)
                children.append((new_id, source_basis_status, page_start, page_end))
        db.event(
            "knowledge_unit_split",
            "knowledge_unit",
            unit_id,
            {
                "new_unit_ids": [left_id, right_id],
                "split_at": payload.split_at,
                "used_edited_body": payload.body is not None and payload.body != existing["body"],
                "retrieval_items_marked_stale": stale_count,
                "source_anchors": [
                    {"unit_id": item[0], "status": item[1], "page_start": item[2], "page_end": item[3]}
                    for item in children
                ],
            },
        )
        return {
            "archived_unit_id": unit_id,
            "units": [get_unit(left_id), get_unit(right_id)],
            "history_preserved": True,
            "retrieval_items_marked_stale": stale_count,
        }

    @app.post("/api/units/{unit_id}/merge")
    def merge_units(unit_id: str, payload: UnitMergeRequest) -> dict[str, Any]:
        if unit_id == payload.other_unit_id:
            raise HTTPException(status_code=422, detail="不能把知识单元与自身合并")
        now = utc_now()
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM knowledge_units WHERE id IN (?, ?)",
                (unit_id, payload.other_unit_id),
            ).fetchall()
            if len(rows) != 2:
                raise HTTPException(status_code=404, detail="待合并知识单元不存在")
            by_id = {row["id"]: row for row in rows}
            first_raw, second_raw = by_id[unit_id], by_id[payload.other_unit_id]
            if first_raw["source_id"] != second_raw["source_id"]:
                raise HTTPException(status_code=409, detail="只能合并同一本教材中的知识单元")
            if first_raw["status"] == "archived" or second_raw["status"] == "archived":
                raise HTTPException(status_code=409, detail="归档知识单元不能参与新合并")
            _assert_units_not_in_active_session(conn, [unit_id, payload.other_unit_id])
            active_ids = [
                row["id"]
                for row in conn.execute(
                    "SELECT id FROM knowledge_units WHERE source_id=? AND status!='archived' ORDER BY page_start, created_at",
                    (first_raw["source_id"],),
                ).fetchall()
            ]
            positions = sorted((active_ids.index(unit_id), active_ids.index(payload.other_unit_id)))
            if positions[1] - positions[0] != 1:
                raise HTTPException(status_code=409, detail="只能合并当前教材中相邻的知识单元")
            ordered = sorted((first_raw, second_raw), key=lambda row: active_ids.index(row["id"]))
            merged_id = str(uuid4())
            merged_title = payload.title or f"{ordered[0]['title']} / {ordered[1]['title']}"
            merged_type = payload.objective_type or (
                ordered[0]["objective_type"] if ordered[0]["objective_type"] == ordered[1]["objective_type"] else "综合型"
            )
            merged_body = f"{ordered[0]['body'].rstrip()}\n\n{ordered[1]['body'].lstrip()}"
            reliable_source_basis = all(
                row["source_basis_text"] and row["source_basis_status"] != "source_anchor_pending"
                for row in ordered
            )
            if reliable_source_basis:
                merged_source_basis = f"{ordered[0]['source_basis_text'].rstrip()}\n\n{ordered[1]['source_basis_text'].lstrip()}"
                merged_source_status = "derived_from_merged_source_basis"
            else:
                merged_source_basis = ""
                merged_source_status = "source_anchor_pending"
            stale_count = _mark_retrieval_stale(conn, [unit_id, payload.other_unit_id], now)
            conn.execute(
                "UPDATE knowledge_units SET status='archived', updated_at=? WHERE id IN (?, ?)",
                (now, unit_id, payload.other_unit_id),
            )
            page_start = min(row["page_start"] for row in ordered)
            page_end = max(row["page_end"] for row in ordered)
            if merged_source_basis:
                page_start, page_end, localized_status = locate_page_range(
                    conn,
                    source_id=ordered[0]["source_id"],
                    text=merged_source_basis,
                    fallback_start=page_start,
                    fallback_end=page_end,
                )
                if localized_status == "source_anchor_pending":
                    merged_source_status = localized_status
            conn.execute(
                "INSERT INTO knowledge_units(id, source_id, title, body, body_hash, source_basis_text, source_basis_hash, source_basis_status, "
                "page_start, page_end, objective_type, status, version, created_at, updated_at) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', 1, ?, ?)",
                (
                    merged_id,
                    ordered[0]["source_id"],
                    merged_title,
                    merged_body,
                    text_hash(merged_body),
                    merged_source_basis,
                    text_hash(merged_source_basis) if merged_source_basis else "",
                    merged_source_status,
                    page_start,
                    page_end,
                    merged_type,
                    now,
                    now,
                ),
            )
            _record_current_unit_version(conn, merged_id, created_at=now)
        db.event(
            "knowledge_units_merged",
            "knowledge_unit",
            merged_id,
            {
                "archived_unit_ids": [unit_id, payload.other_unit_id],
                "retrieval_items_marked_stale": stale_count,
                "source_basis_status": merged_source_status,
                "page_start": page_start,
                "page_end": page_end,
            },
        )
        return {
            "unit": get_unit(merged_id),
            "archived_unit_ids": [unit_id, payload.other_unit_id],
            "history_preserved": True,
            "retrieval_items_marked_stale": stale_count,
        }

    @app.post("/api/units/{unit_id}/sessions")
    def start_session(unit_id: str, payload: StartSessionRequest) -> dict[str, Any]:
        method_pack_to_persist: dict[str, Any] | None = None
        snapshot_to_event: dict[str, Any] | None = None
        with db.connect() as conn:
            unit = conn.execute("SELECT * FROM knowledge_units WHERE id=?", (unit_id,)).fetchone()
            if unit is None:
                raise HTTPException(status_code=404, detail="知识单元不存在")
            if unit["status"] == "archived":
                raise HTTPException(status_code=409, detail="归档知识单元只保留历史证据，不能继续启动学习")
            active = conn.execute(
                "SELECT * FROM study_sessions WHERE status='active' ORDER BY last_activity_at DESC LIMIT 1"
            ).fetchone()
            if active:
                if active["knowledge_unit_id"] == unit_id:
                    session = dict(active)
                    material = _session_material(session)
                    selection, persisted = _method_pack_selection(
                        conn,
                        session_id=session["id"],
                        objective_type=material.get("objective_type") or unit["objective_type"],
                    )
                    selection = _annotate_method_pack_target(selection, material)
                    session["method_pack"] = selection
                    session["unit_snapshot"] = material
                    if not persisted:
                        method_pack_to_persist = selection
                    response = {"resumed": True, "session": session, "unit": dict(unit)}
                else:
                    raise HTTPException(status_code=409, detail="已有未完成的闭卷会话，请先继续或结束本轮学习")
            else:
                now = utc_now()
                if unit["status"] == "draft":
                    if not payload.approve_unit:
                        raise HTTPException(status_code=409, detail="知识单元尚未确认，请先核对来源与学习文本后再开始闭卷")
                    conn.execute(
                        "UPDATE knowledge_units SET status='approved', updated_at=? WHERE id=?",
                        (now, unit_id),
                    )
                    unit = conn.execute("SELECT * FROM knowledge_units WHERE id=?", (unit_id,)).fetchone()
                snapshot = capture_session_snapshot(conn, unit)
                session_id = str(uuid4())
                conn.execute(
                    "INSERT INTO study_sessions(id, knowledge_unit_id, status, unit_version, unit_body_hash, unit_snapshot_json, snapshot_status, started_at, last_activity_at) "
                    "VALUES(?, ?, 'active', ?, ?, ?, 'captured', ?, ?)",
                    (
                        session_id,
                        unit_id,
                        snapshot["version"],
                        snapshot["body_hash"],
                        json.dumps(snapshot, ensure_ascii=False),
                        now,
                        now,
                    ),
                )
                session = dict(conn.execute("SELECT * FROM study_sessions WHERE id=?", (session_id,)).fetchone())
                selection = _annotate_method_pack_target(select_method_pack(snapshot["objective_type"]), snapshot)
                session["method_pack"] = selection
                session["unit_snapshot"] = snapshot
                method_pack_to_persist = selection
                snapshot_to_event = snapshot
                response = {"resumed": False, "session": session, "unit": dict(unit)}
        session_id = response["session"]["id"]
        if method_pack_to_persist is not None:
            db.event("method_pack_selected", "study_session", session_id, method_pack_to_persist)
        if not response["resumed"]:
            db.event(
                "session_started",
                "study_session",
                session_id,
                {
                    "unit_id": unit_id,
                    "unit_version": snapshot_to_event["version"] if snapshot_to_event else None,
                    "unit_body_hash": snapshot_to_event["body_hash"] if snapshot_to_event else None,
                    "source_anchor": snapshot_to_event.get("source_anchor") if snapshot_to_event else None,
                    "method_pack_id": response["session"]["method_pack"]["id"],
                    "method_pack_version": response["session"]["method_pack"]["version"],
                },
            )
        return response

    @app.get("/api/sessions/active")
    def active_session() -> dict[str, Any] | None:
        with db.connect() as conn:
            row = conn.execute(
                "SELECT ss.*, u.title AS current_title, u.body AS current_body, u.body_hash AS current_unit_body_hash, "
                "u.page_start AS current_page_start, u.page_end AS current_page_end, u.objective_type AS current_objective_type, "
                "u.version AS current_unit_version, s.original_name "
                "FROM study_sessions ss JOIN knowledge_units u ON u.id=ss.knowledge_unit_id "
                "JOIN source_documents s ON s.id=u.source_id "
                "WHERE ss.status='active' ORDER BY ss.last_activity_at DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        with db.connect() as conn:
            return _hydrate_session(conn, row)

    @app.get("/api/sessions/{session_id}")
    def get_session(session_id: str) -> dict[str, Any]:
        with db.connect() as conn:
            row = conn.execute(
                "SELECT ss.*, u.title AS current_title, u.body AS current_body, u.body_hash AS current_unit_body_hash, "
                "u.page_start AS current_page_start, u.page_end AS current_page_end, u.objective_type AS current_objective_type, "
                "u.version AS current_unit_version, s.original_name "
                "FROM study_sessions ss JOIN knowledge_units u ON u.id=ss.knowledge_unit_id "
                "JOIN source_documents s ON s.id=u.source_id WHERE ss.id=?",
                (session_id,),
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="学习会话不存在")
            attempt = conn.execute(
                "SELECT * FROM attempts WHERE session_id=? ORDER BY created_at DESC LIMIT 1", (session_id,)
            ).fetchone()
        with db.connect() as conn:
            result = _hydrate_session(conn, row)
        result["attempt"] = _hydrate_attempt(dict(attempt)) if attempt else None
        return result

    @app.put("/api/sessions/{session_id}/draft")
    def save_draft(session_id: str, payload: DraftUpdate) -> dict[str, Any]:
        now = utc_now()
        with db.connect() as conn:
            row = conn.execute("SELECT * FROM study_sessions WHERE id=?", (session_id,)).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="学习会话不存在")
            if row["status"] != "active":
                raise HTTPException(status_code=409, detail="该会话已结束")
            conn.execute(
                "UPDATE study_sessions SET draft_text=?, draft_confidence=?, draft_updated_at=?, last_activity_at=? WHERE id=?",
                (payload.text, payload.confidence, now, now, session_id),
            )
        return {"session_id": session_id, "saved_at": now}

    @app.post("/api/sessions/{session_id}/cancel")
    def cancel_session(session_id: str) -> dict[str, Any]:
        now = utc_now()
        with db.connect() as conn:
            row = conn.execute("SELECT * FROM study_sessions WHERE id=?", (session_id,)).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="学习会话不存在")
            if row["status"] == "active":
                conn.execute(
                    "UPDATE study_sessions SET status='cancelled', completed_at=?, last_activity_at=? WHERE id=?",
                    (now, now, session_id),
                )
        db.event("session_cancelled", "study_session", session_id)
        return {"session_id": session_id, "status": "cancelled"}

    @app.post("/api/sessions/{session_id}/hint")
    def use_hint(session_id: str, payload: HintRequest) -> dict[str, Any]:
        with db.connect() as conn:
            row = conn.execute("SELECT * FROM study_sessions WHERE id=?", (session_id,)).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="学习会话不存在")
            if row["status"] != "active":
                raise HTTPException(status_code=409, detail="该会话已结束")
            level = max(row["hint_level"], payload.level)
            conn.execute(
                "UPDATE study_sessions SET hint_level=?, last_activity_at=? WHERE id=?",
                (level, utc_now(), session_id),
            )
        db.event("hint_used", "study_session", session_id, {"level": payload.level})
        return {"session_id": session_id, "hint_level": level}

    @app.post("/api/sessions/{session_id}/attempts")
    def submit_attempt(session_id: str, payload: AttemptCreate) -> dict[str, Any]:
        with db.connect() as conn:
            session = conn.execute(
                "SELECT ss.*, u.id AS unit_id, u.version AS current_unit_version, u.body_hash AS current_unit_body_hash, "
                "u.title AS current_title, u.body AS current_body, u.page_start AS current_page_start, "
                "u.page_end AS current_page_end, u.objective_type AS current_objective_type "
                "FROM study_sessions ss JOIN knowledge_units u ON u.id=ss.knowledge_unit_id WHERE ss.id=?",
                (session_id,),
            ).fetchone()
            if session is None:
                raise HTTPException(status_code=404, detail="学习会话不存在")
            if session["status"] != "active":
                prior = conn.execute(
                    "SELECT * FROM attempts WHERE session_id=? ORDER BY created_at DESC LIMIT 1", (session_id,)
                ).fetchone()
                if prior:
                    return _hydrate_attempt(dict(prior))
                raise HTTPException(status_code=409, detail="该会话已结束")
            material = _session_material(session)
            previous_errors = [
                row["detail"]
                for row in conn.execute(
                    "SELECT er.detail FROM error_records er JOIN attempts a ON a.id=er.attempt_id "
                    "WHERE er.knowledge_unit_id=? AND er.status='open' AND a.unit_body_hash=? AND a.unit_version=? "
                    "ORDER BY er.created_at DESC LIMIT 5",
                    (session["unit_id"], material["body_hash"], material["version"]),
                ).fetchall()
            ]
            method_pack_selection, method_pack_persisted = _method_pack_selection(
                conn,
                session_id=session_id,
                objective_type=material["objective_type"],
            )
            method_pack_selection = _annotate_method_pack_target(method_pack_selection, material)

        if not method_pack_persisted:
            db.event("method_pack_selected", "study_session", session_id, method_pack_selection)

        score_request = ScoreRequest(
            unit_title=material["title"],
            source_text=material["body"],
            page_start=material["page_start"],
            page_end=material["page_end"],
            answer_text=payload.answer_text,
            confidence=payload.confidence,
            hint_level=session["hint_level"],
            previous_errors=previous_errors,
        )
        configured_provider = provider_from_settings(
            settings.ai_provider,
            settings.ai_base_url,
            settings.ai_api_key,
            settings.ai_model,
        )
        provider = configured_provider
        run_id = new_provider_run_id()
        warning: str | None = None
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO provider_runs(id, provider, task_type, input_chars, status, created_at) VALUES(?, ?, 'score_attempt', ?, 'running', ?)",
                (run_id, provider.name, len(material["body"]) + len(payload.answer_text), utc_now()),
            )
        try:
            feedback = provider.score(score_request)
            with db.connect() as conn:
                conn.execute(
                    "UPDATE provider_runs SET output_chars=?, status='completed' WHERE id=?",
                    (len(feedback.model_dump_json()), run_id),
                )
        except Exception as exc:
            if settings.ai_provider == "local":
                with db.connect() as conn:
                    conn.execute(
                        "UPDATE provider_runs SET status='failed', error_message=? WHERE id=?", (str(exc), run_id)
                    )
                raise HTTPException(status_code=502, detail=str(exc)) from exc
            with db.connect() as conn:
                conn.execute(
                    "UPDATE provider_runs SET status='failed', error_message=? WHERE id=?", (str(exc), run_id)
                )
            provider = LocalEvidenceScorer()
            feedback = provider.score(score_request)
            warning = f"云端评分失败，已降级为本地证据覆盖评分：{exc}"
            feedback.warning = warning

        try:
            method_pack_snapshot = evaluate_method_pack(
                selection=method_pack_selection,
                request=score_request,
                base_feedback=feedback,
            )
        except Exception as exc:
            fallback_provider = LocalEvidenceScorer()
            feedback = fallback_provider.score(score_request)
            provider = fallback_provider
            method_warning = f"方法包诊断失败，已退回基础来源覆盖反馈：{exc}"
            feedback.warning = "；".join(item for item in [warning, method_warning] if item)
            method_pack_snapshot = degraded_method_pack_snapshot(method_pack_selection, str(exc))

        method_pack_snapshot["method_pack"] = _annotate_method_pack_target(method_pack_snapshot["method_pack"], material)
        method_pack_snapshot["generated_flags"] = method_pack_snapshot["method_pack"]["generated_flags"]

        provider_score = float(feedback.score)
        weight = evidence_weight(session["hint_level"])
        verdict = derive_evidence_verdict(
            provider_score=provider_score,
            evidence_weight=weight,
            confidence=payload.confidence,
            method_pack_snapshot=method_pack_snapshot,
        )
        effective_score = verdict.effective_score
        mastery_status = verdict.mastery_status
        interval_days = verdict.interval_days
        review_reason = verdict.reason
        due_at = due_at_after(interval_days)
        now = utc_now()

        current_contract_matches = (
            session["current_unit_body_hash"] == material["body_hash"]
            and int(session["current_unit_version"] or 0) == int(material["version"] or 0)
        )
        if not current_contract_matches:
            mastery_status = "历史版本证据"
            interval_days = 0
            due_at = now
            review_reason = "当前知识单元已变化，本次只保存为历史版本证据，不更新当前掌握状态。"

        feedback_payload = feedback.model_dump()
        feedback_payload["provider_score"] = provider_score
        feedback_payload["score"] = effective_score
        feedback_payload["next_action"] = review_reason
        feedback_payload["method_pack"] = method_pack_snapshot["method_pack"]
        feedback_payload["dimension_results"] = method_pack_snapshot["dimension_results"]
        feedback_payload["method_source_refs"] = method_pack_snapshot["source_refs"]
        feedback_payload["generated_flags"] = method_pack_snapshot["generated_flags"]
        feedback_payload["evidence_verdict"] = verdict.as_dict()
        feedback_payload["unit_snapshot"] = {
            "version": material["version"],
            "body_hash": material["body_hash"],
            "snapshot_status": session["snapshot_status"],
            "source_anchor": material.get("source_anchor", {}),
        }

        attempt_id = str(uuid4())
        error_specs: list[tuple[str, str]] = []
        if verdict.hard_conflicts:
            messages: list[str] = []
            for conflict in verdict.hard_conflicts[:3]:
                messages.extend(conflict.get("mismatches") or [])
            detail = "；".join(dict.fromkeys(messages)) or "检测到关键法律冲突，必须回源修正后重答。"
            error_specs.append(("critical_legal_conflict", detail))
        if effective_score < 70:
            error_specs.append(("knowledge_gap", "当前有效证据不足，需要重新闭卷复现。"))
        if payload.confidence >= 80 and effective_score < 60:
            error_specs.append(("high_confidence_error", "高置信度低有效证据，可能存在稳定性误记。"))
        if session["hint_level"] >= 2:
            error_specs.append(("hint_dependency", "查看完整原文后作答，尚未形成无提示提取证据。"))
        if feedback.missing_points and effective_score < 85:
            error_specs.append(("condition_omission", feedback.missing_points[0]))
        deduped_errors = list(dict.fromkeys(error_specs))[:4]

        with db.connect() as conn:
            conn.execute(
                "INSERT INTO attempts(id, session_id, knowledge_unit_id, unit_version, unit_body_hash, unit_snapshot_status, "
                "answer_text, confidence, elapsed_ms, hint_level, score, evidence_weight, feedback_json, provider, created_at) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    attempt_id,
                    session_id,
                    session["unit_id"],
                    material["version"],
                    material["body_hash"],
                    session["snapshot_status"],
                    payload.answer_text,
                    payload.confidence,
                    payload.elapsed_ms,
                    session["hint_level"],
                    effective_score,
                    weight,
                    json.dumps(feedback_payload, ensure_ascii=False),
                    provider.name,
                    now,
                ),
            )
            for error_type, detail in deduped_errors:
                conn.execute(
                    "INSERT INTO error_records(id, attempt_id, knowledge_unit_id, error_type, detail, status, created_at) "
                    "VALUES(?, ?, ?, ?, ?, 'open', ?)",
                    (str(uuid4()), attempt_id, session["unit_id"], error_type, detail, now),
                )
            if current_contract_matches:
                conn.execute(
                    "INSERT INTO review_states(knowledge_unit_id, knowledge_unit_version, unit_body_hash, mastery_status, due_at, interval_days, last_score, last_attempt_id, updated_at) "
                    "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(knowledge_unit_id) DO UPDATE SET knowledge_unit_version=excluded.knowledge_unit_version, "
                    "unit_body_hash=excluded.unit_body_hash, mastery_status=excluded.mastery_status, due_at=excluded.due_at, "
                    "interval_days=excluded.interval_days, last_score=excluded.last_score, last_attempt_id=excluded.last_attempt_id, updated_at=excluded.updated_at",
                    (
                        session["unit_id"],
                        material["version"],
                        material["body_hash"],
                        mastery_status,
                        due_at,
                        interval_days,
                        effective_score,
                        attempt_id,
                        now,
                    ),
                )
            conn.execute(
                "UPDATE study_sessions SET status='completed', draft_text='', completed_at=?, last_activity_at=? WHERE id=?",
                (now, now, session_id),
            )
        db.event(
            "attempt_submitted",
            "attempt",
            attempt_id,
            {
                "provider_score": provider_score,
                "effective_score": effective_score,
                "evidence_weight": weight,
                "evidence_verdict": verdict.as_dict(),
                "review_due_at": due_at,
                "review_state_written": current_contract_matches,
                "unit_version": material["version"],
                "unit_body_hash": material["body_hash"],
                "provider": provider.name,
                "method_pack_id": method_pack_snapshot["method_pack"]["id"],
                "method_pack_version": method_pack_snapshot["method_pack"]["version"],
                "method_pack_runtime_status": method_pack_snapshot["method_pack"]["runtime_status"],
                "dimension_statuses": {
                    item["id"]: item["status"] for item in method_pack_snapshot["dimension_results"]
                },
            },
        )
        db.event(
            "method_pack_evaluated",
            "attempt",
            attempt_id,
            {
                "session_id": session_id,
                "knowledge_unit_id": session["unit_id"],
                **method_pack_snapshot,
            },
        )
        return {
            "id": attempt_id,
            "session_id": session_id,
            "knowledge_unit_id": session["unit_id"],
            "unit_version": material["version"],
            "unit_body_hash": material["body_hash"],
            "provider_score": provider_score,
            "score": effective_score,
            "evidence_weight": weight,
            "evidence_verdict": verdict.as_dict(),
            "feedback": feedback_payload,
            "method_pack": method_pack_snapshot["method_pack"],
            "dimension_results": method_pack_snapshot["dimension_results"],
            "provider": provider.name,
            "review": {
                "mastery_status": mastery_status,
                "interval_days": interval_days,
                "due_at": due_at,
                "reason": review_reason,
                "current_version": current_contract_matches,
            },
            "errors_created": len(deduped_errors),
            "created_at": now,
        }


    @app.get("/api/errors")
    def list_errors(
        status: str = Query(default="open", pattern="^(open|repairing|resolved|superseded|all)$"),
        unit_id: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        conditions: list[str] = []
        params: list[Any] = []
        if status != "all":
            conditions.append("er.status=?")
            params.append(status)
        if unit_id:
            conditions.append("er.knowledge_unit_id=?")
            params.append(unit_id)
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT er.*, u.title AS unit_title, u.status AS unit_status, s.original_name "
                "FROM error_records er JOIN knowledge_units u ON u.id=er.knowledge_unit_id "
                "JOIN source_documents s ON s.id=u.source_id" + where + " ORDER BY er.created_at DESC LIMIT ?",
                (*params, limit),
            ).fetchall()
            return [_hydrate_error_record(conn, row) for row in rows]

    @app.post("/api/errors/{error_id}/repair")
    def start_error_repair(error_id: str) -> dict[str, Any]:
        with db.connect() as conn:
            error = conn.execute(
                "SELECT er.*, u.status AS unit_status, u.body_hash AS current_unit_body_hash, "
                "a.unit_body_hash AS error_unit_body_hash, a.unit_version AS error_unit_version, u.version AS current_unit_version FROM error_records er "
                "JOIN knowledge_units u ON u.id=er.knowledge_unit_id "
                "JOIN attempts a ON a.id=er.attempt_id WHERE er.id=?",
                (error_id,),
            ).fetchone()
        if error is None:
            raise HTTPException(status_code=404, detail="错因记录不存在")
        if error["status"] == "resolved":
            raise HTTPException(status_code=409, detail="该错因已经解决，如再次出现请保留新的错误记录")
        if error["status"] == "superseded":
            raise HTTPException(status_code=409, detail="该错因属于旧版学习材料，已被新版本取代，不能继续作为当前修复任务")
        if (
            (error["error_unit_body_hash"] and error["error_unit_body_hash"] != error["current_unit_body_hash"])
            or (error["error_unit_version"] is not None and int(error["error_unit_version"]) != int(error["current_unit_version"]))
        ):
            raise HTTPException(status_code=409, detail="该错因绑定旧版知识单元，请在当前版本重新作答后建立新的修复证据")
        if error["unit_status"] == "archived":
            raise HTTPException(status_code=409, detail="该错因属于已归档知识单元，请在当前知识单元中重新建立修复任务")
        session_result = start_session(error["knowledge_unit_id"], StartSessionRequest(approve_unit=True))
        now = utc_now()
        with db.connect() as conn:
            conn.execute("UPDATE error_records SET status='repairing', resolved_at=NULL WHERE id=?", (error_id,))
            refreshed = conn.execute(
                "SELECT er.*, u.title AS unit_title, u.status AS unit_status, s.original_name "
                "FROM error_records er JOIN knowledge_units u ON u.id=er.knowledge_unit_id "
                "JOIN source_documents s ON s.id=u.source_id WHERE er.id=?",
                (error_id,),
            ).fetchone()
        db.event(
            "error_repair_started",
            "error_record",
            error_id,
            {"session_id": session_result["session"]["id"], "knowledge_unit_id": error["knowledge_unit_id"], "started_at": now},
        )
        with db.connect() as conn:
            hydrated = _hydrate_error_record(conn, refreshed)
        return {"error": hydrated, **session_result}

    @app.post("/api/errors/{error_id}/resolve")
    def resolve_error(error_id: str) -> dict[str, Any]:
        with db.connect() as conn:
            row = conn.execute(
                "SELECT er.*, u.title AS unit_title, u.status AS unit_status, s.original_name "
                "FROM error_records er JOIN knowledge_units u ON u.id=er.knowledge_unit_id "
                "JOIN source_documents s ON s.id=u.source_id WHERE er.id=?",
                (error_id,),
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="错因记录不存在")
            if row["status"] == "resolved":
                return _hydrate_error_record(conn, row)
            hydrated = _hydrate_error_record(conn, row)
            if row["status"] != "repairing" or not hydrated["can_resolve"]:
                raise HTTPException(status_code=409, detail=hydrated.get("resolution_gate_reason") or "请先完成达到当前证据门槛的新无提示闭卷，再人工确认解决")
            now = utc_now()
            conn.execute(
                "UPDATE error_records SET status='resolved', resolved_at=? WHERE id=?",
                (now, error_id),
            )
            resolved = conn.execute(
                "SELECT er.*, u.title AS unit_title, u.status AS unit_status, s.original_name "
                "FROM error_records er JOIN knowledge_units u ON u.id=er.knowledge_unit_id "
                "JOIN source_documents s ON s.id=u.source_id WHERE er.id=?",
                (error_id,),
            ).fetchone()
        db.event(
            "error_resolved",
            "error_record",
            error_id,
            {"retest_attempt_id": hydrated["retest_attempt_id"], "retest_score": hydrated["retest_score"], "manual_confirmation": True},
        )
        with db.connect() as conn:
            return _hydrate_error_record(conn, resolved)


    @app.post("/api/units/{unit_id}/retrieval-items/generate")
    def generate_unit_retrieval_items(unit_id: str, payload: RetrievalGenerateRequest) -> dict[str, Any]:
        with db.connect() as conn:
            unit = conn.execute("SELECT * FROM knowledge_units WHERE id=?", (unit_id,)).fetchone()
            if unit is None:
                raise HTTPException(status_code=404, detail="知识单元不存在")
            if unit["status"] == "archived":
                raise HTTPException(status_code=409, detail="归档知识单元不能生成新卡片")
        drafts = generate_retrieval_items(
            title=unit["title"],
            body=unit["body"],
            item_types=payload.item_types,
            max_per_type=payload.max_per_type,
        )
        if not drafts:
            raise HTTPException(status_code=422, detail="当前知识单元无法生成有效的挖空或闪卡，请先修订知识单元文本")

        now = utc_now()
        created_ids: list[str] = []
        reused = 0
        reactivated = 0
        skipped_archived = 0
        with db.connect() as conn:
            for draft in drafts:
                existing = conn.execute(
                    "SELECT id, status FROM retrieval_items WHERE knowledge_unit_id=? AND content_hash=?",
                    (unit_id, draft.content_hash),
                ).fetchone()
                if existing is not None:
                    if existing["status"] == "stale":
                        conn.execute(
                            "UPDATE retrieval_items SET status='active', generation_method=?, version=version+1, updated_at=? "
                            "WHERE id=?",
                            (draft.generation_method, now, existing["id"]),
                        )
                        conn.execute(
                            "INSERT INTO retrieval_review_states(retrieval_item_id, mastery_status, due_at, interval_minutes, "
                            "streak, lapses, last_score, last_rating, last_attempt_id, updated_at) "
                            "VALUES(?, '新卡', ?, 0, 0, 0, 0, 'new', NULL, ?) "
                            "ON CONFLICT(retrieval_item_id) DO UPDATE SET mastery_status=excluded.mastery_status, "
                            "due_at=excluded.due_at, interval_minutes=0, streak=0, lapses=0, last_score=0, "
                            "last_rating='new', last_attempt_id=NULL, updated_at=excluded.updated_at",
                            (existing["id"], now, now),
                        )
                        reactivated += 1
                    elif existing["status"] == "active":
                        reused += 1
                    else:
                        skipped_archived += 1
                    continue
                conn.execute(
                    "INSERT INTO retrieval_items(id, knowledge_unit_id, item_type, prompt, answer, cloze_text, "
                    "source_excerpt, content_hash, status, generation_method, created_at, updated_at) "
                    "VALUES(?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)",
                    (
                        draft.id,
                        unit_id,
                        draft.item_type,
                        draft.prompt,
                        draft.answer,
                        draft.cloze_text,
                        draft.source_excerpt,
                        draft.content_hash,
                        draft.generation_method,
                        now,
                        now,
                    ),
                )
                created_ids.append(draft.id)
                conn.execute(
                    "INSERT INTO retrieval_review_states(retrieval_item_id, mastery_status, due_at, interval_minutes, "
                    "streak, lapses, last_score, last_rating, last_attempt_id, updated_at) "
                    "VALUES(?, '新卡', ?, 0, 0, 0, 0, 'new', NULL, ?)",
                    (draft.id, now, now),
                )
            rows = conn.execute(
                RETRIEVAL_SELECT
                + " WHERE ri.knowledge_unit_id=? AND ri.status='active' ORDER BY ri.created_at, ri.item_type",
                (unit_id,),
            ).fetchall()
        db.event(
            "retrieval_items_generated",
            "knowledge_unit",
            unit_id,
            {
                "requested_types": payload.item_types,
                "created": len(created_ids),
                "reactivated": reactivated,
                "reused": reused,
                "skipped_archived": skipped_archived,
                "generation_method": "local_rule_v1",
            },
        )
        return {
            "knowledge_unit_id": unit_id,
            "created": len(created_ids),
            "reactivated": reactivated,
            "reused": reused,
            "skipped_archived": skipped_archived,
            "items": [_hydrate_retrieval_item(dict(row), include_answer=True) for row in rows],
        }

    @app.post("/api/units/{unit_id}/retrieval-items")
    def create_retrieval_item(unit_id: str, payload: RetrievalItemCreate) -> dict[str, Any]:
        with db.connect() as conn:
            unit = conn.execute("SELECT * FROM knowledge_units WHERE id=?", (unit_id,)).fetchone()
            if unit is None:
                raise HTTPException(status_code=404, detail="知识单元不存在")
            if unit["status"] == "archived":
                raise HTTPException(status_code=409, detail="归档知识单元不能建立新卡片")
        source_excerpt = (payload.source_excerpt or unit["body"]).strip()
        cloze_text = payload.cloze_text.strip() if payload.cloze_text else None
        prompt = payload.prompt.strip()
        if payload.item_type == "cloze" and cloze_text is not None:
            prompt = f"填空：{cloze_text}"
        content_hash = retrieval_content_hash(payload.item_type, prompt, payload.answer.strip(), source_excerpt)
        item_id = str(uuid4())
        now = utc_now()
        try:
            with db.connect() as conn:
                conn.execute(
                    "INSERT INTO retrieval_items(id, knowledge_unit_id, item_type, prompt, answer, cloze_text, source_excerpt, "
                    "content_hash, status, generation_method, created_at, updated_at) "
                    "VALUES(?, ?, ?, ?, ?, ?, ?, ?, 'active', 'manual_v1', ?, ?)",
                    (
                        item_id,
                        unit_id,
                        payload.item_type,
                        prompt,
                        payload.answer.strip(),
                        cloze_text,
                        source_excerpt,
                        content_hash,
                        now,
                        now,
                    ),
                )
                conn.execute(
                    "INSERT INTO retrieval_review_states(retrieval_item_id, mastery_status, due_at, interval_minutes, "
                    "streak, lapses, last_score, last_rating, last_attempt_id, updated_at) "
                    "VALUES(?, '新卡', ?, 0, 0, 0, 0, 'new', NULL, ?)",
                    (item_id, now, now),
                )
                row = conn.execute(RETRIEVAL_SELECT + " WHERE ri.id=?", (item_id,)).fetchone()
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="相同卡片已经存在") from exc
        db.event("retrieval_item_created", "retrieval_item", item_id, {"item_type": payload.item_type})
        return _hydrate_retrieval_item(dict(row), include_answer=True)

    @app.get("/api/units/{unit_id}/retrieval-items")
    def list_unit_retrieval_items(
        unit_id: str,
        include_answer: bool = Query(default=True),
    ) -> list[dict[str, Any]]:
        with db.connect() as conn:
            exists = conn.execute("SELECT id FROM knowledge_units WHERE id=?", (unit_id,)).fetchone()
            if exists is None:
                raise HTTPException(status_code=404, detail="知识单元不存在")
            rows = conn.execute(
                RETRIEVAL_SELECT
                + " WHERE ri.knowledge_unit_id=? ORDER BY CASE ri.status WHEN 'active' THEN 0 ELSE 1 END, ri.created_at",
                (unit_id,),
            ).fetchall()
        return [_hydrate_retrieval_item(dict(row), include_answer=include_answer) for row in rows]

    @app.get("/api/retrieval-items")
    def list_retrieval_items(
        due_only: bool = Query(default=False),
        item_type: str | None = Query(default=None, pattern="^(flashcard|cloze)$"),
        unit_id: str | None = None,
        include_answer: bool = Query(default=False),
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        conditions = ["ri.status='active'", "u.status!='archived'"]
        params: list[Any] = []
        if due_only:
            conditions.append("COALESCE(rr.due_at, ri.created_at) <= ?")
            params.append(utc_now())
        if item_type:
            conditions.append("ri.item_type=?")
            params.append(item_type)
        if unit_id:
            conditions.append("ri.knowledge_unit_id=?")
            params.append(unit_id)
        sql = (
            RETRIEVAL_SELECT
            + " WHERE "
            + " AND ".join(conditions)
            + " ORDER BY COALESCE(rr.due_at, ri.created_at), CASE ri.item_type WHEN 'flashcard' THEN 0 ELSE 1 END, ri.created_at LIMIT ?"
        )
        params.append(limit)
        with db.connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [_hydrate_retrieval_item(dict(row), include_answer=include_answer) for row in rows]

    @app.get("/api/study-pack/export")
    def export_study_pack(
        mode: str = Query(default="due", pattern="^(due|all)$"),
        item_type: str | None = Query(default=None, pattern="^(flashcard|cloze)$"),
        limit: int = Query(default=50, ge=1, le=500),
    ) -> FileResponse:
        conditions = ["ri.status='active'", "u.status!='archived'"]
        params: list[Any] = []
        if mode == "due":
            conditions.append("COALESCE(rr.due_at, ri.created_at) <= ?")
            params.append(utc_now())
        if item_type:
            conditions.append("ri.item_type=?")
            params.append(item_type)
        sql = (
            RETRIEVAL_SELECT
            + " WHERE "
            + " AND ".join(conditions)
            + " ORDER BY COALESCE(rr.due_at, ri.created_at), CASE ri.item_type WHEN 'flashcard' THEN 0 ELSE 1 END, ri.created_at LIMIT ?"
        )
        params.append(limit)
        with db.connect() as conn:
            rows = [dict(row) for row in conn.execute(sql, tuple(params)).fetchall()]
        if not rows:
            raise HTTPException(status_code=409, detail="当前没有符合条件的闪卡或挖空可导出")
        exported_at = utc_now()
        pack = build_study_pack(rows, product_version="0.8.0", mode=mode, exported_at=exported_at)
        export_path = settings.export_dir / f"study-pack-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}-{pack['pack_id'][:8]}.json"
        export_path.write_text(json.dumps(pack, ensure_ascii=False, indent=2), encoding="utf-8")
        db.event(
            "study_pack_exported",
            "study_pack",
            pack["pack_id"],
            {"protocol": STUDY_PACK_PROTOCOL, "pack_hash": pack["pack_hash"], "mode": mode, "count": len(rows), "item_type": item_type},
        )
        return FileResponse(export_path, media_type="application/json", filename=export_path.name)


    @app.get("/api/retrieval-items/{item_id}")
    def get_retrieval_item(item_id: str, include_answer: bool = Query(default=False)) -> dict[str, Any]:
        with db.connect() as conn:
            row = conn.execute(RETRIEVAL_SELECT + " WHERE ri.id=?", (item_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="挖空或闪卡不存在")
        return _hydrate_retrieval_item(dict(row), include_answer=include_answer)

    @app.post("/api/retrieval-items/{item_id}/reveal")
    def reveal_retrieval_item(item_id: str) -> dict[str, Any]:
        with db.connect() as conn:
            row = conn.execute(RETRIEVAL_SELECT + " WHERE ri.id=?", (item_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="挖空或闪卡不存在")
        if row["status"] != "active" or row["unit_status"] == "archived":
            raise HTTPException(status_code=409, detail="该卡片所属知识单元已停用")
        db.event("retrieval_answer_revealed", "retrieval_item", item_id, {"item_type": row["item_type"]})
        return {
            "id": item_id,
            "answer": row["answer"],
            "source_excerpt": row["source_excerpt"],
            "page_start": row["page_start"],
            "page_end": row["page_end"],
            "unit_title": row["unit_title"],
        }

    @app.patch("/api/retrieval-items/{item_id}")
    def update_retrieval_item(item_id: str, payload: RetrievalItemUpdate) -> dict[str, Any]:
        changes = payload.model_dump(exclude_none=True)
        with db.connect() as conn:
            existing = conn.execute("SELECT * FROM retrieval_items WHERE id=?", (item_id,)).fetchone()
            if existing is None:
                raise HTTPException(status_code=404, detail="挖空或闪卡不存在")
        if not changes:
            return get_retrieval_item(item_id, include_answer=True)

        final_prompt = changes.get("prompt", existing["prompt"]).strip()
        final_answer = changes.get("answer", existing["answer"]).strip()
        final_cloze = changes.get("cloze_text", existing["cloze_text"])
        final_excerpt = changes.get("source_excerpt", existing["source_excerpt"]).strip()
        if existing["item_type"] == "cloze":
            if not final_cloze:
                raise HTTPException(status_code=422, detail="挖空题必须保留挖空文本")
            if final_cloze.count("____") != 1:
                raise HTTPException(status_code=422, detail="挖空题必须且只能包含一个 ____ 空位")
            if "cloze_text" in changes and "prompt" not in changes:
                final_prompt = f"填空：{final_cloze}"
                changes["prompt"] = final_prompt

        content_changed = any(key in changes for key in {"prompt", "answer", "cloze_text", "source_excerpt"})
        fields = list(changes)
        values = [changes[field] for field in fields]
        if content_changed:
            fields.append("content_hash")
            values.append(retrieval_content_hash(existing["item_type"], final_prompt, final_answer, final_excerpt))
        now = utc_now()
        try:
            with db.connect() as conn:
                sql = ", ".join(f"{field}=?" for field in fields)
                conn.execute(
                    f"UPDATE retrieval_items SET {sql}, version=version+1, updated_at=? WHERE id=?",
                    (*values, now, item_id),
                )
                if content_changed:
                    conn.execute(
                        "UPDATE retrieval_review_states SET mastery_status='新卡', due_at=?, interval_minutes=0, streak=0, "
                        "lapses=0, last_score=0, last_rating='new', last_attempt_id=NULL, updated_at=? WHERE retrieval_item_id=?",
                        (now, now, item_id),
                    )
                row = conn.execute(RETRIEVAL_SELECT + " WHERE ri.id=?", (item_id,)).fetchone()
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="修改后与现有卡片重复") from exc
        db.event(
            "retrieval_item_updated",
            "retrieval_item",
            item_id,
            {"fields": list(changes), "review_reset": content_changed},
        )
        return _hydrate_retrieval_item(dict(row), include_answer=True)

    @app.post("/api/retrieval-items/{item_id}/attempts")
    def submit_retrieval_attempt(item_id: str, payload: RetrievalAttemptCreate) -> dict[str, Any]:
        with db.connect() as conn:
            row = conn.execute(RETRIEVAL_SELECT + " WHERE ri.id=?", (item_id,)).fetchone()
            fresh_reveal = (
                _has_fresh_retrieval_reveal(
                    conn,
                    item_id=item_id,
                    item_updated_at=row["updated_at"],
                )
                if row is not None and row["item_type"] == "flashcard"
                else False
            )
        if row is None:
            raise HTTPException(status_code=404, detail="挖空或闪卡不存在")
        if row["status"] != "active" or row["unit_status"] == "archived":
            raise HTTPException(status_code=409, detail="该卡片所属知识单元已停用")

        response_text = payload.response_text.strip()
        critical_mismatches: list[str] = []
        if row["item_type"] == "flashcard":
            if not payload.revealed_answer or not fresh_reveal:
                raise HTTPException(status_code=422, detail="请先显示答案，再根据真实回忆情况评分")
            if payload.rating is None:
                raise HTTPException(status_code=422, detail="闪卡需要选择忘记、困难、记得或轻松")
            rating = payload.rating
            score = score_for_rating(rating)
            correct = rating in {"good", "easy"}
            note = {
                "again": "本轮未能独立恢复，十分钟后再次提取。",
                "hard": "基本想起但不稳定，缩短复习间隔。",
                "good": "能够独立恢复，进入正常间隔。",
                "easy": "提取轻松且完整，适当延长间隔。",
            }[rating]
            revealed_answer = True
        else:
            if not response_text:
                raise HTTPException(status_code=422, detail="请先填写挖空答案")
            grade = grade_cloze(response_text, row["answer"])
            rating = grade.rating
            score = grade.score
            correct = grade.correct
            note = grade.note
            critical_mismatches = list(grade.critical_mismatches)
            revealed_answer = True

        attempt_id = str(uuid4())
        now = utc_now()
        plan_now = datetime.fromisoformat(now)
        with db.connect() as conn:
            plan = _persist_retrieval_attempt(
                conn,
                row=row,
                attempt_id=attempt_id,
                response_text=response_text,
                rating=rating,
                score=score,
                elapsed_ms=payload.elapsed_ms,
                revealed_answer=revealed_answer,
                created_at=now,
                plan_now=plan_now,
                snapshot_status="captured",
            )
        db.event(
            "retrieval_attempt_submitted",
            "retrieval_attempt",
            attempt_id,
            {
                "item_id": item_id,
                "item_type": row["item_type"],
                "rating": rating,
                "score": score,
                "due_at": plan.due_at,
            },
        )
        return {
            "id": attempt_id,
            "retrieval_item_id": item_id,
            "knowledge_unit_id": row["knowledge_unit_id"],
            "item_type": row["item_type"],
            "score": score,
            "rating": rating,
            "correct": correct,
            "note": note,
            "critical_mismatches": critical_mismatches,
            "expected_answer": row["answer"],
            "source_excerpt": row["source_excerpt"],
            "page_start": row["page_start"],
            "page_end": row["page_end"],
            "review": {
                "mastery_status": plan.mastery_status,
                "due_at": plan.due_at,
                "interval_minutes": plan.interval_minutes,
                "streak": plan.streak,
                "lapses": plan.lapses,
                "reason": plan.reason,
            },
            "created_at": now,
        }

    @app.post("/api/study-events/import")
    def import_study_events(payload: PortableStudyEventsImport) -> dict[str, Any]:
        received_at = utc_now()
        with db.connect() as conn:
            pack_event = conn.execute(
                "SELECT payload_json, created_at FROM study_events WHERE event_type='study_pack_exported' AND entity_type='study_pack' AND entity_id=? ORDER BY id DESC LIMIT 1",
                (payload.pack_id,),
            ).fetchone()
        if pack_event is None:
            raise HTTPException(status_code=409, detail="无法确认这个 StudyPack 来自当前工作台")
        pack_meta = _json_field(pack_event["payload_json"], {})
        if pack_meta.get("pack_hash") != payload.pack_hash:
            raise HTTPException(status_code=409, detail="StudyPack 身份校验失败，事件文件与导出包不匹配")
        pack_exported_at = datetime.fromisoformat(pack_event["created_at"])

        results: list[dict[str, Any]] = []
        seen_event_ids: set[str] = set()
        imported = 0
        duplicates = 0
        conflicts = 0

        for event in payload.events:
            if event.event_id in seen_event_ids:
                conflicts += 1
                results.append({"event_id": event.event_id, "status": "conflict", "reason": "duplicate_event_in_bundle"})
                continue
            seen_event_ids.add(event.event_id)

            try:
                occurred = validate_event_time(event.occurred_at)
            except ValueError as exc:
                conflicts += 1
                results.append({"event_id": event.event_id, "status": "conflict", "reason": "invalid_event_time", "detail": str(exc)})
                continue

            with db.connect_immediate() as conn:
                existing_attempt = conn.execute("SELECT id FROM retrieval_attempts WHERE id=?", (event.event_id,)).fetchone()
                if existing_attempt is not None:
                    duplicates += 1
                    results.append({"event_id": event.event_id, "status": "duplicate"})
                    continue

                row = conn.execute(RETRIEVAL_SELECT + " WHERE ri.id=?", (event.item_id,)).fetchone()
                if row is None:
                    conflicts += 1
                    results.append({"event_id": event.event_id, "status": "conflict", "reason": "item_missing"})
                    continue
                if row["status"] != "active" or row["unit_status"] == "archived":
                    conflicts += 1
                    results.append({"event_id": event.event_id, "status": "conflict", "reason": "item_inactive"})
                    continue
                if int(row["version"] or 1) != int(event.item_version) or row["content_hash"] != event.content_hash:
                    conflicts += 1
                    results.append({
                        "event_id": event.event_id,
                        "status": "conflict",
                        "reason": "item_version_drift",
                        "current_version": int(row["version"] or 1),
                    })
                    continue

                current_last_attempt_id = row["last_attempt_id"] or None
                if current_last_attempt_id != event.base_last_attempt_id:
                    conflicts += 1
                    results.append({
                        "event_id": event.event_id,
                        "status": "conflict",
                        "reason": "history_advanced",
                        "expected_base_last_attempt_id": current_last_attempt_id,
                    })
                    continue

                if occurred < pack_exported_at - timedelta(minutes=10):
                    conflicts += 1
                    results.append({"event_id": event.event_id, "status": "conflict", "reason": "event_predates_pack"})
                    continue
                effective_occurred = max(occurred, pack_exported_at)
                if current_last_attempt_id:
                    base_attempt = conn.execute("SELECT created_at FROM retrieval_attempts WHERE id=?", (current_last_attempt_id,)).fetchone()
                    if base_attempt is None:
                        conflicts += 1
                        results.append({"event_id": event.event_id, "status": "conflict", "reason": "base_attempt_missing"})
                        continue
                    base_created_at = datetime.fromisoformat(base_attempt["created_at"])
                    if occurred < base_created_at - timedelta(minutes=10):
                        conflicts += 1
                        results.append({"event_id": event.event_id, "status": "conflict", "reason": "event_predates_base"})
                        continue
                    effective_occurred = max(effective_occurred, base_created_at)

                item_created_at = datetime.fromisoformat(row["created_at"])
                if effective_occurred < item_created_at - timedelta(minutes=1):
                    conflicts += 1
                    results.append({"event_id": event.event_id, "status": "conflict", "reason": "event_predates_item"})
                    continue

                response_text = event.response_text.strip()
                critical_mismatches: list[str] = []
                if row["item_type"] == "flashcard":
                    if not event.revealed_answer or event.rating is None:
                        conflicts += 1
                        results.append({
                            "event_id": event.event_id,
                            "status": "conflict",
                            "reason": "flashcard_requires_reveal_and_rating",
                        })
                        continue
                    rating = event.rating
                    score = score_for_rating(rating)
                    evaluation = "self_report"
                else:
                    if not response_text:
                        conflicts += 1
                        results.append({"event_id": event.event_id, "status": "conflict", "reason": "cloze_response_required"})
                        continue
                    grade = grade_cloze(response_text, row["answer"])
                    rating = grade.rating
                    score = grade.score
                    critical_mismatches = list(grade.critical_mismatches)
                    evaluation = "desktop_grade_cloze"

                occurred_at = effective_occurred.isoformat()
                plan = _persist_retrieval_attempt(
                    conn,
                    row=row,
                    attempt_id=event.event_id,
                    response_text=response_text,
                    rating=rating,
                    score=score,
                    elapsed_ms=event.elapsed_ms,
                    revealed_answer=True,
                    created_at=occurred_at,
                    plan_now=effective_occurred,
                    snapshot_status="portable_v0",
                )
                conn.execute(
                    "INSERT INTO study_events(event_type, entity_type, entity_id, payload_json, created_at) VALUES(?, ?, ?, ?, ?)",
                    (
                        "portable_attempt_imported",
                        "retrieval_attempt",
                        event.event_id,
                        json.dumps(
                            {
                                "protocol": STUDY_EVENTS_PROTOCOL,
                                "bundle_id": payload.bundle_id,
                                "pack_id": payload.pack_id,
                                "device": payload.device.model_dump(),
                                "reported_occurred_at": occurred.isoformat(),
                                "effective_occurred_at": occurred_at,
                                "received_at": received_at,
                                "item_id": event.item_id,
                                "item_version": event.item_version,
                                "base_last_attempt_id": event.base_last_attempt_id,
                                "evaluation": evaluation,
                                "rating": rating,
                                "score": score,
                            },
                            ensure_ascii=False,
                        ),
                        received_at,
                    ),
                )
                imported += 1
                results.append(
                    {
                        "event_id": event.event_id,
                        "status": "imported",
                        "item_id": event.item_id,
                        "item_type": row["item_type"],
                        "rating": rating,
                        "score": score,
                        "critical_mismatches": critical_mismatches,
                        "evaluation": evaluation,
                        "review": {
                            "mastery_status": plan.mastery_status,
                            "due_at": plan.due_at,
                            "interval_minutes": plan.interval_minutes,
                            "streak": plan.streak,
                            "lapses": plan.lapses,
                        },
                    }
                )

        db.event(
            "study_events_bundle_imported",
            "study_events_bundle",
            payload.bundle_id,
            {
                "protocol": payload.protocol,
                "pack_id": payload.pack_id,
                "device": payload.device.model_dump(),
                "event_count": len(payload.events),
                "imported": imported,
                "duplicates": duplicates,
                "conflicts": conflicts,
            },
        )
        return {
            "protocol": payload.protocol,
            "bundle_id": payload.bundle_id,
            "pack_id": payload.pack_id,
            "received_at": received_at,
            "summary": {"imported": imported, "duplicates": duplicates, "conflicts": conflicts},
            "results": results,
        }


    @app.get("/api/retrieval/summary")
    def retrieval_summary() -> dict[str, Any]:
        now = utc_now()
        with db.connect() as conn:
            counts = conn.execute(
                "SELECT COUNT(*) AS total, "
                "SUM(CASE WHEN item_type='flashcard' THEN 1 ELSE 0 END) AS flashcards, "
                "SUM(CASE WHEN item_type='cloze' THEN 1 ELSE 0 END) AS clozes "
                "FROM retrieval_items ri JOIN knowledge_units u ON u.id=ri.knowledge_unit_id "
                "WHERE ri.status='active' AND u.status!='archived'"
            ).fetchone()
            due = conn.execute(
                "SELECT COUNT(*) AS count FROM retrieval_items ri JOIN knowledge_units u ON u.id=ri.knowledge_unit_id "
                "LEFT JOIN retrieval_review_states rr ON rr.retrieval_item_id=ri.id "
                "WHERE ri.status='active' AND u.status!='archived' AND COALESCE(rr.due_at, ri.created_at) <= ?",
                (now,),
            ).fetchone()["count"]
            new_count = conn.execute(
                "SELECT COUNT(*) AS count FROM retrieval_items ri JOIN knowledge_units u ON u.id=ri.knowledge_unit_id "
                "LEFT JOIN retrieval_review_states rr ON rr.retrieval_item_id=ri.id "
                "WHERE ri.status='active' AND u.status!='archived' AND rr.last_attempt_id IS NULL"
            ).fetchone()["count"]
            attempt_metrics = conn.execute(
                "SELECT COUNT(*) AS attempts, COALESCE(AVG(score), 0) AS average_score, "
                "SUM(CASE WHEN substr(created_at, 1, 10)=substr(?, 1, 10) THEN 1 ELSE 0 END) AS reviewed_today "
                "FROM retrieval_attempts",
                (now,),
            ).fetchone()
        return {
            "total": int(counts["total"] or 0),
            "flashcards": int(counts["flashcards"] or 0),
            "clozes": int(counts["clozes"] or 0),
            "due": int(due or 0),
            "new": int(new_count or 0),
            "attempts": int(attempt_metrics["attempts"] or 0),
            "average_score": float(attempt_metrics["average_score"] or 0),
            "reviewed_today": int(attempt_metrics["reviewed_today"] or 0),
        }

    @app.get("/api/today")
    def today() -> dict[str, Any]:
        now = datetime.now(UTC).isoformat()
        with db.connect() as conn:
            due = conn.execute(
                "SELECT u.id, u.title, u.page_start, u.page_end, u.objective_type, s.original_name, "
                "r.mastery_status, r.due_at, r.last_score "
                "FROM review_states r JOIN knowledge_units u ON u.id=r.knowledge_unit_id AND r.unit_body_hash=u.body_hash AND r.knowledge_unit_version=u.version "
                "JOIN source_documents s ON s.id=u.source_id WHERE u.status!='archived' AND r.due_at <= ? ORDER BY r.due_at LIMIT 20",
                (now,),
            ).fetchall()
            active = conn.execute(
                "SELECT ss.id AS session_id, u.id AS unit_id, u.title, u.page_start, u.page_end, s.original_name, ss.started_at "
                "FROM study_sessions ss JOIN knowledge_units u ON u.id=ss.knowledge_unit_id "
                "JOIN source_documents s ON s.id=u.source_id WHERE ss.status='active' ORDER BY ss.last_activity_at DESC LIMIT 1"
            ).fetchone()
            suggested = conn.execute(
                "SELECT u.id, u.title, u.page_start, u.page_end, u.objective_type, s.original_name "
                "FROM knowledge_units u JOIN source_documents s ON s.id=u.source_id "
                "LEFT JOIN attempts a ON a.knowledge_unit_id=u.id AND a.unit_body_hash=u.body_hash AND a.unit_version=u.version "
                "WHERE a.id IS NULL AND u.status != 'archived' ORDER BY s.created_at, u.page_start LIMIT 8"
            ).fetchall()
            attempts_today = conn.execute(
                "SELECT COUNT(*) AS count FROM attempts WHERE substr(created_at, 1, 10)=substr(?, 1, 10)", (now,)
            ).fetchone()["count"]
            retrieval_due = conn.execute(
                RETRIEVAL_SELECT
                + " WHERE ri.status='active' AND u.status!='archived' AND COALESCE(rr.due_at, ri.created_at) <= ? "
                "ORDER BY COALESCE(rr.due_at, ri.created_at), ri.created_at LIMIT 8",
                (now,),
            ).fetchall()
            retrieval_attempts_today = conn.execute(
                "SELECT COUNT(*) AS count FROM retrieval_attempts WHERE substr(created_at, 1, 10)=substr(?, 1, 10)",
                (now,),
            ).fetchone()["count"]
        return {
            "active": dict(active) if active else None,
            "due": rows_to_dicts(due),
            "suggested": rows_to_dicts(suggested),
            "attempts_today": attempts_today,
            "retrieval_due": [_hydrate_retrieval_item(dict(row), include_answer=False) for row in retrieval_due],
            "retrieval_attempts_today": retrieval_attempts_today,
        }

    @app.get("/api/learning-model")
    def learning_model() -> dict[str, Any]:
        with db.connect() as conn:
            mastery = conn.execute(
                "SELECT r.mastery_status, COUNT(*) AS count FROM review_states r "
                "JOIN knowledge_units u ON u.id=r.knowledge_unit_id AND r.unit_body_hash=u.body_hash AND r.knowledge_unit_version=u.version "
                "WHERE u.status!='archived' GROUP BY r.mastery_status ORDER BY count DESC"
            ).fetchall()
            recurring = conn.execute(
                "SELECT er.error_type, er.detail, COUNT(*) AS count FROM error_records er "
                "JOIN knowledge_units u ON u.id=er.knowledge_unit_id "
                "JOIN attempts ea ON ea.id=er.attempt_id AND ea.unit_body_hash=u.body_hash AND ea.unit_version=u.version "
                "WHERE er.status IN ('open', 'repairing') AND u.status!='archived' "
                "GROUP BY er.error_type, er.detail ORDER BY count DESC, er.created_at DESC LIMIT 10"
            ).fetchall()
            metrics = conn.execute(
                "SELECT COUNT(*) AS attempts, COALESCE(AVG(score), 0) AS average_score, "
                "COALESCE(AVG(confidence), 0) AS average_confidence, COALESCE(AVG(elapsed_ms), 0) AS average_elapsed_ms, "
                "COALESCE(AVG(evidence_weight), 0) AS average_evidence_weight FROM attempts"
            ).fetchone()
            latest = conn.execute(
                "SELECT a.created_at, a.score, a.confidence, a.hint_level, u.title, s.original_name "
                "FROM attempts a JOIN knowledge_units u ON u.id=a.knowledge_unit_id "
                "JOIN source_documents s ON s.id=u.source_id ORDER BY a.created_at DESC LIMIT 10"
            ).fetchall()
            retrieval_metrics = conn.execute(
                "SELECT COUNT(*) AS attempts, COALESCE(AVG(score), 0) AS average_score, "
                "SUM(CASE WHEN rating='again' THEN 1 ELSE 0 END) AS again_count, "
                "SUM(CASE WHEN rating IN ('good', 'easy') THEN 1 ELSE 0 END) AS successful_count "
                "FROM retrieval_attempts"
            ).fetchone()
            repair_rows = conn.execute(
                "SELECT er.*, u.title AS unit_title, u.status AS unit_status, s.original_name "
                "FROM error_records er JOIN knowledge_units u ON u.id=er.knowledge_unit_id "
                "JOIN attempts ea ON ea.id=er.attempt_id AND ea.unit_body_hash=u.body_hash AND ea.unit_version=u.version "
                "JOIN source_documents s ON s.id=u.source_id "
                "WHERE er.status IN ('open', 'repairing') AND u.status!='archived' ORDER BY er.created_at DESC LIMIT 20"
            ).fetchall()
            repair_queue = [_hydrate_error_record(conn, row) for row in repair_rows]
        return {
            "mastery": rows_to_dicts(mastery),
            "recurring_errors": rows_to_dicts(recurring),
            "repair_queue": repair_queue,
            "metrics": dict(metrics),
            "retrieval_metrics": dict(retrieval_metrics),
            "latest_attempts": rows_to_dicts(latest),
            "model_note": "学习证据画像只聚合真实作答、自评卡片、提示和复测记录；当前不声称具有个体能力预测模型。",
        }

    @app.get("/api/export")
    def export_data() -> FileResponse:
        tables = [
            "user_profile",
            "source_documents",
            "source_pages",
            "knowledge_units",
            "knowledge_unit_versions",
            "study_sessions",
            "attempts",
            "error_records",
            "review_states",
            "retrieval_items",
            "retrieval_attempts",
            "retrieval_review_states",
            "study_events",
            "provider_runs",
        ]
        payload: dict[str, Any] = {
            "product": "law-study-workbench",
            "schema_version": settings.schema_version,
            "exported_at": utc_now(),
            "tables": {},
        }
        with db.connect() as conn:
            for table in tables:
                payload["tables"][table] = rows_to_dicts(conn.execute(f"SELECT * FROM {table}").fetchall())
        export_path = settings.export_dir / f"study-export-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}.json"
        export_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        db.event("data_exported", "export", export_path.name, {"path": str(export_path)})
        return FileResponse(export_path, media_type="application/json", filename=export_path.name)

    @app.get("/api/source-files/{source_id}")
    def source_file(source_id: str) -> FileResponse:
        with db.connect() as conn:
            row = conn.execute(
                "SELECT original_name, stored_path FROM source_documents WHERE id=?", (source_id,)
            ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="教材不存在")
        path = Path(row["stored_path"])
        if not path.exists():
            raise HTTPException(status_code=410, detail="本地教材文件已丢失")
        return FileResponse(path, media_type="application/pdf", filename=row["original_name"])

    @app.exception_handler(Exception)
    async def unhandled_exception(_, exc: Exception):
        # Never echo raw exception text to the client (may leak local paths /
        # internals). Log server-side; return a generic 500.
        import logging
        logging.getLogger("law-study").exception("unhandled error", exc_info=exc)
        return JSONResponse(status_code=500, content={"detail": "本地服务发生错误，请查看服务端日志"})

    app.mount("/", StaticFiles(directory=settings.static_dir, html=True), name="static")
    return app

