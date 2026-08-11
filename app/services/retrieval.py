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
    # 先按行移除版权水印行，再做 CJK 跨行断字重组——否则水印行会被
    # rejoin 无缝粘进正文句，把前后正文粘成怪句并污染句子内容。
    lines = [line for line in text.split("\n") if not _WATERMARK.search(line)]
    text = "\n".join(lines)
    # 章节/小标题行（“第一节 民法的渊源”“【本节知识点详述】”“一、民法渊源概述”）
    # 行尾补句号：否则行尾汉字紧邻下一行汉字会被 rejoin 当成跨行断字粘进正文句，
    # 生成卡片时把标题/目录行混进题面（历史卡“【本节知识点详述】…”“西政，等你。”即源于此）。
    text = re.sub(
        r"^(?:第[一二三四五六七八九十百]+[编篇章节部分]|【[^】\n]{1,30}】|[一二三四五六七八九十]+、)[^，。；:：\n]{0,40}$",
        lambda match: match.group(0) + "。",
        text,
        flags=re.MULTILINE,
    )
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
        if _WATERMARK.search(sentence) and "\n" in part:
            # 水印行夹在正文行之间（无句号）会把前后正文粘成超长怪句：
            # 按行拆开，让正文句独立成句，水印片段随后由调用方过滤。
            for line_part in part.split("\n"):
                line = re.sub(r"\s+", " ", line_part).strip()
                if len(line) >= 8:
                    sentences.append(line)
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


def _sentence_score(sentence: str, index: int) -> tuple[int, int]:
    """句子“可出题性”评分（本地启发式，越高越值得做挖空/闪卡）。

    结构信号权重：
      - 规则句（情态动词 + 法律后果/行为）……4 分
      - 法条引用（《X》第N条）………………3 分
      - 数字/期限/期间（X日/周岁/年以上）…2 分
      - 例外/但书………………………………2 分
      - 要件/条件列举 ((1)(2)(3))…………2 分
      - 高价值判定词密度……………………每词 1 分
      - 长度 20–160 适中……………………2 分
    同分时正文顺序靠前者优先（-index 作为次级键）。
    """
    score = 0
    # 章节/小标题行（“第X节…”“【本节…】”“一、…概述”）不是可出题内容，直接压到最低
    if re.match(r"^(?:第[一二三四五六七八九十百]+[编篇章节部分]|【[^】]{1,30}】|[一二三四五六七八九十]+、)", sentence):
        return -10, -index
    if re.search(r"(?:应当|必须|不得|可以|有权|无权|须)[\u4e00-\u9fff]{0,8}(?:的|为|是|成立|生效|承担|取得|转让|登记|交付|撤销|解除|无效|有效|赔偿)", sentence):
        score += 4
    elif re.search(r"应当|必须|不得|可以|有权|无权|须", sentence):
        score += 3
    if re.search(r"《[^》]{1,16}》第[一二三四五六七八九十百零0-9]+条", sentence) or re.search(r"(?<!第)第[一二三四五六七八九十百零0-9]+条", sentence):
        score += 3
    if re.search(r"[\d一二三四五六七八九十百]+(?:周岁|日内|个月|个月以内|年以上|年以下|年以内|小时|日|个月)", sentence):
        score += 2
    if re.search(r"但是|但书|除外|例外|除非|不得.{0,12}但", sentence):
        score += 2
    if re.search(r"\([0-9一二三四五六七八九十]+\)", sentence):
        score += 2
    markers = ("是指", "系指", "包括", "条件", "要件", "标准", "期限", "效力", "分为", "种类", "属于")
    score += sum(1 for marker in markers if marker in sentence)
    if 20 <= len(sentence) <= 160:
        score += 2
    elif len(sentence) < 20:
        score += 1
    return score, -index


def important_sentences(text: str, limit: int = 5) -> list[str]:
    sentences = split_sentences(text)
    ranked = sorted(
        enumerate(sentences),
        key=lambda pair: (_sentence_score(pair[1], pair[0]), -pair[0]),
        reverse=True,
    )
    selected_indexes = sorted(index for index, _ in ranked[:limit])
    return [sentences[index] for index in selected_indexes]


