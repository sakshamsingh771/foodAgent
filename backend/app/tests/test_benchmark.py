from app import benchmark as bm
from app.services import allocation as alg


def test_improved_engine_has_no_hard_constraint_violations_and_never_recovers_less():
    r = bm.run(400)
    assert r["improved"]["violations"] == 0
    assert r["improved"]["recovered_kg"] >= r["baseline"]["recovered_kg"]
    assert r["infeasible_correct"]["improved"] == r["infeasible_scenarios"]


def test_per_scenario_dominance_over_baseline():
    for lot, cands, cons in bm.scenarios(400):
        assert alg.optimize(lot, cands, cons).allocated_kg >= alg.baseline_plan(lot, cands, cons)["allocated_kg"] - 1e-9
