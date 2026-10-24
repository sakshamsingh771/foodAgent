from datetime import datetime, timezone

from app.services import freshness
from app.services import recovery_engine as eng


def recips():
    return [
        eng.RecipientInput("ngo1", "Food Bank", "ngo", ["R1"], 0.86, 9, 800),
        eng.RecipientInput("buy1", "Buyer", "buyer", ["R2"], 0.7, 18, 1000),
        eng.RecipientInput("feed1", "Feed Co-op", "feed", ["R3"], 0.9, 38, 1500),
        eng.RecipientInput("bio1", "Biogas", "biogas", ["R4"], 0.97, 26, 3000),
    ]


def lot(**kw):
    base = dict(quantity_kg=300, remaining_minutes=600, freshness_percent=40, evidence_score=1.0)
    base.update(kw)
    return eng.LotInput(**base)


def test_recommends_highest_rung_when_time_is_ample():
    opts = eng.plan(lot(), recips(), eng.Constraints())
    rec = next(o for o in opts if o.is_recommended)
    assert rec.rung == "R1" and rec.eligible and rec.p_success >= eng.CONFIDENCE_BAR
    assert rec.requires_food_safety_review is True


def test_time_is_a_hard_constraint():
    opts = {o.rung: o for o in eng.plan(lot(remaining_minutes=90), recips(), eng.Constraints())}
    assert not opts["R1"].eligible and "Not enough time" in opts["R1"].reason


def test_missing_evidence_blocks_human_consumption_but_not_feed():
    opts = {o.rung: o for o in eng.plan(lot(evidence_score=0.0), recips(), eng.Constraints())}
    assert not opts["R1"].eligible and not opts["R2"].eligible
    assert opts["R3"].eligible and opts["R4"].eligible


def test_product_flags_respected():
    opts = {o.rung: o for o in eng.plan(lot(human_grade_eligible=False), recips(), eng.Constraints())}
    assert not opts["R1"].eligible and not opts["R2"].eligible


def test_replan_excludes_declined_recipient_and_rung():
    c = eng.Constraints(excluded_recipients=["ngo1"])
    opts = {o.rung: o for o in eng.plan(lot(), recips(), c)}
    assert not opts["R1"].eligible and "No available recipient" in opts["R1"].reason
    rec = next(o for o in opts.values() if o.is_recommended)
    assert rec.rung == "R2"
    c2 = eng.Constraints(excluded_rungs=["R1", "R2"])
    assert next(o for o in eng.plan(lot(), recips(), c2) if o.is_recommended).rung == "R3"


def test_hedge_differs_from_recommendation():
    opts = eng.plan(lot(), recips(), eng.Constraints())
    assert sum(o.is_recommended for o in opts) == 1 and sum(o.is_hedge for o in opts) == 1
    assert not any(o.is_recommended and o.is_hedge for o in opts)


def test_p_success_increases_with_acceptance_and_falls_with_delay():
    now = datetime.now(timezone.utc)
    kw = dict(handover_buffer_min=20, remaining_minutes=400, now=now)
    lo = eng.simulate(lot(), recips(), pickup_delay_min=30, acceptance_prob=0.4, **kw)
    hi = eng.simulate(lot(), recips(), pickup_delay_min=30, acceptance_prob=0.9, **kw)
    late = eng.simulate(lot(), recips(), pickup_delay_min=300, acceptance_prob=0.9, **kw)
    r1 = lambda sim: next(o for o in sim["options"] if o.rung == "R1").p_success
    assert r1(hi) > r1(lo)          # more acceptance -> better odds for donation
    assert r1(late) < r1(hi)        # longer pickup delay -> worse odds for donation
    # at low acceptance the plan falls back to a rung that is more certain to complete
    assert lo["recommended"].rung in ("R3", "R4")
    assert hi["simulated"] is True and hi["recommended"].method == "SIMULATED"


def test_deterministic():
    a = [(o.rung, o.p_success) for o in eng.plan(lot(), recips(), eng.Constraints())]
    b = [(o.rung, o.p_success) for o in eng.plan(lot(), recips(), eng.Constraints())]
    assert a == b


def test_freshness_states():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    from datetime import timedelta as td
    assert freshness.assess(now + td(minutes=60), 4000, now).state == freshness.LOSS_IMMINENT
    assert freshness.assess(now + td(minutes=300), 1000, now).state == freshness.ACT_SOON
    assert freshness.assess(now + td(minutes=3000), 4000, now).state == freshness.SAFE
    assert freshness.assess(now - td(minutes=5), 4000, now).percent == 0.0
