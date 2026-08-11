"""挖空/闪卡质量升级回归测试：多空、段落上下文、素材分流、模板库、多空评分。

覆盖 UX_GAP_ANALYSIS.md 的 P0/P1 改进：挖空与闪卡语义区分、
划选建卡（手动建卡多空）、挖空带段落上下文、闪卡提问多样化。
"""
from __future__ import annotations

from app.services.retrieval import (
    ANSWER_SEP,
    _flashcard_prompt,
    find_cloze_span,
    find_cloze_spans,
    generate_retrieval_items,
    grade_cloze,
)

BODY = (
    "物权是权利人依法对特定的物享有直接支配和排他的权利。"
    "善意取得应当具备下列条件：(1)处分人为无处分权人；(2)受让人受让时是善意的；(3)以合理价格转让。"
    "动产物权变动区别于不动产物权变动：动产以交付为生效要件，不动产以登记为生效要件。"
    "确立这一规则的意义在于保障交易安全，保护善意第三人的合理信赖。"
)


class TestMultiSpanCloze:
    def test_cloze_can_blank_multiple_spans(self):
        drafts = generate_retrieval_items(title="物权编", body=BODY, item_types=["cloze"], max_per_type=3)
        cloze = [d for d in drafts if d.item_type == "cloze"]
        assert cloze, "no cloze generated"
        assert any(d.answer.count(ANSWER_SEP) >= 1 for d in cloze), "expected at least one multi-blank cloze"

    def test_blank_order_matches_answer_order(self):
        drafts = generate_retrieval_items(title="物权编", body=BODY, item_types=["cloze"], max_per_type=3)
        for draft in drafts:
            if draft.item_type != "cloze" or ANSWER_SEP not in draft.answer:
                continue
            spans = draft.answer.split(ANSWER_SEP)
            # 每个空在 prompt 中的相对位置应与其答案在正文中的位置顺序一致
            text = draft.prompt.replace("填空：", "")
            last_blank = -1
            for span in spans:
                pos = text.find(span)
                blank_pos = text.find("____", last_blank + 1)
                assert blank_pos > last_blank, "blank order mismatch"
                if pos != -1:
                    assert pos >= last_blank
                last_blank = blank_pos

    def test_no_half_word_span(self):
        # “权人/权利人”处不应截出“物权是权”“无处分权”这类半截词
        spans = find_cloze_spans("物权是权利人依法对特定的物享有直接支配和排他的权利。", "物权编")
        for span in spans:
            assert not any(marker in span for marker in ("是", "为")), f"half-word span: {span}"
            assert span in "物权是权利人依法对特定的物享有直接支配和排他的权利。"


class TestContextWindow:
    def test_source_excerpt_has_context(self):
        drafts = generate_retrieval_items(title="物权编", body=BODY, item_types=["cloze"], max_per_type=3)
        for draft in drafts:
            if draft.item_type == "cloze":
                assert draft.source_excerpt != draft.prompt.replace("填空：", "").replace("____", draft.answer.split(ANSWER_SEP)[0]), "excerpt should carry context"
                assert len(draft.source_excerpt) >= 20, "excerpt too short"

    def test_excerpt_marks_truncation(self):
        long_body = ("物权是权利人依法对特定的物享有直接支配和排他的权利。" * 6) + BODY
        drafts = generate_retrieval_items(title="物权编", body=long_body, item_types=["cloze"], max_per_type=1)
        assert drafts, "no draft"
        assert "……" in drafts[0].source_excerpt, "long body should be truncated with ……"


class TestPoolSplit:
    def test_same_sentence_not_both_types(self):
        # 同一素材句不应既被挖空又被闪卡（视角重复）
        cloze = generate_retrieval_items(title="物权编", body=BODY, item_types=["cloze"], max_per_type=5)
        flash = generate_retrieval_items(title="物权编", body=BODY, item_types=["flashcard"], max_per_type=5)
        cloze_sentences = {d.prompt.replace("填空：", "") for d in cloze}
        flash_excerpts = {d.answer for d in flash}
        # 挖空 prompt 与闪卡答案不应完全重叠（“请闭卷复述”总览卡除外）
        overlaps = cloze_sentences & flash_excerpts
        assert len(overlaps) <= 0, f"duplicate source perspective: {overlaps}"

    def test_logic_sentence_goes_to_flashcard(self):
        drafts = generate_retrieval_items(title="物权编", body=BODY, item_types=["flashcard"], max_per_type=5)
        prompts = [d.prompt for d in drafts]
        assert any("区别" in p or "意义" in p for p in prompts), "logic sentences should produce differentiated prompts"


