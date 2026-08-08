from __future__ import annotations

import io
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import fitz
from fastapi.testclient import TestClient


SOURCE_TEXT = (
    "善意取得应当具备下列条件：处分人为无处分权人；受让人在受让该财产时是善意；"
    "以合理价格转让；依法应当登记的已经登记，不需要登记的已经交付。"
)


def make_pdf() -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_textbox(fitz.Rect(50, 60, 540, 760), SOURCE_TEXT, fontsize=12, fontname="china-s")
    payload = document.tobytes()
    document.close()
    return payload


def prepare_items(client: TestClient) -> list[dict]:
    response = client.post(
        "/api/sources/import?wait=true",
        files={"file": ("portable.pdf", io.BytesIO(make_pdf()), "application/pdf")},
    )
    assert response.status_code == 200, response.text
    source = response.json()["source"]
    unit = client.get(f"/api/sources/{source['id']}/units").json()[0]
    generated = client.post(
        f"/api/units/{unit['id']}/retrieval-items/generate",
        json={"item_types": ["flashcard", "cloze"], "max_per_type": 2},
    )
    assert generated.status_code == 200, generated.text
    return generated.json()["items"]


def export_pack(client: TestClient) -> dict:
    response = client.get("/api/study-pack/export?mode=due&limit=50")
    assert response.status_code == 200, response.text
    return response.json()


def portable_event(item: dict, *, response_text: str = "", rating: str | None = None, base_last_attempt_id=None) -> dict:
    return {
        "event_id": str(uuid4()),
        "event_type": "retrieval_attempt",
        "item_id": item["id"],
        "item_version": item["version"],
        "content_hash": item["content_hash"],
        "base_last_attempt_id": base_last_attempt_id,
        "occurred_at": datetime.now(UTC).isoformat(),
        "response_text": response_text,
        "rating": rating,
        "elapsed_ms": 1200,
        "revealed_answer": True,
    }


def bundle(pack: dict, events: list[dict]) -> dict:
    return {
        "protocol": "study-events/0.1",
        "bundle_id": str(uuid4()),
        "pack_id": pack["pack_id"],
        "pack_hash": pack["pack_hash"],
        "exported_at": datetime.now(UTC).isoformat(),
        "device": {"id": "phone-test", "label": "测试手机", "client": "portable-reviewer/0.1"},
        "events": events,
    }


def test_study_pack_contains_portable_items_without_database_dump(client: TestClient):
    prepare_items(client)
    pack = export_pack(client)
    assert pack["protocol"] == "study-pack/0.1"
    assert pack["contract"]["state_sync"] == "attempt-events-only"
    assert pack["selection"]["count"] >= 2
    assert "tables" not in pack
    types = {item["type"] for item in pack["items"]}
    assert {"flashcard", "cloze"}.issubset(types)
    for item in pack["items"]:
        assert item["content"]["answer"]
        assert item["content_hash"]
        assert "last_attempt_id" in item["review_base"]


def test_portable_events_roundtrip_regrades_cloze_and_is_idempotent(client: TestClient):
    prepare_items(client)
    pack = export_pack(client)
    flash = next(item for item in pack["items"] if item["type"] == "flashcard")
    cloze = next(item for item in pack["items"] if item["type"] == "cloze")
    events = [
        portable_event(flash, rating="good", base_last_attempt_id=flash["review_base"]["last_attempt_id"]),
        portable_event(
            cloze,
            response_text=cloze["content"]["answer"],
            base_last_attempt_id=cloze["review_base"]["last_attempt_id"],
        ),
    ]
    payload = bundle(pack, events)
    first = client.post("/api/study-events/import", json=payload)
    assert first.status_code == 200, first.text
    result = first.json()
    assert result["summary"] == {"imported": 2, "duplicates": 0, "conflicts": 0}
    flash_result = next(item for item in result["results"] if item["item_type"] == "flashcard")
    cloze_result = next(item for item in result["results"] if item["item_type"] == "cloze")
    assert flash_result["evaluation"] == "self_report"
    assert flash_result["score"] == 85
    assert cloze_result["evaluation"] == "desktop_grade_cloze"
    assert cloze_result["score"] == 100

    second = client.post("/api/study-events/import", json=payload)
    assert second.status_code == 200
    assert second.json()["summary"] == {"imported": 0, "duplicates": 2, "conflicts": 0}
    assert client.get("/api/retrieval/summary").json()["attempts"] == 2

    full_export = client.get("/api/export").json()
    attempts = full_export["tables"]["retrieval_attempts"]
    assert {row["snapshot_status"] for row in attempts} == {"portable_v0"}


