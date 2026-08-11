from __future__ import annotations

import json
import math
import re
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4

from app.schemas import Feedback


@dataclass(frozen=True)
class ScoreRequest:
    unit_title: str
    source_text: str
    page_start: int
    page_end: int
    answer_text: str
    confidence: int
    hint_level: int
    previous_errors: list[str]


class ScoringProvider(Protocol):
    name: str

    def score(self, request: ScoreRequest) -> Feedback:
        ...


def _normalize(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", text).lower()


def _grams(text: str, n: int) -> Counter[str]:
    normalized = _normalize(text)
    if len(normalized) < n:
        return Counter(normalized)
    return Counter(normalized[index : index + n] for index in range(len(normalized) - n + 1))


def _containment(source: str, answer: str) -> float:
    if not source or not answer:
        return 0.0
    source_bi = _grams(source, 2)
    answer_bi = _grams(answer, 2)
    source_uni = _grams(source, 1)
    answer_uni = _grams(answer, 1)
    bi_total = sum(source_bi.values()) or 1
    uni_total = sum(source_uni.values()) or 1
    bi_hit = sum((source_bi & answer_bi).values()) / bi_total
    uni_hit = sum((source_uni & answer_uni).values()) / uni_total
    return 0.72 * bi_hit + 0.28 * uni_hit


def _key_clauses(text: str) -> list[str]:
    clauses = [
        re.sub(r"\s+", " ", item).strip(" ：:、")
        for item in re.split(r"(?<=[。！？；])|\n+", text)
    ]
    clauses = [item for item in clauses if 8 <= len(_normalize(item)) <= 130]
    keywords = ("应当", "包括", "条件", "不得", "可以", "必须", "构成", "责任", "效力", "除外", "例外", "要件")

    def importance(clause: str) -> float:
        keyword_score = sum(1.2 for keyword in keywords if keyword in clause)
        length_score = min(len(_normalize(clause)), 80) / 80
        position_bonus = 0.2 if clauses.index(clause) < 3 else 0
        return keyword_score + length_score + position_bonus

    ranked = sorted(clauses, key=importance, reverse=True)
    selected: list[str] = []
    for clause in ranked:
        if all(_containment(clause, existing) < 0.75 for existing in selected):
            selected.append(clause)
        if len(selected) >= 8:
            break
    return selected or clauses[:6]


class LocalEvidenceScorer:
    name = "local_evidence_v1"

    def score(self, request: ScoreRequest) -> Feedback:
        clauses = _key_clauses(request.source_text)
        scored = [(clause, _containment(clause, request.answer_text)) for clause in clauses]
        matched = [clause for clause, score in scored if score >= 0.38]
        partial = [clause for clause, score in scored if 0.18 <= score < 0.38]
        missing = [clause for clause, score in scored if score < 0.18]

        if not scored:
            raw_score = min(100.0, len(_normalize(request.answer_text)) / 3)
        else:
            similarities = [score for _, score in scored]
            mean_score = sum(similarities) / len(similarities)
            best_bonus = min(0.18, max(similarities, default=0) * 0.18)
            length_factor = min(1.0, len(_normalize(request.answer_text)) / max(80, len(_normalize(request.source_text)) * 0.25))
            raw_score = 100 * min(1.0, (mean_score + best_bonus) * (0.72 + 0.28 * length_factor))

        score = round(max(0.0, min(100.0, raw_score)), 1)
        expression_issues: list[str] = []
        answer_len = len(_normalize(request.answer_text))
        if answer_len < 50:
            expression_issues.append("答案偏短，可能只写出结论，尚未展开规则、条件或例外。")
        if not re.search(r"应当|构成|要件|条件|责任|效力|因此|据此", request.answer_text):
            expression_issues.append("规范性连接词和法律术语较少，建议按“规则—条件—结论”组织表达。")
        if request.confidence >= 80 and score < 60:
            expression_issues.append("本次属于高置信度低覆盖，优先排查稳定性误记或关键条件遗漏。")
        if request.hint_level >= 2:
            expression_issues.append("本次查看过完整原文，结果仅能证明理解，不能作为无提示掌握证据。")

        incorrect_points: list[str] = []
        if re.search(r"一定|绝对|全部|任何情况下|均应", request.answer_text) and not re.search(
            r"一定|绝对|全部|任何情况下|均应", request.source_text
        ):
            incorrect_points.append("答案中出现绝对化表述，原文未显示同等强度限定，建议复核适用边界。")
        if not incorrect_points:
            incorrect_points.append("本地初筛只核对覆盖度，具体事实性错误需由来源对照或云端法学评分器确认。")

        if score >= 82 and request.hint_level == 0:
            next_action = "保留当前答案并安排延迟复测；当前版本尚未实现独立变式题任务。"
        elif score >= 60:
            next_action = "根据遗漏点立即补写一次，提交后再进入延迟复测。"
        else:
            next_action = "回到原文核对关键条件，关闭原文后重新完成一次完整闭卷回答。"

        evidence = [
            {
                "page_start": request.page_start,
                "page_end": request.page_end,
                "text": clause,
                "coverage": round(similarity, 3),
            }
            for clause, similarity in scored[:8]
        ]

        return Feedback(
            score=score,
            matched_points=matched[:4] or ["尚未识别出稳定覆盖的核心要点。"],
            missing_points=(missing + partial)[:4] or ["未发现明显遗漏，仍需通过延迟复测确认保持。"],
            incorrect_points=incorrect_points,
            expression_issues=expression_issues or ["表达结构基本完整，下一步重点验证延迟保持和变式迁移。"],
            next_action=next_action,
            evidence=evidence,
            provider_note="本地证据覆盖评分，不发送教材或答案到云端；分数用于学习反馈，不等同于正式考试评分。",
        )


class OpenAICompatibleScorer:
    name = "openai_compatible"

    def __init__(self, endpoint: str, api_key: str, model: str) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.api_key = api_key
        self.model = model

    def score(self, request: ScoreRequest) -> Feedback:
        if not self.endpoint or not self.api_key or not self.model:
            raise RuntimeError("云端评分器配置不完整")
        prompt = {
            "task": "依据给定教材原文，评价用户闭卷作答。不得补充原文之外的法律结论。",
            "unit_title": request.unit_title,
            "source": {
                "page_start": request.page_start,
                "page_end": request.page_end,
                "text": request.source_text,
            },
            "attempt": {
                "answer": request.answer_text,
                "confidence": request.confidence,
                "hint_level": request.hint_level,
            },
            "previous_errors": request.previous_errors,
            "required_json": {
                "score": "0-100",
                "matched_points": [],
                "missing_points": [],
                "incorrect_points": [],
                "expression_issues": [],
                "next_action": "",
                "evidence": [{"page_start": 1, "page_end": 1, "text": "", "coverage": 0.0}],
                "provider_note": "",
            },
        }
        payload = json.dumps(
            {
                "model": self.model,
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": [
                    {
                        "role": "system",
                        "content": "你是来源受限的法学应试评分器。只依据用户提供的教材原文评分，并返回严格JSON。",
                    },
                    {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                ],
            },
            ensure_ascii=False,
        ).encode("utf-8")
        http_request = urllib.request.Request(
            self.endpoint,
            data=payload,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(http_request, timeout=90) as response:
                raw = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise RuntimeError(f"云端评分请求失败（网络/超时/服务不可达）: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError("云端评分返回的不是有效 JSON，请检查接口地址与模型配置") from exc
        try:
            content = raw["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("云端评分响应缺少 choices[0].message.content 字段，请检查接口兼容性") from exc
        try:
            return Feedback.model_validate_json(content)
        except Exception as exc:
            raise RuntimeError(f"云端评分返回的 JSON 不符合评分契约: {exc}") from exc


def provider_from_settings(provider: str, endpoint: str, api_key: str, model: str) -> ScoringProvider:
    if provider == "openai_compatible":
        return OpenAICompatibleScorer(endpoint, api_key, model)
    return LocalEvidenceScorer()


def new_provider_run_id() -> str:
    return str(uuid4())


def evidence_weight(hint_level: int) -> float:
    return {0: 1.0, 1: 0.75, 2: 0.45}.get(hint_level, math.exp(-0.4 * hint_level))
