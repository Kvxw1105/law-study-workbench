from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Literal


ConflictSeverity = Literal["hard", "possible"]


@dataclass(frozen=True)
class MismatchDetail:
    severity: ConflictSeverity
    message: str


@dataclass(frozen=True)
class ClauseConflict:
    source_clause: str
    answer_clause: str
    similarity: float
    severity: ConflictSeverity
    mismatches: tuple[str, ...]


_POLARITY_GROUPS: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    ("是否发生效力", ("不发生效力", "未发生效力"), ("发生效力",)),
    ("是否生效", ("不生效", "未生效"), ("生效",)),
    ("效力正反", ("无效",), ("有效",)),
    ("是否成立", ("不成立", "未成立"), ("成立",)),
    ("权限正反", ("无权",), ("有权",)),
    ("允许/禁止", ("不得", "不可以", "不能"), ("可以",)),
    ("义务极性", ("不应当", "无需", "不必"), ("应当", "必须", "须")),
    ("责任承担", ("不承担", "无需承担"), ("承担",)),
    ("是否适用", ("不适用",), ("适用",)),
    ("是否取得", ("未取得", "不能取得"), ("取得",)),
    ("主观善恶意", ("恶意",), ("善意",)),
)

_ROLE_TOKENS = (
    "被代理人",
    "无处分权人",
    "被保证人",
    "被继承人",
    "人民法院",
    "仲裁机构",
    "代理人",
    "相对人",
    "受让人",
    "转让人",
    "处分人",
    "所有权人",
    "权利人",
    "义务人",
    "债权人",
    "债务人",
    "保证人",
    "出租人",
    "承租人",
    "买受人",
    "出卖人",
    "继承人",
    "行为人",
    "当事人",
    "第三人",
)

_ACTION_TOKENS = (
    "提起诉讼",
    "申请仲裁",
    "履行债务",
    "承担责任",
    "损害赔偿",
    "请求赔偿",
    "请求返还",
    "通知",
    "起诉",
    "诉讼",
    "仲裁",
    "催告",
    "追认",
    "撤销",
    "登记",
    "交付",
    "履行",
    "支付",
    "给付",
    "返还",
    "赔偿",
    "申请",
    "主张",
    "请求",
)

_NUMBER_PATTERN = re.compile(
    r"(?P<num>\d+(?:\.\d+)?|[零〇一二两三四五六七八九十百千万亿]+)"
    r"(?P<unit>年|个月|月|周|星期|日|天|小时|分钟|百分之|%)?"
)

_CLAUSE_SPLIT = re.compile(r"(?<=[。！？；.!?;])|\n+")
_SENTENCE_END = re.compile(r"[。！？.!?]")
_ENUM_SEPARATOR = re.compile(r"[\s、，,；;]+")
_SCOPED_NEGATION_PREFIXES = ("并非", "并不", "并未", "未必", "不当然", "不必然", "并不是")


