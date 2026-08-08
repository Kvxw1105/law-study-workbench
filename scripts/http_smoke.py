from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx


ROOT = Path(__file__).resolve().parents[1]
DEMO_PDF = ROOT / "artifacts" / "demo-civil-law.pdf"
PORT = 8768
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


def main() -> None:
    subprocess.run([sys.executable, str(ROOT / "scripts" / "create_demo_pdf.py")], check=True, cwd=ROOT)
    with tempfile.TemporaryDirectory(prefix="law-study-http-") as home:
        process = start_server(home)
        try:
            with httpx.Client(base_url=BASE_URL, timeout=30) as client:
                wait_for_server(client)
                health = client.get("/api/health")
                health.raise_for_status()
                assert health.json()["version"] == "0.8.0"

                with DEMO_PDF.open("rb") as handle:
                    imported = client.post(
                        "/api/sources/import?wait=true",
                        files={"file": (DEMO_PDF.name, handle, "application/pdf")},
                    )
                imported.raise_for_status()
                source = imported.json()["source"]
                units = client.get(f"/api/sources/{source['id']}/units").json()
                unit = units[0]

                started = client.post(
                    f"/api/units/{unit['id']}/sessions",
                    json={"approve_unit": True},
                )
                started.raise_for_status()
                session = started.json()["session"]
                method_pack = session["method_pack"]
                assert method_pack["id"] == "law_full_recall_v1"
                assert method_pack["version"] == "0.3.0"
                assert len(method_pack["training_dimensions"]) == 5

                submitted = client.post(
                    f"/api/sessions/{session['id']}/attempts",
                    json={
                        "answer_text": (
                            "善意取得要求处分人为无处分权人，受让人在受让时善意，支付合理价格，"
                            "并完成登记或者交付。受让人取得所有权后，原权利人可以请求损害赔偿。"
                        ),
                        "confidence": 78,
                        "elapsed_ms": 48_000,
                    },
                )
                submitted.raise_for_status()
                attempt = submitted.json()
                assert attempt["method_pack"]["id"] == "law_full_recall_v1"
                assert attempt["method_pack"]["runtime_status"] == "completed"
                assert len(attempt["dimension_results"]) == 5
                assert attempt["feedback"]["method_pack"] == attempt["method_pack"]
                assert attempt["feedback"]["dimension_results"] == attempt["dimension_results"]
                assert attempt["feedback"]["generated_flags"]["formal_legal_grade"] is False
                restored_session_id = session["id"]

                generated = client.post(
                    f"/api/units/{unit['id']}/retrieval-items/generate",
                    json={"item_types": ["flashcard", "cloze"], "max_per_type": 3},
                )
                generated.raise_for_status()
                items = generated.json()["items"]
                flash = next(item for item in items if item["item_type"] == "flashcard")
                cloze = next(item for item in items if item["item_type"] == "cloze")
                client.post(f"/api/retrieval-items/{flash['id']}/reveal").raise_for_status()
                flash_result = client.post(
                    f"/api/retrieval-items/{flash['id']}/attempts",
                    json={"rating": "good", "elapsed_ms": 1200, "revealed_answer": True},
                )
                flash_result.raise_for_status()
                cloze_result = client.post(
                    f"/api/retrieval-items/{cloze['id']}/attempts",
                    json={"response_text": cloze["answer"], "elapsed_ms": 900},
                )
                cloze_result.raise_for_status()
                assert client.get("/api/retrieval/summary").json()["attempts"] == 2

                critical_card = client.post(
                    f"/api/units/{unit['id']}/retrieval-items",
                    json={
                        "item_type": "cloze",
                        "prompt": "受让人主观状态专项",
                        "answer": "善意",
                        "cloze_text": "受让人主观状态应为 ____。",
                        "source_excerpt": "受让人在受让该财产时为善意。",
                    },
                )
                critical_card.raise_for_status()
                critical_result = client.post(
                    f"/api/retrieval-items/{critical_card.json()['id']}/attempts",
                    json={"response_text": "恶意", "elapsed_ms": 700},
                )
                critical_result.raise_for_status()
                critical_payload = critical_result.json()
                assert critical_payload["correct"] is False
                assert critical_payload["rating"] == "again"
                assert critical_payload["score"] <= 45
                assert critical_payload["critical_mismatches"]

                poor_session = client.post(
                    f"/api/units/{unit['id']}/sessions",
                    json={"approve_unit": True},
                )
                poor_session.raise_for_status()
                poor_session_id = poor_session.json()["session"]["id"]
                poor_attempt = client.post(
                    f"/api/sessions/{poor_session_id}/attempts",
                    json={"answer_text": "不知道", "confidence": 25, "elapsed_ms": 4_000},
                )
                poor_attempt.raise_for_status()
                assert poor_attempt.json()["errors_created"] >= 1
                errors = client.get(f"/api/errors?status=open&unit_id={unit['id']}")
                errors.raise_for_status()
                error = errors.json()[0]
                repair = client.post(f"/api/errors/{error['id']}/repair")
                repair.raise_for_status()
                repair_session_id = repair.json()["session"]["id"]
                repair_attempt = client.post(
                    f"/api/sessions/{repair_session_id}/attempts",
                    json={
                        "answer_text": unit["body"],
                        "confidence": 72,
                        "elapsed_ms": 18_000,
                    },
                )
                repair_attempt.raise_for_status()
                refreshed_error = client.get(f"/api/errors?status=repairing&unit_id={unit['id']}")
                refreshed_error.raise_for_status()
                repair_record = next(item for item in refreshed_error.json() if item["id"] == error["id"] )
                assert repair_record["can_resolve"] is True
                resolved = client.post(f"/api/errors/{error['id']}/resolve")
                resolved.raise_for_status()
                assert resolved.json()["status"] == "resolved"
                assert resolved.json()["resolved_at"]

                restored_item_id = flash["id"]
        finally:
            stop_server(process)

        process = start_server(home)
        try:
            with httpx.Client(base_url=BASE_URL, timeout=30) as client:
                wait_for_server(client)
                restored_item = client.get(f"/api/retrieval-items/{restored_item_id}?include_answer=true")
                restored_item.raise_for_status()
                assert restored_item.json()["last_rating"] == "good"
                assert restored_item.json()["attempt_count"] == 1

                restored_session = client.get(f"/api/sessions/{restored_session_id}")
                restored_session.raise_for_status()
                restored_payload = restored_session.json()
                assert restored_payload["method_pack"]["id"] == "law_full_recall_v1"
                assert restored_payload["attempt"]["feedback"]["method_pack"]["version"] == "0.3.0"
                assert len(restored_payload["attempt"]["feedback"]["dimension_results"]) == 5
        finally:
            stop_server(process)
    print("HTTP full-recall method-pack and retrieval smoke passed")


if __name__ == "__main__":
    main()
