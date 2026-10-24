"""Pure optimizer tests: no database."""
import itertools
import random

import pytest

from app.services import allocation as alg


def cand(id, rungs, cap, rate=0.8, dist=10, name=None):
    return alg.Candidate(id, name or id, rungs, rate, dist, cap)


def lot(**kw):
    base = dict(quantity_kg=120, remaining_minutes=600, freshness_percent=60, evidence_score=1.0)
    base.update(kw)
    return alg.AllocLot(**base)


A, B, C = cand("A", ["R1"], 50), cand("B", ["R1"], 40, 0.7), cand("C", ["R1"], 30, 0.6)


def test_multi_recipient_split_fills_exactly():
    p = alg.optimize(lot(), [A, B, C])
    assert p.status == "feasible" and p.allocated_kg == 120 and p.unallocated_kg == 0
    assert {l.recipient_id: l.quantity_kg for l in p.lines} == {"A": 50, "B": 40, "C": 30}
    assert p.engine_version == alg.ENGINE_VERSION and p.requires_human_review


def test_capacity_is_a_hard_limit_and_unallocated_is_reported():
    p = alg.optimize(lot(quantity_kg=200), [A, B, C])
    assert p.allocated_kg == 120 and p.unallocated_kg == 80 and p.status == "partial"
    assert any("could not be allocated" in w for w in p.warnings)
    assert all(l.quantity_kg <= {"A": 50, "B": 40, "C": 30}[l.recipient_id] for l in p.lines)


def test_never_allocates_more_than_the_lot():
    p = alg.optimize(lot(quantity_kg=60), [A, B, C])
    assert p.allocated_kg == 60 and sum(l.quantity_kg for l in p.lines) == 60


def test_already_reserved_quantity_is_not_replanned():
    p = alg.optimize(lot(already_reserved_kg=100), [A, B, C])
    assert p.plannable_kg == 20 and p.allocated_kg == 20
    assert any("already reserved" in w for w in p.warnings)


def test_deadline_is_hard_constraint():
    far = cand("far", ["R1"], 500, dist=400)
    p = alg.optimize(lot(remaining_minutes=150), [far])
    assert p.status == "infeasible" and p.rejected[0].code == "DEADLINE"
    assert "Human intervention" in " ".join(p.warnings)


def test_missing_evidence_blocks_human_pathways_but_not_feed_or_biogas():
    cs = [cand("n", ["R1"], 500), cand("f", ["R3"], 500), cand("b", ["R4"], 500)]
    p = alg.optimize(lot(evidence_score=0.0), cs)
    assert {l.recipient_id for l in p.lines} == {"f"} or {l.recipient_id for l in p.lines} <= {"f", "b"}
    assert any(r.code == "EVIDENCE_MISSING" and r.recipient_id == "n" for r in p.rejected)
    only_ngo = alg.optimize(lot(evidence_score=0.0), [cand("n", ["R1"], 500)])
    assert only_ngo.status == "blocked" and not only_ngo.lines


def test_marked_unsafe_only_allows_compost_biogas():
    cs = [cand("n", ["R1"], 500), cand("f", ["R3"], 500), cand("b", ["R4"], 500)]
    p = alg.optimize(lot(marked_unsafe=True), cs)
    assert [l.recipient_id for l in p.lines] == ["b"]
    assert {r.code for r in p.rejected} == {"MARKED_UNSAFE"}


def test_product_compatibility():
    p = alg.optimize(lot(human_grade_eligible=False), [cand("n", ["R1"], 500), cand("f", ["R3"], 500)])
    assert [l.recipient_id for l in p.lines] == ["f"]
    p = alg.optimize(lot(feed_eligible=False), [cand("f", ["R3"], 500)])
    assert p.status in ("infeasible", "blocked") and p.rejected[0].code == "NOT_FEED_ELIGIBLE"


