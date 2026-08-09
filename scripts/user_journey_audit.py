#!/usr/bin/env python3
"""user_journey_audit.py — Phase 12 product-integrity walkthrough (real UI).

Walks the real user journey against a running workbench (127.0.0.1:8765):
empty state -> import -> library populated -> study entry -> retrieval area ->
settings/portable visible. Checks for critical console errors and that the UI
speaks human language (no raw exceptions in visible text).

Usage:
    python scripts/user_journey_audit.py [--port 8765] [--chromium PATH]
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import urllib.request
from pathlib import Path

CHROME_DEFAULT = r"C:\Users\kvxkf\AppData\Local\ms-playwright\chromium-1228\chrome-win64\chrome.exe"


def _post_json(url: str, payload: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def _post_file(url: str, filename: str, data: bytes) -> dict:
    boundary = "----auditboundary"
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
        f"Content-Type: application/pdf\r\n\r\n"
    ).encode() + data + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--chromium", default=CHROME_DEFAULT)
    args = ap.parse_args()
    base = f"http://127.0.0.1:{args.port}"

    from playwright.sync_api import sync_playwright

    results: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = ""):
        results.append((name, ok, detail))
        print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=args.chromium)
        page = browser.new_page()
        errors = []

        def on_console(m):
            if m.type == "error":
                url = (m.location or {}).get("url", "")
                if "favicon" not in url:
                    errors.append(f"{m.text} @ {url}")

        page.on("console", on_console)
        page.on("pageerror", lambda e: errors.append(str(e)))

        # 1. home / empty state
        page.goto(base, wait_until="networkidle", timeout=20000)
        body0 = page.inner_text("body")
        check("home loads", "学习" in body0 or "library" in body0.lower(), "empty state visible")
        check("empty state speaks", ("导入" in body0) or ("教材" in body0), "empty prompt text present")

        # 2. import a synthetic PDF via API (UI import is a file picker; API equivalent)
        import fitz
        doc = fitz.open()
        pg = doc.new_page()
        pg.insert_textbox(fitz.Rect(50, 60, 540, 760),
                          "善意取得应当具备下列条件：处分人为无处分权人。受让人在受让时为善意。以合理价格转让。",
                          fontsize=12, fontname="china-s")
        pdf_bytes = doc.tobytes()
        doc.close()
        _post_file(f"{base}/api/sources/import?wait=true", "audit.pdf", pdf_bytes)

        # 3. library populated
        page.reload(wait_until="networkidle", timeout=20000)
        body1 = page.inner_text("body")
        check("library shows content", len(body1) > 100, "page text non-trivial after import")

        # 4. retrieval area reachable (flashcard/cloze entry)
        check("retrieval labels", ("卡片" in body1) or ("闪卡" in body1) or ("复习" in body1))

        # 5. settings / portable
        check("portable/settings", ("Portable" in body1) or ("导出" in body1) or ("设置" in body1))

        # 6. no critical console errors (ignore favicon 404)
        critical = [e for e in errors if "favicon" not in e]
        check("no critical console errors", not critical, f"errors={critical[:3]}")

        # 7. raw exceptions must not leak into visible UI text
        leak_markers = ("Traceback", "Internal Server Error", "HTTPException")
        check("no raw exception text", not any(m in body1 for m in leak_markers))

        page.screenshot(path=str(Path(__file__).resolve().parents[1] / "artifacts" / "ui-user-journey-audit.png"))
        browser.close()

    failed = [r for r in results if not r[1]]
    print(f"\n=== user journey audit: {len(results)-len(failed)}/{len(results)} PASS ===")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
