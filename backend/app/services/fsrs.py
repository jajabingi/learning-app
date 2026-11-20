"""FSRS-4.5 spaced-repetition scheduler (Free Spaced Repetition Scheduler).

Memory model per card: Stability S (days for retrievability to fall to 90%) and Difficulty D (1..10).
Retrievability: R(t, S) = (1 + FACTOR * t / S) ** DECAY, with t = days since last review.
Reference: https://github.com/open-spaced-repetition/fsrs4anki (default 4.5 weights).

Ratings: 1 Again, 2 Hard, 3 Good, 4 Easy.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

AGAIN, HARD, GOOD, EASY = 1, 2, 3, 4

W = [0.4872, 1.4003, 3.7145, 13.8206, 5.1618, 1.2298, 0.8975, 0.031, 1.6474,
     0.1367, 1.0461, 2.1072, 0.0793, 0.3246, 1.587, 0.2272, 2.8755]
DECAY = -0.5
FACTOR = 19 / 81  # chosen so that R(S, S) = 0.9
MAX_INTERVAL = 36500
LEARNING_STEP = timedelta(minutes=10)  # "Again" is re-shown after 10 minutes, not days later
MASTERY_STABILITY_DAYS = 21.0
MASTERY_MIN_RETRIEVABILITY = 0.85


@dataclass
class CardState:
    state: str  # new | learning | review | relearning
    stability: float
    difficulty: float
    reps: int
    lapses: int
    last_review_at: datetime | None


@dataclass
class Result:
    state: str
    stability: float
    difficulty: float
    reps: int
    lapses: int
    due_at: datetime
    scheduled_days: float
    elapsed_days: float
    retrievability_before: float | None


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def retrievability(elapsed_days: float, stability: float) -> float:
    if stability <= 0:
        return 0.0
    return (1 + FACTOR * max(elapsed_days, 0.0) / stability) ** DECAY


def next_interval(stability: float, desired_retention: float) -> int:
    ivl = stability / FACTOR * (desired_retention ** (1 / DECAY) - 1)
    return int(clamp(round(ivl), 1, MAX_INTERVAL))


def _init_stability(rating: int) -> float:
    return max(W[rating - 1], 0.1)


def _init_difficulty(rating: int) -> float:
    return clamp(W[4] - W[5] * (rating - 3), 1.0, 10.0)


def _next_difficulty(d: float, rating: int) -> float:
    d1 = d - W[6] * (rating - 3)
    # mean reversion toward the "Good" initial difficulty prevents difficulty hell
    return clamp(W[7] * _init_difficulty(3) + (1 - W[7]) * d1, 1.0, 10.0)


def _recall_stability(d: float, s: float, r: float, rating: int) -> float:
    hard = W[15] if rating == HARD else 1.0
    easy = W[16] if rating == EASY else 1.0
    return s * (1 + math.exp(W[8]) * (11 - d) * s ** -W[9] * (math.exp(W[10] * (1 - r)) - 1) * hard * easy)


def _forget_stability(d: float, s: float, r: float) -> float:
    new = W[11] * d ** -W[12] * ((s + 1) ** W[13] - 1) * math.exp(W[14] * (1 - r))
    return min(new, s)


def review(card: CardState, rating: int, now: datetime, desired_retention: float = 0.9) -> Result:
    if rating not in (AGAIN, HARD, GOOD, EASY):
        raise ValueError("rating must be 1..4")

    if card.state == "new" or card.last_review_at is None or card.stability <= 0:
        s, d = _init_stability(rating), _init_difficulty(rating)
        reps, lapses = card.reps + 1, card.lapses
        elapsed, r = 0.0, None
        new_state = "learning" if rating == AGAIN else "review"
    else:
        elapsed = max((now - card.last_review_at).total_seconds() / 86400, 0.0)
        r = retrievability(elapsed, card.stability)
        d = _next_difficulty(card.difficulty, rating)
        reps, lapses = card.reps + 1, card.lapses
        if rating == AGAIN:
            s = _forget_stability(card.difficulty, card.stability, r)
            lapses += 1
            new_state = "relearning"
        else:
            s = _recall_stability(card.difficulty, card.stability, r, rating)
            new_state = "review"
    s = clamp(s, 0.1, MAX_INTERVAL)

    if rating == AGAIN:
        due, days = now + LEARNING_STEP, LEARNING_STEP.total_seconds() / 86400
    else:
        days = next_interval(s, desired_retention)
        due = now + timedelta(days=days)
    return Result(new_state, s, d, reps, lapses, due, float(days), elapsed, r)


def preview_intervals(card: CardState, now: datetime, desired_retention: float = 0.9) -> dict[int, float]:
    """Days until next review for each possible rating (shown on the rating buttons)."""
    return {r: review(card, r, now, desired_retention).scheduled_days for r in (AGAIN, HARD, GOOD, EASY)}


def current_retrievability(card_stability: float, last_review_at: datetime | None, now: datetime) -> float | None:
    if last_review_at is None or card_stability <= 0:
        return None
    return retrievability((now - last_review_at).total_seconds() / 86400, card_stability)


def derive_status(state: str, stability: float, last_review_at: datetime | None, suspended: bool,
                  now: datetime) -> str:
    """Learning status. 'mastered' is never permanent: it is recomputed from current retrievability,
    so a mastered question that has been left alone for too long falls back to 'reviewing'."""
    if suspended:
        return "suspended"
    if state == "new":
        return "new"
    if state in ("learning", "relearning"):
        return "learning"
    r = current_retrievability(stability, last_review_at, now)
    if stability >= MASTERY_STABILITY_DAYS and r is not None and r >= MASTERY_MIN_RETRIEVABILITY:
        return "mastered"
    return "reviewing"


def mastery_score(state: str, stability: float, last_review_at: datetime | None, now: datetime) -> float:
    """0..1 estimate of how well a question is currently known: current recall probability scaled by
    how mature the memory is (stability / 21 days, capped at 1). Never-reviewed questions score 0."""
    if state == "new":
        return 0.0
    r = current_retrievability(stability, last_review_at, now) or 0.0
    return r * min(1.0, stability / MASTERY_STABILITY_DAYS)
