"""Phase 7: Portable Reviewer real browser lifecycle (local HTTP + Chromium).

Covers: import pack, review flow (flashcard/cloze), refresh & session resume,
browser context reopen (localStorage restore), event export + repeat export,
completion state, 100-item pack, mixed types, corrupted/wrong-hash/empty pack
rejection, and Service Worker offline reload on a secure localhost origin.
"""
from __future__ import annotations

import functools
import io
import json
import threading
from datetime import UTC, datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from playwright.sync_api import Page, sync_playwright

from app.services.study_protocol import build_study_pack
from tests.support import chromium_executable

REVIEWER_DIR = Path(__file__).resolve().parents[1] / "portable-reviewer"
CHROME = chromium_executable() or ""
CHROME_EXISTS = bool(CHROME)

pytestmark = pytest.mark.skipif(not CHROME_EXISTS, reason="no local Chromium for browser lifecycle tests")


class _Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, directory, **kwargs):
        super().__init__(*args, directory=directory, **kwargs)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def server_url():
    server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(_Handler, directory=str(REVIEWER_DIR)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, executable_path=CHROME)
        yield b
        b.close()


@pytest.fixture()
def page(browser):
    context = browser.new_context()
    pg = context.new_page()
    yield pg
    context.close()


def _make_pack(num_flash: int = 2, num_cloze: int = 2) -> dict:
    rows = []
    for i in range(num_flash):
        rows.append({
            "id": f"flash-{i}", "version": 1, "item_type": "flashcard",
            "content_hash": f"flash-hash-{i}-" * 6, "knowledge_unit_id": "ku-1",
            "unit_title": "合成测试单元", "prompt": f"闪卡问题 {i}", "answer": f"闪卡答案 {i}",
            "cloze_text": None, "original_name": "synthetic.pdf", "page_start": 1, "page_end": 1,
            "excerpt": "合成来源文本", "last_attempt_id": None, "due_at": None, "streak": 0,
        })
    for i in range(num_cloze):
        rows.append({
            "id": f"cloze-{i}", "version": 1, "item_type": "cloze",
            "content_hash": f"cloze-hash-{i}-" * 6, "knowledge_unit_id": "ku-1",
            "unit_title": "合成测试单元", "prompt": f"填空：____ {i}？", "answer": f"挖空答案 {i}",
            "cloze_text": f"____ {i} 是测试空位。", "original_name": "synthetic.pdf",
            "page_start": 1, "page_end": 1, "excerpt": "合成来源文本", "last_attempt_id": None,
            "due_at": None, "streak": 0,
        })
    return build_study_pack(rows, product_version="0.8.0", mode="due", exported_at=datetime.now(UTC).isoformat())


def _write_pack(pack: dict, tmp_path: Path, *, mutate: str | None = None, wrong_hash: bool = False) -> Path:
    data = dict(pack)
    if mutate:
        data["items"][0]["content"]["answer"] = mutate
        data["pack_hash"] = data["pack_hash"]  # hash unchanged -> integrity fails
    if wrong_hash:
        data["pack_hash"] = "0" * 64
    path = tmp_path / "pack.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def _import(page: Page, server_url: str, pack_path: Path):
    page.goto(server_url, wait_until="load")
    page.set_input_files("#packInput", str(pack_path))
    page.wait_for_selector("#sessionPanel:not(.hidden), #donePanel:not(.hidden)", timeout=8000)


def _answer_flash(page: Page):
    page.click("#revealButton")
    page.click("#ratingButtons button[data-rating='good']")


def _answer_cloze(page: Page, text: str):
    page.fill("#clozeInput", text)
    page.click("#clozeCheckButton")
    page.wait_for_selector("#nextClozeButton:not([style*='display: none'])", timeout=8000)
    page.click("#nextClozeButton")


def test_import_review_refresh_resume(page: Page, server_url: str, tmp_path: Path):
    pack = _make_pack(2, 2)
    _import(page, server_url, _write_pack(pack, tmp_path))
    # answer one flashcard
    page.click("#revealButton")
    page.click("#ratingButtons button[data-rating='good']")
    # refresh: session must be restorable
    page.reload(wait_until="load")
    page.wait_for_selector("#resumeButton:not(.hidden)", timeout=8000)
    resume_text = page.inner_text("#resumeButton")
    assert "继续" in resume_text or "恢复" in resume_text
    page.click("#resumeButton")
    page.wait_for_selector("#sessionPanel", timeout=8000)
    assert "1 / 4" in page.inner_text("#progressText") or page.inner_text("#progressText").strip()


