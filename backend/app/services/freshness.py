"""Freshness window calculation. Method: RULE (deterministic, time-based).

This is a recovery-window indicator derived from the lot's recorded safe-until time.
It is NOT a food-safety certification.
"""
from dataclasses import dataclass
from datetime import datetime

SAFE, ACT_SOON, LOSS_IMMINENT = "SAFE", "ACT_SOON", "LOSS_IMMINENT"
LOSS_PCT, ACT_PCT = 15.0, 40.0
LOSS_MIN, ACT_MIN = 90, 240


@dataclass(frozen=True)
class Freshness:
    remaining_minutes: int
    percent: float
    state: str


def assess(safe_until: datetime, window_minutes: int, now: datetime) -> Freshness:
    remaining = int((safe_until - now).total_seconds() // 60)
    remaining_clamped = max(remaining, 0)
    pct = 0.0 if window_minutes <= 0 else max(0.0, min(100.0, remaining_clamped / window_minutes * 100))
    if remaining < LOSS_MIN or pct < LOSS_PCT:
        state = LOSS_IMMINENT
    elif remaining < ACT_MIN or pct < ACT_PCT:
        state = ACT_SOON
    else:
        state = SAFE
    return Freshness(remaining_clamped, round(pct, 1), state)


def at_risk(state: str) -> bool:
    return state != SAFE
