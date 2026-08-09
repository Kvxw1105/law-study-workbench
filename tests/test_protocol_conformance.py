"""Phase 4: Study Protocol 0.1 adversarial / conformance suite.

Systematic attacks on study-pack/0.1 + study-events/0.1 beyond happy paths:
pack identity, item drift, event validation, clock edges, rating/reveal gates,
idempotency, bundle mixing, restart durability and concurrent imports.

Invariants asserted throughout:
  - duplicate event ids never create a second Attempt;
  - conflicts never silently modify ReviewState;
  - invalid events never earn mastery;
  - ReviewState is derived only by the desktop Runtime.
"""
from __future__ import annotations

import io
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.support import make_pdf

from app.config import Settings
from app.main import create_app

SOURCE_TEXT = (
    "善意取得应当具备下列条件：处分人为无处分权人；受让人在受让该财产时是善意；"
    "以合理价格转让；依法应当登记的已经登记，不需要登记的已经交付。"
)


def prepare_items(client: TestClient, *, max_per_type: int = 2) -> list[dict]:
    response = client.post(
        "/api/sources/import?wait=true",
        files={"file": ("portable.pdf", io.BytesIO(make_pdf()), "application/pdf")},
    )
    assert response.status_code == 200, response.text
    source = response.json()["source"]
    unit = client.get(f"/api/sources/{source['id']}/units").json()[0]
    generated = client.post(
        f"/api/units/{unit['id']}/retrieval-items/generate",
        json={"item_types": ["flashcard", "cloze"], "max_per_type": max_per_type},
    )
    assert generated.status_code == 200, generated.text
    return generated.json()["items"], unit


def export_pack(client: TestClient, **kw) -> dict:
    response = client.get("/api/study-pack/export?" + "&".join(f"{k}={v}" for k, v in kw.items()) or "/api/study-pack/export?mode=due&limit=50")
    assert response.status_code == 200, response.text
    return response.json()


def portable_event(item: dict, **overrides) -> dict:
    event = {
        "event_id": str(uuid4()),
        "event_type": "retrieval_attempt",
        "item_id": item["id"],
        "item_version": item["version"],
        "content_hash": item["content_hash"],
        "base_last_attempt_id": item["review_base"]["last_attempt_id"],
        "occurred_at": datetime.now(UTC).isoformat(),
        "response_text": "",
        "rating": None,
        "elapsed_ms": 1200,
        "revealed_answer": True,
    }
    event.update(overrides)
    return event


def bundle(pack: dict, events: list[dict], **overrides) -> dict:
    payload = {
        "protocol": "study-events/0.1",
        "bundle_id": str(uuid4()),
        "pack_id": pack["pack_id"],
        "pack_hash": pack["pack_hash"],
        "exported_at": datetime.now(UTC).isoformat(),
        "device": {"id": "phone-test", "label": "测试手机", "client": "portable-reviewer/0.1"},
        "events": events,
    }
    payload.update(overrides)
    return payload


