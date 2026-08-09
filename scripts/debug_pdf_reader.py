# -*- coding: utf-8 -*-
"""调试：轮询 PdfReader 状态时间线，定位高亮间歇性失败点。"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765/?v=dbg5"
CHROME = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH", "")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, executable_path=CHROME)
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    page.goto(BASE, wait_until="load", timeout=30000)
    page.wait_for_timeout(1000)
    page.click("nav button:nth-of-type(4)")
    page.wait_for_timeout(500)
    page.click("a.pdf-jump")

    for i in range(50):
        state = page.evaluate("""() => {
          const r = window.PdfReader;
          const status = document.querySelector('#pdfReaderStatus');
          return {
            page: r ? r.page : null,
            pages: r && r.pdfDoc ? r.pdfDoc.numPages : 0,
            rects: r ? r.locateRects.length : -1,
            locatePage: r ? r.locatePage : null,
            hasLastViewport: r ? !!r.lastViewport : false,
            hlCount: document.querySelectorAll('.pdf-highlight').length,
            statusText: status ? status.textContent : '',
            statusHidden: status ? status.hidden : true,
          };
        }""")
        line = f"[{i * 1}s] page={state['page']} pages={state['pages']} rects={state['rects']} locatePage={state['locatePage']} vp={state['hasLastViewport']} hl={state['hlCount']} status='{state['statusText']}' hidden={state['statusHidden']}"
        print(line)
        if state["hlCount"] > 0 or state["rects"] >= 0 and i > 3 and state["hlCount"] == 0:
            pass
        if i > 6 and state["hlCount"] > 0:
            break
        if i > 12:
            break
        page.wait_for_timeout(1000)
    browser.close()