def _flashcard_topic(sentence: str) -> str | None:
    """从句子开头提取一个可作为提问主题的短语（2–16 字）。"""
    match = re.match(r"^([\u4e00-\u9fffA-Za-z0-9]{2,16}?)(?:是|指|即|包括|分为|应当|必须|不得|须|与|同|对|在|于|作为|属于|具有|可以|需要|只要|只有|当|除|依|根|按|就|从|以|由|而|并|也|都|则|还)", sentence)
    if match:
        return _meaningful_topic(match.group(1))
    first = re.match(r"^([\u4e00-\u9fffA-Za-z0-9]{2,16}?)[，,：:。；;]", sentence)
    if first:
        return _meaningful_topic(first.group(1))
    return None


# 弱词/虚词单独作为主题时题面无语义（如“什么是主要？”“什么是概述？”），应回退到标题
_WEAK_TOPICS = {"主要", "可以", "应当", "必须", "一般", "直接", "间接", "根据", "包括", "分为", "同时", "此外", "首先", "其次", "最后", "所谓", "就是", "概述", "概念", "特征", "类型", "种类", "意义", "作用", "方式", "内容"}


def _meaningful_topic(topic: str | None) -> str | None:
    if topic is None:
        return None
    stripped = topic.strip(" ，,。.:：;；、")
    if stripped in _WEAK_TOPICS or len(stripped) < 2:
        return None
    return stripped


def _clean_title(title: str) -> str:
    """去掉标题的章节前缀（“第二节 民法的性质”→“民法的性质”），
    避免 fallback 时把“第二节”带进题面；弱词标题（“概述”“概念”…）
    同样视为无主题，返回空让调用方使用兜底。"""
    cleaned = re.sub(r"^(?:第[一二三四五六七八九十百]+[编篇章节部分])", "", title or "").strip(" ：:、。")
    if not cleaned:
        return ""
    if cleaned in _WEAK_TOPICS:
        return ""
    return cleaned


def _flashcard_prompt(title: str, sentence: str, index: int) -> str:
    # 9 类提问模板：先按信号词匹配提问角度，再提取主题。
    # 兜底不把原文贴进 prompt（避免“背课文”），只问主题。
    topic = _flashcard_topic(sentence) or _clean_title(title) or "本部分内容"
    # 法条引用优先：《民法典》第187条 → 直接问该条内容（数字/期限类规则常落在法条）
    law_ref = re.search(r"(《[^》]{1,16}》)?第([一二三四五六七八九十百零0-9]+)条", sentence)
    if law_ref:
        law = law_ref.group(1) or ""
        return f"{law}第{law_ref.group(2)}条规定了什么内容？"
    templates: list[tuple[re.Pattern, Callable[[str], str]]] = [
        (re.compile(r"是指|系指|即|定义为|叫做"), lambda t: f"什么是{t}？"),
        (re.compile(r"要件|应当具备|须具备|必须具备|构成条件"), lambda t: f"{t}的构成要件有哪些？"),
        (re.compile(r"条件|前提|方可|才能|须|必须|应当"), lambda t: f"{t}的适用条件是什么？"),
        (re.compile(r"分为|包括|种类|类型|分类|有以下几"), lambda t: f"{t}分为哪几类？"),
        (re.compile(r"区别于|不同于|与[^，。]{1,12}不同|差别|差异"), lambda t: f"{t}与相近概念有何区别？"),
        (re.compile(r"例外|除外|但书|不得|禁止"), lambda t: f"{t}的例外或限制情形有哪些？"),
        (re.compile(r"依据|根据|依照|规定|法条"), lambda t: f"{t}的法律依据是什么？"),
        (re.compile(r"意义|作用|价值|目的|重要性"), lambda t: f"{t}的意义是什么？"),
    ]
    for pattern, formatter in templates:
        if pattern.search(sentence):
            return formatter(topic)
    # 数字/期限句（非法条）→ 问时间/期限要求
    if re.search(r"[\d一二三四五六七八九十百]+(?:周岁|日内|个月|年以上|年以下|年以内|小时|日|年)", sentence):
        return f"{topic}的时间或期限要求是什么？"

    english = re.match(
        r"^(.{3,60}?)\s+(requires|includes|means|must|shall|may)\s+(.+)$",
        sentence,
        flags=re.IGNORECASE,
    )
    if english:
        subject = english.group(1).strip(" ,:;.")
        verb = english.group(2).lower()
        return f"According to the source, what does {subject} {verb}?"

    return f"用自己的话复述：{topic}（注意规则、条件与例外）"


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
    clean_title = _clean_title(title)
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


