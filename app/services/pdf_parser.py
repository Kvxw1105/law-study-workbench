from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from uuid import uuid4

import fitz


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
    return text.strip()


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


def _title_from_text(text: str, page_start: int, page_end: int) -> str:
    first_line = re.split(r"[\n。！？；]", text.strip())[0].strip(" ：:、")
    first_line = re.sub(r"\s+", " ", first_line)
    if 4 <= len(first_line) <= 44:
        return first_line
    suffix = f"第{page_start}页" if page_start == page_end else f"第{page_start}-{page_end}页"
    return f"{suffix}知识单元"


def build_units(
    pages: list[ParsedPage],
    target_chars: int = 1000,
    max_chars: int = 1600,
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
