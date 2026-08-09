"""PDF 文本质量回归测试：CJK 跨行断字重组、标题智能提取、句子切分完整性。

背景：真实教材 PDF（“可搜索”文本层）把中文词拆在两行（如“两\\n\\n个”），
导致单元正文、挖空卡片、证据片段丢失行首/行尾字（如“两个必要条件”
变成“个必要条件”），对法律文本可能反转语义。本测试防止该问题回归。
"""
from __future__ import annotations

from app.services.pdf_parser import _title_from_text, normalize_page_text
from app.services.retrieval import generate_retrieval_items, split_sentences
from app.services.text_utils import rejoin_cjk_line_breaks


class TestRejoinCjkLineBreaks:
    def test_rejoin_single_newline(self):
        assert rejoin_cjk_line_breaks("有赖于两\n个必要条件") == "有赖于两个必要条件"

    def test_rejoin_double_newline(self):
        assert rejoin_cjk_line_breaks("有赖于两\n\n个必要条件") == "有赖于两个必要条件"

    def test_rejoin_no_space_when_leading_indent(self):
        # 段首缩进 = 段落分隔，不合并
        text = "基本法\n\n  本质上看"
        assert rejoin_cjk_line_breaks(text) == text

    def test_keep_paragraph_split_after_punctuation(self):
        text = "重点内容。\n\n【本节知识点详述】"
        assert rejoin_cjk_line_breaks(text) == text

    def test_keep_paragraph_split_number_lead(self):
        text = "民法是市场经济的基本法。\n\n一、民法是私法"
        assert rejoin_cjk_line_breaks(text) == text

    def test_rejoin_full_page_snippet(self):
        raw = (
            "而商品生产与交换有赖于两\n\n个必要条件：作为权利主体的人\n"
            "是自由的，作为权利主体的人应享有自主的财产权。"
        )
        result = rejoin_cjk_line_breaks(raw)
        assert "两个必要条件" in result
        assert "人是自由的" in result


class TestNormalizePageText:
    def test_breaks_rejoined_through_normalize(self):
        raw = "本质上看，……有赖于两\n\n个必要条件：作为权利主体的人是自由的。"
        assert "两个必要条件" in normalize_page_text(raw)


class TestTitleExtraction:
    def test_chapter_title_preferred(self):
        text = (
            "溏研毓秀 强化讲义：807专B方向一民法学(2025)\n\n"
            "【本节知识点详述】\n\n"
            "第二节 民法的性质\n\n"
            "本质上看，市场经济是围绕商品的生产与交换运行的。"
        )
        assert _title_from_text(text, 15, 15) == "第二节 民法的性质"

    def test_numbered_heading_preferred(self):
        text = "溏研毓秀 强化讲义：807专B方向一民法学(2025)\n\n三、民法的间接渊源\n\n正文开始……"
        assert _title_from_text(text, 16, 16) == "三、民法的间接渊源"

    def test_header_noise_not_used_as_title(self):
        text = "溏研毓秀 强化讲义：807专B方向一民法学(2025)\n\n(一)民法为何被称之为权利法\n\n1.从民法的体系上看：……"
        assert _title_from_text(text, 14, 14) == "(一)民法为何被称之为权利法"

    def test_fallback_first_content_line(self):
        text = "溏研毓秀 强化讲义：807专B方向一民法学(2025)\n\n从以下三个方面来理解平等原则：……"
        assert "强化讲义" not in _title_from_text(text, 25, 25)


class TestSentenceSplitting:
    def test_sentence_not_split_at_cjk_line_break(self):
        body = (
            "而商品生产与交换有赖于两\n\n个必要条件：作为权利主体的人是自由的，"
            "作为权利主体的人应享有自主的财产权。"
        )
        sentences = split_sentences(body)
        assert any("两个必要条件" in s for s in sentences)
        assert not any(s.startswith("个必要条件") for s in sentences)


class TestClozeContext:
    def test_cloze_keeps_leading_context(self):
        body = (
            "本质上看，市场经济是围绕商品的生产与交换运行的。"
            "而商品生产与交换有赖于两\n\n个必要条件：作为权利主体的人是自由的，"
            "作为权利主体的人应享有自主的财产权。"
        )
        drafts = generate_retrieval_items(
            title="第二节 民法的性质", body=body, item_types=["cloze"], max_per_type=2
        )
        cloze = [d for d in drafts if d.prompt.startswith("填空")]
        assert cloze, "no cloze generated"
        # 任何挖空 prompt 都不能再出现“个必要条件”这种丢字残句
        for draft in cloze:
            assert "两个必要条件" in draft.prompt or "个必要条件" not in draft.prompt
