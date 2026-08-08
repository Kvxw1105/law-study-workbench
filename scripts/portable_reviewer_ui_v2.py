from __future__ import annotations

import os

import hashlib
import json
import tempfile
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
PORTABLE = ROOT / "portable-reviewer"
ARTIFACTS = ROOT / "artifacts"

PACK = {
    "protocol": "study-pack/0.1",
    "pack_id": "pack-ui-v2",
    "exported_at": "2026-08-08T10:00:00+00:00",
    "producer": {"product": "law-study-workbench", "version": "0.8.0"},
    "selection": {"mode": "due", "count": 2},
    "contract": {
        "event_protocol": "study-events/0.1",
        "authoritative_evaluation": "desktop-runtime",
        "state_sync": "attempt-events-only",
        "offline_capable": True,
    },
    "items": [
        {
            "id": "flash-ui-v2",
            "version": 1,
            "type": "flashcard",
            "content_hash": "ui-v2-flash-hash",
            "knowledge_unit_id": "unit-wuquan",
            "unit_title": "无权代理",
            "content": {
                "prompt": "善意相对人在无权代理中，什么时候可以行使撤销权？",
                "answer": "在被代理人追认前，善意相对人有权撤销。",
                "cloze_text": None,
            },
            "source": {
                "document_name": "民法教材.pdf",
                "page_start": 12,
                "page_end": 12,
                "excerpt": "善意相对人有权在被代理人追认前撤销。",
            },
            "review_base": {
                "last_attempt_id": None,
                "mastery_status": "新卡",
                "due_at": "2026-08-08T10:00:00+00:00",
                "interval_minutes": 0,
                "streak": 0,
                "lapses": 0,
            },
        },
        {
            "id": "cloze-ui-v2",
            "version": 1,
            "type": "cloze",
            "content_hash": "ui-v2-cloze-hash",
            "knowledge_unit_id": "unit-shanyi",
            "unit_title": "善意取得",
            "content": {
                "prompt": "填空：受让人在受让财产时为 ____。",
                "answer": "善意",
                "cloze_text": "受让人在受让财产时为 ____。",
            },
            "source": {
                "document_name": "民法教材.pdf",
                "page_start": 30,
                "page_end": 30,
                "excerpt": "受让人在受让该财产时为善意。",
            },
            "review_base": {
                "last_attempt_id": None,
                "mastery_status": "新卡",
                "due_at": "2026-08-08T10:00:00+00:00",
                "interval_minutes": 0,
                "streak": 0,
                "lapses": 0,
            },
        },
    ],
}


def canonical_hash(payload: dict) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


PACK["pack_hash"] = canonical_hash(PACK)


def bootstrap(page: Page, *, color_scheme: str, width: int, height: int, text_scale: float = 1.0) -> None:
    page.set_viewport_size({"width": width, "height": height})
    page.emulate_media(color_scheme=color_scheme)
    html = (PORTABLE / "index.html").read_text(encoding="utf-8")
    html = html.replace('<link rel="manifest" href="./manifest.webmanifest">', "")
    html = html.replace('<link rel="stylesheet" href="./styles.css">', "")
    html = html.replace('<script src="./app.js" defer></script>', "")
    page.set_content(html, wait_until="domcontentloaded")
    page.add_style_tag(path=str(PORTABLE / "styles.css"))
    if text_scale != 1.0:
        page.add_style_tag(content=f"html {{ font-size: {text_scale * 100:.0f}%; }}")
    page.add_script_tag(path=str(PORTABLE / "app.js"))


def assert_no_horizontal_overflow(page: Page) -> None:
    values = page.evaluate("() => ({sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth})")
    assert values["sw"] <= values["cw"] + 1, values


def assert_touch_targets(page: Page, selector: str) -> None:
    for locator in page.locator(selector).all():
        if not locator.is_visible():
            continue
        box = locator.bounding_box()
        assert box is not None
        assert box["height"] >= 44, (selector, box)


