from app.scoring.events import GradeAEvent, publish_grade_a, subscribe, unsubscribe


def test_publish_delivers_to_a_subscribed_queue() -> None:
    queue = subscribe()
    try:
        event = GradeAEvent(score_id=1, offer_id=2, title="t", company="c")
        publish_grade_a(event)
        assert queue.get_nowait() == event
    finally:
        unsubscribe(queue)


def test_publish_delivers_to_multiple_subscribers() -> None:
    queue_a = subscribe()
    queue_b = subscribe()
    try:
        event = GradeAEvent(score_id=1, offer_id=2, title="t", company="c")
        publish_grade_a(event)
        assert queue_a.qsize() == 1
        assert queue_b.qsize() == 1
        assert queue_a.get_nowait() == event
        assert queue_b.get_nowait() == event
    finally:
        unsubscribe(queue_a)
        unsubscribe(queue_b)


def test_unsubscribe_stops_further_delivery() -> None:
    queue = subscribe()
    unsubscribe(queue)
    publish_grade_a(GradeAEvent(score_id=1, offer_id=2, title="t", company="c"))
    assert queue.empty() is True


def test_publish_with_no_subscribers_does_not_raise() -> None:
    publish_grade_a(GradeAEvent(score_id=1, offer_id=2, title="t", company="c"))
