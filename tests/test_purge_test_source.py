"""purge_test_source.py 守卫与行为测试。

该脚本用于彻底删除真实库中残留的测试教材（audit.pdf），必须保证：
  1. 只命中测试残留特征（名称/页数/大小），真实教材绝不误删；
  2. 删除前自动备份；
  3. 删除后写入审计事件；
  4. 特征不符的同类文件被拒绝。
全部使用临时数据库，不触碰真实 data/。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import scripts.purge_test_source as purge

TABLES = {
    "source_documents": "id TEXT PRIMARY KEY, original_name TEXT, stored_path TEXT, file_size INTEGER, page_count INTEGER, created_at TEXT",
    "knowledge_units": "id TEXT PRIMARY KEY, source_id TEXT, title TEXT, status TEXT",
    "knowledge_unit_versions": "id TEXT PRIMARY KEY, knowledge_unit_id TEXT",
    "source_pages": "id TEXT PRIMARY KEY, source_id TEXT, page_number INTEGER, created_at TEXT",
    "study_events": "id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT, entity_type TEXT, entity_id TEXT, payload_json TEXT, created_at TEXT",
    "retrieval_review_states": "id TEXT PRIMARY KEY, retrieval_item_id TEXT",
    "retrieval_attempts": "id TEXT PRIMARY KEY, knowledge_unit_id TEXT",
    "retrieval_items": "id TEXT PRIMARY KEY, knowledge_unit_id TEXT",
    "review_states": "id TEXT PRIMARY KEY, knowledge_unit_id TEXT",
    "attempts": "id TEXT PRIMARY KEY, knowledge_unit_id TEXT",
    "study_sessions": "id TEXT PRIMARY KEY, knowledge_unit_id TEXT",
    "error_records": "id TEXT PRIMARY KEY, knowledge_unit_id TEXT",
}


def _build_db(tmp_path: Path) -> Path:
    """构造含 2 个测试残留来源 + 1 个真实来源的临时库，并放好库文件。"""
    db_path = tmp_path / "workbench.db"
    library = tmp_path / "library"
    library.mkdir()
    conn = sqlite3.connect(db_path)
    for name, ddl in TABLES.items():
        conn.execute(f"CREATE TABLE {name} ({ddl})")
    # 测试残留（特征符合守卫）
    for i, sid in enumerate(("audit-1", "audit-2")):
        file_path = library / f"{sid}.pdf"
        file_path.write_bytes(b"%PDF-test")
        conn.execute(
            "INSERT INTO source_documents VALUES(?,?,?,?,?,?)",
            (sid, "audit.pdf", str(file_path), 1224, 1, "2026-08-09T06:00:00+00:00"),
        )
        conn.execute(
            "INSERT INTO knowledge_units VALUES(?,?,?,?)",
            (f"unit-{sid}", sid, "善意取得应当具备下列条件", "draft"),
        )
        conn.execute("INSERT INTO knowledge_unit_versions VALUES(?,?)", (f"ver-{sid}", f"unit-{sid}"))
        conn.execute("INSERT INTO source_pages VALUES(?,?,?,?)", (f"page-{sid}", sid, 1, "2026-08-09T06:00:00+00:00"))
    # 真实来源（守卫必须跳过）
    real_file = library / "real.pdf"
    real_file.write_bytes(b"%PDF-real")
    conn.execute(
        "INSERT INTO source_documents VALUES(?,?,?,?,?,?)",
        ("real-1", "（已压缩）2025民法（强化讲义）_可搜索.pdf", str(real_file), 44462341, 198, "2026-08-09T09:00:00+00:00"),
    )
    conn.execute("INSERT INTO knowledge_units VALUES(?,?,?,?)", ("unit-real", "real-1", "第三节 民法的渊源", "approved"))
    conn.commit()
    conn.close()
    return db_path


def test_dry_run_reports_only_test_sources(tmp_path, monkeypatch):
    db_path = _build_db(tmp_path)
    monkeypatch.setattr(purge, "DB", db_path)
    monkeypatch.setattr(purge, "LIBRARY_DIR", tmp_path / "library")
    monkeypatch.setattr(purge, "BACKUP_DIR", tmp_path / "backups")

    assert purge.main(["--dry-run"]) == 0
    conn = sqlite3.connect(db_path)
    remaining = sorted(r[0] for r in conn.execute("SELECT original_name FROM source_documents").fetchall())
    assert remaining == ["audit.pdf", "audit.pdf", "（已压缩）2025民法（强化讲义）_可搜索.pdf"]  # dry-run 不落盘
    conn.close()
    assert not (tmp_path / "backups").exists()


def test_confirm_purges_audit_and_keeps_real(tmp_path, monkeypatch):
    db_path = _build_db(tmp_path)
    monkeypatch.setattr(purge, "DB", db_path)
    monkeypatch.setattr(purge, "LIBRARY_DIR", tmp_path / "library")
    backup_dir = tmp_path / "backups"
    monkeypatch.setattr(purge, "BACKUP_DIR", backup_dir)

    assert purge.main(["--confirm"]) == 0

    conn = sqlite3.connect(db_path)
    remaining = [r[0] for r in conn.execute("SELECT original_name FROM source_documents").fetchall()]
    assert remaining == ["（已压缩）2025民法（强化讲义）_可搜索.pdf"]  # 真实教材毫发无损
    assert conn.execute("SELECT COUNT(*) c FROM knowledge_units").fetchone()[0] == 1
    audit = conn.execute(
        "SELECT event_type, entity_id FROM study_events WHERE event_type='test_data_purged'"
    ).fetchall()
    assert audit, "必须写入审计事件"
    assert "audit-1" in audit[0][1] and "audit-2" in audit[0][1]
    conn.close()
    # 备份已生成且可用
    backups = list(backup_dir.glob("purge-*.db"))
    assert len(backups) == 1
    # 库文件已删除
    assert not (tmp_path / "library" / "audit-1.pdf").exists()
    assert not (tmp_path / "library" / "audit-2.pdf").exists()
    assert (tmp_path / "library" / "real.pdf").exists()


def test_guard_rejects_oversized_audit(tmp_path, monkeypatch):
    db_path = _build_db(tmp_path)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO source_documents VALUES(?,?,?,?,?,?)",
        ("audit-big", "audit.pdf", str(tmp_path / "library" / "big.pdf"), 999999, 1, "2026-08-09T06:00:00+00:00"),
    )
    conn.commit()
    conn.close()
    (tmp_path / "library" / "big.pdf").write_bytes(b"%PDF-big")
    monkeypatch.setattr(purge, "DB", db_path)
    monkeypatch.setattr(purge, "LIBRARY_DIR", tmp_path / "library")
    monkeypatch.setattr(purge, "BACKUP_DIR", tmp_path / "backups")

    assert purge.main(["--confirm"]) == 0
    conn = sqlite3.connect(db_path)
    names = sorted(r[0] for r in conn.execute("SELECT original_name FROM source_documents").fetchall())
    conn.close()
    assert names == ["audit.pdf", "（已压缩）2025民法（强化讲义）_可搜索.pdf"]  # 大小不符 → 拒绝；真实教材保留


def test_confirm_requires_no_dry_run_flag(tmp_path, monkeypatch):
    """未加 --confirm 时不执行删除（防手滑）。"""
    db_path = _build_db(tmp_path)
    monkeypatch.setattr(purge, "DB", db_path)
    monkeypatch.setattr(purge, "LIBRARY_DIR", tmp_path / "library")
    monkeypatch.setattr(purge, "BACKUP_DIR", tmp_path / "backups")

    assert purge.main([]) == 0  # 无参数 = 等同 dry-run
    conn = sqlite3.connect(db_path)
    count = conn.execute("SELECT COUNT(*) c FROM source_documents").fetchone()[0]
    conn.close()
    assert count == 3
