# Assumptions & limitations
- Built from scratch (no existing repository was available). 
- Meals-per-kg, CO₂e-per-kg and rung CO₂e factors (`R1 1.0, R2 0.9, R3 0.6, R4 0.25`) are **illustrative placeholders**, not audited emission factors. Replace with verified factors before reporting externally.
- Acceptance probabilities come from per-recipient historical rates stored in the database (seeded for the demo). No ML model is trained; forecasts are seeded statistical series and backtest numbers are computed from that stored history.
- Freshness is a time-window indicator from a recorded safe-until time; it is not a safety determination. Human-consumption rungs (R1/R2) require condition evidence and human approval.
- Scenarios modify simulated state, are reversible via recorded snapshots, and are audited.
- Not implemented (documented rather than faked): PDF report export (CSV only), maps, a standalone ProductionPlan/SystemSetting/Handover entity (handover is part of `pickups`), LLM explanations (the optional `LLM_API_KEY` is reserved; the deterministic explanation is always used), multi-replica rate limiting, httpOnly-cookie auth.
- Audit hash chain serialises writers per organization with a row lock; under very high concurrency a retry may be needed on `UNIQUE(org_id, seq)`.
