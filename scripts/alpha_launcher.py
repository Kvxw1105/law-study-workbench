#!/usr/bin/env python3
"""alpha_launcher.py — reliable Windows launcher core for law-study-workbench.

START_WINDOWS.bat is a thin shell over this script.

Behavior:
  1. Python >= 3.11 required.
  2. If port 8765 is already listening: probe /api/health — if it IS this
     workbench (version matches manifest), just open the browser; otherwise
     report "8765 occupied by another program" and exit (never kill others).
  3. Create .venv if missing.
  4. Sync dependencies only when requirements-lock.txt hash changed
     (marker file .venv/.requirements.sha256) — no full reinstall every time.
  5. Start uvicorn, poll /api/health until ready, then open the browser.
     On timeout, print the log path.

Options:
    --no-browser   do not open the browser (for tests/CI)
    --timeout N    readiness timeout in seconds (default 45)
Exit codes: 0 ok, 2 python too old, 3 port occupied by other program,
            4 dependency sync failed, 5 startup timeout, 6 unexpected error.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PORT = 8765
BASE_URL = f"http://127.0.0.1:{PORT}"
HEALTH_URL = f"{BASE_URL}/api/health"
VENV = ROOT / ".venv"
VENV_PY = VENV / "Scripts" / "python.exe" if sys.platform == "win32" else VENV / "bin" / "python"
MARKER = VENV / ".requirements.sha256"
LOG_DIR = ROOT / "logs"
LOG_FILE = LOG_DIR / "launcher.log"


def health_json() -> dict | None:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=2) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except Exception:
        return None


def port_listening() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", PORT)) == 0


def check_python() -> bool:
    major, minor = sys.version_info[:2]
    if (major, minor) < (3, 11):
        print(f"[错误] 需要 Python >= 3.11，当前为 {major}.{minor}。请升级后重试。")
        return False
    print(f"[python] {major}.{minor} (>=3.11 OK)")
    return True


def manifest_version() -> str | None:
    try:
        return json.loads((ROOT / "project-manifest.json").read_text(encoding="utf-8")).get("version")
    except Exception:
        return None


def identity_ok() -> bool:
    """True when the listener on 8765 really is this workbench (version match)."""
    h = health_json()
    if not h:
        return False
    expected = manifest_version()
    return bool(expected) and h.get("status") == "ok" and h.get("version") == expected


def ensure_venv() -> bool:
    if VENV_PY.exists():
        return True
    print("[venv] 未找到 .venv，正在创建...")
    try:
        subprocess.run([sys.executable, "-m", "venv", str(VENV)], check=True, timeout=120)
        return True
    except Exception as e:
        print(f"[错误] 创建 .venv 失败：{e}")
        return False


def sync_requirements() -> bool:
    lock = ROOT / "requirements-lock.txt"
    if not lock.exists():
        print("[warn] requirements-lock.txt 不存在，跳过依赖同步")
        return True
    digest = hashlib.sha256(lock.read_bytes()).hexdigest()
    if MARKER.exists() and MARKER.read_text(encoding="utf-8").strip() == digest:
        print("[deps] requirements 已同步（hash 未变）")
        return True
    print("[deps] requirements-lock.txt 已变化，同步依赖（仅本项目 .venv）...")
    try:
        subprocess.run(
            [str(VENV_PY), "-m", "pip", "install", "-q", "-r", str(lock)],
            check=True, timeout=600,
        )
        MARKER.write_text(digest, encoding="utf-8")
        print("[deps] 依赖同步完成")
        return True
    except Exception as e:
        print(f"[错误] 依赖同步失败：{e}")
        return False


def start_server() -> subprocess.Popen:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    fh = open(LOG_FILE, "a", encoding="utf-8")
    fh.write(f"\n=== launcher start {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
    fh.flush()
    return subprocess.Popen(
        [str(VENV_PY), "-m", "uvicorn", "app.asgi:app",
         "--host", "127.0.0.1", "--port", str(PORT), "--log-level", "warning"],
        cwd=ROOT, stdout=fh, stderr=subprocess.STDOUT,
    )


def wait_ready(timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        h = health_json()
        if h and h.get("status") == "ok":
            return True
        time.sleep(0.5)
    return False


def open_browser() -> None:
    try:
        if sys.platform == "win32":
            subprocess.Popen(["cmd", "/c", "start", "", BASE_URL], shell=False)
        else:
            subprocess.Popen(["xdg-open", BASE_URL])
    except Exception:
        pass


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Reliable launcher for law-study-workbench.")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--timeout", type=float, default=45.0)
    args = ap.parse_args(argv)

    if not check_python():
        return 2

    if port_listening():
        if identity_ok():
            print(f"[提示] 工作台已在 {BASE_URL} 运行（version 匹配）。")
            if not args.no_browser:
                open_browser()
            return 0
        print(f"[错误] 端口 {PORT} 已被其他程序占用，且 /api/health 不是本工作台。")
        print("       请先关闭占用 {PORT} 的程序，再重新启动。不会自动终止其他进程。")
        return 3

    if not ensure_venv():
        return 6
    if not sync_requirements():
        return 4

    print(f"[启动] uvicorn -> {BASE_URL}（日志：{LOG_FILE}）")
    proc = start_server()
    if wait_ready(args.timeout):
        print(f"[就绪] {HEALTH_URL} OK，工作台可用。")
        if not args.no_browser:
            open_browser()
        return 0
    # timeout path: stop the server we just started and report the log path
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)
    print(f"[错误] 启动超时（{args.timeout:.0f}s）。请查看日志：{LOG_FILE}")
    return 5


if __name__ == "__main__":
    sys.exit(main())
