from app.scoring.batch import BatchScoringSummary


def test_batch_scoring_summary_score_events_defaults_to_empty_tuple() -> None:
    summary = BatchScoringSummary(scored=0, skipped=0, failed=0)
    assert summary.score_events == ()
