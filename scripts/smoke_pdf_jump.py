import os
# -*- coding: utf-8 -*-
"""PDF 跳转与原文去重冒烟：链接存在性 + href 正确性 + attempt 响应 source_id。"""
import sys

sys.stdout.reconfigure(encoding="utf-8")
import httpx
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765"
CHROME = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH", "")

c = httpx.Client(base_url=BASE, timeout=30)
srcs = c.get("/api/sources").json()
real = [s for s in srcs if "2025民法" in s.get("original_name", "")][0]
units = c.get(f"/api/sources/{real['id']}/units").json()
u = next((x for x in units if "民法的渊源" in x.get("title", "")), None)
print("unit:", u["id"][:8], "| source:", real["id"][:8], "| pages:", u["page_start"], "-", u["page_end"])

# 1) attempt 响应含 source_id（后端修复验证）
sess = c.post(f"/api/units/{u['id']}/sessions", json={"approve_unit": True}).json()
sess_id = sess["session"]["id"]
att = c.post(f"/api/sessions/{sess_id}/attempts", json={"answer_text": "民法的渊源", "confidence": 60, "elapsed_ms": 3000}).json()
print("session attempt ok, source_id in response:", "source_id" in att)

# 2) 浏览器链接检查
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, executable_path=CHROME)
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    page.goto(BASE, wait_until="load", timeout=20000)
    page.wait_for_timeout(1000)

    # 教材库选中来源 → 打开原 PDF 链接
    page.click("text=教材库", timeout=5000)
    page.wait_for_timeout(600)
    pdf_links = page.evaluate("() => Array.from(document.querySelectorAll('a[href*=\"source-files\"]')).map(a => a.href)")
    print("library pdf links:", len(pdf_links))
    for link in pdf_links[:2]:
        print("   ", link[:80])

    # 打开单元对话框 → 在 PDF 中打开本单元（含 #page）
    try:
        page.click('[data-action="review-unit"]', timeout=5000)
        page.wait_for_timeout(600)
        unit_links = page.evaluate("() => Array.from(document.querySelectorAll('.pdf-jump')).map(a => ({text: a.textContent, href: a.href}))")
        print("unit dialog pdf-jump:", unit_links)
    except Exception as exc:
        print("unit dialog open failed:", exc)

    # 卡片管理 → 在 PDF 中查看
    page.evaluate("() => { document.querySelector('[data-action=\"close-unit-dialog\"]')?.click(); }")
    page.wait_for_timeout(300)
    page.click("text=卡片", timeout=5000)
    page.wait_for_timeout(800)
    manage_links = page.evaluate("() => Array.from(document.querySelectorAll('.pdf-jump')).map(a => a.href).filter(h => h.includes('source-files'))")
    print("manage pdf-jump count:", len(manage_links))
    for link in manage_links[:3]:
        print("   ", link[:90])
    browser.close()
