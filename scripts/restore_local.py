from __future__ import annotations

import argparse
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


def validate_database(path: Path) -> None:
    if not path.exists():
        raise RuntimeError("备份中缺少 workbench.db")
    connection = sqlite3.connect(path)
    try:
        result = connection.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        connection.close()
    if result != "ok":
        raise RuntimeError(f"备份数据库完整性检查失败：{result}")


def main() -> None:
    parser = argparse.ArgumentParser(description="恢复本地学习库。执行前请关闭工作台。")
    parser.add_argument("backup", type=Path)
    parser.add_argument("--yes", action="store_true", help="跳过交互确认")
    args = parser.parse_args()

    backup = args.backup.expanduser().resolve()
    home = resolve_home()
    if not backup.exists():
        raise SystemExit(f"备份不存在：{backup}")

    print(f"将从以下备份恢复：{backup}")
    print(f"目标目录：{home}")
    print("当前数据会先移动到 rollback-时间戳 目录，不会直接删除。")
    if not args.yes:
        confirmation = input("输入 RESTORE 继续：").strip()
        if confirmation != "RESTORE":
            raise SystemExit("已取消")

    with tempfile.TemporaryDirectory(prefix="law-study-restore-") as temp_name:
        temp = Path(temp_name)
        with zipfile.ZipFile(backup) as archive:
            archive.extractall(temp)
        validate_database(temp / "workbench.db")

        home.parent.mkdir(parents=True, exist_ok=True)
        rollback = home.parent / f"rollback-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}"
        if home.exists():
            shutil.move(str(home), str(rollback))
        home.mkdir(parents=True, exist_ok=True)
        shutil.copy2(temp / "workbench.db", home / "workbench.db")
        if (temp / "library").exists():
            shutil.copytree(temp / "library", home / "library", dirs_exist_ok=True)
    print(f"恢复完成。旧数据保存在：{rollback}")


if __name__ == "__main__":
    main()
