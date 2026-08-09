#!/usr/bin/env python3
"""alpha_perf_benchmark.py — synthetic scale benchmark for law-study-workbench.

Builds a fully synthetic dataset (tempdir, never touches real data) at a chosen
scale and measures: startup, due query, pack export, event import, summary,
backup, restore, DB size. Writes docs/ALPHA_PERFORMANCE_BASELINE.md.

Usage:
    python scripts/alpha_perf_benchmark.py            # scale 100/1000/1000
    python scripts/alpha_perf_benchmark.py --units 100 --items 1000 --events 1000
    python scripts/alpha_perf_benchmark.py --json
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import io
import fitz
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

BENCH_DOC = ROOT / "docs" / "ALPHA_PERFORMANCE_BASELINE.md"


def timed(name: str, fn, results: list[dict]) -> float:
    start = time.perf_counter()
    fn()
    elapsed = time.perf_counter() - start
    results.append({"operation": name, "seconds": round(elapsed, 3)})
    return elapsed


def timed_value(name: str, fn, results: list[dict]):
    """Like timed() but returns the callable's value."""
    start = time.perf_counter()
    value = fn()
    elapsed = time.perf_counter() - start
    results.append({"operation": name, "seconds": round(elapsed, 3)})
    return value


def make_pdf() -> bytes:
    text = (
        "善意取得应当具备下列条件：处分人为无处分权人；受让人在受让该财产时为善意；"
        "以合理价格转让；依法应当登记的已经登记，不需要登记的已经交付。"
    )
    document = fitz.open()
    page = document.new_page()
    page.insert_textbox(fitz.Rect(50, 60, 540, 760), text, fontsize=12, fontname="china-s")
    payload = document.tobytes()
    document.close()
    return payload