def test_portable_import_rejects_history_that_advanced_after_pack_export(client: TestClient):
    prepare_items(client)
    pack = export_pack(client)
    flash = next(item for item in pack["items"] if item["type"] == "flashcard")

    reveal = client.post(f"/api/retrieval-items/{flash['id']}/reveal")
    assert reveal.status_code == 200
    online = client.post(
        f"/api/retrieval-items/{flash['id']}/attempts",
        json={"rating": "good", "elapsed_ms": 500, "revealed_answer": True},
    )
    assert online.status_code == 200

    event = portable_event(flash, rating="easy", base_last_attempt_id=flash["review_base"]["last_attempt_id"])
    imported = client.post("/api/study-events/import", json=bundle(pack, [event])).json()
    assert imported["summary"] == {"imported": 0, "duplicates": 0, "conflicts": 1}
    assert imported["results"][0]["reason"] == "history_advanced"


def test_portable_import_rejects_item_version_drift(client: TestClient):
    prepare_items(client)
    pack = export_pack(client)
    flash = next(item for item in pack["items"] if item["type"] == "flashcard")
    updated = client.patch(
        f"/api/retrieval-items/{flash['id']}",
        json={"answer": flash["content"]["answer"] + " 补充一个新的限定。"},
    )
    assert updated.status_code == 200

    event = portable_event(flash, rating="good", base_last_attempt_id=flash["review_base"]["last_attempt_id"])
    imported = client.post("/api/study-events/import", json=bundle(pack, [event])).json()
    assert imported["summary"]["conflicts"] == 1
    assert imported["results"][0]["reason"] == "item_version_drift"


def test_portable_import_rejects_future_clock(client: TestClient):
    prepare_items(client)
    pack = export_pack(client)
    flash = next(item for item in pack["items"] if item["type"] == "flashcard")
    event = portable_event(flash, rating="good", base_last_attempt_id=flash["review_base"]["last_attempt_id"])
    event["occurred_at"] = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
    imported = client.post("/api/study-events/import", json=bundle(pack, [event])).json()
    assert imported["summary"]["conflicts"] == 1
    assert imported["results"][0]["reason"] == "invalid_event_time"


def test_portable_import_requires_pack_identity_from_current_runtime(client: TestClient):
    prepare_items(client)
    pack = export_pack(client)
    flash = next(item for item in pack["items"] if item["type"] == "flashcard")
    event = portable_event(flash, rating="good", base_last_attempt_id=flash["review_base"]["last_attempt_id"])
    forged = bundle(pack, [event])
    forged["pack_id"] = "unknown-pack"
    response = client.post("/api/study-events/import", json=forged)
    assert response.status_code == 409
    assert "无法确认" in response.json()["detail"]

    mismatch = bundle(pack, [event])
    mismatch["pack_hash"] = "deadbeefdeadbeef"
    response = client.post("/api/study-events/import", json=mismatch)
    assert response.status_code == 409
    assert "身份校验失败" in response.json()["detail"]


def test_portable_import_rejects_event_that_predates_pack(client: TestClient):
    prepare_items(client)
    pack = export_pack(client)
    flash = next(item for item in pack["items"] if item["type"] == "flashcard")
    event = portable_event(flash, rating="good", base_last_attempt_id=flash["review_base"]["last_attempt_id"])
    event["occurred_at"] = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    imported = client.post("/api/study-events/import", json=bundle(pack, [event]))
    assert imported.status_code == 200
    assert imported.json()["summary"]["conflicts"] == 1
    assert imported.json()["results"][0]["reason"] == "event_predates_pack"


def test_portable_import_uses_effective_time_for_schedule_when_device_clock_is_slightly_behind(client: TestClient):
    prepare_items(client)
    pack = export_pack(client)
    flash = next(item for item in pack["items"] if item["type"] == "flashcard")
    event = portable_event(flash, rating="good", base_last_attempt_id=flash["review_base"]["last_attempt_id"])
    pack_time = datetime.fromisoformat(pack["exported_at"])
    event["occurred_at"] = (pack_time - timedelta(minutes=5)).isoformat()

    imported = client.post("/api/study-events/import", json=bundle(pack, [event]))
    assert imported.status_code == 200, imported.text
    result = imported.json()
    assert result["summary"] == {"imported": 1, "duplicates": 0, "conflicts": 0}

    attempt = next(
        row for row in client.get("/api/export").json()["tables"]["retrieval_attempts"]
        if row["id"] == event["event_id"]
    )
    created_at = datetime.fromisoformat(attempt["created_at"])
    due_at = datetime.fromisoformat(result["results"][0]["review"]["due_at"])
    assert created_at >= pack_time
    assert due_at >= created_at + timedelta(days=3) - timedelta(seconds=1)
