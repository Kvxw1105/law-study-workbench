from app.services.scorer import LocalEvidenceScorer, ScoreRequest, evidence_weight


SOURCE = """
善意取得应当具备下列条件：处分人为无处分权人；受让人受让该财产时是善意；以合理价格转让；依法应当登记的已经登记，不需要登记的已经交付。受让人取得所有权后，原所有权人有权向无处分权人请求损害赔偿。
"""


def request(answer: str, confidence: int = 70, hint_level: int = 0) -> ScoreRequest:
    return ScoreRequest(
        unit_title="善意取得的构成要件",
        source_text=SOURCE,
        page_start=12,
        page_end=13,
        answer_text=answer,
        confidence=confidence,
        hint_level=hint_level,
        previous_errors=[],
    )


def test_local_scorer_rewards_source_coverage():
    scorer = LocalEvidenceScorer()
    strong = scorer.score(
        request("善意取得要求处分人无处分权，受让人在受让时善意，以合理价格受让，并完成登记或者交付。原权利人可向无处分权人主张赔偿。")
    )
    weak = scorer.score(request("善意取得就是受让人可以取得所有权。"))
    assert strong.score > weak.score
    assert strong.evidence
    assert weak.missing_points


def test_hint_levels_reduce_evidence_weight():
    assert evidence_weight(0) == 1.0
    assert evidence_weight(1) == 0.75
    assert evidence_weight(2) == 0.45
