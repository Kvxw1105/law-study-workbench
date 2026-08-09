"""Shared synthetic test helpers for the conformance/recovery/lifecycle suites.

Synthetic fixtures only — never real user data. Extracted to remove duplicated
make_pdf / chromium-lookup code across test modules.
"""
from __future__ import annotations

import os
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]


def _discover_playwright_chromium() -> str | None:
    """Find a local Playwright Chromium without hardcoding user paths."""
    env = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH")
    if env and Path(env).exists():
        return env
    base = Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"
    if base.exists():
        found = sorted(base.glob("chromium-*/chrome-win64/chrome.exe"))
        if found:
            return str(found[-1])
    if Path("/usr/bin/chromium").exists():
        return "/usr/bin/chromium"
    return None


def chromium_executable() -> str | None:
    return _discover_playwright_chromium()


def make_pdf(
    text: str = "善意取得应当具备下列条件：处分人为无处分权人。受让人在受让时为善意。以合理价格转让。",
) -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_textbox(fitz.Rect(45, 55, 545, 780), text, fontsize=12, fontname="china-s")
    payload = document.tobytes()
    document.close()
    return payload
