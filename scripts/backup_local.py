from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path


def resolve_home() -> Path:
    root = Path(__file__).resolve().parents[1]
    return Path(os.getenv("LAW_STUDY_HOME", root / "data")).expanduser().resolve()


def main() -> None:
    home = resolve_home()
    db_path = home / "workbench.db"
    library = home / "library"
    backup_dir = home / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    output = backup_dir / f"law-study-backup-{stamp}.zip"

    with tempfile.TemporaryDirectory(prefix="law-study-backup-") as temp_name:
        temp = Path(temp_name)
        snapshot = temp / "workbench.db"
        if db_path.exists():
            source = sqlite3.connect(db_path)
            target = sqlite3.connect(snapshot)
            try:
                source.backup(target)
            finally:
                target.close()
                source.close()
        manifest = temp / "BACKUP_INFO.txt"
        manifest.write_text(
            f"created_at={datetime.now(UTC).isoformat()}\nsource_home={home}\n",
            encoding="utf-8",
        )
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            if snapshot.exists():
                archive.write(snapshot, "workbench.db")
            archive.write(manifest, "BACKUP_INFO.txt")
            if library.exists():
                for path in library.rglob("*"):
                    if path.is_file():
                        archive.write(path, Path("library") / path.relative_to(library))
    print(output)


if __name__ == "__main__":
    main()
