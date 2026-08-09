"""Phase 11: public_repo_guard quality proof — the guard really blocks."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.public_repo_guard import check_content, check_path, main  # noqa: E402


def findings_for_path(name: str) -> list:
    out = []
    check_path(name, out)
    return out


def findings_for_content(name: str, text: str, tmp_path: Path) -> list:
    f = tmp_path / name
    f.write_text(text, encoding="utf-8")
    out = []
    # check_content reads ROOT/name — monkeypatch by resolving via tmp is not
    # possible without chdir; so test the pure regexes through check_content
    # on a file placed at repo root path is unsafe. Instead test patterns via
    # check_path (names) and a direct content probe below.
    return out


def test_check_path_blocks_forbidden_names():
    bad = [
        "data/workbench.db",
        "exports/StudyPack-2026.json",
        "x.sqlite",
        "x.db-wal",
        "x.sqlite3-shm",
        "docs/textbook.pdf",
        ".env",
        ".env.local",
        "secrets/token.pem",
        "id_rsa",
        "private/key.p12",
        "artifacts/shot.png",
        ".reasonix/token",
        "handoff/local-agent-handoff-v0.1.zip",
        "backup.zip",
    ]
    for name in bad:
        assert findings_for_path(name), f"guard missed {name}"


def test_check_path_allows_clean_names():
    good = [
        "app/main.py",
        "tests/test_foo.py",
        "docs/ARCHITECTURE.md",
        "portable-reviewer/app.js",
        "README.md",
        "synthetic_fixture.json",
        "scripts/backup_local.py",
        ".agent/PROJECT_STATE.md",
        "requirements-lock.txt",
    ]
    for name in good:
        assert not findings_for_path(name), f"guard false positive {name}"


def test_check_content_catches_secrets(tmp_path: Path, monkeypatch):
    import scripts.public_repo_guard as guard
    monkeypatch.setattr(guard, "ROOT", tmp_path)
    secrets = [
        "-----BEGIN PRIVATE KEY-----\nMIIE",
        "AKIAIOSFODNN7EXAMPLE",
        "ghp_0123456789abcdef0123456789abcdef0123456789abcdef",
        "sk-proj-abcdef0123456789abcdef0123456789abcdef",
    ]
    for secret in secrets:
        f = tmp_path / "s.txt"
        f.write_text(secret, encoding="utf-8")
        out = []
        check_content(str(f), out)
        assert out, f"guard missed secret {secret[:20]}"


def test_check_content_allows_legal_chinese_text(tmp_path: Path, monkeypatch):
    import scripts.public_repo_guard as guard
    monkeypatch.setattr(guard, "ROOT", tmp_path)
    legal = "善意取得应当具备下列条件：处分人为无处分权人。受让人在受让时为善意。以合理价格转让。"
    f = tmp_path / "fixture.txt"
    f.write_text(legal, encoding="utf-8")
    out = []
    check_content(str(f), out)
    assert not out, "legal text must not be treated as a secret"


def test_check_content_catches_real_user_path(tmp_path: Path, monkeypatch):
    import scripts.public_repo_guard as guard
    monkeypatch.setattr(guard, "ROOT", tmp_path)
    f = tmp_path / "p.txt"
    f.write_text(r"home = C:\Users\realuser\Documents", encoding="utf-8")
    out = []
    check_content(str(f), out)
    assert out, "guard missed a real user absolute path"


def test_main_tracked_clean_exit_zero():
    # current tracked tree must pass the guard (fail-closed only when needed)
    assert main(["--tracked"]) == 0
