# -*- coding: utf-8 -*-
"""检查 canvas 是否真有内容 + 字体/cMap 警告是否消除。"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765/?v=dbg4"
CHROME = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH", "")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, executable_path=CHROME)
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    warnings = []
    page.on("console", lambda m: warnings.append(f"[{m.type}] {m.text[:130]}") if m.type in ("warning", "error") else None)
    page.goto(BASE, wait_until="load", timeout=30000)
    page.wait_for_timeout(1000)
    page.click("nav button:nth-of-type(4)")
    page.wait_for_timeout(600)
    page.click("a.pdf-jump")
    page.wait_for_selector(".pdf-highlight", timeout=45000)
    page.wait_for_timeout(1500)
    stats = page.evaluate("""() => {
      const c = document.querySelector('#pdfReaderCanvas');
      if (!c) return { error: 'no canvas' };
      const ctx = c.getContext('2d');
      const d = ctx.getImageData(0, 0, c.width, c.height).data;
      let nonBlank = 0, total = 0;
      for (let i = 0; i < d.length; i += 16) {
        total++;
        if (d[i] < 250 || d[i + 1] < 250 || d[i + 2] < 250) nonBlank++;
      }
      return { w: c.width, h: c.height, samples: total, nonBlankSamples: nonBlank, pct: (nonBlank / total * 100).toFixed(1) };
    }""")
    print("canvas stats:", stats)
    print("--- warnings ---")
    for w in warnings[:10]:
        print(w)
    browser.close()
