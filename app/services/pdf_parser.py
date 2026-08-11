from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

import fitz

from app.services.text_utils import rejoin_cjk_line_breaks


@dataclass(frozen=True)
class ParsedPage:
    page_number: int
    text: str
    text_hash: str
    quality_status: str


@dataclass(frozen=True)
class UnitDraft:
    id: str
    title: str
    body: str
    page_start: int
    page_end: int
    objective_type: str


def normalize_page_text(text: str) -> str:
    text = text.replace("\u00a0", " ").replace("\r\n", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = rejoin_cjk_line_breaks(text)
    return text.strip()


# 进程内缓存：{id(文档对象): (文档强引用, {页码: [(归一化 span 文本, bbox), ...]})}
# 句子跨行时 search_for 精确匹配会失败，需要按 span 做空白归一化定位；
# get_text("dict") 较慢，命中页面后缓存可避免重复请求重复提取。
# 同时持有文档强引用：防止文档被 GC 后 id() 复用导致脏缓存。
_NORM_SPAN_CACHE: dict[int, tuple[Any, dict[int, list[tuple[str, tuple[float, float, float, float]]]]]] = {}
_NORM_SPAN_CACHE_LIMIT = 6  # 文档级缓存上限（LRU 语义：超限淘汰最旧）


def _page_norm_spans(page: fitz.Page) -> list[tuple[str, tuple[float, float, float, float]]]:
    """返回页面所有 span 的空白归一化文本与 bbox（跨文档、跨请求缓存）。"""
    doc = page.parent
    doc_key = id(doc)
    cached_doc = _NORM_SPAN_CACHE.get(doc_key)
    if cached_doc is None:
        cached_doc = (doc, {})
        _NORM_SPAN_CACHE[doc_key] = cached_doc
        if len(_NORM_SPAN_CACHE) > _NORM_SPAN_CACHE_LIMIT:
            _NORM_SPAN_CACHE.pop(next(iter(_NORM_SPAN_CACHE)))
    _doc_ref, page_cache = cached_doc
    cached = page_cache.get(page.number)
    if cached is not None:
        return cached
    spans: list[tuple[str, tuple[float, float, float, float]]] = []
    for block in page.get_text("dict").get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                norm = re.sub(r"\s+", "", span.get("text", ""))
                if norm:
                    spans.append((norm, tuple(span["bbox"])))
    page_cache[page.number] = spans
    return spans


def search_text_rects(page: fitz.Page, candidate: str) -> list[dict[str, float]] | None:
    """在单个 PDF 页面中定位一段文本，返回左上原点坐标系矩形。

    先走 PyMuPDF 精确 search_for；句子跨换行/含其他空白差异时精确匹配会落空，
    再按 span 做空白归一化匹配：拼接归一化全文找到命中区间，映射回覆盖该区间的
    span bbox（跨行句子会得到多行矩形）。找不到返回 None。
    """
    exact = page.search_for(candidate)
    if exact:
        return [{"x0": r.x0, "y0": r.y0, "x1": r.x1, "y1": r.y1} for r in exact[:8]]
    norm_needle = re.sub(r"\s+", "", candidate)
    if len(norm_needle) < 2:
        return None
    spans = _page_norm_spans(page)
    if not spans:
        return None
    full = ""
    starts: list[int] = []
    for norm, _bbox in spans:
        starts.append(len(full))
        full += norm
    pos = full.find(norm_needle)
    if pos < 0:
        return None
    end = pos + len(norm_needle)
    rects = [
        {"x0": bbox[0], "y0": bbox[1], "x1": bbox[2], "y1": bbox[3]}
        for (norm, bbox), start in zip(spans, starts)
        if start < end and start + len(norm) > pos
    ]
    return rects or None


def parse_pdf(
    path: Path,
    progress: Callable[[int, int], None] | None = None,
) -> tuple[list[ParsedPage], dict[str, int]]:
    document = fitz.open(path)
    pages: list[ParsedPage] = []
    low_text_pages = 0
    total = document.page_count
    try:
        for index in range(total):
            page = document.load_page(index)
            text = normalize_page_text(page.get_text("text", sort=True))
            quality = "ok"
            if len(text) < 80:
                quality = "low_text"
                low_text_pages += 1
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
            pages.append(
                ParsedPage(
                    page_number=index + 1,
                    text=text,
                    text_hash=digest,
                    quality_status=quality,
                )
            )
            if progress:
                progress(index + 1, total)
    finally:
        document.close()
    return pages, {"low_text_pages": low_text_pages, "total_pages": total}


def _paragraphs(page: ParsedPage) -> list[str]:
    if not page.text:
        return []
    raw = re.split(r"\n\s*\n|(?<=[。！？；])\s*\n", page.text)
    cleaned = [re.sub(r"\s+", " ", item).strip() for item in raw]
    return [item for item in cleaned if item]


def _objective_type(text: str) -> str:
    if re.search(r"区别|不同于|辨析|混淆|比较", text):
        return "辨析型"
    if re.search(r"构成要件|应当具备|条件|包括|必须|不得", text):
        return "精确复现型"
    if re.search(r"本案|案例|甲|乙|行为人|当事人", text):
        return "适用型"
    if re.search(r"原理|意义|理由|价值|目的|基础", text):
        return "理解解释型"
    if re.search(r"简述|论述|如何理解|评析", text):
        return "表达型"
    return "综合型"


_HEADING_RE = re.compile(
    r"^(?:第[一二三四五六七八九十百\d]+[章节编部分讲篇]|"
    r"[一二三四五六七八九十]+、|"
    r"【[^】]{2,20}】|"
    r"\（[一二三四五六七八九十]+\）|"
    r"\([一二三四五六七八九十\d]+\))"
)
# 页眉/版权水印特征（几乎每页出现），不能作为单元标题
_HEADER_NOISE = re.compile(r"毓秀|强化讲义|内部讲义|正版资料|盗印")
_CHAPTER_RE = re.compile(r"^第[一二三四五六七八九十百\d]+[章节编部分讲篇]")


def _title_from_text(text: str, page_start: int, page_end: int) -> str:
    """优先用章节标题行做单元标题（如“第二节 民法的性质”“一、民法是市场经济的基本法”），
    避免正文首句残段或页眉成为标题。"""
    lines = [raw_line.strip(" ：:、") for raw_line in text.splitlines()[:30]]
    candidates = [line for line in lines if 4 <= len(line) <= 44 and not _HEADER_NOISE.search(line)]
    for line in candidates:
        if _CHAPTER_RE.match(line):
            return line
    for line in candidates:
        if _HEADING_RE.search(line):
            return line
    if candidates:
        return candidates[0]
    suffix = f"第{page_start}页" if page_start == page_end else f"第{page_start}-{page_end}页"
    return f"{suffix}知识单元"


def build_units(
    pages: list[ParsedPage],
    target_chars: int = 2400,
    max_chars: int = 3600,
) -> list[UnitDraft]:
    units: list[UnitDraft] = []
    current: list[str] = []
    current_len = 0
    page_start = 1
    page_end = 1

    def flush() -> None:
        nonlocal current, current_len, page_start, page_end
        body = "\n\n".join(current).strip()
        if not body:
            current = []
            current_len = 0
            return
        units.append(
            UnitDraft(
                id=str(uuid4()),
                title=_title_from_text(body, page_start, page_end),
                body=body,
                page_start=page_start,
                page_end=page_end,
                objective_type=_objective_type(body),
            )
        )
        current = []
        current_len = 0

    for page in pages:
        paragraphs = _paragraphs(page)
        for paragraph in paragraphs:
            if not current:
                page_start = page.page_number
            projected = current_len + len(paragraph) + 2
            if current and projected > max_chars:
                flush()
                page_start = page.page_number
            current.append(paragraph)
            current_len += len(paragraph) + 2
            page_end = page.page_number
            if current_len >= target_chars and re.search(r"[。！？；]$", paragraph):
                flush()
    flush()

    if not units and pages:
        text = "\n\n".join(page.text for page in pages if page.text).strip()
        if text:
            units.append(
                UnitDraft(
                    id=str(uuid4()),
                    title=_title_from_text(text, 1, pages[-1].page_number),
                    body=text,
                    page_start=1,
                    page_end=pages[-1].page_number,
                    objective_type=_objective_type(text),
                )
            )
    return units
