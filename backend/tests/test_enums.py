from domain.enums import FurthestStage, further_stage, stage_rank


def test_stage_order_is_strictly_increasing() -> None:
    stages = list(FurthestStage)
    ranks = [stage_rank(s) for s in FurthestStage]
    # every stage has a distinct rank
    assert len(set(ranks)) == len(stages)


def test_stage_order_matches_glossary() -> None:
    assert stage_rank(FurthestStage.STARTED) < stage_rank(FurthestStage.APPLIED)
    assert stage_rank(FurthestStage.APPLIED) < stage_rank(FurthestStage.ONLINE_ASSESSMENT)
    assert stage_rank(FurthestStage.ONLINE_ASSESSMENT) < stage_rank(FurthestStage.INTERVIEW)
    assert stage_rank(FurthestStage.INTERVIEW) < stage_rank(FurthestStage.FINAL_ROUND)
    assert stage_rank(FurthestStage.FINAL_ROUND) < stage_rank(FurthestStage.OFFER)


def test_further_stage_picks_the_more_advanced() -> None:
    assert further_stage(FurthestStage.APPLIED, FurthestStage.INTERVIEW) is FurthestStage.INTERVIEW
    assert further_stage(FurthestStage.INTERVIEW, FurthestStage.APPLIED) is FurthestStage.INTERVIEW
    assert further_stage(None, FurthestStage.APPLIED) is FurthestStage.APPLIED
    assert further_stage(FurthestStage.OFFER, None) is FurthestStage.OFFER
    assert further_stage(None, None) is None
