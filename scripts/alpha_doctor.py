#!/usr/bin/env python3
"""alpha_doctor.py — Alpha self-check doctor for law-study-workbench.

Usage:
    python scripts/alpha_doctor.py --quick      # fast checks (seconds)
    python scripts/alpha_doctor.py --full       # quick + compile/JS/pytest/smokes
    python scripts/alpha_doctor.py --quick --json

Output lines: PASS / WARN / FAIL / BLOCKED
Exit code: 0 all pass (WARN ok), 1 FAIL, 2 BLOCKED, 3 usage error.

--full writes .agent/VERIFICATION.json (ephemeral, git-ignored) with
last_verified_commit / verified_at / tests_passed / verification_level.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HEALTH_URL = "http://127.0.0.1:8765/api/health"
CHROME_ENV = "PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH"
VERIFICATION_FILE = ROOT / ".agent" / "VERIFICATION.json"

RESULTS: list[dict] = []
JSON_MODE = False


def rec(level: str, name: str, detail: str = "") -> None:
    RESULTS.append({"level": level, "name": name, "detail": detail})
    if not JSON_MODE:
        print(f"{level:<7} {name}" + (f"  | {detail}" if detail else ""))


def run(cmd: list[str], timeout: int = 120, cwd: Path | None = None, env: dict | None = None) -> tuple[str, int]:
    try:
        full_env = os.environ.copy()
        if env:
            full_env.update(env)
        r = subprocess.run(cmd, cwd=cwd or ROOT, capture_output=True, text=True, timeout=timeout, env=full_env)
        return (r.stdout + r.stderr).strip(), r.returncode
    except subprocess.TimeoutExpired:
        return "TIMEOUT", -1
    except Exception as e:
        return str(e), -1


def chromium_env() -> dict:
    """Inject a local Chromium executable if one is known to exist."""
    env_path = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH")
    candidates = []
    if env_path:
        candidates.append(env_path)
    base = Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"
    if base.exists():
        found = sorted(base.glob("chromium-*/chrome-win64/chrome.exe"))
        candidates.extend(str(c) for c in found)
    candidates.append("/usr/bin/chromium")
    for candidate in candidates:
        if os.path.exists(candidate):
            return {"PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH": candidate}
    return {}


def check_git() -> None:
    out, rc = run(["git", "status", "--porcelain"])
    dirty = bool(out.strip())
    branch, _ = run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    head, _ = run(["git", "rev-parse", "HEAD"])
    rec("WARN" if dirty else "PASS", "git_clean", f"branch={branch} head={head[:12]} dirty={dirty}")


def check_python() -> None:
    v = sys.version_info
    ok = (v.major, v.minor) >= (3, 11)
    rec("PASS" if ok else "FAIL", "python_version", f"{v.major}.{v.minor}.{v.micro}")

def check_node() -> None:
    out, _ = run(["node", "--version"])
    rec("PASS" if out else "FAIL", "node", out or "not found")

def check_venv() -> None:
    py = ROOT / ".venv" / "Scripts" / "python.exe"
    if not py.exists():
        rec("FAIL", "venv", ".venv missing — run START_WINDOWS.bat once or python -m venv .venv")
        return
    out, _ = run([str(py), "--version"], timeout=30)
    rec("PASS", "venv", out)

def check_requirements_sync() -> None:
    lock = ROOT / "requirements-lock.txt"
    marker = ROOT / ".venv" / ".requirements.sha256"
    if not lock.exists():
        rec("WARN", "requirements", "no requirements-lock.txt")
        return
    import hashlib
    digest = hashlib.sha256(lock.read_bytes()).hexdigest()
    if marker.exists() and marker.read_text(encoding="utf-8").strip() == digest:
        rec("PASS", "requirements_sync", "marker matches")
    else:
        rec("WARN", "requirements_sync", "marker missing/stale — launcher will reinstall")

def check_manifest() -> None:
    mf = ROOT / "project-manifest.json"
    try:
        data = json.loads(mf.read_text(encoding="utf-8"))
        schema = data.get("data", {}).get("schema_version")
        proto = data.get("capabilities", {}).get("portable_study_protocol", {})
        rec("PASS", "product", f"v{data.get('version')} schema={schema} protocol={proto.get('study_pack_protocol')}")
    except Exception as e:
        rec("FAIL", "manifest", str(e))

def check_data_path() -> None:
    home = os.environ.get("LAW_STUDY_HOME") or "data"
    p = Path(home)
    if not p.is_absolute():
        p = ROOT / home
    writable = False
    try:
        with tempfile.NamedTemporaryFile(dir=str(p), delete=True) as f:
            writable = True
    except Exception:
        pass
    rec("PASS" if writable else "WARN", "data_path", f"{p} writable={writable}")

def check_protected_paths_ignored() -> None:
    gi = ROOT / ".gitignore"
    text = gi.read_text(encoding="utf-8") if gi.exists() else ""
    needed = ["data/", "*.db", "*.sqlite", "*.pdf", ".env", "secrets/", "private/", "artifacts/", "*.zip"]
    missing = [pat for pat in needed if pat not in text]
    rec("PASS" if not missing else "FAIL", "gitignore_protections", f"missing={missing or 'none'}")

def check_port_health() -> None:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=2) as r:
            body = json.loads(r.read().decode("utf-8", "replace"))
            rec("PASS", "health", f"UP version={body.get('version')}")
            return
    except Exception:
        pass
    rec("WARN", "health", "DOWN (not running — start with START_WINDOWS.bat)")

def check_reviewer_files() -> None:
    files = ["index.html", "app.js", "styles.css", "sw.js", "manifest.webmanifest"]
    missing = [f for f in files if not (ROOT / "portable-reviewer" / f).exists()]
    rec("PASS" if not missing else "FAIL", "portable_reviewer_files", f"missing={missing or 'none'}")

def check_public_repo_guard_script() -> None:
    rec("PASS" if (ROOT / "scripts" / "public_repo_guard.py").exists() else "FAIL",
        "public_repo_guard_script", "")

def quick_checks() -> None:
    check_git()
    check_python()
    check_node()
    check_venv()
    check_requirements_sync()
    check_manifest()
    check_data_path()
    check_protected_paths_ignored()
    check_port_health()
    check_reviewer_files()
    check_public_repo_guard_script()

def full_checks() -> None:
    checks = [
        ("compile", ["python", "-m", "compileall", "-q", "app", "tests", "scripts"], 180),
        ("js_app", ["node", "--check", "app/static/app.js"], 60),
        ("js_reviewer", ["node", "--check", "portable-reviewer/app.js"], 60),
        ("js_sw", ["node", "--check", "portable-reviewer/sw.js"], 60),
        ("pytest", ["python", "-m", "pytest", "-q"], 600),
        ("http_smoke", ["python", "scripts/http_smoke.py"], 300),
        ("protocol_smoke", ["python", "scripts/study_protocol_roundtrip_smoke.py"], 300),
        ("backup_restore", ["python", "scripts/backup_restore_smoke.py"], 300),
        ("portable_smoke", ["python", "scripts/portable_reviewer_smoke.py"], 300),
    ]
    env = chromium_env()
    for name, cmd, timeout in checks:
        out, rc = run(cmd, timeout=timeout, env=env)
        rec("PASS" if rc == 0 else "FAIL", name, "" if rc == 0 else (out.strip().splitlines()[-1][:200] if out.strip() else "exit=%d" % rc))

def write_verification(ok: bool, tests_passed: int | None) -> None:
    head, _ = run(["git", "rev-parse", "HEAD"])
    data = {
        "verification_level": "LOCALLY_VERIFIED_FULL" if ok else "VERIFICATION_FAILED",
        "last_verified_commit": head or "unknown",
        "verified_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "tests_passed": tests_passed,
    }
    VERIFICATION_FILE.parent.mkdir(parents=True, exist_ok=True)
    VERIFICATION_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Alpha doctor self-check.")
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--quick", action="store_true")
    group.add_argument("--full", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    global JSON_MODE
    JSON_MODE = args.json

    if args.full:
        quick_checks()
        full_checks()
        tests_passed = None
        for r in RESULTS:
            if r["name"] == "pytest":
                try:
                    tests_passed = int(r["detail"].split()[0])
                except Exception:
                    pass
        ok = not any(r["level"] == "FAIL" for r in RESULTS)
        write_verification(ok, tests_passed)
    else:
        quick_checks()

    blocked = any(r["level"] == "BLOCKED" for r in RESULTS)
    failed = any(r["level"] == "FAIL" for r in RESULTS)

    if args.json:
        print(json.dumps({"exit_code": 2 if blocked else (1 if failed else 0), "results": RESULTS},
                         ensure_ascii=False, indent=2))
    print(f"\n== alpha doctor: {sum(1 for r in RESULTS if r['level']=='PASS')} PASS, "
          f"{sum(1 for r in RESULTS if r['level']=='WARN')} WARN, "
          f"{sum(1 for r in RESULTS if r['level']=='FAIL')} FAIL, "
          f"{sum(1 for r in RESULTS if r['level']=='BLOCKED')} BLOCKED")
    if blocked:
        return 2
    if failed:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
