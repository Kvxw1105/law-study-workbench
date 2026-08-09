# -*- coding: utf-8 -*-
"""验证自研阅读器高亮 DOM：定位命中后 .pdf-highlight 出现且坐标正确。"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765/?v=dbg3"
CHROME = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH", "")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, executable_path=CHROME)
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    page.goto(BASE, wait_until="load", timeout=30000)
    page.wait_for_timeout(1000)
    page.click("nav button:nth-of-type(4)")
    page.wait_for_timeout(600)
    page.click("a.pdf-jump")
    page.wait_for_selector(".pdf-highlight", timeout=45000)
    hl = page.evaluate("""() => {
      const els = Array.from(document.querySelectorAll('.pdf-highlight'));
      const canvas = document.querySelector('#pdfReaderCanvas');
      const pageLabel = document.querySelector('#pdfViewerPage').textContent;
      return {
        count: els.length,
        first: els[0] ? { left: els[0].style.left, top: els[0].style.top, w: els[0].style.width, h: els[0].style.height } : null,
        pageLabel,
        canvasW: canvas ? canvas.width : 0,
        canvasH: canvas ? canvas.height : 0,
      };
    }""")
    print("highlight:", hl)
    out = r"D:\A-Project\1法学学习台\artifacts\walk\reader-highlight.png"
    page.screenshot(path=out)
    print("screenshot:", out)
    browser.close()
