from __future__ import annotations

import re
from collections import Counter
from typing import Any

from app.schemas import Feedback
from app.services.legal_signals import detect_clause_conflicts, looks_like_keyword_pile
from app.services.scorer import ScoreRequest

METHOD_PACK_ID = "law_full_recall_v1"
METHOD_PACK_VERSION = "0.3.0"
METHOD_PACK_NAME = "法学完整闭卷方法包"

_DIMENSIONS: tuple[dict[str, Any], ...] = (
    {
        "id": "core_question",
        "label": "核心设问",
        "instruction": "先用一句话回答：本单元究竟要求解释、辨析或适用什么。",
        "atom_refs": ["SEM-08", "RET-02"],
    },
    {
        "id": "rule_elements",
        "label": "规则与要件",
        "instruction": "恢复一般规则、启动条件，并标明条件之间的并列或选择关系。",
        "atom_refs": ["LAW-14", "LAW-15", "LAW-19"],
    },
    {
        "id": "exceptions_boundaries",
        "label": "例外与边界",
        "instruction": "检查原文是否存在例外、限制、阻断条件或相邻制度边界。",
        "atom_refs": ["STR-06", "LAW-17", "SEM-15"],
    },
    {
        "id": "legal_effect",
        "label": "法律效果",
        "instruction": "明确规则触发后产生的权利、义务、效力、责任或程序后果。",
        "atom_refs": ["LAW-16"],
    },
    {
        "id": "terminology_expression",
        "label": "术语与规范表达",
        "instruction": "使用来源内术语和限定词，按规则、条件、结论组织答案。",
        "atom_refs": ["QUA-03", "QUA-04", "OUT-07"],
    },
)

_PROFILE_BY_OBJECTIVE: dict[str, dict[str, Any]] = {
    "精确复现型": {
        "id": "precision_recall",
        "label": "精确复现",
        "emphasis": ["rule_elements", "exceptions_boundaries", "legal_effect"],
        "reason": "知识单元被标记为精确复现型，优先检查规则条件、限定语和法律效果是否完整恢复。",
    },
    "辨析型": {
        "id": "distinction",
        "label": "辨析边界",
        "emphasis": ["core_question", "exceptions_boundaries", "terminology_expression"],
        "reason": "知识单元被标记为辨析型，优先检查决定性差异、适用边界和术语区分。",
    },
    "适用型": {
        "id": "application",
        "label": "规则适用",
        "emphasis": ["core_question", "rule_elements", "legal_effect"],
        "reason": "知识单元被标记为适用型，优先检查争点定位、规则启动条件和结论后果。",
    },
    "理解解释型": {
        "id": "explanation",
        "label": "制度解释",
        "emphasis": ["core_question", "rule_elements", "terminology_expression"],
        "reason": "知识单元被标记为理解解释型，优先检查主线问题、规则结构和规范化解释。",
    },
    "表达型": {
        "id": "subjective_expression",
        "label": "主观表达",
        "emphasis": ["core_question", "terminology_expression", "legal_effect"],
        "reason": "知识单元被标记为表达型，优先检查答题立场、规范展开和明确结论。",
    },
    "综合型": {
        "id": "balanced_recall",
        "label": "综合闭卷",
        "emphasis": ["core_question", "rule_elements", "exceptions_boundaries", "legal_effect", "terminology_expression"],
        "reason": "知识单元未命中单一任务类型，使用五维平衡闭卷检查。",
    },
}

_RULE_PATTERN = re.compile(
    r"应当|必须|不得|可以|包括|构成|要件|条件|前提|须|shall|must|may|requires?|conditions?|elements?",
    re.IGNORECASE,
)
_EXCEPTION_PATTERN = re.compile(
    r"但|但是|除外|除非|例外|限制|不适用|特殊|不得对抗|仍然|否则|except|unless|however|provided that|limitation",
    re.IGNORECASE,
)
_EFFECT_PATTERN = re.compile(
    r"有权|无权|取得|丧失|承担|责任|效力|无效|撤销|解除|赔偿|请求|返还|优先|对抗|后果|"
    r"right|liable|liability|valid|invalid|acquires?|damages?|remedy|effect|entitled",
    re.IGNORECASE,
)
_NORMATIVE_CONNECTOR_PATTERN = re.compile(
    r"应当|不得|可以|有权|构成|要件|条件|因此|据此|但是|除外|例外|责任|效力|"
    r"shall|must|may|therefore|however|except|liable|effect",
    re.IGNORECASE,
)

_ENGLISH_STOPWORDS = {
    "about",
    "after",
    "before",
    "being",
    "between",
    "could",
    "during",
    "every",
    "several",
    "should",
    "their",
    "therefore",
    "these",
    "those",
    "through",
    "under",
    "where",
    "which",
    "while",
    "would",
}


