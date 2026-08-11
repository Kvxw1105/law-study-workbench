"""句子级定位回归：跨换行句子必须命中。

真实场景：用户在 198 页真实教材中发现 8/37 卡片答案定位失败。根因是句子在
PDF 文本提取中跨换行（如“……获得社会认可从而得以实\\n施的信仰基础”），
PyMuPDF search_for 按整句精确匹配必然落空，前端只能回退到“只跳页不高亮”。

修复：search_text_rects 在精确匹配落空后，按 span 做空白归一化匹配，再映射回
span bbox（跨行句子会得到多行矩形）。本文件全部使用合成 PDF，无真实数据。
"""
from __future__ import annotations

import io
import re

import fitz
import pytest
from fastapi.testclient import TestClient

from app.services.pdf_parser import search_text_rects
from tests.support import make_pdf

# 故意加宽的句子：在窄 textbox 中必然跨两行
WRAPPED_SENTENCE = (
    "实质渊源是指法律作为以暴力为后盾的公共规则体系，"
    "获得社会认可从而得以实施的信仰基础。"
)


def _pdf_with_wrapped_sentence(text: str = WRAPPED_SENTENCE) -> bytes:
    """构造句子跨两行的单页 PDF（窄 textbox 自动换行）。"""
    document = fitz.open()
    page = document.new_page()
    page.insert_textbox(fitz.Rect(45, 55, 170, 300), text, fontsize=12, fontname="china-s")
    payload = document.tobytes()
    document.close()
    return payload


def test_premise_sentence_actually_wraps():
    """前提自检：该句在构造的 PDF 中确实跨了换行（精确 search_for 必落空）。"""
    document = fitz.open(stream=_pdf_with_wrapped_sentence(), filetype="pdf")
    try:
        page = document[0]
        # 跨行 → 整句精确匹配失败
        assert not page.search_for(WRAPPED_SENTENCE)
        # 但句子完整存在于页面文本中（归一化后）
        norm_page = re.sub(r"\s+", "", page.get_text("text"))
        norm_needle = re.sub(r"\s+", "", WRAPPED_SENTENCE)
        assert norm_needle in norm_page
    finally:
        document.close()


def test_wrapped_sentence_normalized_hits():
    """核心回归：跨行句子必须通过归一化回退命中，且返回矩形。"""
    document = fitz.open(stream=_pdf_with_wrapped_sentence(), filetype="pdf")
    try:
        page = document[0]
        rects = search_text_rects(page, WRAPPED_SENTENCE)
        assert rects, "跨行句子必须命中"
        for rect in rects:
            assert rect["x0"] < rect["x1"] and rect["y0"] < rect["y1"]
    finally:
        document.close()


def test_needle_with_embedded_newline_hits():
    """候选文本自身带换行/空格差异时同样命中（前端复制粘贴的文本常见）。"""
    document = fitz.open(stream=_pdf_with_wrapped_sentence(), filetype="pdf")
    try:
        page = document[0]
        noisy = "实质渊源是指法律作为\n 以暴力为后盾的公共规则体系，获得社会认可从而得以实施 的信仰基础。"
        assert search_text_rects(page, noisy)
    finally:
        document.close()


def test_single_line_exact_match_still_hits():
    """不跨行的短句仍走精确匹配（原有行为不回归）。"""
    document = fitz.open(stream=make_pdf(), filetype="pdf")
    try:
        page = document[0]
        rects = search_text_rects(page, "处分人为无处分权人")
        assert rects
    finally:
        document.close()


def test_absent_text_returns_none():
    document = fitz.open(stream=_pdf_with_wrapped_sentence(), filetype="pdf")
    try:
        page = document[0]
        assert search_text_rects(page, "这句文本根本不在 PDF 里。") is None
    finally:
        document.close()


def test_locate_api_wrapped_sentence_returns_page_and_rects(client: TestClient):
    """API 级回归：跨行句子的 /api/locate 必须 200 + 页码 + 矩形（不再 404）。"""
    response = client.post(
        "/api/sources/import?wait=true",
        files={"file": ("wrapped.pdf", io.BytesIO(_pdf_with_wrapped_sentence()), "application/pdf")},
    )
    assert response.status_code == 200, response.text
    source = response.json()["source"]

    located = client.get(
        "/api/locate",
        params={"source_id": source["id"], "text": WRAPPED_SENTENCE},
    )
    assert located.status_code == 200, located.text
    body = located.json()
    assert body["page"] == 1
    assert body["rects"], "跨行句子必须返回高亮矩形"


def test_locate_api_absent_text_404(client: TestClient):
    """真正不存在的文本仍 404（前端回退到页码定位，语义不变）。"""
    response = client.post(
        "/api/sources/import?wait=true",
        files={"file": ("wrapped.pdf", io.BytesIO(_pdf_with_wrapped_sentence()), "application/pdf")},
    )
    assert response.status_code == 200, response.text
    source = response.json()["source"]

    located = client.get(
        "/api/locate",
        params={"source_id": source["id"], "text": "这段文本完全不存在于该 PDF 中。"},
    )
    assert located.status_code == 404
