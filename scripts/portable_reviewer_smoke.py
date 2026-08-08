from __future__ import annotations

import os

import hashlib
import json
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
PORTABLE = ROOT / "portable-reviewer"
ARTIFACT = ROOT / "artifacts" / "ui-portable-reviewer-v01.png"

PACK = {
    "protocol": "study-pack/0.1",
    "pack_id": "pack-browser-smoke",
    "exported_at": "2026-08-08T10:00:00+00:00",
    "producer": {"product": "law-study-workbench", "version": "0.8.0"},
    "selection": {"mode": "due", "count": 2},
    "contract": {"event_protocol": "study-events/0.1", "authoritative_evaluation": "desktop-runtime", "state_sync": "attempt-events-only", "offline_capable": True},
    "items": [
        {
            "id": "flash-smoke", "version": 1, "type": "flashcard", "content_hash": "12345678flash",
            "knowledge_unit_id": "unit-smoke", "unit_title": "无权代理",
            "content": {"prompt": "善意相对人何时可以撤销？", "answer": "被代理人追认前。", "cloze_text": None},
            "source": {"document_name": "民法教材.pdf", "page_start": 12, "page_end": 12, "excerpt": "善意相对人有权在被代理人追认前撤销。"},
            "review_base": {"last_attempt_id": None, "mastery_status": "新卡", "due_at": "2026-08-08T10:00:00+00:00", "interval_minutes": 0, "streak": 0, "lapses": 0},
        },
        {
            "id": "cloze-smoke", "version": 1, "type": "cloze", "content_hash": "12345678cloze",
            "knowledge_unit_id": "unit-smoke", "unit_title": "善意取得",
            "content": {"prompt": "填空：受让人在受让财产时为 ____。", "answer": "善意", "cloze_text": "受让人在受让财产时为 ____。"},
            "source": {"document_name": "民法教材.pdf", "page_start": 30, "page_end": 30, "excerpt": "受让人在受让该财产时为善意。"},
            "review_base": {"last_attempt_id": None, "mastery_status": "新卡", "due_at": "2026-08-08T10:00:00+00:00", "interval_minutes": 0, "streak": 0, "lapses": 0},
        },
    ],
}


def canonical_hash(payload: dict) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


PACK["pack_hash"] = canonical_hash(PACK)


def main() -> None:
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    html = (PORTABLE / "index.html").read_text(encoding="utf-8")
    html = html.replace('<link rel="manifest" href="./manifest.webmanifest">', "")
    html = html.replace('<link rel="stylesheet" href="./styles.css">', "")
    html = html.replace('<script src="./app.js" defer></script>', "")
    with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8", delete=False) as handle:
        json.dump(PACK, handle, ensure_ascii=False)
        pack_path = Path(handle.name)
    tampered = json.loads(json.dumps(PACK, ensure_ascii=False))
    tampered["items"][0]["content"]["answer"] = "被篡改的答案"
    with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8", delete=False) as handle:
        json.dump(tampered, handle, ensure_ascii=False)
        tampered_path = Path(handle.name)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH", "/usr/bin/chromium"), args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.set_content(html, wait_until="domcontentloaded")
        page.add_style_tag(path=str(PORTABLE / "styles.css"))
        page.add_script_tag(path=str(PORTABLE / "app.js"))
        with page.expect_event("dialog") as dialog_info:
            page.locator("#packInput").set_input_files(str(tampered_path))
        dialog = dialog_info.value
        assert "完整性校验失败" in dialog.message
        dialog.accept()
        page.locator("#packInput").set_input_files(str(pack_path))
        page.get_by_text("善意相对人何时可以撤销？").wait_for(timeout=10000)
        page.get_by_role("button", name="显示答案").click()
        page.get_by_role("button", name="记得").click()
        page.locator("#clozeInput").fill("善意")
        page.get_by_role("button", name="核对答案").click()
        page.get_by_text("离线字面核对：一致", exact=False).wait_for(timeout=10000)
        page.screenshot(path=str(ARTIFACT), full_page=True)
        page.get_by_role("button", name="记录并下一题").click()
        page.get_by_text("这一轮已完成").wait_for(timeout=10000)
        with page.expect_download() as download_info:
            page.get_by_role("button", name="导出 StudyEvents").click()
        target = Path(tempfile.gettempdir()) / "portable-events-smoke.json"
        download_info.value.save_as(str(target))
        payload = json.loads(target.read_text(encoding="utf-8"))
        assert payload["protocol"] == "study-events/0.1"
        assert payload["pack_hash"] == PACK["pack_hash"]
        assert len(payload["events"]) == 2
        assert payload["events"][0]["rating"] == "good"
        assert payload["events"][1]["response_text"] == "善意"
        assert payload["events"][1]["rating"] is None
        browser.close()
    print(ARTIFACT)


if __name__ == "__main__":
    main()