# 多空答案分隔符：与 content_hash payload 分隔符一致，保持协议自洽。
ANSWER_SEP = "\x1f"


def find_cloze_spans(sentence: str, title: str, max_spans: int = 3) -> list[str]:
    """多空挖空候选：按信息量分级收集（引号/标题/数字期限 > 判定词后短语 >
    法律术语 > 句尾兜底），去重、去包含（保留高优先级）、过滤弱词碎片，
    并保证相邻空位在句中有足够间距（连续挖空破坏可读性）。"""
    generic = {
        "以下条件", "下列条件", "具备以下条件", "具备下列条件", "具备的条件", "有关规定",
        "法律规定", "依法处理", "相应责任", "相关责任", "下列情形", "以下情形",
        "本条", "前款", "本款",
    }
    candidates: list[tuple[str, int]] = []

    def add(candidate: str, priority: int, max_len: int = 42) -> None:
        candidate = candidate.strip(" ，,。.;；:：、")
        if len(candidate) < 2 or len(candidate) > max_len:
            return
        if candidate in generic or re.fullmatch(r"[的是为与及和或内]", candidate):
            return
        # 以情态动词开头的短语是规则句的动词部分，不是可作答的知识点
        if re.match(r"^(?:应当|必须|不得|可以|有权|无权|须)", candidate):
            return
        candidates.append((candidate, priority))

    # 高：引号/书名号内容、章节标题、数字期限组合
    for quoted in re.findall(r"[“\"'『《]([^”\"'』》]{2,24})[”\"'』》]", sentence):
        add(quoted, 4)
    clean_title = _clean_title(title)
    if 2 <= len(clean_title) <= 24 and clean_title in sentence:
        add(clean_title, 4)
    for match in re.finditer(r"[0-9一二三四五六七八九十百]+(?:周岁|日内|个月|年以上|年以下|年以内|小时|日|年)", sentence):
        add(match.group(0), 3)
    # 中：判定词/情态动词后的具体短语
    marker_patterns = [
        r"[:：]\s*([^，。；:：]{2,32})",
        r"(?:为|是)\s*([^，。；:：]{2,20})",
        r"(?:是指|系指|包括|条件(?:是|为)|要件(?:是|为)|应当具备|须具备)\s*([^，。；:：]{2,28})",
        r"(?:应当|必须|不得|可以|有权|无权)\s*([^，。；:：]{2,22})",
    ]
    for pattern in marker_patterns:
        for match in re.finditer(pattern, sentence):
            add(match.group(1), 2, max_len=12)
    # 中：法律术语（排除含判定虚词的半截碎片）
    for legal in re.findall(
        r"[\u4e00-\u9fff]{2,12}(?:权|义务|责任|行为|制度|原则|要件|条件|效力|期限|期间|合同|主体|客体|关系|标准|时点|程序|救济)(?![\u4e00-\u9fff])",
        sentence,
    ):
        if not re.search(r"[是为与的之]", legal):
            add(legal, 2)

    # 去重、去包含（保留高优先级）
    seen: dict[str, int] = {}
    for candidate, priority in candidates:
        if candidate in seen:
            if priority > seen[candidate]:
                seen[candidate] = priority
            continue
        overlap = next((other for other in seen if candidate in other or other in candidate), None)
        if overlap:
            if priority > seen[overlap]:
                del seen[overlap]
                seen[candidate] = priority
            continue
        seen[candidate] = priority
    if not seen:
        fallback = _fallback_chinese(sentence)
        if fallback:
            seen[fallback] = 1
    # 按出现位置排序，保证“第 N 个空 == 第 N 个答案”一一对应；
    # 相邻空位间距 ≥ 8 字符，避免把一句话挖成筛子
    ordered = sorted(seen, key=lambda candidate: sentence.find(candidate))
    spaced: list[str] = []
    last_pos = -9
    for candidate in ordered:
        pos = sentence.find(candidate)
        if pos - last_pos >= 8:
            spaced.append(candidate)
            last_pos = pos
    return spaced[:max_spans]


