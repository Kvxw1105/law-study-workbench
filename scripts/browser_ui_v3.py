from __future__ import annotations

import os

from pathlib import Path
from playwright.sync_api import sync_playwright

from browser_ui_round2 import mount, assert_no_horizontal_overflow

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts"

VIEWPORTS = [
    (320, 568),
    (390, 844),
    (430, 932),
    (768, 1024),
    (1024, 768),
    (1440, 900),
    (1700, 864),
]


def assert_core_geometry(page, width: int) -> None:
    assert_no_horizontal_overflow(page)
    heading = page.get_by_role("heading", name="今日学习")
    assert heading.is_visible()
    if width <= 520:
        nav = page.locator(".nav-list")
        box = nav.bounding_box()
        assert box and box["height"] >= 48
        # Full names remain the accessible button names, concise labels are visual only.
        assert page.get_by_role("button", name="本地教材库").is_visible()
        assert page.locator('.nav-item[data-short-label="教材"]').count() == 1


def main() -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH", "/usr/bin/chromium"), args=["--no-sandbox"])
        browser_errors: list[str] = []

        for width, height in VIEWPORTS:
            page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=1)
            page.on("pageerror", lambda error, w=width: browser_errors.append(f"{w}px pageerror: {error}"))
            page.on("console", lambda message, w=width: browser_errors.append(f"{w}px console: {message.text}") if message.type == "error" else None)
            mount(page)
            assert_core_geometry(page, width)

            if width == 320:
                page.screenshot(path=str(ARTIFACTS / "ui-v3-today-320-dark.png"), full_page=True)
            if width == 430:
                page.get_by_role("button", name="本地教材库").click()
                page.get_by_role("heading", name="添加本地教材").wait_for(timeout=8_000)
                assert_no_horizontal_overflow(page)
                page.screenshot(path=str(ARTIFACTS / "ui-v3-library-430-dark.png"), full_page=True)
            if width == 1024:
                page.get_by_role("button", name="本地教材库").click()
                page.get_by_role("button", name="再次完整复测").first.click()
                page.get_by_role("heading", name="闭卷回答").wait_for(timeout=8_000)
                assert_no_horizontal_overflow(page)
                page.evaluate("window.scrollTo(0, 0)")
                page.wait_for_timeout(80)
                page.screenshot(path=str(ARTIFACTS / "ui-v3-study-1024-dark.png"), full_page=False)
            if width == 1440:
                page.screenshot(path=str(ARTIFACTS / "ui-v3-today-1440-dark.png"), full_page=True)
                page.get_by_role("button", name="本地教材库").click()
                page.get_by_role("heading", name="添加本地教材").wait_for(timeout=8_000)
                page.screenshot(path=str(ARTIFACTS / "ui-v3-library-1440-dark.png"), full_page=True)
                page.get_by_role("button", name="再次完整复测").first.click()
                page.get_by_role("heading", name="闭卷回答").wait_for(timeout=8_000)
                page.get_by_role("button", name="切换到浅色主题").click()
                page.wait_for_timeout(120)
                assert page.locator("html").get_attribute("data-theme") == "light"
                assert_no_horizontal_overflow(page)
                page.evaluate("window.scrollTo(0, 0)")
                page.wait_for_timeout(80)
                page.screenshot(path=str(ARTIFACTS / "ui-v3-study-1440-light.png"), full_page=False)

                # Explicit reduced-motion verification.
                page.evaluate("document.documentElement.dataset.motion = 'reduced'")
                duration = page.locator(".primary-button").first.evaluate("el => getComputedStyle(el).transitionDuration")
                assert duration in {"0s", "1e-06s", "0.000001s"} or duration.startswith("0.000")

                # Keyboard focus remains visually exposed.
                page.keyboard.press("Tab")
                page.keyboard.press("Tab")
                focused = page.evaluate("document.activeElement && document.activeElement.tagName")
                assert focused in {"BUTTON", "A", "TEXTAREA", "INPUT", "SELECT"}

            page.close()

        assert not browser_errors, "\n".join(browser_errors)
        browser.close()

    for name in [
        "ui-v3-today-320-dark.png",
        "ui-v3-library-430-dark.png",
        "ui-v3-study-1024-dark.png",
        "ui-v3-today-1440-dark.png",
        "ui-v3-library-1440-dark.png",
        "ui-v3-study-1440-light.png",
    ]:
        path = ARTIFACTS / name
        if path.exists():
            print(path)


if __name__ == "__main__":
    main()
