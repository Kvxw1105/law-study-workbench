"""句子切分与挖空质量回归测试：换行/分号不当句界、水印过滤。

背景：真实走查发现挖空卡“2.民事习惯要成为民法的渊源，必须具备的条件”
被 \n+ 与分号切碎成半句（条件列举 (1)(2)(3) 全部丢失），且版权水印
（“正版资料，请注意加入会员群 内部讲义，请勿盗印”）混入挖空上下文。
"""
from __future__ import annotations

from app.services.retrieval import (
    _WATERMARK,
    generate_retrieval_items,
    split_sentences,
)

CONDITIONS_BODY = (
    "2.民事习惯要成为民法的渊源，必须具备的条件\n"
    "(1)须能证明有习惯的存在；\n"
    "(2)须对有关问题成文法无明文规定；\n"
    "(3)须不违反民法基本原则、不损害社会公共利益。"
)


class TestSentenceBoundary:
    def test_numbered_list_not_split_at_newline_or_semicolon(self):
        sentences = split_sentences(CONDITIONS_BODY)
        hit = [s for s in sentences if "民事习惯要成为民法的渊源" in s]
        assert hit, "编号列举句应作为一个完整句子保留"
        assert "(3)须不违反" in hit[0], "条件 (3) 不应被分号切走"

    def test_sentence_without_final_punct_stays_whole(self):
        body = "本节理解难度不大，多属于记忆性知识点，往年真题多以论述题形式出现。"
        sentences = split_sentences(body)
        assert len(sentences) == 1


class TestWatermarkFilter:
    def test_watermark_pattern_matches_known_noise(self):
        assert _WATERMARK.search("正版资料，请注意加入会员群 内部讲义，请勿盗印")
        assert _WATERMARK.search("内部讲义，请勿盗印")

    def test_watermark_sentence_excluded_from_cloze(self):
        body = (
            "习惯法作为民法的间接渊源，需要经过国家的认可。"
            "这些也属正版资料，请注意加入会员群 第6页 内部讲义，请勿盗印，例如产品质量法中关于瑕疵担保责任的规定。"
            "法理通过法学的系统研究形成，拥有强大的解释力。"
        )
        drafts = generate_retrieval_items(title="民法的渊源", body=body, item_types=["cloze"], max_per_type=3)
        for draft in drafts:
            assert "正版资料" not in draft.prompt
            assert "盗印" not in draft.prompt
            assert "会员群" not in draft.prompt


class TestClozeWithFullContext:
    def test_cloze_keeps_full_condition_list(self):
        body = (
            "本节理解难度不大。"
            + CONDITIONS_BODY
            + "可见，民事习惯成为渊源有严格的门槛。"
        )
        drafts = generate_retrieval_items(title="民法的渊源", body=body, item_types=["cloze"], max_per_type=3)
        cloze = [d for d in drafts if "____" in d.prompt]
        assert cloze, "no cloze generated"
        # 只有编号句（“2.民事习惯…”）的卡片必须保留 (1)(2)(3) 完整列举；
        # “可见，民事习惯成为____”这类后续句不含条件列表，不应误判。
        for draft in cloze:
            if draft.prompt.startswith("填空：2.民事习惯"):
                assert "(1)须能证明" in draft.prompt
                assert "(3)须不违反" in draft.prompt
