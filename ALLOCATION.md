# Multi-recipient allocation engine (`multi-alloc-v1`)

Extends the existing recovery engine; the single-recipient `recovery_engine.plan` is kept as the benchmark **baseline**.

## What it does
* `backend/app/services/allocation.py` is a pure, deterministic optimizer. Inputs: lot (kg, minutes left, evidence, product flags, already-reserved kg), candidates (remaining capacity, distance, pathways), constraints (exclusions, delay, split policy).
* **Hard constraints** (never traded for score): product flags, evidence threshold per pathway, a lot marked unsafe may only go to compost/biogas, deadline (`pickup delay + transit + handover buffer <= minutes left`), recipient remaining capacity, total never above the lot, excluded recipients/rungs, finite positive kg.
* **Objective** (lexicographic): maximise kg allocated, then pathway value (donation before secondary buyer before feed before biogas), then the chosen strategy tie-break. Capacities are independent, so this is a fractional-knapsack LP and the greedy fill is exactly optimal; a randomized brute-force test checks it (`test_optimal_against_brute_force_on_random_instances`).
* **Strategies** (all keep every hard constraint): `max_recovery`, `fastest`, `lowest_distance` (distance is a proxy; no cost data is stored), `lowest_risk` (highest historical acceptance), `non_human_pathway`.
* **Result**: lines (recipient, rung, kg, estimated minutes and margin, deadline flag, why), rejected alternatives with codes, unallocated kg, status (`feasible|partial|infeasible|blocked`), warnings, objective metrics, rule-based explanation, engine version.

## Persistence and double-allocation protection
* `inventory_lots.reserved_kg` is changed only by one conditional `UPDATE ... WHERE reserved_kg + :kg <= quantity_kg`; a CHECK constraint backs it. Two simultaneous requests cannot reserve the same kg.
* Every allocation state change is a compare-and-set on `(status, version)`. A duplicate or retried rejection returns `duplicate: true` and releases nothing.
* A partial unique index allows one live allocation per (case, recipient).
* Lifecycle: `proposed -> offered -> accepted -> completed`; `proposed|offered|accepted -> rejected|cancelled|failed`. A person approves before recipients are notified. Committing needs `confirm: true`.

## Failure recovery
* **Rejection**: reason + timestamp stored, only that slice released, recipient excluded for this lot, only the unreserved kg is replanned, accepted/in-progress slices are untouched. Replanning is capped at 5 per case, then a human is asked.
* **Partial acceptance**: slice shrinks to the accepted kg, the difference is released and replanned.
* **Transport delay**: if the deadline still holds the ETA is updated; otherwise the slice is released and replanned.
* **Transport failure**: only the affected slice is released and replanned. No alternative vehicle or route is modelled, and the API says so.
* **No feasible option**: nothing is invented; a critical notification asks for human intervention.
* Everything is written to the existing hash-chained audit log.

## Endpoints (`/api/v1`)
`GET /recovery-cases/{id}/allocations` · `POST .../allocation/plan` (read-only preview) · `POST .../allocation/compare` · `POST .../allocation/simulate` (scenarios: recipient_rejection, capacity_reduction, vehicle_delay, missing_evidence, no_feasible_option; read-only) · `POST .../allocation/commit` · `POST .../allocation/approve` · `POST /allocations/{id}/cancel|transport|handover` · `GET /recipient/allocations` · `POST /recipient/allocations/{id}/respond`.
Permissions reuse the existing roles (`cases:approve` to commit/approve/cancel, `pickups:write` for transport/handover, `recipient:respond` for recipients).

## Honest limits
* Time estimates come from the engine's fixed heuristic, not routing or live traffic. Distances are stored recipient distances.
* `acceptance_rate` orders options; it is not a calibrated probability and is never shown as one.
* Evidence thresholds and pathway rules are operational heuristics, **not** validated food-safety regulation. A qualified authority must validate them before real use.
* Capacity is a stored number per recipient minus live allocations; it is not live recipient data.
