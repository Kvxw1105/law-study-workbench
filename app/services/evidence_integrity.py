from __future__ import annotations

import hashlib
import json
import sqlite3
import re
from difflib import SequenceMatcher
from dataclasses import dataclass
from typing import Any


def text_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def version_id(unit_id: str, version: int) -> str:
    return f"{unit_id}:v{int(version)}"


def base_unit_snapshot(unit: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    data = dict(unit)
    return {
        "knowledge_unit_id": data["id"],
        "source_id": data["source_id"],
        "version": int(data.get("version") or 1),
        "title": data["title"],
        "body": data["body"],
        "body_hash": data.get("body_hash") or text_hash(data["body"]),
        "source_basis_text": data.get("source_basis_text") or "",
        "source_basis_hash": data.get("source_basis_hash") or "",
        "source_basis_status": data.get("source_basis_status") or "unknown",
        "page_start": int(data["page_start"]),
        "page_end": int(data["page_end"]),
        "objective_type": data["objective_type"],
    }


def capture_source_anchor(conn: sqlite3.Connection, unit: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    data = dict(unit)
    pages = conn.execute(
        "SELECT page_number, text_hash FROM source_pages WHERE source_id=? AND page_number BETWEEN ? AND ? ORDER BY page_number",
        (data["source_id"], int(data["page_start"]), int(data["page_end"])),
    ).fetchall()
    source = conn.execute(
        "SELECT content_hash, parser_version FROM source_documents WHERE id=?",
        (data["source_id"],),
    ).fetchone()
    return {
        "source_id": data["source_id"],
        "page_start": int(data["page_start"]),
        "page_end": int(data["page_end"]),
        "page_hashes": [
            {"page_number": int(page["page_number"]), "text_hash": page["text_hash"]}
            for page in pages
        ],
        "document_hash": source["content_hash"] if source else "",
        "parser_version": source["parser_version"] if source else "",
    }


def capture_session_snapshot(conn: sqlite3.Connection, unit: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    snapshot = base_unit_snapshot(unit)
    snapshot["source_anchor"] = capture_source_anchor(conn, unit)
    return snapshot


def insert_unit_version(
    conn: sqlite3.Connection,
    unit: sqlite3.Row | dict[str, Any],
    *,
    snapshot_status: str = "captured",
    created_at: str,
) -> None:
    snapshot = base_unit_snapshot(unit)
    conn.execute(
        "INSERT OR REPLACE INTO knowledge_unit_versions("
        "id, knowledge_unit_id, version, title, body, body_hash, source_basis_text, source_basis_hash, "
        "source_basis_status, page_start, page_end, objective_type, snapshot_status, created_at"
        ") VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            version_id(snapshot["knowledge_unit_id"], snapshot["version"]),
            snapshot["knowledge_unit_id"],
            snapshot["version"],
            snapshot["title"],
            snapshot["body"],
            snapshot["body_hash"],
            snapshot["source_basis_text"],
            snapshot["source_basis_hash"],
            snapshot["source_basis_status"],
            snapshot["page_start"],
            snapshot["page_end"],
            snapshot["objective_type"],
            snapshot_status,
            created_at,
        ),
    )


def parse_snapshot(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _compact(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", text or "").lower()


def locate_page_range(
    conn: sqlite3.Connection,
    *,
    source_id: str,
    text: str,
    fallback_start: int,
    fallback_end: int,
) -> tuple[int, int, str]:
    target = _compact(text)
    if not target:
        return fallback_start, fallback_end, "source_anchor_pending"
    pages = conn.execute(
        "SELECT page_number, text FROM source_pages WHERE source_id=? AND page_number BETWEEN ? AND ? ORDER BY page_number",
        (source_id, fallback_start, fallback_end),
    ).fetchall()
    matched: list[int] = []
    minimum_match = min(40, max(16, int(len(target) * 0.08)))
    for page in pages:
        page_text = _compact(page["text"])
        if not page_text:
            continue
        match = SequenceMatcher(None, page_text, target, autojunk=False).find_longest_match(0, len(page_text), 0, len(target))
        if match.size >= minimum_match:
            matched.append(int(page["page_number"]))
    if not matched:
        return fallback_start, fallback_end, "source_anchor_pending"
    return min(matched), max(matched), "localized_from_source_pages"


@dataclass(frozen=True)
class EvidenceVerdict:
    status: str
    effective_score: float
    mastery_status: str
    interval_days: int
    reason: str
    hard_conflicts: tuple[dict[str, Any], ...]
    possible_conflicts: tuple[dict[str, Any], ...]
    structure_warning: bool
    method_runtime_status: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "effective_score": self.effective_score,
            "mastery_status": self.mastery_status,
            "interval_days": self.interval_days,
            "reason": self.reason,
            "hard_conflicts": list(self.hard_conflicts),
            "possible_conflicts": list(self.possible_conflicts),
            "structure_warning": self.structure_warning,
            "method_runtime_status": self.method_runtime_status,
        }


def derive_evidence_verdict(
    *,
    provider_score: float,
    evidence_weight: float,
    confidence: int,
    method_pack_snapshot: dict[str, Any],
) -> EvidenceVerdict:
    from app.services.scheduler import review_plan

    dimensions = method_pack_snapshot.get("dimension_results") or []
    hard_conflicts: list[dict[str, Any]] = []
    possible_conflicts: list[dict[str, Any]] = []
    structure_warning = False
    for dimension in dimensions:
        structure_warning = structure_warning or bool(dimension.get("structure_warning"))
        for conflict in dimension.get("critical_conflicts") or []:
            hard_conflicts.append({"dimension_id": dimension.get("id"), **conflict})
        for conflict in dimension.get("possible_conflicts") or []:
            possible_conflicts.append({"dimension_id": dimension.get("id"), **conflict})

    runtime_status = (method_pack_snapshot.get("method_pack") or {}).get("runtime_status", "unknown")
    raw = round(max(0.0, min(100.0, float(provider_score))), 1)

    if hard_conflicts:
        return EvidenceVerdict(
            status="blocked_critical",
            effective_score=min(raw, 45.0),
            mastery_status="需立即修复",
            interval_days=0,
            reason="检测到可靠的关键法律冲突，本轮证据被阻断；修正后立即重新闭卷。",
            hard_conflicts=tuple(hard_conflicts),
            possible_conflicts=tuple(possible_conflicts),
            structure_warning=structure_warning,
            method_runtime_status=runtime_status,
        )
    if structure_warning:
        return EvidenceVerdict(
            status="blocked_structure",
            effective_score=min(raw, 55.0),
            mastery_status="学习中",
            interval_days=1,
            reason="答案呈关键词堆砌或结构证据不足，本轮不能进入稳定状态；请用完整语句重答。",
            hard_conflicts=(),
            possible_conflicts=tuple(possible_conflicts),
            structure_warning=True,
            method_runtime_status=runtime_status,
        )
    if possible_conflicts or runtime_status != "completed":
        return EvidenceVerdict(
            status="needs_verification",
            effective_score=raw,
            mastery_status="待核验",
            interval_days=1,
            reason="存在待核对关系或诊断降级，本轮保留作答证据，但不写入稳定掌握。",
            hard_conflicts=(),
            possible_conflicts=tuple(possible_conflicts),
            structure_warning=False,
            method_runtime_status=runtime_status,
        )

    mastery_status, interval_days, reason = review_plan(raw, evidence_weight, confidence)
    return EvidenceVerdict(
        status="accepted",
        effective_score=raw,
        mastery_status=mastery_status,
        interval_days=interval_days,
        reason=reason,
        hard_conflicts=(),
        possible_conflicts=(),
        structure_warning=False,
        method_runtime_status=runtime_status,
    )