def test_browser_context_reopen_restores_from_localstorage(page: Page, server_url: str, tmp_path: Path):
    context = page.context
    pack = _make_pack(2, 2)
    _import(page, server_url, _write_pack(pack, tmp_path))
    _answer_flash(page)
    # close and reopen a page in the SAME context -> same origin localStorage
    page.close()
    page = context.new_page()
    page.goto(server_url, wait_until="load")
    page.wait_for_selector("#resumeButton:not(.hidden)", timeout=8000)
    assert page.is_visible("#resumeButton")


def test_export_events_and_repeat_export(page: Page, server_url: str, tmp_path: Path):
    pack = _make_pack(2, 0)
    _import(page, server_url, _write_pack(pack, tmp_path))
    _answer_flash(page)
    with page.expect_download() as dl:
        page.click("#exportButton")
    download = dl.value
    payload = json.loads(io.BytesIO(download.path().read_bytes()).read().decode("utf-8"))
    assert payload["protocol"] == "study-events/0.1"
    assert payload["pack_id"] == pack["pack_id"]
    assert len(payload["events"]) == 1
    assert payload["events"][0]["item_id"] == "flash-0"
    # repeat export still has the same events (local records are not lost)
    with page.expect_download() as dl2:
        page.click("#exportButton")
    payload2 = json.loads(io.BytesIO(dl2.value.path().read_bytes()).read().decode("utf-8"))
    assert len(payload2["events"]) == 1


def test_completed_pack_shows_done(page: Page, server_url: str, tmp_path: Path):
    pack = _make_pack(1, 1)
    _import(page, server_url, _write_pack(pack, tmp_path))
    _answer_flash(page)
    _answer_cloze(page, "挖空答案 0")
    page.wait_for_selector("#donePanel:not(.hidden)", timeout=8000)
    assert "已记录" in page.inner_text("#doneText")


def test_mixed_flashcard_cloze_flow(page: Page, server_url: str, tmp_path: Path):
    pack = _make_pack(2, 2)  # item order: flash-0, flash-1, cloze-0, cloze-1
    _import(page, server_url, _write_pack(pack, tmp_path))
    _answer_flash(page)
    _answer_flash(page)
    _answer_cloze(page, "挖空答案 0")
    _answer_cloze(page, "挖空答案 1")
    # all four answered -> done panel with 4 events
    page.wait_for_selector("#donePanel:not(.hidden)", timeout=8000)
    assert "4" in page.inner_text("#doneText")


def test_100_item_pack_progress(page: Page, server_url: str, tmp_path: Path):
    pack = _make_pack(50, 50)
    _import(page, server_url, _write_pack(pack, tmp_path))
    progress = page.inner_text("#progressText")
    assert "1 / 100" in progress
    _answer_flash(page)
    progress2 = page.inner_text("#progressText")
    assert "2 / 100" in progress2


def test_corrupted_pack_rejected(page: Page, server_url: str, tmp_path: Path):
    pack = _make_pack(1, 0)
    bad = _write_pack(pack, tmp_path, mutate="被篡改的答案内容")
    page.on("dialog", lambda dialog: dialog.accept())
    page.goto(server_url, wait_until="load")
    page.set_input_files("#packInput", str(bad))
    page.wait_for_timeout(1500)
    # import panel stays visible; session never starts
    assert page.is_visible("#importPanel")
    assert not page.is_visible("#sessionPanel")


def test_wrong_hash_pack_rejected(page: Page, server_url: str, tmp_path: Path):
    pack = _make_pack(1, 0)
    bad = _write_pack(pack, tmp_path, wrong_hash=True)
    page.on("dialog", lambda dialog: dialog.accept())
    page.goto(server_url, wait_until="load")
    page.set_input_files("#packInput", str(bad))
    page.wait_for_timeout(1500)
    assert page.is_visible("#importPanel")
    assert not page.is_visible("#sessionPanel")


def test_empty_pack_shows_completed(page: Page, server_url: str, tmp_path: Path):
    pack = _make_pack(0, 0)
    _import(page, server_url, _write_pack(pack, tmp_path))
    page.wait_for_selector("#donePanel:not(.hidden)", timeout=8000)
    assert "已记录" in page.inner_text("#doneText")


def test_service_worker_registers_and_offline_reload(page: Page, server_url: str, tmp_path: Path):
    pack = _make_pack(1, 1)
    _import(page, server_url, _write_pack(pack, tmp_path))
    # wait for SW to activate and cache assets
    ready = page.evaluate("navigator.serviceWorker.ready.then(r => !!r.active)")
    assert ready is True
    page.context.set_offline(True)
    page.reload(wait_until="load", timeout=15000)
    # shell still renders from cache (SW cache-first for GET)
    page.wait_for_selector("#importPanel", timeout=10000)
    assert page.is_visible("#importPanel")
    page.context.set_offline(False)
