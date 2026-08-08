from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

STUDY_PACK_PROTOCOL = "study-pack/0.1"
STUDY_EVENTS_PROTOCOL = "study-events/0.1"
PORTABLE_REVIEWER_VERSION = "0.1.0"


def _canonical_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def build_study_pack(
    rows: list[dict[str, Any]],
    *,
    product_version: str,
    mode: str,
    exported_at: str,
) -> dict[str, Any]:
    pack_id = str(uuid4())
    items: list[dict[str, Any]] = []
    for row in rows:
        items.append(
            {
                "id": row["id"],
                "version": int(row.get("version") or 1),
                "type": row["item_type"],
                "content_hash": row["content_hash"],
                "knowledge_unit_id": row["knowledge_unit_id"],
                "unit_title": row.get("unit_title") or "",
                "content": {
                    "prompt": row["prompt"],
                    "answer": row["answer"],
                    "cloze_text": row.get("cloze_text"),
                },
                "source": {
                    "document_name": row.get("original_name") or "",
                    "page_start": int(row.get("page_start") or 1),
                    "page_end": int(row.get("page_end") or row.get("page_start") or 1),
                    "excerpt": row.get("source_excerpt") or "",
                },
                "review_base": {
                    "last_attempt_id": row.get("last_attempt_id"),
                    "mastery_status": row.get("mastery_status") or "新卡",
                    "due_at": row.get("due_at") or row.get("created_at"),
                    "interval_minutes": int(row.get("interval_minutes") or 0),
                    "streak": int(row.get("streak") or 0),
                    "lapses": int(row.get("lapses") or 0),
                },
            }
        )
    payload: dict[str, Any] = {
        "protocol": STUDY_PACK_PROTOCOL,
        "pack_id": pack_id,
        "exported_at": exported_at,
        "producer": {"product": "law-study-workbench", "version": product_version},
        "selection": {"mode": mode, "count": len(items)},
        "contract": {
            "event_protocol": STUDY_EVENTS_PROTOCOL,
            "authoritative_evaluation": "desktop-runtime",
            "state_sync": "attempt-events-only",
            "offline_capable": True,
        },
        "items": items,
    }
    payload["pack_hash"] = _canonical_hash(payload)
    return payload


def validate_event_time(value: datetime, *, server_now: datetime | None = None) -> datetime:
    if value.tzinfo is None:
        raise ValueError("occurred_at 必须包含时区")
    normalized = value.astimezone(UTC)
    now = server_now or datetime.now(UTC)
    if normalized > now + timedelta(minutes=10):
        raise ValueError("occurred_at 不能明显晚于当前服务器时间")
    return normalized