def main() -> int:
    ap = argparse.ArgumentParser(description="Synthetic scale benchmark.")
    ap.add_argument("--units", type=int, default=150)
    ap.add_argument("--items", type=int, default=1000)
    ap.add_argument("--events", type=int, default=1000)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--write-doc", action="store_true", default=True)
    args = ap.parse_args()

    results: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="law-study-perf-") as temp_name:
        home = Path(temp_name) / "data"
        settings = Settings(
            home=home, db_path=home / "workbench.db",
            library_dir=home / "library", export_dir=home / "exports",
            static_dir=ROOT / "app" / "static",
        )

        def t(name, fn):
            return timed(name, fn, results)

        with TestClient(create_app(settings)) as client:
            # seed synthetic sources/units (one PDF -> one unit)
            def seed_units():
                for i in range(args.units):
                    r = client.post(
                        "/api/sources/import?wait=true",
                        files={"file": (f"perf-{i}.pdf", io.BytesIO(make_pdf()), "application/pdf")},
                    )
                    assert r.status_code == 200, r.text
                return len(client.get("/api/sources").json())

            unit_count = timed_value("seed_sources", seed_units, results)

            def seed_items():
                sources = client.get("/api/sources").json()
                created = 0
                for src in sources:
                    for unit in client.get(f"/api/sources/{src['id']}/units").json():
                        r = client.post(
                            f"/api/units/{unit['id']}/retrieval-items/generate",
                            json={"item_types": ["flashcard", "cloze"], "max_per_type": 10},
                        )
                        if r.status_code == 200:
                            created += len(r.json()["items"])
                        if created >= args.items:
                            return created
                return created

            item_count = timed_value("seed_retrieval_items", seed_items, results)

            def due_query():
                return client.get("/api/retrieval/summary").json()

            t("due_query", due_query)

            def pack_export():
                r = client.get("/api/study-pack/export?mode=all&limit=500")
                assert r.status_code == 200, r.text
                return r.json()

            pack = timed_value("pack_export", pack_export, results)

            def events_import():
                items = pack["items"]
                events = []
                for i in range(min(args.events, len(items))):
                    item = items[i % len(items)]
                    events.append({
                        "event_id": f"perf-event-{i}",
                        "event_type": "retrieval_attempt",
                        "item_id": item["id"],
                        "item_version": item["version"],
                        "content_hash": item["content_hash"],
                        "base_last_attempt_id": item["review_base"]["last_attempt_id"],
                        "occurred_at": datetime.now(UTC).isoformat(),
                        "response_text": item["content"]["answer"] if item["type"] == "cloze" else "",
                        "rating": "good" if item["type"] == "flashcard" else None,
                        "elapsed_ms": 800,
                        "revealed_answer": True,
                    })
                payload = {
                    "protocol": "study-events/0.1",
                    "bundle_id": "perf-bundle",
                    "pack_id": pack["pack_id"],
                    "pack_hash": pack["pack_hash"],
                    "exported_at": datetime.now(UTC).isoformat(),
                    "device": {"id": "perf", "label": "perf", "client": "perf/0.1"},
                    "events": events,
                }
                r = client.post("/api/study-events/import", json=payload)
                assert r.status_code == 200, r.text
                return r.json()["summary"]

            import_summary = timed_value("events_import", events_import, results)

            def summary_again():
                return client.get("/api/retrieval/summary").json()

            t("summary_after_import", summary_again)

            def make_backup():
                backup_dir = home / "backups"
                backup_dir.mkdir(parents=True, exist_ok=True)
                out = backup_dir / "perf-backup.zip"
                with tempfile.TemporaryDirectory(prefix="lsb-") as tt:
                    snap = Path(tt) / "workbench.db"
                    src = sqlite3.connect(home / "workbench.db")
                    dst = sqlite3.connect(snap)
                    try:
                        src.backup(dst)
                    finally:
                        dst.close(); src.close()
                    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                        archive.write(snap, "workbench.db")
                return out

            backup_path = timed_value("backup", make_backup, results)

            def do_restore():
                with tempfile.TemporaryDirectory(prefix="lsr-") as tt:
                    with zipfile.ZipFile(backup_path) as archive:
                        archive.extractall(tt)
                    conn = sqlite3.connect(Path(tt) / "workbench.db")
                    ok = conn.execute("PRAGMA integrity_check").fetchone()[0]
                    conn.close()
                    assert ok == "ok"
                return ok

            t("restore_validate", do_restore)

            db_size = (home / "workbench.db").stat().st_size

        # startup measurement (fresh process reading the same home)
        def startup_time():
            start = time.perf_counter()
            with TestClient(create_app(settings)) as c:
                c.get("/api/health")
            return time.perf_counter() - start

        startup_s = t("startup_health", startup_time)

    payload = {
        "scale": {"units": unit_count, "items": item_count, "events_imported": import_summary.get("imported")},
        "db_size_bytes": db_size,
        "measurements": results,
        "generated_at": datetime.now(UTC).isoformat(),
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"scale: {unit_count} units / {item_count} items / {import_summary.get('imported')} events")
        for m in results:
            print(f"  {m['operation']:<22} {m['seconds']:>8.3f}s")
        print(f"  db size: {db_size / 1024:.0f} KiB")

    if args.write_doc:
        rows = "\n".join(f"| {m['operation']} | {m['seconds']:.3f} s |" for m in results)
        doc = f"""# Alpha Performance Baseline

生成时间：{payload['generated_at']}
环境：Windows / Python {sys.version.split()[0]} / SQLite WAL / 本机合成数据（tempdir，不含真实数据）

## 规模

- 合成知识单元：{unit_count}
- 合成检索项（flashcard/cloze）：{item_count}
- 导入 StudyEvents：{import_summary.get('imported')}
- 数据库大小：{db_size / 1024:.0f} KiB

## 测量

| 操作 | 耗时 |
| --- | --- |
{rows}

## 说明

- 全部为合成数据，测量前无真实用户数据参与。
- 若单条本地操作出现明显秒级以上异常或 N² 行为，需定位根因并做低风险修复。
- 真实设备（手机）PWA 与真实教材规模仍为 REAL_DEVICE_PENDING / REAL_USER_ALPHA_PENDING。
"""
        BENCH_DOC.write_text(doc, encoding="utf-8")
        print(f"wrote {BENCH_DOC}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
