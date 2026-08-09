#!/usr/bin/env python3
"""public_repo_guard.py — fail-closed safety scan for the PUBLIC repository.

Scans tracked and/or staged files for content that must never enter the
public repo. Exits non-zero to block a mistaken commit.

Usage:
    python scripts/public_repo_guard.py --tracked
    python scripts/public_repo_guard.py --staged
    python scripts/public_repo_guard.py --tracked --staged --json

Checks (paths): *.db / *.sqlite* / *-wal / *-shm / *.pdf / StudyPack*.json /
StudyEvents*.json / .env* / private keys / token-like secrets / data/ /
artifacts/ / .reasonix/ / handoff zips / absolute user paths.

Checks (content, staged/tracked text files): obvious secrets, absolute user
paths, local usernames. Synthetic fixtures (tests/scripts data) are allowed:
legal text or Chinese content is NOT treated as a secret.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Guard's own test file intentionally contains secret-shaped samples.
ALLOWED_CONTENT_FILES = {"tests/test_public_repo_guard.py"}

FORBIDDEN_PATH_PATTERNS = (
    r"\.db$", r"\.sqlite$", r"\.sqlite3$", r"\.sqlite-wal$", r"\.sqlite-shm$",
    r"-wal$", r"-shm$", r"-journal$", r"\.pdf$", r"(^|/)StudyPack.*\.json$",
    r"(^|/)StudyEvents.*\.json$", r"(^|/)\.env($|\.)", r"\.pem$", r"\.key$",
    r"\.p12$", r"\.pfx$", r"\.jks$", r"\.keystore$", r"id_rsa$", r"id_ed25519$",
    r"(^|/)data/", r"(^|/)artifacts/", r"(^|/)\.reasonix/",
    r".*local-agent-handoff.*\.zip$", r"\.zip$",
)

FORBIDDEN_CONTENT_PATTERNS = (
    r"BEGIN (RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY",
    r"AKIA[0-9A-Z]{16}",
    r"ghp_[A-Za-z0-9]{36,}",
    r"sk-[A-Za-z0-9-]{24,}",
    r"xox[baprs]-[A-Za-z0-9-]{10,}",
)

USER_PATH_PATTERNS = (
    r"[A-Za-z]:\\Users\\[A-Za-z0-9_.-]+",
    r"/Users/[A-Za-z0-9_.-]+",
    r"/home/[A-Za-z0-9_.-]+",
    r"C:\\Windows",
)


def git_files(scope: str) -> list[str]:
    if scope == "tracked":
        cmd = ["git", "ls-files"]
    else:
        cmd = ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"]
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=30)
    return [line for line in r.stdout.splitlines() if line.strip()]


def check_path(name: str, findings: list[dict]) -> None:
    for pattern in FORBIDDEN_PATH_PATTERNS:
        if re.search(pattern, name):
            findings.append({"file": name, "kind": "path", "pattern": pattern})
            return


def check_content(name: str, findings: list[dict]) -> None:
    if name in ALLOWED_CONTENT_FILES:
        return
    if name.startswith("app/static/vendor/"):
        # 第三方库（如 pdf.js 压缩代码）可能含 /home/ 等假路径，不属用户数据泄露
        return
    try:
        # scan every UTF-8-decodable file (binaries fail decode and are skipped)
        text = (ROOT / name).read_bytes().decode("utf-8")
    except Exception:
        return
    for pattern in FORBIDDEN_CONTENT_PATTERNS:
        m = re.search(pattern, text)
        if m:
            findings.append({"file": name, "kind": "secret", "pattern": pattern, "sample": m.group(0)[:40]})
            return
    for pattern in USER_PATH_PATTERNS:
        m = re.search(pattern, text)
        if m:
            findings.append({"file": name, "kind": "path", "pattern": pattern, "sample": m.group(0)[:60]})


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Public repo safety guard.")
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--tracked", action="store_true")
    group.add_argument("--staged", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    scope = "tracked" if args.tracked else "staged"
    files = git_files(scope)
    findings: list[dict] = []
    for name in files:
        check_path(name, findings)
        check_content(name, findings)

    if args.json:
        print(json.dumps({"scope": scope, "files_scanned": len(files),
                          "findings": findings, "blocked": bool(findings)}, ensure_ascii=False, indent=2))
    else:
        print(f"public_repo_guard: scope={scope} files={len(files)} findings={len(findings)}")
        for f in findings:
            print(f"  BLOCK {f['kind']:<6} {f['file']}  ({f.get('pattern', '')})")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
