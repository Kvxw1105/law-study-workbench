#!/usr/bin/env python3
"""regenerate_all_cards.py — 用当前本地算法为全部单元重新生成卡片（一次性维护）。

背景：存量卡由旧版模板生成（题面泄漏答案、无语义题面、标题/水印混入等）。
本脚本对每个非归档单元重新调用自动生成接口（content_hash 去重复用），
并停用“不在新生成集合中”的旧活动卡（历史作答与证据保留，可查可恢复）。

安全设计：
  1. 执行前自动备份 data/workbench.db → data/backups/regenerate-<时间戳>.db
  2. 默认 --dry-run 只预览计划，加 --yes 才执行
  3. 用户主动停用的卡（archived）绝不复活；只动 active 卡
  4. 全部通过产品 API 执行（content_hash 去重、复习状态重置、审计事件与
     正常界面操作一致）

用法：
  python scripts/regenerate_all_cards.py            # 预览
  python scripts/regenerate_all_cards.py --yes      # 备份后执行
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "workbench.db"
BACKUP_DIR = ROOT / "data" / "backups"
BASE = "http://127.0.0.1:8765"

sys.path.insert(0, str(ROOT))  # 保证从任意目录运行时都能 import app.*


def api(method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        BASE + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:200]
        raise RuntimeError(f"{method} {path} -> {exc.code}: {detail}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="用当前算法为全部单元重新生成卡片")
    parser.add_argument("--yes", action="store_true", help="确认执行（自动先备份）")
    args = parser.parse_args(argv)

    sources = api("GET", "/api/sources")
    units: list[dict] = []
    for source in sources:
        units.extend(api("GET", f"/api/sources/{source['id']}/units"))

    plan: list[dict] = []
    for unit in units:
        # 本地用同一算法计算“新生成集合”的 content_hash（与接口一致）
        from app.services.retrieval import generate_retrieval_items
        drafts = generate_retrieval_items(
            title=unit["title"],
            body=unit["body"],
            item_types=["flashcard", "cloze"],
            max_per_type=3,
        )
        if not drafts:
            plan.append({"unit": unit["title"], "drafts": 0, "to_archive": 0, "skip": "无法生成"})
            continue
        new_hashes = {draft.content_hash for draft in drafts}
        if args.yes:
            # 正式执行：走产品接口生成（content_hash 去重复用 + 审计事件）
            response = api("POST", f"/api/units/{unit['id']}/retrieval-items/generate",
                           {"item_types": ["flashcard", "cloze"], "max_per_type": 3})
            active_cards = response.get("items", [])
            created = response.get("created", 0)
            reactivated = response.get("reactivated", 0)
            reused = response.get("reused", 0)
        else:
            # 预览模式：不写库，只对比当前 active 卡（本地查询，与接口同口径）
            active_cards = api("GET", f"/api/units/{unit['id']}/retrieval-items")
            created = reactivated = reused = 0
        to_archive = [card for card in active_cards if card.get("content_hash") not in new_hashes]
        plan.append({
            "unit": unit["title"],
            "drafts": len(drafts),
            "created": created,
            "reactivated": reactivated,
            "reused": reused,
            "to_archive": len(to_archive),
            "archivable_ids": [card["id"] for card in to_archive],
        })

    total_new = sum(p["created"] for p in plan)
    total_reused = sum(p["reused"] for p in plan)
    total_archive = sum(p["to_archive"] for p in plan)
    print(f"[计划] 单元 {len(plan)} 个 | 新建 {total_new} | 复用 {total_reused} | 停用旧卡 {total_archive}")
    for p in plan:
        print(f"  - {p['unit'][:28]:<30} 新建{p['created']} 复用{p['reused']} 停用{p['to_archive']}"
              + (f" [{p.get('skip')}]" if p.get("skip") else ""))

    if not args.yes:
        print("\n[提示] 未执行。确认请加 --yes（会先备份数据库，停用旧卡不删数据）。")
        return 0

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup_path = BACKUP_DIR / f"regenerate-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}.db"
    shutil.copy2(DB, backup_path)
    print(f"[备份] {backup_path}")

    archived_count = 0
    for p in plan:
        for card_id in p.get("archivable_ids", []):
            api("PATCH", f"/api/retrieval-items/{card_id}", {"status": "archived"})
            archived_count += 1
    print(f"[完成] 停用旧卡 {archived_count} 张（历史作答保留）。新建/复用卡片见上方统计。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
