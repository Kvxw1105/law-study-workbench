from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
PORT = 8771
BASE_URL = f"http://127.0.0.1:{PORT}"
ARTIFACT = ROOT / "artifacts" / "ui-v070-real-critical-block.png"
LAW_BODY = (
    "无权代理未经被代理人追认的，对被代理人不发生效力。"
    "善意相对人有权在被代理人追认前撤销。"
    "相对人可以催告被代理人自收到通知之日起三十日内予以追认。"
)
REVERSED_ANSWER = (
    "无权代理未经被代理人追认的，对被代理人发生效力。"
    "善意相对人无权在被代理人追认前撤销。"
    "相对人可以催告被代理人自收到通知之日起三十日内予以追认。"
)


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
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.asgi:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(PORT),
            "--log-level",
            "warning",
        ],
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
    # POSIX: SIGTERM -> -15; Windows: TerminateProcess -> exit code 1
    if process.returncode not in (0, -15, 1):
        output = process.stdout.read() if process.stdout else ""
        raise RuntimeError(f"server exited unexpectedly: {process.returncode}\n{output}")


def seed(client: httpx.Client) -> tuple[str, str]:
    subprocess.run([sys.executable, str(ROOT / "scripts" / "create_demo_pdf.py")], check=True, cwd=ROOT)
    demo_pdf = ROOT / "artifacts" / "demo-civil-law.pdf"
    with demo_pdf.open("rb") as handle:
        response = client.post(
            "/api/sources/import?wait=true",
            files={"file": (demo_pdf.name, handle, "application/pdf")},
        )
    response.raise_for_status()
    source = response.json()["source"]
    unit = client.get(f"/api/sources/{source['id']}/units").json()[0]
    edited = client.patch(f"/api/units/{unit['id']}", json={"body": LAW_BODY})
    edited.raise_for_status()
    approved = client.patch(f"/api/units/{unit['id']}", json={"status": "approved"})
    approved.raise_for_status()
    return source["id"], unit["id"]


def main() -> None:
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="law-study-real-browser-") as home:
        process = start_server(home)
        try:
            with httpx.Client(base_url=BASE_URL, timeout=30) as client:
                wait_for_server(client)
                source_id, unit_id = seed(client)

                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(
                        headless=True,
                        executable_path=os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH", "/usr/bin/chromium"),
                        args=["--no-sandbox"],
                    )
                    page = browser.new_page(viewport={"width": 1280, "height": 900})
                    browser_errors: list[str] = []
                    page.on("pageerror", lambda error: browser_errors.append(f"pageerror: {error}"))
                    page.on(
                        "console",
                        lambda message: browser_errors.append(f"console: {message.text}") if message.type == "error" else None,
                    )

                    def api_bridge(url: str, method: str = "GET", body: str | None = None, headers: dict | None = None) -> dict:
                        path = url if url.startswith("/") else "/api/" + url.split("/api/", 1)[-1]
                        if not path.startswith("/api/"):
                            raise RuntimeError(f"unexpected bridge URL: {url}")
                        clean_headers = {
                            key: value
                            for key, value in (headers or {}).items()
                            if key.lower() not in {"host", "content-length", "connection", "accept-encoding"}
                        }
                        response = client.request(method, path, headers=clean_headers, content=body)
                        return {
                            "status": response.status_code,
                            "body": response.text,
                            "content_type": response.headers.get("content-type", "application/json"),
                        }

                    page.expose_function("realApiBridge", api_bridge)
                    html = (ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")
                    html = html.replace('<link rel="stylesheet" href="/styles.css">', "")
                    html = html.replace('<script src="/app.js" defer></script>', "")
                    page.set_content(html, wait_until="domcontentloaded")
                    page.add_style_tag(path=str(ROOT / "app" / "static" / "styles.css"))
                    page.add_script_tag(
                        content="""
                        (() => {
                          window.fetch = async (url, options = {}) => {
                            const headers = {};
                            if (options.headers instanceof Headers) {
                              options.headers.forEach((value, key) => { headers[key] = value; });
                            } else if (options.headers) {
                              Object.assign(headers, options.headers);
                            }
                            const response = await window.realApiBridge(
                              String(url),
                              options.method || 'GET',
                              typeof options.body === 'string' ? options.body : null,
                              headers
                            );
                            return new Response(response.body, {
                              status: response.status,
                              headers: {'Content-Type': response.content_type}
                            });
                          };
                        })();
                        """
                    )
                    page.add_script_tag(path=str(ROOT / "app" / "static" / "app.js"))

                    page.get_by_role("heading", name="今日学习").wait_for(timeout=10_000)
                    page.get_by_role("button", name="本地教材库").click()
                    page.get_by_role("heading", name="添加本地教材").wait_for(timeout=8_000)

                    page.get_by_role("button", name="审核 / 编辑").first.click()
                    page.get_by_text("教材来源快照（只读）", exact=True).wait_for(timeout=8_000)
                    source_textarea = page.locator("#unitDialogBody textarea[readonly]").first
                    assert source_textarea.is_visible()
                    assert source_textarea.get_attribute("readonly") is not None
                    page.get_by_role("button", name="取消").click()

                    page.get_by_role("button", name="开始完整闭卷").first.click()
                    page.get_by_role("heading", name="闭卷回答").wait_for(timeout=8_000)
                    page.locator("#answerText").fill(REVERSED_ANSWER)
                    page.keyboard.press("Control+Enter")
                    page.get_by_text("有效学习证据分", exact=True).wait_for(timeout=10_000)
                    page.get_by_text("目标=人工改写学习文本", exact=False).wait_for(timeout=10_000)
                    page.get_by_text("需立即修复", exact=True).wait_for(timeout=10_000)
                    score = float(page.locator(".result-score-block strong").inner_text())
                    assert score <= 45, score
                    page.get_by_text("关键冲突", exact=True).first.wait_for(timeout=8_000)
                    page.screenshot(path=str(ARTIFACT), full_page=True)
                    assert not browser_errors, "\n".join(browser_errors)
                    browser.close()

                units = client.get(f"/api/sources/{source_id}/units").json()
                current = next(item for item in units if item["id"] == unit_id)
                assert current["mastery_status"] == "需立即修复"
                errors = client.get(f"/api/errors?unit_id={unit_id}&status=open").json()
                assert any(item["error_type"] == "critical_legal_conflict" for item in errors)
        finally:
            stop_server(process)
    print(ARTIFACT)
    print("Real Chromium UI + bridged real FastAPI critical-conflict E2E passed")


if __name__ == "__main__":
    main()
