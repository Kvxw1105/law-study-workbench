from __future__ import annotations

from datetime import UTC, datetime, timedelta


def review_plan(score: float, evidence_weight: float, confidence: int) -> tuple[str, int, str]:
    effective = score * evidence_weight
    if confidence >= 80 and score < 60:
        return "不稳定", 1, "高置信度错误，优先进行辨析与次日复测。"
    if effective >= 82:
        return "基本稳定", 7, "七日后再次进行完整闭卷，检验延迟保持。"
    if effective >= 65:
        return "不稳定", 3, "三日后复测，先补齐遗漏要点。"
    return "学习中", 1, "次日复测，建议先完成一次无提示重答。"


def due_at_after(days: int) -> str:
    return (datetime.now(UTC) + timedelta(days=days)).isoformat()
