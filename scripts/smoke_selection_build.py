import os
# -*- coding: utf-8 -*-
"""划选建卡浏览器冒烟：打开单元审核 → 划选正文 → 浮动条 → 挖空/闪卡建卡。"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
from playwright.sync_api import sync_playwright

OUT = Path(r"D:\A-Project\1法学学习台\artifacts\walk")
OUT.mkdir(parents=True, exist_ok=True)
CHROME = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH", "")
BASE = "http://127.0.0.1:8765"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, executable_path=CHROME)
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    page.goto(BASE, wait_until="load", timeout=20000)
    page.wait_for_timeout(1200)
    page.screenshot(path=str(OUT / "u1-home.png"))
    print("home loaded:", page.title())

    # 教材库 → 打开第一个单元的审核对话框
    page.click("text=教材库", timeout=5000)
    page.wait_for_timeout(800)
    try:
        page.click('[data-action="review-unit"]', timeout=5000)
        print("unit dialog opened")
    except Exception as exc:
        print("review-unit click failed:", exc)
        page.screenshot(path=str(OUT / "u2-lib.png"))
        raise SystemExit(1)
    page.wait_for_timeout(800)
    page.screenshot(path=str(OUT / "u3-unit-dialog.png"))

    # 在正文 textarea 中划选一段文字（取正文中段，不依赖特定词）
    text = page.evaluate("""() => {
      const area = document.querySelector('#unitDialogText');
      const value = area.value;
      const idx = Math.min(80, Math.max(0, Math.floor(value.length / 2) - 4));
      if (value.length < 12) return null;
      area.focus();
      area.setSelectionRange(idx, idx + 8);
      area.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
      return value.slice(idx, idx + 8);
    }""")
    print("selected:", text)
    page.wait_for_timeout(600)
    builder_visible = page.evaluate("() => !document.querySelector('#unitSelectionBuilder').hidden")
    preview = page.evaluate("() => document.querySelector('#unitSelectionPreview')?.textContent || ''")
    print("builder visible:", builder_visible, "| preview:", preview)
    page.screenshot(path=str(OUT / "u4-selection.png"))

    # 点挖空 → 建卡
    before = page.evaluate("() => document.querySelectorAll('#retrievalManageList .unit-card').length")
    page.click('[data-action="selection-cloze"]', timeout=5000)
    page.wait_for_timeout(1200)
    toast_text = page.evaluate("() => document.querySelector('#toast')?.textContent || ''")
    print("toast:", toast_text)
    page.screenshot(path=str(OUT / "u5-after-cloze.png"))

    # 验证卡片真的创建成功：查 API
    created = page.evaluate("""async () => {
      const unitId = localStorage.getItem('unitDialogContextId') || '';
      const res = await fetch('/api/retrieval/summary');
      const data = await res.json();
      return { total: data.total, before: ${before} };
    }""")
    print("retrieval summary:", created)
    print("page errors:", errors[:3])
    browser.close()