def _context_window(body: str, sentence: str, window: int = 140) -> str:
    """挖空卡片的段落上下文：从单元正文定位句子，前后各取 window 字符，
    越界加“……”。找不到句子时回退为句子本身。"""
    idx = body.find(sentence)
    if idx < 0:
        return sentence
    start = max(0, idx - window)
    end = min(len(body), idx + len(sentence) + window)
    prefix = "……" if start > 0 else ""
    suffix = "……" if end < len(body) else ""
    return prefix + body[start:end].replace("\r", "").strip() + suffix


_CLOZE_MARKERS = re.compile(r"是指|系指|即|属于|应当|必须|不得|须|可以|有权|无权|要件|条件|标准|期限|效力")
# 分类/枚举句（“分为/种类/类型/包括A、B、C”）→ 闪卡“分为哪几类”，
# 与 classify 模板配对；旧版把它们送进挖空池导致 flash 池拿不到素材。
_CLASSIFY_MARKERS = re.compile(r"分为|种类|类型|分类|有(?:以下|下列)|包括[\u4e00-\u9fff]{0,6}[、，,]")
_FLASHCARD_MARKERS = re.compile(r"为什么|因为|所以|区别|不同于|例外|除外|意义|作用|价值|目的|依据|根据|规定|但是|然而|如果|只要|才能")


def _split_pools(sentences: list[str]) -> tuple[list[str], list[str]]:
    """素材分流（互斥，一句只进一个池）：
      定义句/规则句/要件列举句 → 挖空池（提取具体知识点）；
      分类枚举句 → 闪卡池（“分为哪几类”整体恢复）；
      逻辑关系句 → 闪卡池（复述结构）；
      都未命中按长度分（短句→提取型，长句→复述型）。"""
    cloze_pool: list[str] = []
    flash_pool: list[str] = []
    for sentence in sentences:
        if _CLASSIFY_MARKERS.search(sentence):
            flash_pool.append(sentence)
            continue
        cloze_hit = bool(_CLOZE_MARKERS.search(sentence))
        flash_hit = bool(_FLASHCARD_MARKERS.search(sentence))
        if cloze_hit and not flash_hit:
            cloze_pool.append(sentence)
        elif flash_hit and not cloze_hit:
            flash_pool.append(sentence)
        elif len(sentence) <= 120:
            cloze_pool.append(sentence)
        else:
            flash_pool.append(sentence)
    return cloze_pool, flash_pool


def retrieval_content_hash(item_type: str, prompt: str, answer: str, source_excerpt: str) -> str:
    payload = "\x1f".join((item_type, prompt, answer, source_excerpt))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _prompt_leaks_answer(prompt: str, answer: str) -> bool:
    """题面不得包含答案原文：闪卡题面若完整包含答案（≥4 字去尾标点），
    用户看题面即得答案，闭卷练习失效。历史版本曾把句子前半塞进题面导致泄漏，
    这里做生成期防线（对未来模板回归同样生效）。"""
    core = re.sub(r"[\s，,。.;；:：、…]+$", "", (answer or "").strip())
    return len(core) >= 4 and core in prompt


def _safe_flashcard_prompt(title: str, sentence: str) -> str:
    """泄漏兜底：退化为“用自己的话复述”，只问主题，不贴原文。"""
    topic = _flashcard_topic(sentence) or _clean_title(title) or "本部分内容"
    return f"用自己的话复述：{topic}（注意规则、条件与例外）"


