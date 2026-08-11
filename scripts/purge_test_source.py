#!/usr/bin/env python3
"""purge_test_source.py — 彻底删除测试残留教材来源（一次性维护脚本）。

背景：上一任 Agent 在真实用户库中导入了 2 个 audit.pdf 测试教材（各 1 页），
造成今日任务/建议列表出现 2 个重复的“善意取得”幽灵单元。用户已授权彻底删除。

安全设计：
  1. 严格守卫：只允许删除 original_name == 'audit.pdf' 且 page_count == 1
     且 file_size <= 5000 的来源（测试文件特征），其余一律拒绝。
  2. 删除前自动备份 data/workbench.db 到 data/backups/purge-<时间戳>.db。
  3. 默认 --dry-run：只报告将要删除的行，不落盘。
  4. 删除完成后写入一条 study_events 审计事件（test_data_purged），
     证据链保持可追溯。

用法：
  python scripts/purge_test_source.py --dry-run          # 只看不改
  python scripts/purge_test_source.py --confirm          # 备份后删除

注意：这是数据维护脚本，不属于产品 API；删除不可逆（有备份可恢复）。
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "workbench.db"
LIBRARY_DIR = ROOT / "data" / "library"
BACKUP_DIR = ROOT / "data" / "backups"

# 守卫：只认测试残留文件特征，杜绝误删真实教材
GUARD_NAME = "audit.pdf"
GUARD_MAX_FILE_SIZE = 5000
GUARD_PAGE_COUNT = 1

# 删除依赖顺序（子表先于父表）
DELETE_ORDER = [
    "retrieval_review_states",  # 依赖 retrieval_items
    "retrieval_attempts",       # 依赖 retrieval_items
    "retrieval_items",          # 依赖 knowledge_units
    "review_states",            # 依赖 knowledge_units
    "attempts",                 # 依赖 study_sessions / knowledge_units
    "study_sessions",           # 依赖 knowledge_units
    "error_records",            # 依赖 attempts / knowledge_units
    "knowledge_unit_versions",  # 依赖 knowledge_units
    "knowledge_units",
    "source_pages",
    "study_events",
    "source_documents",
]


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def collect_targets(conn: sqlite3.Connection) -> list[dict]:
    """收集所有符合守卫条件的来源及其关联数据（计数 + 主键）。"""
    rows = conn.execute(
        "SELECT id, original_name, stored_path, file_size, page_count "
        "FROM source_documents ORDER BY created_at"
    ).fetchall()
    targets: list[dict] = []
    for row in rows:
        if row["original_name"] != GUARD_NAME:
            print(f"  [跳过] {row['original_name']}（不是测试残留，名称不匹配）")
            continue
        if row["page_count"] != GUARD_PAGE_COUNT or row["file_size"] > GUARD_MAX_FILE_SIZE:
            print(f"  [拒绝] {row['original_name']} 特征不符（page={row['page_count']} size={row['file_size']}）")
            continue
        unit_ids = [
            r["id"] for r in conn.execute(
                "SELECT id FROM knowledge_units WHERE source_id=?", (row["id"],)
            ).fetchall()
        ]
        item_ids = [
            r["id"] for r in conn.execute(
                "SELECT id FROM retrieval_items WHERE knowledge_unit_id IN (%s)"
                % ",".join("?" * len(unit_ids)) if unit_ids else "SELECT NULL WHERE 0",
                unit_ids,
            ).fetchall()
        ]
        counts: dict[str, int] = {}
        for table in DELETE_ORDER:
            if table == "retrieval_review_states":
                sql = "SELECT COUNT(*) c FROM retrieval_review_states WHERE retrieval_item_id IN (%s)" % (
                    ",".join("?" * len(item_ids)) if item_ids else "SELECT NULL WHERE 0"
                )
                params: tuple = tuple(item_ids)
            elif table == "retrieval_attempts":
                sql = "SELECT COUNT(*) c FROM retrieval_attempts WHERE knowledge_unit_id IN (%s)" % (
                    ",".join("?" * len(unit_ids)) if unit_ids else "SELECT NULL WHERE 0"
                )
                params = tuple(unit_ids)
            elif table == "retrieval_items":
                sql = "SELECT COUNT(*) c FROM retrieval_items WHERE knowledge_unit_id IN (%s)" % (
                    ",".join("?" * len(unit_ids)) if unit_ids else "SELECT NULL WHERE 0"
                )
                params = tuple(unit_ids)
            elif table in ("study_events",):
                sql = (
                    "SELECT COUNT(*) c FROM study_events WHERE entity_type='knowledge_unit' AND entity_id IN (%s)"
                    % (",".join("?" * len(unit_ids)) if unit_ids else "SELECT NULL WHERE 0")
                )
                params = tuple(unit_ids)
            elif table == "source_pages":
                sql = "SELECT COUNT(*) c FROM source_pages WHERE source_id=?"
                params = (row["id"],)
            elif table == "source_documents":
                sql = "SELECT COUNT(*) c FROM source_documents WHERE id=?"
                params = (row["id"],)
            elif table == "knowledge_units":
                sql = "SELECT COUNT(*) c FROM knowledge_units WHERE id IN (%s)" % (
                    ",".join("?" * len(unit_ids)) if unit_ids else "SELECT NULL WHERE 0"
                )
                params = tuple(unit_ids)
            else:
                sql = "SELECT COUNT(*) c FROM %s WHERE knowledge_unit_id IN (%s)" % (
                    table,
                    ",".join("?" * len(unit_ids)) if unit_ids else "SELECT NULL WHERE 0",
                )
                params = tuple(unit_ids)
            counts[table] = conn.execute(sql, params).fetchone()["c"]
        targets.append(
            {
                "source_id": row["id"],
                "original_name": row["original_name"],
                "stored_path": row["stored_path"],
                "unit_ids": unit_ids,
                "item_ids": item_ids,
                "counts": counts,
            }
        )
    return targets


def purge(conn: sqlite3.Connection, target: dict) -> None:
    """按依赖顺序删除单个来源及其关联数据。"""
    unit_ids = target["unit_ids"]
    item_ids = target["item_ids"]
    source_id = target["source_id"]

    def run(sql: str, params: tuple = ()) -> None:
        conn.execute(sql, params)

    if item_ids:
        run(
            "DELETE FROM retrieval_review_states WHERE retrieval_item_id IN (%s)"
            % ",".join("?" * len(item_ids)),
            tuple(item_ids),
        )
        run(
            "DELETE FROM retrieval_attempts WHERE knowledge_unit_id IN (%s)"
            % ",".join("?" * len(unit_ids)),
            tuple(unit_ids),
        )
        run(
            "DELETE FROM retrieval_items WHERE knowledge_unit_id IN (%s)"
            % ",".join("?" * len(unit_ids)),
            tuple(unit_ids),
        )
    if unit_ids:
        run(
            "DELETE FROM review_states WHERE knowledge_unit_id IN (%s)"
            % ",".join("?" * len(unit_ids)),
            tuple(unit_ids),
        )
        run(
            "DELETE FROM attempts WHERE knowledge_unit_id IN (%s)"
            % ",".join("?" * len(unit_ids)),
            tuple(unit_ids),
        )
        run(
            "DELETE FROM study_sessions WHERE knowledge_unit_id IN (%s)"
            % ",".join("?" * len(unit_ids)),
            tuple(unit_ids),
        )
        run(
            "DELETE FROM error_records WHERE knowledge_unit_id IN (%s)"
            % ",".join("?" * len(unit_ids)),
            tuple(unit_ids),
        )
        run(
            "DELETE FROM knowledge_unit_versions WHERE knowledge_unit_id IN (%s)"
            % ",".join("?" * len(unit_ids)),
            tuple(unit_ids),
        )
        run(
            "DELETE FROM knowledge_units WHERE id IN (%s)"
            % ",".join("?" * len(unit_ids)),
            tuple(unit_ids),
        )
        run(
            "DELETE FROM study_events WHERE entity_type='knowledge_unit' AND entity_id IN (%s)"
            % ",".join("?" * len(unit_ids)),
            tuple(unit_ids),
        )
    run("DELETE FROM source_pages WHERE source_id=?", (source_id,))
    run("DELETE FROM source_documents WHERE id=?", (source_id,))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="彻底删除测试残留教材来源（审计 + 备份 + 守卫）")
    parser.add_argument("--dry-run", action="store_true", help="只报告将删除的行，不落盘")
    parser.add_argument("--confirm", action="store_true", help="确认执行（自动先备份）")
    args = parser.parse_args(argv)

    if not DB.exists():
        print(f"[错误] 数据库不存在：{DB}")
        return 1

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    try:
        targets = collect_targets(conn)
        if not targets:
            print("[结果] 未发现符合条件的测试残留来源，无需清理。")
            return 0

        total = sum(t["counts"][table] for t in targets for table in DELETE_ORDER)
        print(f"[计划] 找到 {len(targets)} 个测试残留来源，将删除 {total} 行数据：")
        for t in targets:
            print(f"  - {t['original_name']} ({t['source_id']}) units={len(t['unit_ids'])} "
                  f"items={len(t['item_ids'])} " + " ".join(f"{k}={v}" for k, v in t["counts"].items() if v))
            if t["stored_path"] and Path(t["stored_path"]).exists():
                print(f"    关联文件：{t['stored_path']}")

        if args.dry_run or not args.confirm:
            print("\n[提示] 未执行删除。确认请加 --confirm（会先备份数据库）。")
            return 0

        # 备份
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        backup_path = BACKUP_DIR / f"purge-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}.db"
        shutil.copy2(DB, backup_path)
        print(f"[备份] {backup_path}")

        # 执行
        for t in targets:
            purge(conn, t)
            if t["stored_path"] and Path(t["stored_path"]).exists():
                Path(t["stored_path"]).unlink()
                print(f"[删除] 文件 {t['stored_path']}")
        conn.execute(
            "INSERT INTO study_events(event_type, entity_type, entity_id, payload_json, created_at) "
            "VALUES('test_data_purged', 'source', ?, ?, ?)",
            (
                ",".join(t["source_id"] for t in targets),
                str({"purged_sources": [t["source_id"] for t in targets], "by": "purge_test_source.py"}),
                _utc_now(),
            ),
        )
        conn.commit()
        print(f"[完成] 已删除 {len(targets)} 个测试残留来源，数据行 {total} 行。审计事件已写入 study_events。")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