class TestFlashcardTemplates:
    def test_definition_template(self):
        prompt = _flashcard_prompt("民法", "善意取得是指受让人善意取得动产或不动产所有权的制度。", 0)
        assert prompt.startswith("什么是"), prompt

    def test_requirement_template(self):
        prompt = _flashcard_prompt("民法", "善意取得应当具备下列条件，包括处分要件和善意要件。", 1)
        assert "要件" in prompt, prompt

    def test_basis_template(self):
        prompt = _flashcard_prompt("民法", "民事习惯要成为民法的渊源，须依据法律规定经国家认可。", 2)
        assert "依据" in prompt or "条件" in prompt, prompt

    def test_fallback_does_not_paste_source(self):
        prompt = _flashcard_prompt("民法", "习惯产生于长时间的反复实践，源于主体的自发性创造，属于所谓的自发性秩序。", 3)
        assert "用自己的话复述" in prompt, prompt
        assert "自发性秩序" not in prompt.split("：")[1][:6] if "：" in prompt else True


class TestGradeMultiCloze:
    def test_all_correct(self):
        expected = f"无处分权人{ANSWER_SEP}善意的"
        grade = grade_cloze(expected, expected)
        assert grade.score == 100.0 and grade.rating == "good" and grade.correct

    def test_partial(self):
        expected = f"无处分权人{ANSWER_SEP}善意的"
        grade = grade_cloze(f"无处分权人{ANSWER_SEP}恶意的", expected)
        assert grade.score < 100 and grade.rating != "good"

    def test_all_wrong(self):
        expected = f"无处分权人{ANSWER_SEP}善意的"
        grade = grade_cloze(f"有权处分{ANSWER_SEP}恶意的", expected)
        assert grade.rating == "again" and not grade.correct

    def test_critical_conflict_flagged(self):
        expected = f"无处分权人{ANSWER_SEP}善意的"
        grade = grade_cloze(f"无处分权人{ANSWER_SEP}恶意", expected)
        assert grade.critical_mismatches, "善恶意冲突必须被标记"


class TestSingleSpanCompat:
    def test_find_cloze_span_still_works(self):
        span = find_cloze_span("善意取得是指受让人善意取得动产所有权的制度。", "善意取得")
        assert span and span in "善意取得是指受让人善意取得动产所有权的制度。"

    def test_single_blank_cloze_grades(self):
        grade = grade_cloze("交付", "交付")
        assert grade.correct and grade.score == 100.0


# ---- 本地算法优化回归（纯本地、零云端约束下的启发式最强形态）----

from app.services.retrieval import (
    _flashcard_prompt,
    _sentence_score,
    find_cloze_spans,
    grade_cloze,
    important_sentences,
    _split_pools,
)


class TestSentenceScoring:
    def test_rule_law_period_sentences_score_higher(self):
        """规则句（情态+后果）、法条句、期限句应比普通叙述句更值得出题。"""
        rule = "民事主体因同一行为应当承担民事责任、行政责任和刑事责任的，承担行政责任或者刑事责任不影响承担民事责任。"
        law = "《民法典》第187条规定：民事主体因同一行为应当承担民事责任、行政责任和刑事责任的，承担行政责任或者刑事责任不影响承担民事责任。"
        period = "相对人可以催告被代理人自收到通知之日起三十日内予以追认。"
        plain = "本节理解难度不大，往年以判断题的形式考察过。"
        assert _sentence_score(rule, 0) > _sentence_score(plain, 0)
        assert _sentence_score(law, 0) > _sentence_score(plain, 0)
        assert _sentence_score(period, 0) > _sentence_score(plain, 0)

    def test_important_sentences_skip_watermark_toc_lines(self):
        body = (
            "第一节 民法的渊源\n"
            "正版资料，请注意加入会员群 第15页 内部讲义，请勿盗印\n"
            "实质渊源是指法律作为以暴力为后盾的公共规则体系，获得社会认可从而得以实施的信仰基础。"
            "形式渊源是社会公认的法的创立方式，以及借以表明法律规范产生效力的表现形式。"
            "习惯产生于长时间的反复实践，源于主体的自发性创造，属于所谓的自发性秩序。"
            "民事习惯要成为民法的渊源，必须具备一定的条件。"
        )
        picked = important_sentences(body, limit=3)
        assert picked
        # 水印行会被剔除；标题行评分为负，正文句足够时不会占用名额
        assert all("正版资料" not in s and "盗印" not in s and "会员群" not in s for s in picked), picked
        assert all("第一节" not in s for s in picked), picked
        assert any("实质渊源" in s for s in picked)