def _normalize(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", text or "").lower()


def _grams(text: str, n: int) -> Counter[str]:
    normalized = _normalize(text)
    if not normalized:
        return Counter()
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


def _split_clauses(text: str) -> list[str]:
    clauses = [
        re.sub(r"\s+", " ", item).strip(" ：:、")
        for item in re.split(r"(?<=[。！？；.!?;])|\n+", text or "")
    ]
    return [item for item in clauses if 2 <= len(_normalize(item)) <= 220]


def _coverage_score(coverages: list[float]) -> float:
    if not coverages:
        return 0.0
    best = max(coverages)
    mean = sum(coverages) / len(coverages)
    return round(min(100.0, (0.62 * best + 0.38 * mean) * 175), 1)


def _status_for_score(score: float | None) -> str:
    if score is None:
        return "not_applicable"
    if score >= 72:
        return "strong"
    if score >= 42:
        return "partial"
    return "missing"


def _semantic_sensitive_status(
    score: float | None,
    *,
    answer_text: str,
    critical_conflicts: list[dict[str, Any]],
    possible_conflicts: list[dict[str, Any]],
    structure_warning: bool,
) -> tuple[str, float | None]:
    if score is None:
        return "not_applicable", None
    if critical_conflicts:
        return "critical_conflict", min(score, 35.0)
    if possible_conflicts or structure_warning:
        return "uncertain", min(score, 55.0) if structure_warning else score
    status = _status_for_score(score)
    if status == "missing" and len(_normalize(answer_text)) >= 20:
        # Local lexical evidence cannot safely distinguish a genuine semantic paraphrase
        # from a wrong but well-formed answer. Mark uncertainty instead of pretending
        # that low surface overlap proves a knowledge gap.
        return "uncertain", score
    return status, score


def _source_ref(clause: str, coverage: float, request: ScoreRequest) -> dict[str, Any]:
    return {
        "page_start": request.page_start,
        "page_end": request.page_end,
        "text": clause,
        "coverage": round(coverage, 3),
    }


def _dimension_copy(label: str, status: str, score: float | None) -> tuple[str, str]:
    if status == "critical_conflict":
        return (
            f"{label}检测到与教材来源相反的关键限定、主体或数字信号。",
            "先核对冲突原句并修正结论，再重新闭卷；本轮不能按高覆盖视为掌握。",
        )
    if status == "uncertain":
        return (
            f"{label}的字面证据不足以判断语义正确性，当前只标记为待核对。",
            "优先人工对照或使用受来源约束的语义核验；不要把低字面重合直接当成错误。",
        )
    if status == "strong":
        return (
            f"{label}与来源存在较高字面恢复信号，但这不等于语义结论已经验证。",
            "保留当前结构，并检查关键限定词、数字和结论方向后再进入延迟复测。",
        )
    if status == "partial":
        return (
            f"{label}已有部分来源恢复信号，仍存在要点或限定语缺口。",
            "对照下方来源锚点补写一次，再关闭原文重新回答。",
        )
    if status == "not_applicable":
        return (
            f"当前来源未检出明确的{label}条款，本维度不计入缺失。",
            "不要自行补造规则；可在答案中注明原文未列明该类内容。",
        )
    return (
        f"{label}在本次答案中的来源恢复信号较弱。",
        "先回源定位关键词和逻辑关系，再进行一次完整闭卷恢复。",
    )


def _build_dimension_result(
    *,
    dimension: dict[str, Any],
    clauses: list[str],
    request: ScoreRequest,
    score: float | None = None,
    not_applicable: bool = False,
    checks: list[str] | None = None,
    semantic_sensitive: bool = False,
    structure_warning: bool = False,
) -> dict[str, Any]:
    coverages = [_containment(clause, request.answer_text) for clause in clauses]
    resolved_score = None if not_applicable else (score if score is not None else _coverage_score(coverages))
    critical_conflicts: list[dict[str, Any]] = []
    possible_conflicts: list[dict[str, Any]] = []
    if semantic_sensitive and clauses and not not_applicable:
        for conflict in detect_clause_conflicts("".join(clauses), request.answer_text):
            payload = {
                "source_clause": conflict.source_clause,
                "answer_clause": conflict.answer_clause,
                "similarity": conflict.similarity,
                "severity": conflict.severity,
                "mismatches": list(conflict.mismatches),
            }
            if conflict.severity == "hard":
                critical_conflicts.append(payload)
            else:
                possible_conflicts.append(payload)
    if not_applicable:
        status = "not_applicable"
    elif semantic_sensitive:
        status, resolved_score = _semantic_sensitive_status(
            resolved_score,
            answer_text=request.answer_text,
            critical_conflicts=critical_conflicts,
            possible_conflicts=possible_conflicts,
            structure_warning=structure_warning,
        )
    else:
        status = _status_for_score(resolved_score)
    summary, next_action = _dimension_copy(dimension["label"], status, resolved_score)
    return {
        "id": dimension["id"],
        "label": dimension["label"],
        "status": status,
        "score": resolved_score,
        "summary": summary,
        "next_action": next_action,
        "checks": checks or [],
        "structure_warning": structure_warning,
        "critical_conflicts": critical_conflicts,
        "possible_conflicts": possible_conflicts,
        "source_refs": [
            _source_ref(clause, coverage, request)
            for clause, coverage in sorted(zip(clauses, coverages), key=lambda item: item[1], reverse=True)[:3]
        ],
        "atom_refs": list(dimension["atom_refs"]),
    }


def _extract_source_terms(title: str, source_text: str) -> list[str]:
    candidates: list[str] = []
    title_clean = re.sub(r"第\d+(?:-\d+)?页|知识单元", "", title or "").strip()
    if 2 <= len(_normalize(title_clean)) <= 32:
        candidates.append(title_clean)

    chinese_patterns = re.findall(
        r"[\u4e00-\u9fff]{2,12}(?:权|义务|责任|效力|要件|条件|规则|登记|交付|赔偿|请求|制度|程序|主体|客体|行为)",
        source_text or "",
    )
    candidates.extend(chinese_patterns)

    english_words = re.findall(r"[A-Za-z][A-Za-z-]{5,}", source_text or "")
    counts = Counter(word.lower() for word in english_words if word.lower() not in _ENGLISH_STOPWORDS)
    candidates.extend(word for word, _ in counts.most_common(10))

    unique: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = _normalize(candidate)
        if len(normalized) < 2 or normalized in seen:
            continue
        seen.add(normalized)
        unique.append(candidate)
        if len(unique) >= 10:
            break
    return unique


def select_method_pack(objective_type: str | None) -> dict[str, Any]:
    resolved_type = objective_type if objective_type in _PROFILE_BY_OBJECTIVE else "综合型"
    profile = _PROFILE_BY_OBJECTIVE[resolved_type]
    emphasis = list(profile["emphasis"])
    ordered = sorted(
        _DIMENSIONS,
        key=lambda item: emphasis.index(item["id"]) if item["id"] in emphasis else len(emphasis),
    )
    dimensions = [
        {
            **dimension,
            "emphasized": dimension["id"] in emphasis[:3],
        }
        for dimension in ordered
    ]
    return {
        "id": METHOD_PACK_ID,
        "version": METHOD_PACK_VERSION,
        "name": METHOD_PACK_NAME,
        "objective_type": objective_type or "综合型",
        "focus_profile": profile["id"],
        "focus_label": profile["label"],
        "selection_reason": profile["reason"],
        "training_dimensions": dimensions,
        "runtime_status": "selected",
        "degradation_reason": None,
        "generated_flags": {
            "source_answer_hidden": True,
            "source_bounded": True,
            "external_knowledge_used": False,
            "lexical_source_signal": True,
            "semantic_correctness_verified": False,
            "formal_legal_grade": False,
        },
    }


def evaluate_method_pack(
    *,
    selection: dict[str, Any],
    request: ScoreRequest,
    base_feedback: Feedback,
) -> dict[str, Any]:
    clauses = _split_clauses(request.source_text)
    if not clauses:
        raise ValueError("知识单元没有可用于方法包诊断的来源文本")

    dimensions_by_id = {item["id"]: item for item in selection["training_dimensions"]}
    structure_warning = looks_like_keyword_pile(request.answer_text)

    core_clauses = clauses[:2]
    title_coverage = _containment(request.unit_title, request.answer_text)
    core_score = _coverage_score([title_coverage, *[_containment(item, request.answer_text) for item in core_clauses]])
    core = _build_dimension_result(
        dimension=dimensions_by_id["core_question"],
        clauses=core_clauses,
        request=request,
        score=core_score,
        checks=["是否直接回应本单元主线", "是否避免只写零散结论"],
        semantic_sensitive=True,
        structure_warning=structure_warning,
    )

    rule_clauses = [clause for clause in clauses if _RULE_PATTERN.search(clause)]
    if not rule_clauses:
        rule_clauses = clauses[: min(3, len(clauses))]
    rule = _build_dimension_result(
        dimension=dimensions_by_id["rule_elements"],
        clauses=rule_clauses[:4],
        request=request,
        checks=["一般规则", "启动条件或构成要件", "并列/选择关系"],
        semantic_sensitive=True,
        structure_warning=structure_warning,
    )

    exception_clauses = [clause for clause in clauses if _EXCEPTION_PATTERN.search(clause)]
    exceptions = _build_dimension_result(
        dimension=dimensions_by_id["exceptions_boundaries"],
        clauses=exception_clauses[:4],
        request=request,
        not_applicable=not exception_clauses,
        checks=["例外或限制", "阻断条件", "相邻制度边界"],
        semantic_sensitive=True,
        structure_warning=structure_warning,
    )

    effect_clauses = [clause for clause in clauses if _EFFECT_PATTERN.search(clause)]
    if not effect_clauses:
        effect_clauses = clauses[-2:]
    effect = _build_dimension_result(
        dimension=dimensions_by_id["legal_effect"],
        clauses=effect_clauses[:4],
        request=request,
        checks=["权利或义务", "效力或责任", "明确结论"],
        semantic_sensitive=True,
        structure_warning=structure_warning,
    )

    source_terms = _extract_source_terms(request.unit_title, request.source_text)
    matched_terms = [term for term in source_terms if _normalize(term) in _normalize(request.answer_text)]
    term_ratio = len(matched_terms) / len(source_terms) if source_terms else 0.0
    connector_hits = len(_NORMATIVE_CONNECTOR_PATTERN.findall(request.answer_text))
    connector_score = min(1.0, connector_hits / 3)
    term_clauses = [
        clause
        for clause in clauses
        if any(_normalize(term) in _normalize(clause) for term in (source_terms[:6] or [request.unit_title]))
    ]
    if not term_clauses:
        term_clauses = clauses[:2]
    clause_coverage_score = _coverage_score(
        [_containment(clause, request.answer_text) for clause in term_clauses[:3]]
    )
    terminology_score = round(
        min(
            100.0,
            clause_coverage_score * 0.55
            + term_ratio * 100 * 0.25
            + connector_score * 100 * 0.20,
        ),
        1,
    )
    if not source_terms:
        terminology_score = round(
            min(100.0, base_feedback.score * 0.65 + connector_score * 35),
            1,
        )
    terminology = _build_dimension_result(
        dimension=dimensions_by_id["terminology_expression"],
        clauses=term_clauses[:3],
        request=request,
        score=terminology_score,
        checks=[
            f"来源术语命中 {len(matched_terms)}/{len(source_terms)}" if source_terms else "来源术语不足，采用表达结构降级检查",
            f"规范连接词命中 {connector_hits} 次",
            "未把启发式诊断标为正式法学评分",
        ],
        structure_warning=structure_warning,
    )

    canonical = {
        "core_question": core,
        "rule_elements": rule,
        "exceptions_boundaries": exceptions,
        "legal_effect": effect,
        "terminology_expression": terminology,
    }
    dimension_results = [canonical[item["id"]] for item in selection["training_dimensions"]]

    all_refs: list[dict[str, Any]] = []
    seen_refs: set[str] = set()
    for result in dimension_results:
        for ref in result["source_refs"]:
            key = f"{ref['page_start']}:{ref['page_end']}:{ref['text']}"
            if key in seen_refs:
                continue
            seen_refs.add(key)
            all_refs.append(ref)

    method_pack = {
        **selection,
        "runtime_status": "completed",
        "degradation_reason": None,
        "generated_flags": {
            **selection.get("generated_flags", {}),
            "heuristic_diagnostic": True,
            "lexical_source_signal": True,
            "semantic_correctness_verified": False,
            "formal_legal_grade": False,
        },
    }
    return {
        "method_pack": method_pack,
        "dimension_results": dimension_results,
        "source_refs": all_refs[:8],
        "generated_flags": method_pack["generated_flags"],
    }


def degraded_method_pack_snapshot(selection: dict[str, Any], reason: str) -> dict[str, Any]:
    method_pack = {
        **selection,
        "runtime_status": "degraded",
        "degradation_reason": reason,
        "generated_flags": {
            **selection.get("generated_flags", {}),
            "heuristic_diagnostic": False,
            "formal_legal_grade": False,
        },
    }
    dimension_results = [
        {
            "id": item["id"],
            "label": item["label"],
            "status": "unavailable",
            "score": None,
            "summary": "方法包诊断本轮不可用，已保留基础来源覆盖反馈。",
            "next_action": "按基础遗漏点回源修订；方法包恢复后再完成五维复测。",
            "checks": [],
            "source_refs": [],
            "atom_refs": list(item.get("atom_refs", [])),
        }
        for item in selection["training_dimensions"]
    ]
    return {
        "method_pack": method_pack,
        "dimension_results": dimension_results,
        "source_refs": [],
        "generated_flags": method_pack["generated_flags"],
    }
