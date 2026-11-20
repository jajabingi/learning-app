from datetime import datetime, timedelta, timezone

from app.services import fsrs

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
NEW = fsrs.CardState("new", 0, 0, 0, 0, None)


def test_retrievability_is_90_percent_at_stability():
    assert abs(fsrs.retrievability(10, 10) - 0.9) < 1e-9


def test_interval_matches_stability_at_default_retention():
    assert fsrs.next_interval(10, 0.9) == 10
    assert fsrs.next_interval(10, 0.8) > 10  # lower retention target => longer interval


def test_first_review_ratings_order():
    ivl = {r: fsrs.review(NEW, r, NOW).scheduled_days for r in (1, 2, 3, 4)}
    assert ivl[1] < 1 <= ivl[2] <= ivl[3] < ivl[4]


def test_again_on_new_stays_learning_and_due_in_minutes():
    r = fsrs.review(NEW, 1, NOW)
    assert r.state == "learning" and r.due_at - NOW == timedelta(minutes=10)


def _card_after(rating, wait_days):
    first = fsrs.review(NEW, 3, NOW)
    card = fsrs.CardState("review", first.stability, first.difficulty, 1, 0, NOW)
    return card, fsrs.review(card, rating, NOW + timedelta(days=wait_days))


def test_successful_recall_grows_stability_and_again_shrinks_it():
    card, good = _card_after(3, 4)
    _, again = _card_after(1, 4)
    assert good.stability > card.stability
    assert again.stability < card.stability and again.lapses == 1 and again.state == "relearning"


def test_easy_beats_good_beats_hard():
    s = {r: _card_after(r, 4)[1].stability for r in (2, 3, 4)}
    assert s[2] < s[3] < s[4]


def test_later_review_increases_stability_more():
    assert _card_after(3, 10)[1].stability > _card_after(3, 2)[1].stability


def test_difficulty_stays_in_bounds():
    card = fsrs.CardState("review", 5, 9.9, 3, 0, NOW)
    for _ in range(20):
        res = fsrs.review(card, 1, NOW + timedelta(days=1))
        assert 1 <= res.difficulty <= 10
        card = fsrs.CardState("relearning", res.stability, res.difficulty, res.reps, res.lapses, NOW)


def test_mastered_is_not_permanent():
    last = NOW
    assert fsrs.derive_status("review", 30, last, False, NOW + timedelta(days=1)) == "mastered"
    assert fsrs.derive_status("review", 30, last, False, NOW + timedelta(days=400)) == "reviewing"
    assert fsrs.derive_status("review", 30, last, True, NOW) == "suspended"
    assert fsrs.derive_status("new", 0, None, False, NOW) == "new"