def test_exclusions_prevent_reassignment_to_rejecting_recipient():
    p = alg.optimize(lot(), [A, B, C], alg.AllocConstraints(excluded_recipients=["A"]))
    assert "A" not in {l.recipient_id for l in p.lines} and p.allocated_kg == 70
    assert any(r.code == "RECIPIENT_EXCLUDED" for r in p.rejected)


def test_human_consumption_first_then_lower_pathways():
    cs = [cand("n", ["R1"], 50), cand("f", ["R3"], 500), cand("b", ["R4"], 500)]
    p = alg.optimize(lot(), cs)
    assert [l.recipient_id for l in p.lines][0] == "n" and p.lines[0].rung == "R1"
    assert p.allocated_kg == 120


def test_no_split_policy_uses_single_recipient():
    p = alg.optimize(lot(), [A, B, C], alg.AllocConstraints(allow_split=False))
    assert len(p.lines) == 1 and p.lines[0].quantity_kg == 50 and p.unallocated_kg == 70


def test_strategies_respect_hard_constraints_and_differ():
    near_slow = cand("near", ["R1"], 120, rate=0.5, dist=2)
    far_sure = cand("sure", ["R1"], 120, rate=0.95, dist=30)
    fast = alg.optimize(lot(), [near_slow, far_sure], strategy="fastest")
    risk = alg.optimize(lot(), [near_slow, far_sure], strategy="lowest_risk")
    assert fast.lines[0].recipient_id == "near" and risk.lines[0].recipient_id == "sure"
    nh = alg.optimize(lot(), [cand("n", ["R1"], 500), cand("f", ["R3"], 500)], strategy="non_human_pathway")
    assert {l.rung for l in nh.lines} == {"R3"}
    unsafe = alg.optimize(lot(marked_unsafe=True), [cand("n", ["R1"], 500)], strategy="fastest")
    assert not unsafe.lines


@pytest.mark.parametrize("bad", [0, -5, float("nan"), float("inf")])
def test_invalid_quantity_is_rejected_not_guessed(bad):
    p = alg.optimize(lot(quantity_kg=bad), [A])
    assert p.status == "blocked" and not p.lines and p.warnings


def test_unknown_strategy_raises():
    with pytest.raises(ValueError):
        alg.optimize(lot(), [A], strategy="nope")


def test_explanation_is_deterministic_text():
    a = alg.optimize(lot(), [A, B, C])
    b = alg.optimize(lot(), [A, B, C])
    assert a.explanation == b.explanation and "50 kg to A" in a.explanation


def test_optimal_against_brute_force_on_random_instances():
    """Allocated kg must equal the true maximum min(Q, sum of feasible capacity)."""
    rng = random.Random(7)
    for _ in range(300):
        n = rng.randint(1, 5)
        cs = [cand(f"r{i}", [rng.choice(["R1", "R2", "R3", "R4"])], rng.choice([0, 10, 25, 60, 100]), rng.random(), rng.choice([2, 10, 40, 300])) for i in range(n)]
        L = lot(quantity_kg=rng.choice([30, 80, 150, 400]), remaining_minutes=rng.choice([60, 200, 600]), evidence_score=rng.choice([0.0, 1.0]))
        p = alg.optimize(L, cs)
        feasible_cap = 0.0
        for c in cs:
            r = c.accepts_rungs[0]
            from app.services import recovery_engine as eng
            need = eng._needed_minutes(r, eng.Constraints(30, 20), c.distance_km)
            if c.remaining_capacity_kg > 0 and L.evidence_score >= eng.MIN_EVIDENCE[r] and L.remaining_minutes >= need:
                feasible_cap += c.remaining_capacity_kg
        assert p.allocated_kg == pytest.approx(min(L.quantity_kg, feasible_cap))
        assert p.allocated_kg <= L.quantity_kg + 1e-9
        assert len({l.recipient_id for l in p.lines}) == len(p.lines)


def test_baseline_single_recipient_recovers_less_than_split():
    base = alg.baseline_plan(lot(), [A, B, C])
    assert base["allocated_kg"] <= 50 < alg.optimize(lot(), [A, B, C]).allocated_kg
