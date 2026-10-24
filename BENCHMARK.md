# Simulated benchmark

Run: `cd backend && python -m app.benchmark` (deterministic, seed 2026, 400 generated scenarios). It compares the existing single-recipient engine with the multi-recipient optimizer on identical inputs. **This is evidence about the simulator, not real-world performance.**

Simulated benchmark, 400 deterministic scenarios (seed 2026), runtime 0.04s

| Metric | Baseline (single recipient) | Improved (multi-recipient) |
|---|---|---|
| Recovered kg | 22980 | 40670 |
| Recovery % of lot kg | 14.1% | 24.9% |
| Unallocated kg | 140160 | 122470 |
| Deadline success (scenarios) | 400/400 | 400/400 |
| Infeasible scenarios correctly identified | 188/188 | 188/188 |
| Hard-constraint violations | 0 | 0 |
| Mean optimize() latency | n/a | 0.022 ms |

Definitions: *Recovered kg* = kg allocated to real recipients. *Deadline success* = scenarios where every allocated slice passes the deadline check. *Infeasible correctly identified* = scenarios where no single recipient can feasibly take any food (checked independently) and the engine allocated nothing. *Violations* = allocations breaking capacity, quantity, deadline, evidence, exclusion, product-flag or unsafe rules.

Caveats, reported honestly:
* The baseline sometimes recommends biogas (R4) with **no identified recipient** (an assumed generic offtake). That is not an allocation to a real recipient, so it counts as 0 kg here (53 of 400 scenarios). If it were counted as full recovery, the baseline would show 45,540 kg versus 40,670 kg for the improved engine, i.e. the baseline would look better on that metric. The improved engine only allocates to recipients that exist and have capacity.
* Per scenario, the improved engine never allocates less than the baseline (tested in `test_per_scenario_dominance_over_baseline`).
* Both engines show 0 hard-constraint violations on these scenarios.
