from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from difflib import SequenceMatcher
from typing import Iterable, Literal

from app.services.legal_signals import detect_critical_mismatches
from uuid import uuid4


RetrievalType = Literal["flashcard", "cloze"]
RetrievalRating = Literal["again", "hard", "good", "easy"]


@dataclass(frozen=True)
class RetrievalDraft:
    id: str
    item_type: RetrievalType
    prompt: str
    answer: str
    cloze_text: str | None
    source_excerpt: str
    content_hash: str
    generation_method: str = "local_rule_v1"


@dataclass(frozen=True)
class ClozeGrade:
    score: float
    rating: RetrievalRating
    correct: bool
    normalized_response: str
    normalized_answer: str
    note: str
    critical_mismatches: tuple[str, ...] = ()


@dataclass(frozen=True)
class RetrievalPlan:
    mastery_status: str
    due_at: str
    interval_minutes: int
    streak: int
    lapses: int
    reason: str


from app.services.text_utils import rejoin_cjk_line_breaks

# 句子边界只看句末标点（。！？!?），不把换行当边界、不把分号当边界——
# PDF 段落内换行与列举分号（“条件 (1)…；(2)…”）会误切碎句子，
# 导致挖空/证据片段孤立无上下文。
_SENTENCE_SPLIT = re.compile(r"(?<=[。！？!?])\s*")

# 版权水印特征：出现在正文中必是水印（“正版资料，请注意加入会员群 内部讲义，请勿盗印”），
# 不能作为挖空/闪卡内容；注意“溶研毓秀/强化讲义”单独出现可能是正文引用，不在此列。
_WATERMARK = re.compile(r"正版资料|盗印|会员群")
_CHINESE = re.compile(r"[\u4e00-\u9fff]")


