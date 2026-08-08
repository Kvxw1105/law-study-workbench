from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from app.db import Database, utc_now
from app.services.evidence_integrity import insert_unit_version, text_hash
from app.services.pdf_parser import build_units, parse_pdf


def process_source(db: Database, source_id: str, path: Path) -> None:
    with db.connect() as conn:
        source = conn.execute("SELECT * FROM source_documents WHERE id = ?", (source_id,)).fetchone()
        if source is None:
            return
        conn.execute(
            "UPDATE source_documents SET status='parsing', error_message=NULL, updated_at=? WHERE id=?",
            (utc_now(), source_id),
        )
    db.event("source_parsing_started", "source_document", source_id)

    def progress(processed: int, total: int) -> None:
        with db.connect() as conn:
            conn.execute(
                "UPDATE source_documents SET processed_pages=?, page_count=?, updated_at=? WHERE id=?",
                (processed, total, utc_now(), source_id),
            )

    try:
        pages, quality = parse_pdf(path, progress=progress)
        units = build_units(pages)
        now = utc_now()
        with db.connect() as conn:
            conn.execute("DELETE FROM source_pages WHERE source_id=?", (source_id,))
            conn.execute("DELETE FROM knowledge_units WHERE source_id=?", (source_id,))
            conn.executemany(
                "INSERT INTO source_pages(id, source_id, page_number, text, text_hash, quality_status, created_at) "
                "VALUES(?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        str(uuid4()),
                        source_id,
                        page.page_number,
                        page.text,
                        page.text_hash,
                        page.quality_status,
                        now,
                    )
                    for page in pages
                ],
            )
            conn.executemany(
                "INSERT INTO knowledge_units(id, source_id, title, body, body_hash, source_basis_text, source_basis_hash, source_basis_status, "
                "page_start, page_end, objective_type, status, version, created_at, updated_at) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, 'parser_generated', ?, ?, ?, 'draft', 1, ?, ?)",
                [
                    (
                        unit.id,
                        source_id,
                        unit.title,
                        unit.body,
                        text_hash(unit.body),
                        unit.body,
                        text_hash(unit.body),
                        unit.page_start,
                        unit.page_end,
                        unit.objective_type,
                        now,
                        now,
                    )
                    for unit in units
                ],
            )
            for unit in units:
                stored_unit = conn.execute("SELECT * FROM knowledge_units WHERE id=?", (unit.id,)).fetchone()
                insert_unit_version(conn, stored_unit, snapshot_status="captured", created_at=now)
            status = "ready" if units else "needs_attention"
            conn.execute(
                "UPDATE source_documents SET status=?, page_count=?, processed_pages=?, quality_json=?, updated_at=? WHERE id=?",
                (status, len(pages), len(pages), json.dumps(quality, ensure_ascii=False), now, source_id),
            )
        db.event(
            "source_parsing_completed",
            "source_document",
            source_id,
            {"pages": len(pages), "units": len(units), "quality": quality},
        )
    except Exception as exc:
        with db.connect() as conn:
            conn.execute(
                "UPDATE source_documents SET status='failed', error_message=?, updated_at=? WHERE id=?",
                (str(exc), utc_now(), source_id),
            )
        db.event("source_parsing_failed", "source_document", source_id, {"error": str(exc)})
        raise
