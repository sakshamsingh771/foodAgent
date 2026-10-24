"""Recovery engine: pure, deterministic, side-effect free.

Inputs   : lot facts, candidate recipients, constraints (pickup delay, handover buffer, exclusions)
Output   : one RungOption per rung (R1..R4) + recommended / hedge selection.

Methods used (labelled in the UI):
  RULE        eligibility (time feasibility, product flags, evidence threshold)
  STATISTICAL acceptance probability = recipient's historical acceptance rate (from stored history)
  SIMULATED   anything produced via `simulate()` with user-supplied what-if inputs

There is NO machine-learning model here. Output is decision support: a human must approve.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta

RUNGS = ["R1", "R2", "R3", "R4"]
RUNG_LABELS = {
    "R1": "Donation",
    "R2": "Food-grade secondary buyer",
    "R3": "Animal feed",
    "R4": "Biogas / Compost",
}
# value weight used only to compare expected outcomes when no rung clears the confidence bar
VALUE_WEIGHT = {"R1": 1.0, "R2": 0.7, "R3": 0.4, "R4": 0.15}
YIELD = {"R1": 0.95, "R2": 0.9, "R3": 1.0, "R4": 1.0}
TRANSIT_MIN = {"R1": 40, "R2": 45, "R3": 60, "R4": 60}
MIN_EVIDENCE = {"R1": 0.34, "R2": 0.34, "R3": 0.0, "R4": 0.0}
CONFIDENCE_BAR = 0.5
R4_FIXED_ACCEPTANCE = 0.97  # contracted biogas offtake, a rule constant (not learned)
HUMAN_REVIEW_RUNGS = {"R1", "R2"}  # human-consumption pathways need a food-safety review step


@dataclass
class LotInput:
    quantity_kg: float
    remaining_minutes: int
    freshness_percent: float
    human_grade_eligible: bool = True
    feed_eligible: bool = True
    evidence_score: float = 0.0  # 0..1, share of required evidence kinds present


@dataclass
class RecipientInput:
    id: str
    name: str
    kind: str
    accepts_rungs: list[str]
    acceptance_rate: float
    distance_km: float
    capacity_kg: float


@dataclass
class Constraints:
    pickup_delay_min: int = 30
    handover_buffer_min: int = 20
    excluded_rungs: list[str] = field(default_factory=list)
    excluded_recipients: list[str] = field(default_factory=list)


@dataclass
class RungOption:
    rung: str
    eligible: bool
    reason: str
    p_success: float = 0.0
    confidence: float = 0.0
    est_recovery_kg: float = 0.0
    recipient_id: str | None = None
    recipient_name: str | None = None
    method: str = "RULE"
    requires_food_safety_review: bool = False
    factors: dict = field(default_factory=dict)
    is_recommended: bool = False
    is_hedge: bool = False


def _needed_minutes(rung: str, c: Constraints, distance_km: float) -> int:
    return int(c.pickup_delay_min + c.handover_buffer_min + TRANSIT_MIN[rung] + distance_km * 0.8)


def _pick_recipient(rung: str, lot: LotInput, recipients: list[RecipientInput], c: Constraints):
    pool = [r for r in recipients if rung in r.accepts_rungs and r.id not in c.excluded_recipients]
    if not pool:
        return None
    return max(pool, key=lambda r: r.acceptance_rate * min(1.0, r.capacity_kg / max(lot.quantity_kg, 1)) / (1 + r.distance_km / 50))


def evaluate_rung(rung: str, lot: LotInput, recipients: list[RecipientInput], c: Constraints) -> RungOption:
    label = RUNG_LABELS[rung]
    review = rung in HUMAN_REVIEW_RUNGS
    if rung in c.excluded_rungs:
        return RungOption(rung, False, f"{label} was ruled out earlier in this case.", requires_food_safety_review=review)
    if rung in ("R1", "R2") and not lot.human_grade_eligible:
        return RungOption(rung, False, "This product is not flagged as eligible for human consumption.", requires_food_safety_review=review)
    if rung == "R3" and not lot.feed_eligible:
        return RungOption(rung, False, "This product is not flagged as eligible for animal feed.", requires_food_safety_review=review)
    if lot.evidence_score < MIN_EVIDENCE[rung]:
        return RungOption(rung, False, "More condition evidence (photo, temperature log, label) is needed for this pathway.", requires_food_safety_review=review)

    recipient = _pick_recipient(rung, lot, recipients, c)
    if recipient is None and rung != "R4":
        return RungOption(rung, False, "No available recipient accepts this pathway right now.", requires_food_safety_review=review)
    distance = recipient.distance_km if recipient else 15.0
    needed = _needed_minutes(rung, c, distance)
    margin = lot.remaining_minutes - needed
    if margin < 0:
        return RungOption(
            rung, False,
            f"Not enough time: needs about {needed} min for pickup, transit and handover, {lot.remaining_minutes} min remain.",
            requires_food_safety_review=review, factors={"needed_minutes": needed, "margin_minutes": margin},
        )

    acceptance = recipient.acceptance_rate if recipient else R4_FIXED_ACCEPTANCE
    if rung == "R4":
        acceptance = R4_FIXED_ACCEPTANCE
    time_factor = 0.55 + 0.45 * (1 - math.exp(-margin / 120))
    pct = lot.freshness_percent / 100
    fresh_factor = {"R1": 0.6 + 0.4 * pct, "R2": 0.6 + 0.4 * pct, "R3": 0.8 + 0.2 * pct, "R4": 1.0}[rung]
    evid_factor = (0.5 + 0.5 * lot.evidence_score) if rung in ("R1", "R2") else 1.0
    p = max(0.0, min(0.99, acceptance * time_factor * fresh_factor * evid_factor))
    qty = min(lot.quantity_kg, recipient.capacity_kg) if recipient else lot.quantity_kg
    method = "STATISTICAL" if rung != "R4" else "RULE"
    return RungOption(
        rung=rung, eligible=True,
        reason=f"Fits the time window with {margin} min to spare" + (f"; {recipient.name} accepted {round(acceptance*100)}% of past offers." if recipient and rung != "R4" else "."),
        p_success=round(p, 3), confidence=round(p, 3),
        est_recovery_kg=round(qty * YIELD[rung] * p, 1),
        recipient_id=recipient.id if recipient else None, recipient_name=recipient.name if recipient else None,
        method=method, requires_food_safety_review=review,
        factors={
            "acceptance": round(acceptance, 3), "time_factor": round(time_factor, 3),
            "freshness_factor": round(fresh_factor, 3), "evidence_factor": round(evid_factor, 3),
            "needed_minutes": needed, "margin_minutes": margin, "distance_km": distance,
        },
    )


def plan(lot: LotInput, recipients: list[RecipientInput], c: Constraints) -> list[RungOption]:
    options = [evaluate_rung(r, lot, recipients, c) for r in RUNGS]
    eligible = [o for o in options if o.eligible]
    if not eligible:
        return options
    # highest appropriate rung that clears the confidence bar, else best expected value
    clear = [o for o in eligible if o.p_success >= CONFIDENCE_BAR]
    if clear:
        rec = min(clear, key=lambda o: RUNGS.index(o.rung))
    else:
        rec = max(eligible, key=lambda o: VALUE_WEIGHT[o.rung] * o.est_recovery_kg)
    rec.is_recommended = True
    others = [o for o in eligible if o is not rec]
    if others:
        # hedge: the most reliable alternative that is not the recommendation
        hedge = max(others, key=lambda o: (o.p_success, -RUNGS.index(o.rung)))
        hedge.is_hedge = True
    return options


def simulate(
    lot: LotInput, recipients: list[RecipientInput], *, pickup_delay_min: int, acceptance_prob: float,
    handover_buffer_min: int, remaining_minutes: int, now: datetime,
) -> dict:
    """What-if: override time and acceptance inputs. All outputs are SIMULATED, not guaranteed."""
    sim_lot = LotInput(**{**lot.__dict__, "remaining_minutes": remaining_minutes})
    uniform = [
        RecipientInput(
            id=f"sim-{r}", name=f"Modelled {RUNG_LABELS[r].lower()} recipient", kind="sim",
            accepts_rungs=[r], acceptance_rate=acceptance_prob, distance_km=10.0, capacity_kg=max(lot.quantity_kg, 1),
        )
        for r in ("R1", "R2", "R3")
    ]
    c = Constraints(pickup_delay_min=pickup_delay_min, handover_buffer_min=handover_buffer_min)
    options = plan(sim_lot, uniform, c)
    for o in options:
        o.method = "SIMULATED"
        if o.rung == "R4":
            o.p_success = o.confidence = round(max(0.0, o.p_success), 3)
    rec = next((o for o in options if o.is_recommended), None)
    hedge = next((o for o in options if o.is_hedge), None)
    deadline = now + timedelta(minutes=max(remaining_minutes - handover_buffer_min, 0))
    return {
        "simulated": True,
        "p_success": rec.p_success if rec else 0.0,
        "recommended": rec,
        "hedge": hedge,
        "deadline": deadline,
        "expected_recovery_kg": rec.est_recovery_kg if rec else 0.0,
        "options": options,
    }