class TestPoolSplitRefined:
    def test_classify_sentence_goes_to_flashcard(self):
        """分类枚举句（分为/种类/包括A、B、C）→ 闪卡池，与“分为哪几类”模板配对。"""
        cloze_pool, flash_pool = _split_pools(["民事责任的形式分为停止侵害、排除妨碍、消除危险等类型。"])
        assert not cloze_pool
        assert flash_pool == ["民事责任的形式分为停止侵害、排除妨碍、消除危险等类型。"]

    def test_definition_and_rule_sentences_stay_cloze(self):
        cloze_pool, flash_pool = _split_pools([
            "善意取得是指受让人善意取得动产或不动产所有权的制度。",
            "处分人应当将标的物交付给受让人。",
        ])
        assert len(cloze_pool) == 2
        assert not flash_pool


class TestClozeSpanQuality:
    def test_period_span_candidate(self):
        spans = find_cloze_spans("相对人可以催告被代理人自收到通知之日起三十日内予以追认。", "追认")
        assert any("三十日" in span for span in spans), spans

    def test_modal_verb_leading_span_rejected(self):
        """以情态动词开头的短语（应当/不得/须…）不是知识点，不得作为挖空答案。"""
        spans = find_cloze_spans("处分人应当将标的物交付给受让人。", "交付")
        for span in spans:
            assert not span.startswith("应当"), span

    def test_spans_not_overlapping_context_words(self):
        spans = find_cloze_spans("2.民事习惯要成为民法的渊源，必须具备的条件 (1)须能证明有习惯的存在；", "民法的渊源")
        for span in spans:
            assert "条件 (1)" not in span, span
            assert len(span) <= 16, span


class TestFlashcardLawAndPeriodTemplates:
    def test_law_article_template(self):
        prompt = _flashcard_prompt("民法", "《民法典》第187条规定：民事主体因同一行为应当承担民事责任、行政责任和刑事责任的，承担行政责任或者刑事责任不影响承担民事责任。", 0)
        assert "《民法典》第187条" in prompt and "规定" in prompt, prompt

    def test_period_template(self):
        prompt = _flashcard_prompt("追认", "相对人可以催告被代理人自收到通知之日起三十日内予以追认。", 0)
        assert "期限" in prompt or "时间" in prompt, prompt


class TestSynonymGrading:
    def test_must_vs_shall_accepted(self):
        """“必须”与“应当”语义等价，评分应按正确处理。"""
        grade = grade_cloze("必须", "应当")
        assert grade.correct and grade.rating == "good"

    def test_synonym_mapping_does_not_break_exact(self):
        grade = grade_cloze("应当", "应当")
        assert grade.score == 100.0


class TestSpanUniqueness:
    def test_duplicated_span_skipped_not_leaking(self):
        """词在句中多次出现时不得挖空：残留的第二个词会泄漏答案（如“被担保债权”）。"""
        from app.services.retrieval import generate_retrieval_items
        body = "一般理论认为，被担保债权应是金钱债权，但非金钱债权在不能实现时，只要能转化为金钱债权，也可以作为被担保债权。"
        drafts = generate_retrieval_items(title="担保", body=body, item_types=["cloze"], max_per_type=2)
        for draft in drafts:
            for part in draft.answer.split(ANSWER_SEP):
                assert draft.prompt.count(part) == 0, f"残留泄漏: {part} in {draft.prompt}"

    def test_weak_topic_overview_rejected(self):
        from app.services.retrieval import _flashcard_topic
        assert _flashcard_topic("概述 1.类型一代理人在代理权限范围内为被代理人计算。") is None
