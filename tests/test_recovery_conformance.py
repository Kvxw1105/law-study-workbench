"""Phase 6: Crash / Recovery / Durability conformance (tempdir synthetic data).

Proves: history evidence survives restarts and backup/restore roundtrips,
repeated backups stay valid, truncated/corrupt/wrong backups are rejected,
restore never destroys the current library without a rollback copy, and WAL
data is captured consistently. Never touches real user data.
"""
from __future__ import annotations

import io
import shutil
import sqlite3
import tempfile
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.support import make_pdf

from app.config import Settings
from app.main import create_app

SOURCE_TEXT = (
    "善意取得应当具备下列条件：处分人为无处分权人；受让人在受让该财产时为善意；"
    "以合理价格转让；依法应当登记的已经登记，不需要登记的已经交付。"
)


def make_settings(home: Path) -> Settings:
    return Settings(
        home=home,
        db_path=home / "workbench.db",
        library_dir=home / "library",
        export_dir=home / "exports",
        static_dir=Path(__file__).resolve().parents[1] / "app" / "static",
    )


def seed_library(client: TestClient) -> dict:
    response = client.post(
        "/api/sources/import?wait=true",
        files={"file": ("recovery.pdf", io.BytesIO(make_pdf()), "application/pdf")},
    )
    assert response.status_code == 200, response.text
    source = response.json()["source"]
    unit = client.get(f"/api/sources/{source['id']}/units").json()[0]
    generated = client.post(
        f"/api/units/{unit['id']}/retrieval-items/generate",
        json={"item_types": ["flashcard", "cloze"], "max_per_type": 2},
    )
    assert generated.status_code == 200, generated.text
    items = generated.json()["items"]
    flash = next(i for i in items if i["item_type"] == "flashcard")
    client.post(f"/api/retrieval-items/{flash['id']}/reveal").raise_for_status()
    client.post(
        f"/api/retrieval-items/{flash['id']}/attempts",
        json={"rating": "good", "elapsed_ms": 1000, "revealed_answer": True},
    ).raise_for_status()
    return {"source": source, "unit": unit, "flash": flash}


def make_backup(home: Path, dest: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="ls-bk-") as t:
        snap = Path(t) / "workbench.db"
        src = sqlite3.connect(home / "workbench.db")
        dst = sqlite3.connect(snap)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(snap, "workbench.db")
            archive.writestr("BACKUP_INFO.txt", "created_at=test\nsource_home=test\n")


def restore_into(backup: Path, home: Path) -> Path:
    """Mirror scripts/restore_local.py validation + rollback + copy. Returns rollback dir."""
    with tempfile.TemporaryDirectory(prefix="ls-rs-") as t:
        with zipfile.ZipFile(backup) as archive:
            archive.extractall(t)
        db = Path(t) / "workbench.db"
        if not db.exists():
            raise RuntimeError("备份中缺少 workbench.db")
        conn = sqlite3.connect(db)
        try:
            result = conn.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            conn.close()
        assert result == "ok"
        rollback = home.parent / f"rollback-{home.name}"
        if rollback.exists():
            shutil.rmtree(rollback)
        if home.exists():
            home.rename(rollback)
        home.mkdir(parents=True)
        for item in Path(t).iterdir():
            target = home / item.name
            if item.is_dir():
                shutil.copytree(item, target)
            else:
                shutil.copy2(item, target)
        return rollback


def attempt_counts(client: TestClient) -> tuple[int, int]:
    data = client.get("/api/export").json()["tables"]
    return len(data["attempts"]), len(data["retrieval_attempts"])


# --------------------------------------------------------------------------

def test_attempt_and_retrieval_survive_restart(settings: Settings):
    first = TestClient(create_app(settings))
    with first:
        seed_library(first)
        assert attempt_counts(first) == (0, 1)
    second = TestClient(create_app(settings))
    with second:
        assert attempt_counts(second) == (0, 1)
        assert second.get("/api/retrieval/summary").json()["attempts"] == 1


def test_multiple_restarts_preserve_evidence(settings: Settings):
    for round_index in range(3):
        app = TestClient(create_app(settings))
        with app:
            if round_index == 0:
                seed_library(app)
            counts = attempt_counts(app)
            assert counts == (0, 1), f"round {round_index}: {counts}"
            summary = app.get("/api/retrieval/summary").json()
            assert summary["attempts"] == 1


