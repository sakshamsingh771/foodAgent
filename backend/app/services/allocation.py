"""Multi-recipient allocation optimizer: pure, deterministic, side-effect free.

Extends `recovery_engine` (reuses its rung table, evidence thresholds and time model) rather than replacing it.
The single-recipient `recovery_engine.plan` stays as the BASELINE the benchmark compares against.

Problem solved
--------------
Given a lot of Q kg and candidate recipients i with remaining capacity cap_i and pathway rung r_i:

    HARD constraints (never traded against score)
      H1 product flags      R1/R2 need human_grade_eligible, R3 needs feed_eligible
      H2 safety evidence    evidence_score >= MIN_EVIDENCE[rung]; a lot marked unsafe may only go to R4
      H3 deadline           needed minutes (pickup delay + transit + handover buffer) <= remaining minutes
      H4 capacity           x_i <= cap_i
      H5 quantity           sum x_i <= Q   (never allocate the same kg twice)
      H6 exclusions         recipients/rungs excluded earlier in the case (e.g. already rejected this lot)
      H7 unit               everything is kilograms; non-finite / non-positive quantities are rejected

    OBJECTIVE (lexicographic)
      1. maximise total kg allocated                      -> min(Q, sum of feasible capacities), always reached
      2. maximise pathway value  sum VALUE_WEIGHT[r_i] * YIELD[r_i] * x_i   (human-consumption first)
      3. strategy tie-break (speed / distance / acceptance rate) and recipient id for determinism

Because capacities are independent and the value per kg is constant per recipient, this is a fractional-knapsack
LP; filling recipients in descending value density is exactly optimal for (1) then (2). No solver dependency needed.

What this is NOT: it does not use routing data (distance is the stored recipient distance, time is the engine's
existing heuristic) and acceptance_rate is a historical rate, not a calibrated probability. Both are labelled.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

from app.services import recovery_engine as eng

ENGINE_VERSION = "multi-alloc-v1"
EPS = 1e-6
STRATEGIES = ("max_recovery", "fastest", "lowest_distance", "lowest_risk", "non_human_pathway")
STRATEGY_LABELS = {
    "max_recovery": "Maximum feasible recovery (human-consumption pathways first)",
    "fastest": "Fastest feasible recovery",
    "lowest_distance": "Shortest distance (proxy for transport cost; no cost data is stored)",
    "lowest_risk": "Lowest operational risk (highest historical acceptance first)",
    "non_human_pathway": "Alternative pathway: feed / biogas only (when donation is unsuitable)",
}


@dataclass
class AllocLot:
    quantity_kg: float
    remaining_minutes: int
    freshness_percent: float = 100.0
    human_grade_eligible: bool = True
    feed_eligible: bool = True
    evidence_score: float = 0.0
    marked_unsafe: bool = False
    already_reserved_kg: float = 0.0  # confirmed / in-progress allocations that must not be touched


@dataclass
class Candidate:
    id: str
    name: str
    accepts_rungs: list[str]
    acceptance_rate: float
    distance_km: float
    remaining_capacity_kg: float  # capacity minus load already committed elsewhere


@dataclass
class AllocConstraints:
    pickup_delay_min: int = 30
    handover_buffer_min: int = 20
    excluded_rungs: list[str] = field(default_factory=list)
    excluded_recipients: list[str] = field(default_factory=list)
    allow_split: bool = True
    min_chunk_kg: float = 0.0


@dataclass
class Line:
    recipient_id: str
    recipient_name: str
    rung: str
    quantity_kg: float
    needed_minutes: int
    margin_minutes: int
    deadline_ok: bool
    why: str


@dataclass
class Rejected:
    recipient_id: str
    recipient_name: str
    rung: str | None
    reason: str
    code: str


@dataclass
class AllocationPlan:
    engine_version: str
    strategy: str
    lot_quantity_kg: float
    plannable_kg: float          # quantity not already reserved
    allocated_kg: float
    unallocated_kg: float
    status: str                  # feasible | partial | infeasible | blocked
    lines: list[Line]
    rejected: list[Rejected]
    warnings: list[str]
    objective: dict
    explanation: str
    requires_human_review: bool
    heuristics: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


HEURISTIC_NOTES = [
    "Transit/handover minutes come from the engine's fixed heuristic, not from routing or live traffic data.",
    "acceptance_rate is a stored historical rate used only to order options, never as a probability of success.",
    "Evidence thresholds and pathway rules are operational heuristics, not validated food-safety regulation.",
]


def validate_lot(lot: AllocLot) -> list[str]:
    problems = []
    for name in ("quantity_kg", "already_reserved_kg", "evidence_score", "freshness_percent"):
        v = getattr(lot, name)
        if not isinstance(v, (int, float)) or not math.isfinite(v):
            problems.append(f"{name} must be a finite number (kilograms for quantities).")
    if not problems:
        if lot.quantity_kg <= 0:
            problems.append("quantity_kg must be greater than zero.")
        if lot.already_reserved_kg < 0 or lot.already_reserved_kg > lot.quantity_kg + EPS:
            problems.append("already_reserved_kg must be between 0 and the lot quantity.")
        if lot.remaining_minutes < 0:
            problems.append("remaining_minutes cannot be negative.")
    return problems


def _screen(rung: str, lot: AllocLot, c: AllocConstraints) -> tuple[str, str] | None:
    """Hard eligibility for a pathway independent of recipient. Returns (code, reason) when blocked."""
    label = eng.RUNG_LABELS[rung]
    if rung in c.excluded_rungs:
        return "RUNG_EXCLUDED", f"{label} was ruled out earlier in this case."
    if lot.marked_unsafe and rung != "R4":
        return "MARKED_UNSAFE", f"Lot is marked unsafe; {label} is not allowed. Only compost/biogas can be considered."
    if rung in ("R1", "R2") and not lot.human_grade_eligible:
        return "NOT_HUMAN_GRADE", "Product is not flagged eligible for human consumption."
    if rung == "R3" and not lot.feed_eligible:
        return "NOT_FEED_ELIGIBLE", "Product is not flagged eligible for animal feed."
    if lot.evidence_score < eng.MIN_EVIDENCE[rung]:
        return "EVIDENCE_MISSING", f"Condition evidence is incomplete ({round(lot.evidence_score * 100)}%); {label} needs more before it can be used."
    return None


def _sort_key(strategy: str, rung: str, cand: Candidate, needed: int):
    value = eng.VALUE_WEIGHT[rung] * eng.YIELD[rung]
    if strategy == "fastest":
        return (needed, -value, cand.id)
    if strategy == "lowest_distance":
        return (cand.distance_km, -value, cand.id)
    if strategy == "lowest_risk":
        return (-cand.acceptance_rate, -value, cand.id)
    # max_recovery / non_human_pathway: value density first, then likelier acceptance, then nearer
    return (-value, -cand.acceptance_rate, cand.distance_km, cand.id)


def optimize(lot: AllocLot, candidates: list[Candidate], c: AllocConstraints | None = None, strategy: str = "max_recovery") -> AllocationPlan:
    c = c or AllocConstraints()
    if strategy not in STRATEGIES:
        raise ValueError(f"Unknown strategy '{strategy}'.")
    problems = validate_lot(lot)
    if problems:
        return _empty(lot, strategy, "blocked", problems, "Input failed validation; nothing was allocated.")

    plannable = round(max(lot.quantity_kg - lot.already_reserved_kg, 0.0), 6)
    rejected: list[Rejected] = []
    options: list[tuple[Candidate, str, int, int]] = []
    rungs_considered = ("R3", "R4") if strategy == "non_human_pathway" else tuple(eng.RUNGS)
    base = eng.Constraints(c.pickup_delay_min, c.handover_buffer_min)

    for cand in candidates:
        if cand.id in c.excluded_recipients:
            rejected.append(Rejected(cand.id, cand.name, None, "Excluded earlier in this case (e.g. rejected this lot).", "RECIPIENT_EXCLUDED"))
            continue
        if not math.isfinite(cand.remaining_capacity_kg) or cand.remaining_capacity_kg <= EPS:
            rejected.append(Rejected(cand.id, cand.name, None, "No remaining capacity.", "NO_CAPACITY"))
            continue
        best: tuple[str, int, int] | None = None
        first_block: tuple[str, str, str] | None = None
        for rung in cand.accepts_rungs:
            if rung not in eng.RUNGS:
                continue
            if rung not in rungs_considered:
                first_block = first_block or (rung, "STRATEGY_FILTER", "Pathway not used by the selected strategy.")
                continue
            blocked = _screen(rung, lot, c)
            if blocked:
                first_block = first_block or (rung, blocked[0], blocked[1])
                continue
            needed = eng._needed_minutes(rung, base, cand.distance_km)
            margin = lot.remaining_minutes - needed
            if margin < 0:
                first_block = first_block or (rung, "DEADLINE", f"Not enough time: needs ~{needed} min, {lot.remaining_minutes} min remain.")
                continue
            # prefer the highest-value feasible rung this recipient offers
            if best is None or eng.VALUE_WEIGHT[rung] > eng.VALUE_WEIGHT[best[0]]:
                best = (rung, needed, margin)
        if best is None:
            rung, code, reason = first_block or (None, "NO_PATHWAY", "Recipient accepts no recognised pathway.")
            rejected.append(Rejected(cand.id, cand.name, rung, reason, code))
        else:
            options.append((cand, *best))

    options.sort(key=lambda o: _sort_key(strategy, o[1], o[0], o[2]))
    lines: list[Line] = []
    remaining = plannable

    if not c.allow_split and options and plannable > EPS:
        # single-recipient policy: pick the option recovering the most kg, then best sort position
        chosen = max(options, key=lambda o: (min(plannable, o[0].remaining_capacity_kg), -options.index(o)))
        options = [chosen]
    for cand, rung, needed, margin in options:
        if remaining <= EPS:
            rejected.append(Rejected(cand.id, cand.name, rung, "Not needed: the lot is already fully allocated.", "NOT_NEEDED"))
            continue
        qty = round(min(remaining, cand.remaining_capacity_kg), 6)
        if qty < c.min_chunk_kg - EPS and qty < remaining - EPS:
            rejected.append(Rejected(cand.id, cand.name, rung, f"Share would be below the {c.min_chunk_kg:g} kg minimum chunk.", "BELOW_MIN_CHUNK"))
            continue
        why = f"{eng.RUNG_LABELS[rung]}: capacity {cand.remaining_capacity_kg:g} kg, {margin} min of margin, {cand.distance_km:g} km."
        lines.append(Line(cand.id, cand.name, rung, qty, needed, margin, True, why))
        remaining = round(remaining - qty, 6)

    allocated = round(sum(l.quantity_kg for l in lines), 6)
    unallocated = round(max(plannable - allocated, 0.0), 6)
    warnings: list[str] = []
    if lot.evidence_score < 1.0:
        warnings.append("Evidence is incomplete; a human must review before any human-consumption pathway is approved.")
    if lines and any(l.margin_minutes < 30 for l in lines):
        warnings.append("At least one allocation has under 30 minutes of margin before the deadline.")
    if lot.already_reserved_kg > EPS:
        warnings.append(f"{lot.already_reserved_kg:g} kg is already reserved by existing allocations and was left untouched.")

    if plannable <= EPS:
        status = "feasible"
    elif not lines:
        status = "blocked" if any(r.code in ("MARKED_UNSAFE", "EVIDENCE_MISSING") for r in rejected) and not any(r.code == "DEADLINE" for r in rejected) else "infeasible"
    elif unallocated > EPS:
        status = "partial"
    else:
        status = "feasible"
    if status in ("infeasible", "blocked"):
        warnings.append("No safe, feasible allocation exists. Human intervention is required.")
    elif status == "partial":
        warnings.append(f"{unallocated:g} kg could not be allocated within the constraints.")

    value = round(sum(eng.VALUE_WEIGHT[l.rung] * eng.YIELD[l.rung] * l.quantity_kg for l in lines), 3)
    return AllocationPlan(
        engine_version=ENGINE_VERSION, strategy=strategy, lot_quantity_kg=lot.quantity_kg, plannable_kg=plannable,
        allocated_kg=allocated, unallocated_kg=unallocated, status=status, lines=lines, rejected=rejected, warnings=warnings,
        objective={"allocated_kg": allocated, "pathway_value": value, "recovery_pct": round(100 * allocated / plannable, 1) if plannable > EPS else 100.0,
                   "max_feasible_kg": round(min(plannable, sum(o[0].remaining_capacity_kg for o in options)), 6)},
        explanation=_explain(strategy, lines, rejected, unallocated, status), requires_human_review=True, heuristics=list(HEURISTIC_NOTES),
    )


def _empty(lot, strategy, status, warnings, explanation) -> AllocationPlan:
    return AllocationPlan(ENGINE_VERSION, strategy, lot.quantity_kg, 0.0, 0.0, 0.0, status, [], [], warnings,
                          {"allocated_kg": 0.0, "pathway_value": 0.0, "recovery_pct": 0.0, "max_feasible_kg": 0.0}, explanation, True, list(HEURISTIC_NOTES))


def _explain(strategy, lines, rejected, unallocated, status) -> str:
    """Deterministic, rule-based explanation. Not AI-generated."""
    head = STRATEGY_LABELS[strategy]
    if not lines:
        reasons = "; ".join(sorted({r.reason for r in rejected})[:3]) or "no candidates were available"
        return f"{head}. No allocation: {reasons}."
    parts = [f"{l.quantity_kg:g} kg to {l.recipient_name} ({eng.RUNG_LABELS[l.rung]})" for l in lines]
    tail = f" {unallocated:g} kg left unallocated." if unallocated > EPS else " The whole available quantity is allocated."
    return f"{head}. Proposed: " + ", ".join(parts) + "." + tail


def compare_strategies(lot: AllocLot, candidates: list[Candidate], c: AllocConstraints | None = None) -> list[AllocationPlan]:
    return [optimize(lot, candidates, c, s) for s in STRATEGIES]


def baseline_plan(lot: AllocLot, candidates: list[Candidate], c: AllocConstraints | None = None) -> dict:
    """What the existing single-recipient engine would recover for the same inputs (benchmark baseline)."""
    c = c or AllocConstraints()
    plannable = max(lot.quantity_kg - lot.already_reserved_kg, 0.0)
    pool = [eng.RecipientInput(x.id, x.name, "x", list(x.accepts_rungs), x.acceptance_rate, x.distance_km, x.remaining_capacity_kg) for x in candidates]
    el = eng.LotInput(plannable, lot.remaining_minutes, lot.freshness_percent, lot.human_grade_eligible and not lot.marked_unsafe,
                      lot.feed_eligible and not lot.marked_unsafe, lot.evidence_score)
    opts = eng.plan(el, pool, eng.Constraints(c.pickup_delay_min, c.handover_buffer_min, list(c.excluded_rungs), list(c.excluded_recipients)))
    rec = next((o for o in opts if o.is_recommended), None)
    if rec is None:
        return {"allocated_kg": 0.0, "rung": None, "recipient_id": None}
    rcp = next((x for x in candidates if x.id == rec.recipient_id), None)
    if rcp is None:
        # the baseline may recommend R4 with NO identified recipient (a generic offtake assumption). That is not an
        # allocation to a real recipient, so it recovers 0 kg here; flagged so the benchmark can report it.
        return {"allocated_kg": 0.0, "rung": rec.rung, "recipient_id": None, "unbacked_pathway": True}
    return {"allocated_kg": round(min(plannable, rcp.remaining_capacity_kg), 6), "rung": rec.rung, "recipient_id": rec.recipient_id}
