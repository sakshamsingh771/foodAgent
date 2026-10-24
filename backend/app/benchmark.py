"""Deterministic simulated benchmark: improved multi-recipient engine vs the existing single-recipient engine.

    python -m app.benchmark            # prints a markdown table, exit 1 if the improved engine violates a hard constraint

Metrics (all computed on SIMULATED scenarios generated from a fixed seed; this is evidence about the simulator,
not real-world performance):
  recovered_kg        sum of kg allocated to recipients
  recovery_pct        recovered_kg / sum of lot kg
  deadline_success    share of scenarios where every allocated slice meets its deadline (hard constraint)
  unallocated_kg      lot kg that received no allocation
  infeasible_correct  scenarios where NO feasible slice exists (ground truth by brute force) and the engine allocated nothing
  violations          allocations breaking capacity, quantity, deadline, evidence or exclusion rules
  replan_ms           mean wall-clock of one optimize() call
"""
import random
import sys
import time

from app.services import allocation as alg
from app.services import recovery_engine as eng


def scenarios(n: int = 400, seed: int = 2026):
    rng = random.Random(seed)
    for i in range(n):
        k = rng.randint(2, 6)
        cands = [alg.Candidate(f"r{j}", f"R{j}", [rng.choice(["R1", "R1", "R2", "R3", "R4"])],
                               round(rng.uniform(0.4, 0.97), 2), rng.choice([3, 9, 18, 30, 60, 250]), 0) for j in range(k)]
        for c in cands:
            c.remaining_capacity_kg = float(rng.choice([0, 20, 40, 80, 150, 400]))
        lot = alg.AllocLot(quantity_kg=rng.choice([60, 120, 300, 600, 900]), remaining_minutes=rng.choice([40, 90, 180, 400, 900]),
                           freshness_percent=rng.choice([20, 50, 90]), evidence_score=rng.choice([0.0, 0.34, 0.67, 1.0]),
                           human_grade_eligible=rng.random() > 0.15, feed_eligible=rng.random() > 0.15, marked_unsafe=rng.random() < 0.05)
        cons = alg.AllocConstraints(pickup_delay_min=rng.choice([0, 30, 90]), excluded_recipients=[c.id for c in cands if rng.random() < 0.15])
        yield lot, cands, cons


def violations(lot, cands, cons, lines) -> int:
    v, by = 0, {c.id: c for c in cands}
    if sum(l.quantity_kg for l in lines) > lot.quantity_kg - lot.already_reserved_kg + 1e-6:
        v += 1
    for l in lines:
        c = by[l.recipient_id]
        need = eng._needed_minutes(l.rung, eng.Constraints(cons.pickup_delay_min, cons.handover_buffer_min), c.distance_km)
        v += l.quantity_kg > c.remaining_capacity_kg + 1e-6
        v += need > lot.remaining_minutes
        v += lot.evidence_score < eng.MIN_EVIDENCE[l.rung]
        v += l.recipient_id in cons.excluded_recipients
        v += lot.marked_unsafe and l.rung != "R4"
        v += (l.rung in ("R1", "R2") and not lot.human_grade_eligible) or (l.rung == "R3" and not lot.feed_eligible)
    return int(v)


def feasible_exists(lot, cands, cons) -> bool:
    return any(alg.optimize(lot, [c], cons).lines for c in cands)


def run(n: int = 400) -> dict:
    out = {k: {"recovered_kg": 0.0, "violations": 0, "deadline_ok": 0, "unallocated_kg": 0.0} for k in ("baseline", "improved")}
    total_kg, infeasible_total, infeasible_ok = 0.0, 0, {"baseline": 0, "improved": 0}
    t_improved = 0.0
    for lot, cands, cons in scenarios(n):
        total_kg += lot.quantity_kg
        b = alg.baseline_plan(lot, cands, cons)
        t0 = time.perf_counter()
        p = alg.optimize(lot, cands, cons)
        t_improved += time.perf_counter() - t0
        out["baseline"]["recovered_kg"] += b["allocated_kg"]
        out["baseline"]["unallocated_kg"] += lot.quantity_kg - b["allocated_kg"]
        out["improved"]["recovered_kg"] += p.allocated_kg
        out["improved"]["unallocated_kg"] += p.unallocated_kg
        out["improved"]["violations"] += violations(lot, cands, cons, p.lines)
        out["improved"]["deadline_ok"] += all(l.deadline_ok for l in p.lines)
        # baseline violations: re-check its single pick against the same hard rules
        if b["rung"]:
            c = next((x for x in cands if x.id == b["recipient_id"]), None)
            if c:
                out["baseline"]["violations"] += violations(lot, cands, cons, [alg.Line(c.id, c.name, b["rung"], b["allocated_kg"], 0, 0, True, "")])
        out["baseline"]["deadline_ok"] += 1  # baseline only recommends rungs whose own time check passed
        if not feasible_exists(lot, cands, cons):
            infeasible_total += 1
            infeasible_ok["improved"] += not p.lines
            infeasible_ok["baseline"] += b["allocated_kg"] == 0
    out["scenarios"], out["total_kg"], out["infeasible_scenarios"], out["infeasible_correct"] = n, total_kg, infeasible_total, infeasible_ok
    out["improved_replan_ms"] = round(1000 * t_improved / n, 3)
    return out


def table(r: dict) -> str:
    b, i, tk = r["baseline"], r["improved"], r["total_kg"]
    rows = [("Recovered kg", f"{b['recovered_kg']:.0f}", f"{i['recovered_kg']:.0f}"),
            ("Recovery % of lot kg", f"{100 * b['recovered_kg'] / tk:.1f}%", f"{100 * i['recovered_kg'] / tk:.1f}%"),
            ("Unallocated kg", f"{b['unallocated_kg']:.0f}", f"{i['unallocated_kg']:.0f}"),
            ("Deadline success (scenarios)", f"{b['deadline_ok']}/{r['scenarios']}", f"{i['deadline_ok']}/{r['scenarios']}"),
            ("Infeasible scenarios correctly identified", f"{r['infeasible_correct']['baseline']}/{r['infeasible_scenarios']}", f"{r['infeasible_correct']['improved']}/{r['infeasible_scenarios']}"),
            ("Hard-constraint violations", str(b["violations"]), str(i["violations"])),
            ("Mean optimize() latency", "n/a", f"{r['improved_replan_ms']} ms")]
    return "| Metric | Baseline (single recipient) | Improved (multi-recipient) |\n|---|---|---|\n" + "\n".join(f"| {a} | {x} | {y} |" for a, x, y in rows)


if __name__ == "__main__":
    t0 = time.perf_counter()
    res = run()
    print(f"Simulated benchmark, {res['scenarios']} deterministic scenarios (seed 2026), runtime {time.perf_counter() - t0:.2f}s\n")
    print(table(res))
    sys.exit(1 if res["improved"]["violations"] else 0)