def import_bundle(client: TestClient, payload: dict) -> dict:
    response = client.post("/api/study-events/import", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def flash_and_cloze(pack: dict) -> tuple[dict, dict]:
    flash = next(i for i in pack["items"] if i["type"] == "flashcard")
    cloze = next(i for i in pack["items"] if i["type"] == "cloze")
    return flash, cloze


# --------------------------------------------------------------------------
# Pack conformance
# --------------------------------------------------------------------------

def test_pack_mixed_types_roundtrip_baseline(client: TestClient):
    prepare_items(client)
    pack = export_pack(client)
    assert pack["protocol"] == "study-pack/0.1"
    assert pack["contract"]["state_sync"] == "attempt-events-only"
    assert pack["contract"]["authoritative_evaluation"] == "desktop-runtime"
    assert len(pack["items"]) >= 2
    assert {"flashcard", "cloze"}.issubset({i["type"] for i in pack["items"]})
    # pack_hash must be a sha256 hex
    assert len(pack["pack_hash"]) == 64


def test_pack_export_empty_library_rejected(client: TestClient):
    # No items exported from an empty library: 409, never an empty pack file
    response = client.get("/api/study-pack/export?mode=due&limit=50")
    assert response.status_code == 409
    assert "没有符合条件" in response.json()["detail"]


def test_pack_unicode_newlines_quotes_roundtrip(client: TestClient):
    items, unit = prepare_items(client)
    special = {
        "item_type": "cloze",
        "prompt": "多行引号测试：\"双引号\"、'单引号'、换行\n第二行、制表\t、中文标点：。；【】",
        "answer": "答案含特殊字符 \"'<>《》& 与换行\n第二行",
        "cloze_text": "受让人主观状态应为 ____。",
        "source_excerpt": "来源摘录含 中文、Unicode：𝕏 𝔸 𝕊𝕂𝕀𝟙 ✓",
    }
    created = client.post(
        f"/api/units/{unit['id']}/retrieval-items",
        json=special,
    )
    assert created.status_code == 200, created.text
    item = created.json()
    # product behavior: cloze prompt is derived from cloze_text
    assert item["prompt"] == f"填空：{special['cloze_text']}"
    pack = export_pack(client, mode="all", limit=100)
    packed = next(i for i in pack["items"] if i["id"] == item["id"])
    assert packed["content"]["answer"] == special["answer"]
    assert packed["content"]["prompt"] == item["prompt"]
    assert packed["source"]["excerpt"] == special["source_excerpt"]
    # and the item imports cleanly
    event = portable_event(packed, response_text=special["answer"])
    result = import_bundle(client, bundle(pack, [event]))
    assert result["summary"]["imported"] == 1


def test_pack_long_source_text_roundtrip(client: TestClient):
    items, unit = prepare_items(client)
    long_text = "证据规则示例。" + "法条引用与推理过程，" * 200
    created = client.post(
        f"/api/units/{unit['id']}/retrieval-items",
        json={
            "item_type": "cloze",
            "prompt": "长来源测试",
            "answer": "answer",
            "cloze_text": "填空 ____。",
            "source_excerpt": long_text,
        },
    )
    assert created.status_code == 200, created.text
    pack = export_pack(client, mode="all", limit=100)
    packed = next(i for i in pack["items"] if i["id"] == created.json()["id"])
    assert packed["source"]["excerpt"] == long_text


def test_event_content_hash_drift_conflict(client: TestClient):
    prepare_items(client)
    pack = export_pack(client)
    flash, _ = flash_and_cloze(pack)
    event = portable_event(flash, rating="good")
    event["content_hash"] = "0" * 64
    result = import_bundle(client, bundle(pack, [event]))
    assert result["summary"] == {"imported": 0, "duplicates": 0, "conflicts": 1}
    assert result["results"][0]["reason"] == "item_version_drift"
    assert client.get("/api/retrieval/summary").json()["attempts"] == 0


def test_event_item_version_drift_conflict(client: TestClient):
    prepare_items(client)
    pack = export_pack(client)
    flash, _ = flash_and_cloze(pack)
    event = portable_event(flash, rating="good")
    event["item_version"] = flash["version"] + 1
    result = import_bundle(client, bundle(pack, [event]))
    assert result["results"][0]["reason"] == "item_version_drift"


def test_event_item_inactive_archived_unit_conflict(client: TestClient):
    items, unit = prepare_items(client)
    pack = export_pack(client)
    flash, _ = flash_and_cloze(pack)
    archived = client.patch(f"/api/units/{unit['id']}", json={"status": "archived"})
    assert archived.status_code == 200, archived.text
    event = portable_event(flash, rating="good")
    result = import_bundle(client, bundle(pack, [event]))
    assert result["summary"]["conflicts"] == 1
    assert result["results"][0]["reason"] == "item_inactive"
    assert client.get("/api/retrieval/summary").json()["attempts"] == 0


# --------------------------------------------------------------------------
# Event conformance
# --------------------------------------------------------------------------

def test_event_duplicate_same_id_different_payload_is_duplicate(client: TestClient):
    prepare_items(client)
    pack = export_pack(client)
    flash, _ = flash_and_cloze(pack)
    event = portable_event(flash, rating="good")
    payload = bundle(pack, [event])
    assert import_bundle(client, payload)["summary"] == {"imported": 1, "duplicates": 0, "conflicts": 0}
    # same event_id, DIFFERENT payload (different rating/base) -> still duplicate, no overwrite
    clone = dict(event)
    clone["rating"] = "easy"
    clone["response_text"] = "改过的内容"
    second = import_bundle(client, bundle(pack, [clone]))
    assert second["summary"] == {"imported": 0, "duplicates": 1, "conflicts": 0}
    attempts = client.get("/api/export").json()["tables"]["retrieval_attempts"]
    assert len([a for a in attempts if a["id"] == event["event_id"]]) == 1
    # original rating survived
    assert [a for a in attempts if a["id"] == event["event_id"]][0]["rating"] == "good"


def test_event_unknown_item_missing_conflict(client: TestClient):
    prepare_items(client)
    pack = export_pack(client)
    event = portable_event(pack["items"][0], rating="good")
    event["item_id"] = "no-such-item"
    result = import_bundle(client, bundle(pack, [event]))
    assert result["results"][0]["reason"] == "item_missing"


def test_event_base_last_attempt_drift_conflict(client: TestClient):
    prepare_items(client)
    pack = export_pack(client)
    flash, _ = flash_and_cloze(pack)
    event = portable_event(flash, rating="good")
    event["base_last_attempt_id"] = "stale-base"
    result = import_bundle(client, bundle(pack, [event]))
    assert result["results"][0]["reason"] == "history_advanced"
    assert client.get("/api/retrieval/summary").json()["attempts"] == 0


def test_event_future_clock_within_tolerance_imports(client: TestClient):
    prepare_items(client)
    pack = export_pack(client)
    flash, _ = flash_and_cloze(pack)
    event = portable_event(flash, rating="good")
    event["occurred_at"] = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()
    result = import_bundle(client, bundle(pack, [event]))
    assert result["summary"] == {"imported": 1, "duplicates": 0, "conflicts": 0}


def test_event_future_clock_beyond_tolerance_conflict(client: TestClient):
    prepare_items(client)
    pack = export_pack(client)
    flash, _ = flash_and_cloze(pack)
    event = portable_event(flash, rating="good")
    event["occurred_at"] = (datetime.now(UTC) + timedelta(minutes=30)).isoformat()
    result = import_bundle(client, bundle(pack, [event]))
    assert result["results"][0]["reason"] == "invalid_event_time"


def test_event_cloze_missing_response_conflict(client: TestClient):
    prepare_items(client)
    pack = export_pack(client)
    _, cloze = flash_and_cloze(pack)
    event = portable_event(cloze, response_text="   ")
    result = import_bundle(client, bundle(pack, [event]))
    assert result["results"][0]["reason"] == "cloze_response_required"
    assert client.get("/api/retrieval/summary").json()["attempts"] == 0


def test_event_flashcard_without_reveal_conflict(client: TestClient):
    prepare_items(client)
    pack = export_pack(client)
    flash, _ = flash_and_cloze(pack)
    event = portable_event(flash, rating="good")
    event["revealed_answer"] = False
    result = import_bundle(client, bundle(pack, [event]))
    assert result["results"][0]["reason"] == "flashcard_requires_reveal_and_rating"


def test_event_flashcard_missing_rating_conflict(client: TestClient):
    prepare_items(client)
    pack = export_pack(client)
    flash, _ = flash_and_cloze(pack)
    event = portable_event(flash)
    event["rating"] = None
    result = import_bundle(client, bundle(pack, [event]))
    assert result["results"][0]["reason"] == "flashcard_requires_reveal_and_rating"


def test_event_cloze_wrong_answer_scores_low(client: TestClient):
    prepare_items(client)
    pack = export_pack(client)
    _, cloze = flash_and_cloze(pack)
    event = portable_event(cloze, response_text="完全不相关的回答")
    result = import_bundle(client, bundle(pack, [event]))
    assert result["summary"]["imported"] == 1
    payload = result["results"][0]
    assert payload["evaluation"] == "desktop_grade_cloze"
    assert payload["score"] <= 45
    assert payload["rating"] == "again"
    # a failed cloze must not earn progress/mastery: streak 0, 10-min retest, not stable
    assert payload["review"]["streak"] == 0
    assert payload["review"]["interval_minutes"] <= 10
    assert payload["review"]["mastery_status"] != "稳定"


def test_event_cloze_correct_answer_scores_high(client: TestClient):
    prepare_items(client)
    pack = export_pack(client)
    _, cloze = flash_and_cloze(pack)
    event = portable_event(cloze, response_text=cloze["content"]["answer"])
    result = import_bundle(client, bundle(pack, [event]))
    payload = result["results"][0]
    assert payload["score"] >= 90
    assert payload["rating"] == "good"


def test_event_flashcard_rating_boundaries(client: TestClient):
    prepare_items(client, max_per_type=4)
    pack = export_pack(client, mode="all", limit=50)
    flashcards = [i for i in pack["items"] if i["type"] == "flashcard"][:4]
    expected = {"again": 20.0, "hard": 60.0, "good": 85.0, "easy": 100.0}
    for item, (rating, score) in zip(flashcards, expected.items()):
        event = portable_event(item, rating=rating)
        result = import_bundle(client, bundle(pack, [event]))
        assert result["summary"]["imported"] == 1, result
        assert result["results"][0]["score"] == score, (rating, result["results"][0]["score"])


def test_event_mixed_valid_invalid_bundle(client: TestClient):
    prepare_items(client)
    pack = export_pack(client)
    flash, cloze = flash_and_cloze(pack)
    good = portable_event(flash, rating="good")
    bad_cloze = portable_event(cloze, response_text="")  # missing response
    dup = dict(good)
    dup["event_id"] = good["event_id"]
    result = import_bundle(client, bundle(pack, [good, bad_cloze, dup]))
    summary = result["summary"]
    assert summary["imported"] == 1
    assert summary["duplicates"] == 0
    assert summary["conflicts"] == 2
    reasons = {r["reason"] for r in result["results"] if r["status"] == "conflict"}
    assert reasons == {"cloze_response_required", "duplicate_event_in_bundle"}


def test_event_bundle_reimport_idempotent(client: TestClient):
    prepare_items(client)
    pack = export_pack(client)
    flash, cloze = flash_and_cloze(pack)
    events = [
        portable_event(flash, rating="good"),
        portable_event(cloze, response_text=cloze["content"]["answer"]),
    ]
    payload = bundle(pack, events)
    assert import_bundle(client, payload)["summary"]["imported"] == 2
    again = import_bundle(client, payload)
    assert again["summary"] == {"imported": 0, "duplicates": 2, "conflicts": 0}
    assert client.get("/api/retrieval/summary").json()["attempts"] == 2


def test_event_restart_import_idempotent(settings: Settings):
    # simulate runtime restart: a NEW app instance over the SAME data home
    first = TestClient(create_app(settings))
    with first:
        prepare_items(first)
        pack = export_pack(first)
        flash, _ = flash_and_cloze(pack)
        event = portable_event(flash, rating="good")
        payload = bundle(pack, [event])
        assert import_bundle(first, payload)["summary"]["imported"] == 1
    second = TestClient(create_app(settings))
    with second:
        again = import_bundle(second, payload)
        assert again["summary"] == {"imported": 0, "duplicates": 1, "conflicts": 0}
        assert second.get("/api/retrieval/summary").json()["attempts"] == 1


def test_event_invalid_time_naive_tz_conflict(client: TestClient):
    prepare_items(client)
    pack = export_pack(client)
    flash, _ = flash_and_cloze(pack)
    event = portable_event(flash, rating="good")
    event["occurred_at"] = datetime.now().isoformat()  # naive, no tz
    result = import_bundle(client, bundle(pack, [event]))
    assert result["summary"]["conflicts"] == 1
    assert result["results"][0]["reason"] == "invalid_event_time"


# --------------------------------------------------------------------------
# Concurrency / races
# --------------------------------------------------------------------------

def _concurrent_import(client: TestClient, payloads: list[dict]) -> list[dict]:
    outputs: list[dict] = [{} for _ in payloads]
    errors: list[Exception] = []

    def worker(payload: dict, idx: int):
        try:
            r = client.post("/api/study-events/import", json=payload)
            outputs[idx] = {"status": r.status_code, "body": r.json() if r.status_code == 200 else {"detail": r.text}}
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(p, i)) for i, p in enumerate(payloads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert not errors, errors
    return outputs


def test_two_devices_same_base_second_conflicts(client: TestClient):
    prepare_items(client)
    pack = export_pack(client)
    flash, _ = flash_and_cloze(pack)
    base = flash["review_base"]["last_attempt_id"]
    event_a = portable_event(flash, rating="good")
    event_a["event_id"] = "device-a-" + str(uuid4())
    event_b = portable_event(flash, rating="easy")
    event_b["event_id"] = "device-b-" + str(uuid4())
    assert import_bundle(client, bundle(pack, [event_a]))["summary"]["imported"] == 1
    # device B based on the same stale base -> history_advanced, no silent overwrite
    result = import_bundle(client, bundle(pack, [event_b]))
    assert result["summary"]["conflicts"] == 1
    assert result["results"][0]["reason"] == "history_advanced"
    attempts = client.get("/api/retrieval/summary").json()["attempts"]
    assert attempts == 1


def test_same_event_concurrent_import_single_attempt(client: TestClient):
    prepare_items(client)
    pack = export_pack(client)
    flash, _ = flash_and_cloze(pack)
    event = portable_event(flash, rating="good")
    payload = bundle(pack, [event])
    outputs = _concurrent_import(client, [payload, payload, payload])
    attempts = client.get("/api/retrieval/summary").json()["attempts"]
    assert attempts == 1, f"expected exactly 1 attempt, got {attempts}: {outputs}"


def test_same_bundle_concurrent_import_idempotent(client: TestClient):
    prepare_items(client)
    pack = export_pack(client)
    flash, cloze = flash_and_cloze(pack)
    events = [
        portable_event(flash, rating="good"),
        portable_event(cloze, response_text=cloze["content"]["answer"]),
    ]
    payload = bundle(pack, events)
    outputs = _concurrent_import(client, [payload, payload])
    attempts = client.get("/api/retrieval/summary").json()["attempts"]
    assert attempts == 2, f"expected exactly 2 attempts, got {attempts}: {outputs}"


def test_concurrent_distinct_events_both_imported(client: TestClient):
    prepare_items(client, max_per_type=4)
    pack = export_pack(client, mode="all", limit=50)
    items = pack["items"]
    flash = next((i for i in items if i["type"] == "flashcard"), None)
    cloze = next((i for i in items if i["type"] == "cloze"), None)
    assert flash is not None and cloze is not None, "需要至少一张闪卡与一张挖空卡构造并发事件"
    e1 = portable_event(flash, rating="good")
    e2 = portable_event(cloze, response_text=cloze["content"]["answer"])
    outputs = _concurrent_import(client, [bundle(pack, [e1]), bundle(pack, [e2])])
    assert all(o["status"] == 200 for o in outputs)
    attempts = client.get("/api/retrieval/summary").json()["attempts"]
    assert attempts == 2, f"expected 2 attempts, got {attempts}"
