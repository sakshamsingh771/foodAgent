# Database
PostgreSQL 16, SQLAlchemy 2 models in `backend/app/models/entities.py`, migration `alembic/versions/0001_initial_schema.py` (verified: `alembic upgrade head` then `alembic check` reports no drift on Postgres).

Core tables: `organizations, plants, users, refresh_tokens, products, inventory_lots, freshness_assessments, recovery_cases, recovery_options (versioned by plan_version), recovery_decisions, recipients, pickups, evidence, compliance_documents, audit_events, notifications, scenario_runs, event_outbox, plant_metrics, anomalies, sustainability_metrics, demand_forecasts`.

UUID primary keys, `created_at/updated_at`, FKs and indexes on org/status/time columns. `audit_events` is append-only and hash-chained per org with `UNIQUE(org_id, seq)`. Critical mutations run in one transaction with their audit/event rows.
