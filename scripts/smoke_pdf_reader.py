# -*- coding: utf-8 -*-
"""排查 pdf.js 加载 44MB PDF 的 numPages/定位问题（playwright 独立验证）。"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765/?v=dbg"
CHROME = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH", "")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, executable_path=CHROME)
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    logs = []
    page.on("console", lambda m: logs.append(f"[{m.type}] {m.text[:150]}"))
    page.on("pageerror", lambda e: logs.append(f"[pageerror] {str(e)[:200]}"))

    page.goto(BASE, wait_until="load", timeout=30000)
    page.wait_for_timeout(1200)
    page.click("nav button:nth-of-type(4)")  # 卡片
    page.wait_for_timeout(800)
    page.click("a.pdf-jump")  # 第一张卡
    print("clicked pdf-jump")

    # 等待阅读器就绪（最多 40s）
    for _ in range(40):
        state = page.evaluate("""() => {
          const r = window.PdfReader;
          return r ? { hasDoc: !!r.pdfDoc, pages: r.pdfDoc ? r.pdfDoc.numPages : 0, page: r.page, rects: r.locateRects.length, status: document.querySelector('#pdfReaderStatus')?.textContent || '', statusHidden: document.querySelector('#pdfReaderStatus')?.hidden } : null;
        }""")
        if state and state["hasDoc"] and state["pages"] > 1:
            break
        page.wait_for_timeout(1000)
    print("reader state:", state)
    print("--- logs ---")
    for line in logs[:12]:
        print(line)
    browser.close()
