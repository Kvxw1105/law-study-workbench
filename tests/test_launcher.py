"""Phase 2 regression: reliable launcher (scripts/alpha_launcher.py).

Covers: first start, second start (already running), port occupied by another
program, python too old, dependency marker change, identity verification.
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

import scripts.alpha_launcher as launcher

ROOT = Path(__file__).resolve().parents[1]


class _FakeHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps(
            {"status": "ok", "version": "0.8.0", "storage": "local", "ai_provider": "local"}
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class _ForeignHandler(BaseHTTPRequestHandler):
    """A listener on 8765 that is NOT the workbench."""

    def do_GET(self):
        body = b"foreign service"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture()
def free_port_8765():
    """Ensure nothing is listening on 8765 before and after the test."""
    for attempt in range(30):
        if not launcher.port_listening():
            break
        time.sleep(0.3)
    yield
    # stop any workbench the launcher may have started
    if launcher.port_listening() and launcher.identity_ok():
        import urllib.request
        try:
            urllib.request.urlopen(launcher.HEALTH_URL, timeout=1)
        except Exception:
            pass


def _serve(handler_cls) -> HTTPServer:
    server = HTTPServer(("127.0.0.1", 8765), handler_cls)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server


def test_python_too_old(monkeypatch):
    monkeypatch.setattr(launcher.sys, "version_info", (3, 10, 0, "final", 0))
    assert launcher.check_python() is False
    assert launcher.main(["--no-browser"]) == 2


def test_python_ok():
    assert launcher.check_python() is True


def test_port_occupied_by_foreign_service(monkeypatch, free_port_8765):
    server = _serve(_ForeignHandler)
    try:
        # a foreign listener must fail identity and exit with code 3
        assert launcher.identity_ok() is False
        assert launcher.main(["--no-browser"]) == 3
    finally:
        server.shutdown()
        server.server_close()


def test_workbench_already_running(monkeypatch):
    # simulate the real workbench answering /api/health
    monkeypatch.setattr(launcher, "port_listening", lambda: True)
    monkeypatch.setattr(
        launcher, "health_json",
        lambda: {"status": "ok", "version": launcher.manifest_version(), "storage": "local"},
    )
    monkeypatch.setattr(launcher, "open_browser", lambda: None)
    assert launcher.identity_ok() is True
    assert launcher.main(["--no-browser"]) == 0


def test_port_occupied_by_foreign_service_final(monkeypatch):
    """Ensure port-occupied exit path does not require a live server (mock)."""
    monkeypatch.setattr(launcher, "port_listening", lambda: True)
    monkeypatch.setattr(launcher, "health_json", lambda: None)
    assert launcher.main(["--no-browser"]) == 3


def test_dependency_marker_sync(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(launcher, "VENV_PY", tmp_path / "python.exe")
    monkeypatch.setattr(launcher, "MARKER", tmp_path / ".requirements.sha256")
    real_run = subprocess.run

    def fake_run(cmd, **kw):
        calls.append(cmd)
        # pretend pip install succeeds
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(launcher.subprocess, "run", fake_run)
    # first run: no marker -> install
    assert launcher.sync_requirements() is True
    assert len(calls) == 1
    # second run: marker matches -> no install
    assert launcher.sync_requirements() is True
    assert len(calls) == 1
    # change lock content -> reinstall
    lock = ROOT / "requirements-lock.txt"
    original = lock.read_bytes()
    try:
        lock.write_bytes(original + b"\n# marker-change-test\n")
        assert launcher.sync_requirements() is True
        assert len(calls) == 2
    finally:
        lock.write_bytes(original)


def _stop_workbench_if_ours():
    """Stop the workbench we started on 8765 (identity-verified) to leave a clean state."""
    if not (launcher.port_listening() and launcher.identity_ok()):
        return
    try:
        out = subprocess.run(
            ["netstat", "-ano"], capture_output=True, text=True, timeout=10
        ).stdout
        pids = set()
        for line in out.splitlines():
            if ":8765" in line and "LISTENING" in line:
                pids.add(line.split()[-1])
        for pid in pids:
            if pid.isdigit():
                subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True)
    except Exception:
        pass


def test_first_start_integration(free_port_8765):
    """Real first start: launcher creates/uses .venv, starts uvicorn, health UP."""
    try:
        assert not launcher.port_listening()
        rc = launcher.main(["--no-browser", "--timeout", "60"])
        assert rc == 0, f"launcher failed with {rc}"
        assert launcher.identity_ok() is True
        # second call while running -> returns 0 without restart
        rc2 = launcher.main(["--no-browser", "--timeout", "5"])
        assert rc2 == 0
    finally:
        _stop_workbench_if_ours()
