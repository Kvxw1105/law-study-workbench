# -*- coding: utf-8 -*-
"""验收：点卡片→阅读器→滚动到原句位置 + 高亮可见。

验证点（对应用户质疑）：
1. 阅读器打开且渲染目标页（pageLabel）
2. 滚动容器 .pdf-viewer-body 的 scrollTop > 0（真的滚了）
3. 高亮元素 .pdf-highlight 存在，且其 boundingBox 在滚动容器可视区内
4. 截图 + 视觉确认高亮可见
"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765/?v=accept1"
CHROME = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH", "")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, executable_path=CHROME)
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)[:180]))
    page.goto(BASE, wait_until="load", timeout=30000)
    page.wait_for_timeout(1200)
    page.click("nav button:nth-of-type(4)")
    page.wait_for_timeout(600)
    page.click("a.pdf-jump")

    # 等待阅读器完成（渲染 + 定位 + 高亮）
    page.wait_for_selector(".pdf-highlight", timeout=45000)
    page.wait_for_timeout(800)  # 等 scrollIntoView smooth 完成

    result = page.evaluate("""() => {
      const scroller = document.querySelector('.pdf-viewer-body');
      const hl = document.querySelector('.pdf-highlight');
      const canvas = document.querySelector('#pdfReaderCanvas');
      const pageLabel = document.querySelector('#pdfViewerPage').textContent;
      const r = hl.getBoundingClientRect();
      const s = scroller.getBoundingClientRect();
      const dialog = document.querySelector('#pdfViewerDialog').getBoundingClientRect();
      return {
        pageLabel,
        scrollTop: scroller.scrollTop,
        scrollHeight: scroller.scrollHeight,
        clientHeight: scroller.clientHeight,
        highlight: { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) },
        scrollerBox: { top: Math.round(s.top), bottom: Math.round(s.bottom) },
        dialogBox: { top: Math.round(dialog.top), bottom: Math.round(dialog.bottom) },
        canvas: { w: canvas.width, h: canvas.height },
        highlightInViewport: r.top >= s.top - 5 && r.bottom <= s.bottom + 5,
      };
    }""")
    print("=== 验收结果 ===")
    for key, value in result.items():
        print(f"  {key}: {value}")

    # 主动滚动验证：把高亮滚出视口，再调用 scrollToHighlight，确认滚回居中
    moved = page.evaluate("""() => {
      const scroller = document.querySelector('.pdf-viewer-body');
      scroller.scrollTop = 600;
      return scroller.scrollTop;
    }""")
    print(f"  [scroll-test] after scrollTop=600: {moved}")
    page.evaluate("() => { window.PdfReader.scrollToHighlight(); }")
    page.wait_for_timeout(900)  # smooth 滚动
    back = page.evaluate("""() => {
      const scroller = document.querySelector('.pdf-viewer-body');
      const hl = document.querySelector('.pdf-highlight').getBoundingClientRect();
      const s = scroller.getBoundingClientRect();
      const center = s.top + s.height / 2;
      return {
        scrollTop: Math.round(scroller.scrollTop),
        highlightY: Math.round(hl.top + hl.height / 2),
        scrollerCenter: Math.round(center),
        scrolledBackToCenter: Math.abs(hl.top + hl.height / 2 - center) < 120,
      };
    }""")
    print(f"  [scroll-test] after scrollToHighlight: {back}")
    page.screenshot(path=r"D:\A-Project\1法学学习台\artifacts\walk\accept-reader-scrolled.png")
    print("  screenshot: artifacts/walk/accept-reader-scrolled.png")
    page.screenshot(path=r"D:\A-Project\1法学学习台\artifacts\walk\accept-reader.png")
    print("  screenshot: artifacts/walk/accept-reader.png")
    print("  pageerrors:", errors[:3])
    browser.close()