def compact(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", text or "").lower()


def _is_scoped_negation(text: str, token: str) -> bool:
    start = 0
    while True:
        index = text.find(token, start)
        if index < 0:
            return False
        prefix = text[max(0, index - 5) : index]
        if any(prefix.endswith(marker) for marker in _SCOPED_NEGATION_PREFIXES):
            return True
        start = index + len(token)


def _polarity_side(
    text: str,
    negatives: tuple[str, ...],
    positives: tuple[str, ...],
) -> tuple[int, str | None, bool]:
    scoped_opposite = False
    for token in sorted(negatives, key=len, reverse=True):
        if token in text:
            if _is_scoped_negation(text, token):
                scoped_opposite = True
                continue
            return -1, token, scoped_opposite
    for token in sorted(positives, key=len, reverse=True):
        if token in text:
            if _is_scoped_negation(text, token):
                scoped_opposite = True
                continue
            return 1, token, scoped_opposite
    return 0, None, scoped_opposite


def _parse_chinese_number(raw: str) -> int | None:
    if not raw:
        return None
    if raw.isdigit():
        return int(raw)
    digits = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    units = {"十": 10, "百": 100, "千": 1000, "万": 10000, "亿": 100000000}
    if all(ch in digits for ch in raw):
        try:
            return int("".join(str(digits[ch]) for ch in raw))
        except ValueError:
            return None
    total = 0
    section = 0
    number = 0
    for ch in raw:
        if ch in digits:
            number = digits[ch]
            continue
        unit = units.get(ch)
        if unit is None:
            return None
        if unit < 10000:
            if number == 0:
                number = 1
            section += number * unit
        else:
            section = (section + number) * unit
            total += section
            section = 0
        number = 0
    return total + section + number


def _number_tokens(text: str) -> list[tuple[int | str, str]]:
    tokens: list[tuple[int | str, str]] = []
    for match in _NUMBER_PATTERN.finditer(text or ""):
        raw = match.group("num")
        unit = match.group("unit") or ""
        parsed = _parse_chinese_number(raw)
        value: int | str = parsed if parsed is not None else raw
        tokens.append((value, unit))
    return tokens


def _number_bindings(text: str) -> dict[str, tuple[int | str, str]]:
    bindings: dict[str, tuple[int | str, str]] = {}
    raw = text or ""
    for match in _NUMBER_PATTERN.finditer(raw):
        number_raw = match.group("num")
        parsed = _parse_chinese_number(number_raw)
        value: int | str = parsed if parsed is not None else number_raw
        unit = match.group("unit") or ""
        start = max(0, match.start() - 8)
        end = min(len(raw), match.end() + 16)
        window = raw[start:end]
        best_action = None
        best_distance = 10_000
        for action in _ACTION_TOKENS:
            pos = window.find(action)
            if pos < 0:
                continue
            absolute = start + pos
            distance = min(abs(absolute - match.start()), abs(absolute - match.end()))
            if distance < best_distance:
                best_action = action
                best_distance = distance
        if best_action:
            bindings[best_action] = (value, unit)
    return bindings


def _role_mentions(text: str) -> list[tuple[int, str]]:
    mentions: list[tuple[int, str]] = []
    working_spans: list[tuple[int, int]] = []
    raw = text or ""
    for token in sorted(_ROLE_TOKENS, key=len, reverse=True):
        for match in re.finditer(re.escape(token), raw):
            span = match.span()
            if any(not (span[1] <= existing[0] or span[0] >= existing[1]) for existing in working_spans):
                continue
            working_spans.append(span)
            mentions.append((span[0], token))
    return sorted(mentions)


def _role_tokens(text: str) -> set[str]:
    return {token for _, token in _role_mentions(text)}


def _role_relation(text: str) -> tuple[str, str, str] | None:
    raw = text or ""
    mentions = _role_mentions(raw)
    if len(mentions) < 2:
        return None
    # Limit hard relation checks to explicit “A ... 向 B ... 行为” grammar. This
    # avoids treating equivalent rights-perspective rewrites as certain errors.
    for subject_pos, subject in mentions:
        subject_end = subject_pos + len(subject)
        tail = raw[subject_end:]
        toward_index = tail.find("向")
        if toward_index < 0 or toward_index > 12:
            continue
        absolute_toward = subject_end + toward_index
        object_candidates = [(pos, role) for pos, role in mentions if absolute_toward < pos <= absolute_toward + 12]
        if not object_candidates:
            continue
        _, obj = object_candidates[0]
        object_pos = object_candidates[0][0]
        action_tail = raw[object_pos + len(obj) : object_pos + len(obj) + 16]
        action = next((token for token in _ACTION_TOKENS if token in action_tail), "")
        if action:
            return subject, obj, action
    return None


def detect_mismatch_details(expected: str, actual: str) -> list[MismatchDetail]:
    """Return hard conflicts separately from possible conflicts.

    Hard conflicts are reserved for high-confidence lexical/relational contradictions.
    Scope-sensitive negation is intentionally downgraded to possible so that expressions
    such as “并非无效” are not falsely treated as the opposite of “有效”.
    """

    details: list[MismatchDetail] = []
    expected_text = expected or ""
    actual_text = actual or ""

    # A short cloze-style role answer such as “被代理人” versus “代理人” must not
    # be softened merely because one token is a substring of the other. Limit this
    # hard rule to exact role-token answers so ordinary sentence rewrites remain safe.
    expected_compact = compact(expected_text)
    actual_compact = compact(actual_text)
    exact_roles = set(_ROLE_TOKENS)
    if expected_compact in exact_roles and actual_compact in exact_roles and expected_compact != actual_compact:
        details.append(
            MismatchDetail(
                "hard",
                f"关键主体限定冲突：标准“{expected_compact}”，回答“{actual_compact}”",
            )
        )

    for label, negatives, positives in _POLARITY_GROUPS:
        expected_side, expected_token, expected_scoped = _polarity_side(expected_text, negatives, positives)
        actual_side, actual_token, actual_scoped = _polarity_side(actual_text, negatives, positives)
        if expected_side and actual_side and expected_side != actual_side:
            details.append(MismatchDetail("hard", f"关键{label}冲突：标准“{expected_token}”，回答“{actual_token}”"))
        elif expected_scoped or actual_scoped:
            if any(token in expected_text or token in actual_text for token in (*negatives, *positives)):
                details.append(MismatchDetail("possible", f"{label}存在否定作用域，需要人工核对语义方向"))

    expected_bindings = _number_bindings(expected_text)
    actual_bindings = _number_bindings(actual_text)
    for action in sorted(set(expected_bindings) & set(actual_bindings)):
        if expected_bindings[action] != actual_bindings[action]:
            expected_value, expected_unit = expected_bindings[action]
            actual_value, actual_unit = actual_bindings[action]
            details.append(
                MismatchDetail(
                    "hard",
                    f"关键期限/数字关系冲突：{action}标准“{expected_value}{expected_unit}”，回答“{actual_value}{actual_unit}”",
                )
            )

    expected_numbers = _number_tokens(expected_text)
    actual_numbers = _number_tokens(actual_text)
    if expected_numbers and actual_numbers:
        expected_values = {value for value, _ in expected_numbers}
        actual_values = {value for value, _ in actual_numbers}
        if expected_values != actual_values:
            details.append(
                MismatchDetail(
                    "hard",
                    "关键期限/数字冲突：标准“{}”，回答“{}”".format(
                        "、".join(f"{value}{unit}" for value, unit in expected_numbers),
                        "、".join(f"{value}{unit}" for value, unit in actual_numbers),
                    ),
                )
            )
        else:
            expected_units = {unit for _, unit in expected_numbers if unit}
            actual_units = {unit for _, unit in actual_numbers if unit}
            if expected_units and actual_units and expected_units != actual_units:
                details.append(
                    MismatchDetail(
                        "hard",
                        "关键期限单位冲突：标准“{}”，回答“{}”".format(
                            "、".join(unit for unit in expected_units),
                            "、".join(unit for unit in actual_units),
                        ),
                    )
                )

    expected_relation = _role_relation(expected_text)
    actual_relation = _role_relation(actual_text)
    if expected_relation and actual_relation:
        exp_subject, exp_object, exp_action = expected_relation
        act_subject, act_object, act_action = actual_relation
        if exp_action == act_action and exp_subject == act_object and exp_object == act_subject:
            details.append(
                MismatchDetail(
                    "hard",
                    f"关键主体关系冲突：标准“{exp_subject}→{exp_object}→{exp_action}”，回答“{act_subject}→{act_object}→{act_action}”",
                )
            )

    expected_roles = _role_tokens(expected_text)
    actual_roles = _role_tokens(actual_text)
    if expected_roles and actual_roles and not (expected_roles & actual_roles):
        details.append(
            MismatchDetail(
                "possible",
                "主体集合变化：标准涉及“{}”，回答写成“{}”，需核对是否为等价改写".format(
                    "、".join(sorted(expected_roles)),
                    "、".join(sorted(actual_roles)),
                ),
            )
        )

    unique: list[MismatchDetail] = []
    seen: set[tuple[str, str]] = set()
    for item in details:
        key = (item.severity, item.message)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def detect_critical_mismatches(expected: str, actual: str) -> list[str]:
    return [item.message for item in detect_mismatch_details(expected, actual) if item.severity == "hard"]


def _strip_critical(text: str) -> str:
    stripped = text or ""
    for _, negatives, positives in _POLARITY_GROUPS:
        for token in (*negatives, *positives):
            stripped = stripped.replace(token, "")
    stripped = _NUMBER_PATTERN.sub("", stripped)
    return compact(stripped)


def _anchor_similarity(source_clause: str, answer_clause: str) -> float:
    source = _strip_critical(source_clause)
    answer = _strip_critical(answer_clause)
    if not source or not answer:
        return 0.0
    ratio = SequenceMatcher(None, source, answer).ratio()
    shorter, longer = sorted((source, answer), key=len)
    containment = 1.0 if shorter and shorter in longer else 0.0
    return max(ratio, containment * min(1.0, len(shorter) / max(len(longer), 1) + 0.25))


def split_clauses(text: str) -> list[str]:
    return [part.strip() for part in _CLAUSE_SPLIT.split(text or "") if len(compact(part)) >= 2]


def detect_clause_conflicts(source_text: str, answer_text: str, *, threshold: float = 0.40) -> list[ClauseConflict]:
    source_clauses = split_clauses(source_text)
    answer_clauses = split_clauses(answer_text)
    conflicts: list[ClauseConflict] = []
    if not source_clauses or not answer_clauses:
        return conflicts

    seen: set[tuple[str, str, str, tuple[str, ...]]] = set()
    for source_clause in source_clauses:
        for answer_clause in answer_clauses:
            similarity = _anchor_similarity(source_clause, answer_clause)
            if similarity < threshold:
                continue
            details = detect_mismatch_details(source_clause, answer_clause)
            for severity in ("hard", "possible"):
                messages = tuple(item.message for item in details if item.severity == severity)
                if not messages:
                    continue
                key = (source_clause, answer_clause, severity, messages)
                if key in seen:
                    continue
                seen.add(key)
                conflicts.append(
                    ClauseConflict(
                        source_clause=source_clause,
                        answer_clause=answer_clause,
                        similarity=round(similarity, 3),
                        severity=severity,
                        mismatches=messages,
                    )
                )
    return conflicts


def looks_like_keyword_pile(text: str) -> bool:
    raw = (text or "").strip()
    if not raw:
        return False
    fragments = [item for item in _ENUM_SEPARATOR.split(raw) if compact(item)]
    if len(fragments) < 6:
        return False
    sentence_end_count = len(_SENTENCE_END.findall(raw))
    short_ratio = sum(1 for item in fragments if len(compact(item)) <= 12) / max(len(fragments), 1)
    predicate_hits = len(
        re.findall(
            r"应当|必须|不得|可以|有权|无权|发生效力|不发生效力|承担|取得|适用|履行|请求|追认|撤销|登记|交付",
            raw,
        )
    )
    separator_count = len(re.findall(r"[\s、，,；;]", raw))
    return separator_count >= 5 and sentence_end_count == 0 and short_ratio >= 0.75 and predicate_hits <= 2
