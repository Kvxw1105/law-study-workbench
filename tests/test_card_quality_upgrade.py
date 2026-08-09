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
