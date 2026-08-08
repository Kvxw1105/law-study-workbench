from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
PORTABLE = ROOT / "portable-reviewer"
PORT = 8774
BASE_URL = f"http://127.0.0.1:{PORT}"
ARTIFACT = ROOT / "artifacts" / "ui-study-protocol-browser-roundtrip.png"


def wait_for_server(client: httpx.Client, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if client.get("/api/health").status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    raise RuntimeError("server did not become ready")


def start_server(home: str) -> subprocess.Popen[str]:
    env = os.environ.copy()
    env["LAW_STUDY_HOME"] = home
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.asgi:app", "--host", "127.0.0.1", "--port", str(PORT), "--log-level", "warning"],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def stop_server(process: subprocess.Popen[str]) -> None:
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def seed_and_export(client: httpx.Client, workdir: Path) -> tuple[dict, Path]:
    subprocess.run([sys.executable, str(ROOT / "scripts" / "create_demo_pdf.py")], check=True, cwd=ROOT)
    demo_pdf = ROOT / "artifacts" / "demo-civil-law.pdf"
    with demo_pdf.open("rb") as handle:
        response = client.post("/api/sources/import?wait=true", files={"file": (demo_pdf.name, handle, "application/pdf")})
    response.raise_for_status()
    source = response.json()["source"]
    unit = client.get(f"/api/sources/{source['id']}/units").json()[0]
    client.patch(f"/api/units/{unit['id']}", json={"status": "approved"}).raise_for_status()
    generated = client.post(
        f"/api/units/{unit['id']}/retrieval-items/generate",
        json={"item_types": ["flashcard", "cloze"], "max_per_type": 1},
    )
    generated.raise_for_status()
    pack_response = client.get("/api/study-pack/export?mode=due&limit=10")
    pack_response.raise_for_status()
    pack = pack_response.json()
    assert {item["type"] for item in pack["items"]} == {"flashcard", "cloze"}
    pack_path = workdir / "study-pack.json"
    pack_path.write_text(json.dumps(pack, ensure_ascii=False, indent=2), encoding="utf-8")
    return pack, pack_path


def browser_review(pack: dict, pack_path: Path, workdir: Path) -> Path:
    html = (PORTABLE / "index.html").read_text(encoding="utf-8")
    html = html.replace('<link rel="manifest" href="./manifest.webmanifest">', "")
    html = html.replace('<link rel="stylesheet" href="./styles.css">', "")
    html = html.replace('<script src="./app.js" defer></script>', "")
    download_target = workdir / "study-events.json"

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH", "/usr/bin/chromium"), args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.set_content(html, wait_until="domcontentloaded")
        page.add_style_tag(path=str(PORTABLE / "styles.css"))
        page.add_script_tag(path=str(PORTABLE / "app.js"))
        page.locator("#packInput").set_input_files(str(pack_path))

        for item in pack["items"]:
            page.get_by_text(item["content"]["prompt"], exact=True).wait_for(timeout=10000)
            if item["type"] == "flashcard":
                page.get_by_role("button", name="显示答案").click()
                page.get_by_role("button", name="记得").click()
            else:
                page.locator("#clozeInput").fill(item["content"]["answer"])
                page.get_by_role("button", name="核对答案").click()
                page.get_by_text("离线字面核对：一致", exact=False).wait_for(timeout=10000)
                page.screenshot(path=str(ARTIFACT), full_page=True)
                page.get_by_role("button", name="记录并下一题").click()

        page.get_by_text("这一轮已完成").wait_for(timeout=10000)
        with page.expect_download() as download_info:
            page.get_by_role("button", name="导出 StudyEvents").click()
        download_info.value.save_as(str(download_target))
        browser.close()
    return download_target


def main() -> None:
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="study-protocol-browser-") as temp:
        workdir = Path(temp)
        home = workdir / "home"
        process = start_server(str(home))
        try:
            with httpx.Client(base_url=BASE_URL, timeout=30) as client:
                wait_for_server(client)
                pack, pack_path = seed_and_export(client, workdir)
                events_path = browser_review(pack, pack_path, workdir)
                events = json.loads(events_path.read_text(encoding="utf-8"))
                assert events["protocol"] == "study-events/0.1"
                assert events["pack_id"] == pack["pack_id"]
                assert len(events["events"]) == len(pack["items"])
                imported = client.post("/api/study-events/import", json=events)
                imported.raise_for_status()
                payload = imported.json()
                assert payload["summary"] == {"imported": 2, "duplicates": 0, "conflicts": 0}
                assert client.get("/api/retrieval/summary").json()["attempts"] == 2
                print("browser-file-runtime roundtrip ok", pack["pack_id"], ARTIFACT)
        finally:
            stop_server(process)


if __name__ == "__main__":
    main()