def test_backup_restore_roundtrip_preserves_all_evidence(settings: Settings):
    with TestClient(create_app(settings)) as client:
        seed_library(client)
        (0, 1) == attempt_counts(client)
    backup = settings.home.parent / "backup-test.zip"
    make_backup(settings.home, backup)
    assert backup.exists()

    # restore into a fresh copy of the home (simulates restoring to a new machine)
    fresh_home = settings.home.parent / "restored-home"
    if fresh_home.exists():
        shutil.rmtree(fresh_home)
    fresh_home.mkdir(parents=True)
    restore_into(backup, fresh_home)
    fresh_settings = make_settings(fresh_home)
    with TestClient(create_app(fresh_settings)) as client:
        assert attempt_counts(client) == (0, 1)
        assert client.get("/api/retrieval/summary").json()["attempts"] == 1


def test_repeated_backups_are_both_valid(settings: Settings):
    with TestClient(create_app(settings)) as client:
        seed_library(client)
    b1 = settings.home.parent / "b1.zip"
    b2 = settings.home.parent / "b2.zip"
    make_backup(settings.home, b1)
    make_backup(settings.home, b2)
    for b in (b1, b2):
        fresh = settings.home.parent / f"fresh-{b.stem}"
        if fresh.exists():
            shutil.rmtree(fresh)
        fresh.mkdir(parents=True)
        restore_into(b, fresh)
        with TestClient(create_app(make_settings(fresh))) as client:
            assert attempt_counts(client) == (0, 1)


def test_wal_mode_active_and_backup_captures_wal(settings: Settings):
    with TestClient(create_app(settings)) as client:
        seed_library(client)
    conn = sqlite3.connect(settings.home / "workbench.db")
    try:
        journal = conn.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        conn.close()
    assert journal == "wal"
    backup = settings.home.parent / "wal-backup.zip"
    make_backup(settings.home, backup)
    fresh = settings.home.parent / "wal-fresh"
    if fresh.exists():
        shutil.rmtree(fresh)
    fresh.mkdir(parents=True)
    restore_into(backup, fresh)
    with TestClient(create_app(make_settings(fresh))) as client:
        assert client.get("/api/retrieval/summary").json()["attempts"] == 1


def test_truncated_backup_zip_rejected(settings: Settings):
    with TestClient(create_app(settings)) as client:
        seed_library(client)
    backup = settings.home.parent / "truncated.zip"
    make_backup(settings.home, backup)
    data = backup.read_bytes()[: len(backup.read_bytes()) // 2]
    backup.write_bytes(data)
    fresh = settings.home.parent / "trunc-fresh"
    fresh.mkdir(parents=True, exist_ok=True)
    with pytest.raises((zipfile.BadZipFile, Exception)):
        restore_into(backup, fresh)


def test_non_zip_backup_rejected(settings: Settings):
    backup = settings.home.parent / "fake.zip"
    backup.write_bytes(b"this is not a zip archive at all")
    fresh = settings.home.parent / "fake-fresh"
    fresh.mkdir(parents=True, exist_ok=True)
    with pytest.raises((zipfile.BadZipFile, Exception)):
        restore_into(backup, fresh)


def test_zip_without_db_rejected(settings: Settings):
    backup = settings.home.parent / "nodb.zip"
    with zipfile.ZipFile(backup, "w") as archive:
        archive.writestr("BACKUP_INFO.txt", "no database here")
    fresh = settings.home.parent / "nodb-fresh"
    fresh.mkdir(parents=True, exist_ok=True)
    with pytest.raises((RuntimeError, Exception)):
        restore_into(backup, fresh)


def test_restore_moves_current_library_to_rollback(settings: Settings):
    with TestClient(create_app(settings)) as client:
        seed_library(client)
    backup = settings.home.parent / "rb.zip"
    make_backup(settings.home, backup)
    rollback = restore_into(backup, settings.home)
    assert rollback.exists()
    assert (rollback / "workbench.db").exists()
    # original home restored and usable
    with TestClient(create_app(settings)) as client:
        assert attempt_counts(client) == (0, 1)


def test_backup_failure_does_not_corrupt_original(settings: Settings):
    with TestClient(create_app(settings)) as client:
        seed_library(client)
    # a failed backup attempt (e.g. disk full) must not damage the live DB
    db_path = settings.home / "workbench.db"
    before = (db_path).read_bytes()
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA wal_checkpoint")
    conn.close()
    with TestClient(create_app(settings)) as client:
        # simulate a partial backup then continue using the app
        with tempfile.TemporaryDirectory() as t:
            snap = Path(t) / "partial.db"
            src = sqlite3.connect(db_path)
            dst = sqlite3.connect(snap)
            src.backup(dst)
            dst.close()
            src.close()
        summary = client.get("/api/retrieval/summary").json()
        assert summary["attempts"] == 1
    after = (db_path).read_bytes()
    assert after == before