def generate_retrieval_items(
    *,
    title: str,
    body: str,
    item_types: Iterable[RetrievalType],
    max_per_type: int = 3,
) -> list[RetrievalDraft]:
    requested = list(dict.fromkeys(item_types))
    sentences = important_sentences(body, limit=max(8, max_per_type * 3))
    if not sentences:
        return []
    sentences = [sentence for sentence in sentences if not _WATERMARK.search(sentence)]
    if not sentences:
        return []
    cloze_pool, flash_pool = _split_pools(sentences)

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
        for index, sentence in enumerate(flash_pool):
            if len(drafts) >= max_per_type:
                break
            prompt = _flashcard_prompt(title, sentence, index)
            if prompt in seen_prompts:
                continue
            if _prompt_leaks_answer(prompt, sentence):
                # 题面包含答案 = 闭卷失效：降级为“用自己的话复述”，不生成泄漏卡
                prompt = _safe_flashcard_prompt(title, sentence)
            seen_prompts.add(prompt)
            excerpt = _context_window(body, sentence)
            drafts.append(
                RetrievalDraft(
                    id=str(uuid4()),
                    item_type="flashcard",
                    prompt=prompt,
                    answer=sentence,
                    cloze_text=None,
                    source_excerpt=excerpt,
                    # content_hash 用稳定句子做卡片身份（正文追加不影响），窗口只用于展示
                    content_hash=retrieval_content_hash("flashcard", prompt, sentence, sentence),
                )
            )

    if "cloze" in requested:
        cloze_count = 0
        seen_pairs: set[tuple[str, str]] = set()
        for sentence in cloze_pool:
            if cloze_count >= max_per_type:
                break
            spans = find_cloze_spans(sentence, title, max_spans=3)
            if not spans:
                continue
            # 词在句中多次出现时挖空有歧义，且未替换的残留会泄漏答案
            # （如“被担保债权”出现两次：挖第一处、第二处留在题面即等于提示答案）。
            # 跳过这类点位；全部不可用则放弃该句。
            usable_spans = [span for span in spans if sentence.count(span) == 1]
            if not usable_spans:
                continue
            cloze_text = sentence
            for span in usable_spans:
                if span in cloze_text:
                    cloze_text = cloze_text.replace(span, "____", 1)
            visible_context = re.sub(r"[_，,。.;；:：\s]", "", cloze_text)
            sentence_content = re.sub(r"[，,。.;；:：\s]", "", sentence)
            if len(visible_context) < 4 or sum(len(s) for s in usable_spans) / max(len(sentence_content), 1) > 0.7:
                continue
            answer = ANSWER_SEP.join(usable_spans)
            pair = (cloze_text, answer)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            prompt = f"填空：{cloze_text}"
            excerpt = _context_window(body, sentence)
            drafts.append(
                RetrievalDraft(
                    id=str(uuid4()),
                    item_type="cloze",
                    prompt=prompt,
                    answer=answer,
                    cloze_text=cloze_text,
                    source_excerpt=excerpt,
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


# 挖空评分同义归一：只做语义等价且语境安全的一对一映射。
# “必须/应当/须”是义务情态词，用户与标准答案互换时应判正确；
# 不做“无/没有”“禁止/不得”等易误伤名词用法的映射。
_SYNONYM_PAIRS = (
    ("必须", "应当"),
    ("须", "应当"),  # 需在“必须”之后替换，避免“必须”→“必应当”
    ("不可以", "不得"),
    ("只", "仅"),  # “只有/只需/只须”等义务限定
)


def _synonym_normalize(text: str) -> str:
    for source, target in _SYNONYM_PAIRS:
        text = text.replace(source, target)
    return text


def grade_cloze(response: str, expected: str) -> ClozeGrade:
    if ANSWER_SEP in expected:
        return _grade_multi_cloze(response, expected)
    actual = _synonym_normalize(normalize_answer(response))
    target = _synonym_normalize(normalize_answer(expected))
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


def _grade_multi_cloze(response: str, expected: str) -> ClozeGrade:
    """多空评分：按 ANSWER_SEP 拆分答案逐一评分，取加权平均；
    全部正确才 good，部分正确按比例降级。"""
    parts = expected.split(ANSWER_SEP)
    if ANSWER_SEP in response:
        given = response.split(ANSWER_SEP)
    else:
        given = [piece.strip() for piece in re.split(r"[；;，,、\s]+", response.strip()) if piece.strip()]
    if not given:
        return ClozeGrade(0.0, "again", False, normalize_answer(response), normalize_answer(expected), "未填写答案。")
    grades = []
    for index, part in enumerate(parts):
        answer_piece = given[index] if index < len(given) else ""
        grades.append(grade_cloze(answer_piece, part))
    average = round(sum(grade.score for grade in grades) / len(grades), 1)
    all_correct = all(grade.correct for grade in grades)
    rating: RetrievalRating = "good" if all_correct else ("hard" if average >= 60 else "again")
    critical = tuple(mismatch for grade in grades for mismatch in grade.critical_mismatches)
    if all_correct:
        note = f"全部 {len(parts)} 个填空均正确。"
    elif average >= 85:
        note = f"多数填空高度接近（平均 {average} 分），请核对每个空位的术语精度。"
    else:
        note = f"部分填空未完全正确（平均 {average} 分），建议回源核对各空位。"
    return ClozeGrade(
        average,
        rating,
        all_correct or average >= 85,
        normalize_answer(response),
        normalize_answer(expected),
        note,
        critical,
    )


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
