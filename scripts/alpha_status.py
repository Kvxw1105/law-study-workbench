#!/usr/bin/env python3
"""alpha_status.py — real-time repository/environment status.

Reads LIVE facts (git, versions, health, verification metadata).
It deliberately does NOT read or print any study data content.

Usage:
    python scripts/alpha_status.py
    python scripts/alpha_status.py --json
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HEALTH_URL = "http://127.0.0.1:8765/api/health"


def run(cmd: list[str], timeout: int = 10) -> tuple[str, int]:
    try:
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip(), r.returncode
    except Exception:
        return "", -1


def git_remote() -> str:
    out, _ = run(["git", "remote", "get-url", "origin"])
    return out or "n/a"


def git_branch() -> str:
    out, _ = run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    return out or "n/a"


def git_head() -> str:
    out, _ = run(["git", "rev-parse", "HEAD"])
    return out or "n/a"


def git_dirty() -> bool:
    out, _ = run(["git", "status", "--porcelain"])
    return bool(out)


def ahead_behind() -> dict | None:
    out, _ = run(["git", "rev-list", "--left-right", "--count", "HEAD...@{u}"])
    if not out:
        return None
    parts = out.split()
    if len(parts) == 2 and all(p.lstrip("-").isdigit() for p in parts):
        return {"ahead": int(parts[0]), "behind": int(parts[1])}
    return None


def baseline_tag() -> str:
    out, _ = run(["git", "tag", "--list", "alpha-*"])
    tags = [t for t in out.splitlines() if t.strip()]
    return tags[-1] if tags else "n/a"


def manifest_facts() -> dict:
    mf = ROOT / "project-manifest.json"
    if not mf.exists():
        return {}
    try:
        data = json.loads(mf.read_text(encoding="utf-8"))
    except Exception:
        return {}
    proto = data.get("capabilities", {}).get("portable_study_protocol", {})
    return {
        "product_version": data.get("version"),
        "schema": data.get("data", {}).get("schema_version"),
        "study_protocol": proto.get("study_pack_protocol"),
        "study_events_protocol": proto.get("study_events_protocol"),
        "data_default_home": data.get("data", {}).get("default_home"),
        "bind": data.get("runtime", {}).get("bind"),
    }


def python_version() -> str:
    out, _ = run([sys.executable, "--version"])
    return out or "n/a"


def node_version() -> str:
    out, _ = run(["node", "--version"])
    return out or "n/a"


def health() -> dict:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=1.5) as r:
            body = json.loads(r.read().decode("utf-8", "replace"))
            return {
                "state": "UP",
                "url": HEALTH_URL,
                "status": body.get("status"),
                "version": body.get("version"),
                "storage": body.get("storage"),
                "ai_provider": body.get("ai_provider"),
            }
    except Exception:
        return {"state": "DOWN", "url": HEALTH_URL, "status": None, "version": None}


def verification_metadata() -> dict:
    # Ephemeral, locally-written facts (produced by alpha_doctor --full).
    vf = ROOT / ".agent" / "VERIFICATION.json"
    if vf.exists():
        try:
            return json.loads(vf.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"verification_level": "UNVERIFIED", "note": "run python scripts/alpha_doctor.py --full"}


def collect() -> dict:
    mf = manifest_facts()
    return {
        "repository": git_remote(),
        "branch": git_branch(),
        "HEAD": git_head(),
        "dirty": git_dirty(),
        "ahead_behind": ahead_behind(),
        "baseline_tag": baseline_tag(),
        "product_version": mf.get("product_version"),
        "schema": mf.get("schema"),
        "study_protocol": mf.get("study_protocol"),
        "study_events_protocol": mf.get("study_events_protocol"),
        "data_path": os.environ.get("LAW_STUDY_HOME") or mf.get("data_default_home"),
        "bind": mf.get("bind"),
        "health": health(),
        "python": python_version(),
        "node": node_version(),
        "verification": verification_metadata(),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Real-time alpha status (no study data content).")
    ap.add_argument("--json", action="store_true", help="JSON output")
    args = ap.parse_args()

    data = collect()
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0

    ab = data["ahead_behind"]
    ab_s = "n/a" if ab is None else f"ahead={ab['ahead']} behind={ab['behind']}"
    print(f"repository     : {data['repository']}")
    print(f"branch         : {data['branch']}")
    print(f"HEAD           : {data['HEAD']}")
    print(f"dirty          : {data['dirty']}")
    print(f"ahead/behind   : {ab_s}")
    print(f"baseline tag   : {data['baseline_tag']}")
    print(f"product version: {data['product_version']}")
    print(f"schema         : {data['schema']}")
    print(f"study protocol : {data['study_protocol']} / {data['study_events_protocol']}")
    print(f"data path      : {data['data_path']}")
    print(f"bind           : {data['bind']}")
    h = data["health"]
    print(f"health         : {h.get('state')} ({h.get('url')}) status={h.get('status')} version={h.get('version')}")
    print(f"python         : {data['python']}")
    print(f"node           : {data['node']}")
    v = data["verification"]
    print(f"verification   : level={v.get('verification_level')}")
    if v.get("verified_at"):
        print(f"                 last_verified_commit={v.get('last_verified_commit')} at={v.get('verified_at')} tests_passed={v.get('tests_passed')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
