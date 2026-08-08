from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[1]
PORT = 8773
BASE_URL = f"http://127.0.0.1:{PORT}"


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


def seed(client: httpx.Client) -> None:
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
        json={"item_types": ["flashcard", "cloze"], "max_per_type": 2},
    )
    generated.raise_for_status()


def event(item: dict, *, response_text: str = "", rating: str | None = None) -> dict:
    return {
        "event_id": str(uuid4()),
        "event_type": "retrieval_attempt",
        "item_id": item["id"],
        "item_version": item["version"],
        "content_hash": item["content_hash"],
        "base_last_attempt_id": item["review_base"]["last_attempt_id"],
        "occurred_at": datetime.now(UTC).isoformat(),
        "response_text": response_text,
        "rating": rating,
        "elapsed_ms": 900,
        "revealed_answer": True,
    }


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="study-protocol-") as home:
        process = start_server(home)
        try:
            with httpx.Client(base_url=BASE_URL, timeout=30) as client:
                wait_for_server(client)
                seed(client)
                pack_response = client.get("/api/study-pack/export?mode=due&limit=50")
                pack_response.raise_for_status()
                pack = pack_response.json()
                assert pack["protocol"] == "study-pack/0.1"
                flash = next(item for item in pack["items"] if item["type"] == "flashcard")
                cloze = next(item for item in pack["items"] if item["type"] == "cloze")
                events = [
                    event(flash, rating="good"),
                    event(cloze, response_text=cloze["content"]["answer"]),
                ]
                bundle = {
                    "protocol": "study-events/0.1",
                    "bundle_id": str(uuid4()),
                    "pack_id": pack["pack_id"],
                    "pack_hash": pack["pack_hash"],
                    "exported_at": datetime.now(UTC).isoformat(),
                    "device": {"id": "smoke-phone", "label": "Smoke Phone", "client": "portable-reviewer/0.1"},
                    "events": events,
                }
                imported = client.post("/api/study-events/import", json=bundle)
                imported.raise_for_status()
                assert imported.json()["summary"] == {"imported": 2, "duplicates": 0, "conflicts": 0}
                replay = client.post("/api/study-events/import", json=bundle)
                replay.raise_for_status()
                assert replay.json()["summary"] == {"imported": 0, "duplicates": 2, "conflicts": 0}
                summary = client.get("/api/retrieval/summary").json()
                assert summary["attempts"] == 2
                print("study protocol roundtrip ok", pack["pack_id"], summary)
        finally:
            stop_server(process)


if __name__ == "__main__":
    main()
