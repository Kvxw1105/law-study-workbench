"""Shared synthetic test helpers for the conformance/recovery/lifecycle suites.

Synthetic fixtures only — never real user data. Extracted to remove duplicated
make_pdf / chromium-lookup code across test modules.
"""
from __future__ import annotations

from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]

CHROMIUM_CANDIDATES = (
    Path(r"C:\Users\kvxkf\AppData\Local\ms-playwright\chromium-1228\chrome-win64\chrome.exe"),
    Path("/usr/bin/chromium"),
)


def chromium_executable() -> str | None:
    for candidate in CHROMIUM_CANDIDATES:
        if candidate.exists():
            return str(candidate)
    return None


def make_pdf(
    text: str = "善意取得应当具备下列条件：处分人为无处分权人。受让人在受让时为善意。以合理价格转让。",
) -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_textbox(fitz.Rect(45, 55, 545, 780), text, fontsize=12, fontname="china-s")
    payload = document.tobytes()
    document.close()
    return payload