def main() -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8", delete=False) as handle:
        json.dump(PACK, handle, ensure_ascii=False)
        pack_path = Path(handle.name)

    outputs: list[Path] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH", "/usr/bin/chromium"), args=["--no-sandbox"])

        # 320 dark import: first-use clarity + narrow width.
        page = browser.new_page()
        bootstrap(page, color_scheme="dark", width=320, height=568)
        assert_no_horizontal_overflow(page)
        assert_touch_targets(page, ".file-button, button, input")
        page.keyboard.press("Tab")
        assert page.locator(".file-button").evaluate("el => el.matches(':focus-visible')")
        target = ARTIFACTS / "ui-portable-reviewer-v02-import-320-dark.png"
        page.screenshot(path=str(target), full_page=True)
        outputs.append(target)
        page.close()

        # 390 dark flashcard answer: answer reveal + rating ergonomics.
        page = browser.new_page()
        bootstrap(page, color_scheme="dark", width=390, height=844)
        page.locator("#packInput").set_input_files(str(pack_path))
        page.get_by_text("善意相对人在无权代理中", exact=False).wait_for(timeout=10000)
        page.get_by_role("button", name="显示答案").click()
        page.get_by_text("目标答案", exact=True).wait_for(timeout=10000)
        assert_touch_targets(page, "#ratingButtons button")
        assert_no_horizontal_overflow(page)
        target = ARTIFACTS / "ui-portable-reviewer-v02-flash-390-dark.png"
        page.screenshot(path=str(target), full_page=True)
        outputs.append(target)
        page.get_by_role("button", name="记得").click()
        assert page.locator("#sessionEventCount").inner_text() == "1 条待同步"
        page.close()

        # 430 light cloze: text scale + provisional feedback.
        page = browser.new_page()
        bootstrap(page, color_scheme="light", width=430, height=932, text_scale=1.2)
        page.locator("#packInput").set_input_files(str(pack_path))
        page.get_by_role("button", name="显示答案").click()
        page.get_by_role("button", name="记得").click()
        page.locator("#clozeInput").fill("善意")
        page.get_by_role("button", name="核对答案").click()
        page.get_by_text("离线字面核对：一致", exact=False).wait_for(timeout=10000)
        assert page.locator("#provisionalNote").evaluate("el => el.classList.contains('is-match')")
        assert_no_horizontal_overflow(page)
        assert_touch_targets(page, "button, input")
        target = ARTIFACTS / "ui-portable-reviewer-v02-cloze-430-light.png"
        page.screenshot(path=str(target), full_page=True)
        outputs.append(target)
        page.get_by_role("button", name="记录并下一题").click()
        page.get_by_text("这一轮已完成", exact=True).wait_for(timeout=10000)
        assert_no_horizontal_overflow(page)
        target = ARTIFACTS / "ui-portable-reviewer-v02-done-430-light.png"
        page.screenshot(path=str(target), full_page=True)
        outputs.append(target)
        page.close()

        # Reduced motion contract.
        page = browser.new_page()
        page.set_viewport_size({"width": 390, "height": 844})
        page.emulate_media(color_scheme="dark", reduced_motion="reduce")
        html = (PORTABLE / "index.html").read_text(encoding="utf-8")
        html = html.replace('<link rel="manifest" href="./manifest.webmanifest">', "")
        html = html.replace('<link rel="stylesheet" href="./styles.css">', "")
        html = html.replace('<script src="./app.js" defer></script>', "")
        page.set_content(html, wait_until="domcontentloaded")
        page.add_style_tag(path=str(PORTABLE / "styles.css"))
        page.add_script_tag(path=str(PORTABLE / "app.js"))
        page.locator("#packInput").set_input_files(str(pack_path))
        animation_name = page.locator(".practice-card").evaluate("el => getComputedStyle(el).animationName")
        assert animation_name == "none", animation_name
        page.close()

        browser.close()

    for output in outputs:
        print(output)


if __name__ == "__main__":
    main()