def _clean_text(text: str) -> str:
    text = text.replace("\u00a0", " ").replace("\r\n", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    text = rejoin_cjk_line_breaks(text)
    return text.strip()


def split_sentences(text: str) -> list[str]:
    cleaned = _clean_text(text)
    if not cleaned:
        return []
    sentences: list[str] = []
    for part in _SENTENCE_SPLIT.split(cleaned):
        sentence = re.sub(r"\s+", " ", part).strip(" \t\n")
        if len(sentence) < 8:
            continue
        if len(sentence) > 260:
            clauses = [item.strip() for item in re.split(r"(?<=[，,：:])", sentence) if item.strip()]
            current = ""
            for clause in clauses:
                if current and len(current) + len(clause) > 180:
                    sentences.append(current)
                    current = clause
                else:
                    current += clause
            if current:
                sentences.append(current)
        else:
            sentences.append(sentence)
    return sentences


def _sentence_score(sentence: str, index: int) -> tuple[int, int, int]:
    markers = (
        "是指",
        "包括",
        "应当",
        "必须",
        "不得",
        "可以",
        "有权",
        "无权",
        "条件",
        "要件",
        "例外",
        "除外",
        "责任",
        "效力",
        "requires",
        "includes",
        "must",
        "shall",
        "may",
        "means",
    )
    marker_score = sum(1 for marker in markers if marker.lower() in sentence.lower())
    length_score = 2 if 20 <= len(sentence) <= 150 else 1
    early_score = max(0, 4 - index)
    return marker_score, length_score, early_score


def important_sentences(text: str, limit: int = 5) -> list[str]:
    sentences = split_sentences(text)
    ranked = sorted(
        enumerate(sentences),
        key=lambda pair: (_sentence_score(pair[1], pair[0]), -pair[0]),
        reverse=True,
    )
    selected_indexes = sorted(index for index, _ in ranked[:limit])
    return [sentences[index] for index in selected_indexes]


def _flashcard_prompt(title: str, sentence: str, index: int) -> str:
    chinese_patterns = [
        (r"^(.{2,24}?)(?:是指|系指)(.+)$", lambda topic: f"什么是{topic}？"),
        (r"^(.{2,24}?)(?:包括|应当具备|须具备|必须具备)(.+)$", lambda topic: f"根据教材，{topic}包括哪些核心内容？"),
    ]
    for pattern, formatter in chinese_patterns:
        match = re.match(pattern, sentence)
        if match:
            topic = match.group(1).strip("，。：:；;、 ")
            if 2 <= len(topic) <= 24:
                return formatter(topic)

    english = re.match(
        r"^(.{3,60}?)\s+(requires|includes|means|must|shall|may)\s+(.+)$",
        sentence,
        flags=re.IGNORECASE,
    )
    if english:
        subject = english.group(1).strip(" ,:;.")
        verb = english.group(2).lower()
        return f"According to the source, what does {subject} {verb}?"

    preview = sentence[:22].rstrip("，,。.;；:： ")
    suffix = "……" if len(sentence) > len(preview) else ""
    return f"请完整说明「{title}」中的规则：{preview}{suffix}"


def _candidate_quoted(sentence: str) -> str | None:
    for pattern in (r"“([^”]{2,24})”", r"《([^》]{2,24})》", r"\"([^\"]{2,24})\""):
        match = re.search(pattern, sentence)
        if match:
            return match.group(1).strip()
    return None


def _candidate_after_marker(sentence: str) -> str | None:
    completed = re.search(r"应当([\u4e00-\u9fff]{1,8})的已经\1", sentence)
    if completed:
        return f"已经{completed.group(1)}"
    generic = {
        "以下条件", "下列条件", "具备以下条件", "具备下列条件", "有关规定", "法律规定",
        "依法处理", "相应责任", "相关责任", "下列情形", "以下情形",
    }
    patterns = [
        r"[:：]\s*([^，。；:：]{2,32})",
        r"(?:为|是)\s*([^，。；:：]{2,20})",
        r"(?:是指|系指|包括|条件(?:是|为)|要件(?:是|为)|应当具备|须具备)\s*([^，。；:：]{2,28})",
        r"(?:应当|必须|不得|可以|有权|无权)\s*([^，。；:：]{2,22})",
        r"\b(?:requires|includes|means|must|shall|may)\s+([A-Za-z][A-Za-z0-9' -]{3,42})",
    ]
    for pattern in patterns:
        match = re.search(pattern, sentence, flags=re.IGNORECASE)
        if match:
            candidate = match.group(1).strip(" ，,。.;；:：")
            if candidate in generic:
                continue
            if 2 <= len(candidate) <= 42:
                return candidate
    return None


def _candidate_legal_phrase(sentence: str) -> str | None:
    matches = re.findall(
        r"[\u4e00-\u9fff]{2,12}(?:权|义务|责任|行为|制度|原则|要件|条件|效力|期限|期间|合同|主体|客体|关系|标准|时点|程序|救济)",
        sentence,
    )
    if matches:
        return max(matches, key=len)
    return None


def _fallback_chinese(sentence: str) -> str | None:
    stop = {"根据规定", "下列条件", "以下条件", "有关规定", "本条规定", "法律规定", "应当依法", "可以依法"}
    stripped = sentence.strip(" ，,。.;；:：")
    tail_clause = re.split(r"[，,:：]", stripped)[-1].strip()
    tail_match = re.search(r"[\u4e00-\u9fff]{2,10}$", tail_clause)
    if tail_match and tail_match.group(0) not in stop:
        candidate = tail_match.group(0)
        for marker in ("应当", "必须", "不得", "可以", "有权", "无权"):
            if candidate.startswith(marker) and len(candidate) > len(marker) + 1:
                candidate = candidate[len(marker):]
        if 2 <= len(candidate) <= 10:
            return candidate
    chunks = re.findall(r"[\u4e00-\u9fff]{2,10}(?:权|义务|责任|制度|原则|要件|条件|效力|期限|期间|合同|标准|时点|程序|救济|善意|价格|登记|交付)", sentence)
    chunks = [chunk for chunk in chunks if chunk not in stop]
    return max(chunks, key=len) if chunks else None


def _fallback_english(sentence: str) -> str | None:
    stop = {"the", "a", "an", "and", "or", "of", "to", "in", "is", "are", "for", "with", "that", "this"}
    words = re.findall(r"[A-Za-z][A-Za-z'-]*", sentence)
    content = [word for word in words if word.lower() not in stop and len(word) >= 4]
    if not content:
        return None
    if len(content) >= 3:
        return " ".join(content[:3])
    return content[0]


def find_cloze_span(sentence: str, title: str) -> str | None:
    quoted = _candidate_quoted(sentence)
    if quoted:
        return quoted
    clean_title = title.strip(" ：:、。")
    if 2 <= len(clean_title) <= 24 and clean_title in sentence:
        return clean_title
    after_marker = _candidate_after_marker(sentence)
    if after_marker:
        return after_marker
    legal = _candidate_legal_phrase(sentence)
    if legal:
        return legal
    if _CHINESE.search(sentence):
        return _fallback_chinese(sentence)
    return _fallback_english(sentence)


def retrieval_content_hash(item_type: str, prompt: str, answer: str, source_excerpt: str) -> str:
    payload = "\x1f".join((item_type, prompt, answer, source_excerpt))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def generate_retrieval_items(
    *,
    title: str,
    body: str,
    item_types: Iterable[RetrievalType],
    max_per_type: int = 3,
) -> list[RetrievalDraft]:
    requested = list(dict.fromkeys(item_types))
    sentences = important_sentences(body, limit=max(6, max_per_type * 2))
    if not sentences:
        return []
    sentences = [sentence for sentence in sentences if not _WATERMARK.search(sentence)]
    if not sentences:
        return []

    drafts: list[RetrievalDraft] = []
    if "flashcard" in requested:
        overview_answer = "\n".join(f"• {sentence}" for sentence in sentences[: min(4, len(sentences))])
        overview_prompt = f"请闭卷复述「{title}」的核心规则、条件与例外。"
        drafts.append(
            RetrievalDraft(
                id=str(uuid4()),
                item_type="flashcard",
                prompt=overview_prompt,
                answer=overview_answer,
                cloze_text=None,
                source_excerpt="\n".join(sentences[: min(4, len(sentences))]),
                content_hash=retrieval_content_hash("flashcard", overview_prompt, overview_answer, body),
            )
        )
        seen_prompts = {overview_prompt}
        for index, sentence in enumerate(sentences):
            if len(drafts) >= max_per_type:
                break
            prompt = _flashcard_prompt(title, sentence, index)
            if prompt in seen_prompts:
                continue
            seen_prompts.add(prompt)
            drafts.append(
                RetrievalDraft(
                    id=str(uuid4()),
                    item_type="flashcard",
                    prompt=prompt,
                    answer=sentence,
                    cloze_text=None,
                    source_excerpt=sentence,
                    content_hash=retrieval_content_hash("flashcard", prompt, sentence, sentence),
                )
            )

    if "cloze" in requested:
        cloze_count = 0
        seen_pairs: set[tuple[str, str]] = set()
        for sentence in sentences:
            if cloze_count >= max_per_type:
                break
            answer = find_cloze_span(sentence, title)
            if not answer or answer not in sentence:
                continue
            cloze_text = sentence.replace(answer, "____", 1)
            visible_context = re.sub(r"[_，,。.;；:：\s]", "", cloze_text)
            sentence_content = re.sub(r"[，,。.;；:：\s]", "", sentence)
            if len(visible_context) < 4 or len(answer) / max(len(sentence_content), 1) > 0.7:
                continue
            pair = (cloze_text, answer)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            prompt = f"填空：{cloze_text}"
            drafts.append(
                RetrievalDraft(
                    id=str(uuid4()),
                    item_type="cloze",
                    prompt=prompt,
                    answer=answer,
                    cloze_text=cloze_text,
                    source_excerpt=sentence,
                    content_hash=retrieval_content_hash("cloze", prompt, answer, sentence),
                )
            )
            cloze_count += 1

    return drafts


def normalize_answer(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).lower().strip()
    normalized = re.sub(r"[\s\u3000]+", "", normalized)
    normalized = re.sub(r"[，,。.!！？?；;：:'\"“”‘’（）()【】\[\]{}<>《》、·—_-]+", "", normalized)
    return normalized


def grade_cloze(response: str, expected: str) -> ClozeGrade:
    actual = normalize_answer(response)
    target = normalize_answer(expected)
    if not actual:
        return ClozeGrade(0.0, "again", False, actual, target, "未填写答案。")
    if actual == target:
        return ClozeGrade(100.0, "good", True, actual, target, "答案与标准填空一致。")

    critical_mismatches = tuple(detect_critical_mismatches(expected, response))
    if critical_mismatches:
        similarity = SequenceMatcher(None, actual, target).ratio()
        score = round(min(45.0, similarity * 100), 1)
        return ClozeGrade(
            score,
            "again",
            False,
            actual,
            target,
            "发现法律关键限定冲突，不能按普通相似度放过；请立即回源后重做。",
            critical_mismatches,
        )

    if target in actual or actual in target:
        shorter = min(len(actual), len(target))
        longer = max(len(actual), len(target)) or 1
        score = 90.0 if shorter / longer >= 0.75 else 78.0
        return ClozeGrade(score, "hard", score >= 85, actual, target, "核心词已覆盖，但表达范围与标准答案不完全一致。")
    similarity = SequenceMatcher(None, actual, target).ratio()
    score = round(similarity * 100, 1)
    if score >= 85:
        return ClozeGrade(score, "hard", True, actual, target, "答案高度接近，请核对术语精度。")
    if score >= 60:
        return ClozeGrade(score, "hard", False, actual, target, "部分接近，但关键术语仍需修正。")
    return ClozeGrade(score, "again", False, actual, target, "答案与目标差距较大，建议立即重做。")


def score_for_rating(rating: RetrievalRating) -> float:
    return {"again": 20.0, "hard": 60.0, "good": 85.0, "easy": 100.0}[rating]


def retrieval_review_plan(
    rating: RetrievalRating,
    *,
    prior_interval_minutes: int = 0,
    prior_streak: int = 0,
    prior_lapses: int = 0,
    now: datetime | None = None,
) -> RetrievalPlan:
    current = now or datetime.now(UTC)
    if rating == "again":
        interval = 10
        streak = 0
        lapses = prior_lapses + 1
        status = "学习中"
        reason = "十分钟后再次提取，当前证据尚不稳定。"
    elif rating == "hard":
        interval = max(24 * 60, int(max(prior_interval_minutes, 60) * 1.25))
        streak = max(1, prior_streak)
        lapses = prior_lapses
        status = "不稳定"
        reason = "一天后复测，优先修正本次犹豫或术语误差。"
    elif rating == "good":
        interval = 3 * 24 * 60 if prior_interval_minutes <= 0 else max(3 * 24 * 60, prior_interval_minutes * 2)
        streak = prior_streak + 1
        lapses = prior_lapses
        status = "基本稳定" if streak >= 2 else "不稳定"
        reason = "按正常间隔复测，并保留来源回指。"
    else:
        interval = 7 * 24 * 60 if prior_interval_minutes <= 0 else max(7 * 24 * 60, prior_interval_minutes * 3)
        streak = prior_streak + 1
        lapses = prior_lapses
        status = "稳定" if streak >= 2 else "基本稳定"
        reason = "延长复测间隔，后续以维护性提取为主。"

    due_at = (current + timedelta(minutes=interval)).isoformat()
    return RetrievalPlan(status, due_at, interval, streak, lapses, reason)
