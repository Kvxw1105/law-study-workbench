from __future__ import annotations

import io
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import fitz
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


SOURCE_TEXT = (
    "善意取得应当具备下列条件：处分人为无处分权人；受让人在受让该财产时为善意；"
    "以合理价格转让；依法应当登记的已经登记，不需要登记的已经交付。"
)


def make_pdf() -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_textbox(fitz.Rect(50, 60, 540, 760), SOURCE_TEXT, fontsize=12, fontname="china-s")
    payload = document.tobytes()
    document.close()
    return payload


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="law-study-backup-smoke-") as temp_name:
        home = Path(temp_name) / "data"
        settings = Settings(
            home=home,
            db_path=home / "workbench.db",
            library_dir=home / "library",
            export_dir=home / "exports",
            static_dir=ROOT / "app" / "static",
            schema_version=4,
        )
        app = create_app(settings)
        with TestClient(app) as client:
            imported = client.post(
                "/api/sources/import?wait=true",
                files={"file": ("backup-smoke.pdf", io.BytesIO(make_pdf()), "application/pdf")},
            )
            imported.raise_for_status()
            source = imported.json()["source"]
            unit = client.get(f"/api/sources/{source['id']}/units").json()[0]
            generated = client.post(
                f"/api/units/{unit['id']}/retrieval-items/generate",
                json={"item_types": ["flashcard", "cloze"], "max_per_type": 2},
            )
            generated.raise_for_status()
            flash = next(item for item in generated.json()["items"] if item["item_type"] == "flashcard")
            client.post(f"/api/retrieval-items/{flash['id']}/reveal").raise_for_status()
            client.post(
                f"/api/retrieval-items/{flash['id']}/attempts",
                json={"rating": "good", "elapsed_ms": 750, "revealed_answer": True},
            ).raise_for_status()

        env = os.environ.copy()
        env["LAW_STUDY_HOME"] = str(home)
        backup_run = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "backup_local.py")],
            check=True,
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
        )
        backup = Path(backup_run.stdout.strip().splitlines()[-1])
        if not backup.exists():
            raise RuntimeError(f"backup not created: {backup}")

        settings.db_path.write_bytes(b"deliberately-corrupted")
        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "restore_local.py"), str(backup), "--yes"],
            check=True,
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
        )

        connection = sqlite3.connect(settings.db_path)
        try:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            card_count = connection.execute("SELECT COUNT(*) FROM retrieval_items").fetchone()[0]
            attempt_count = connection.execute("SELECT COUNT(*) FROM retrieval_attempts").fetchone()[0]
            captured_snapshot_count = connection.execute(
                "SELECT COUNT(*) FROM retrieval_attempts WHERE snapshot_status='captured' "
                "AND prompt_snapshot != '' AND answer_snapshot != ''"
            ).fetchone()[0]
            schema_version = connection.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
        finally:
            connection.close()
        assert integrity == "ok"
        assert schema_version == "4"
        assert card_count >= 2
        assert attempt_count == 1
        assert captured_snapshot_count == 1
    print("Backup/restore retrieval smoke passed")


if __name__ == "__main__":
    main()
