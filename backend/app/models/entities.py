import uuid
from datetime import date, datetime

from sqlalchemy import (JSON, BigInteger, Boolean, CheckConstraint, Date, Float, ForeignKey, Index, Integer, String, Text,
                        UniqueConstraint, Uuid, text)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import UTCDateTime, utcnow
from app.models.base import Base, Entity


def fk(target: str, nullable: bool = False, index: bool = True):
    return mapped_column(Uuid, ForeignKey(target), nullable=nullable, index=index)


class Organization(Entity):
    __tablename__ = "organizations"
    name: Mapped[str] = mapped_column(String(160))
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    type: Mapped[str] = mapped_column(String(20), default="MANUFACTURER")  # MANUFACTURER|NGO|BUYER|PARTNER
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class Plant(Entity):
    __tablename__ = "plants"
    org_id: Mapped[uuid.UUID] = fk("organizations.id")
    name: Mapped[str] = mapped_column(String(160))
    city: Mapped[str] = mapped_column(String(80))
    lat: Mapped[float] = mapped_column(Float, default=0.0)
    lng: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(20), default="active")


class Recipient(Entity):
    __tablename__ = "recipients"
    org_id: Mapped[uuid.UUID | None] = fk("organizations.id", nullable=True)
    name: Mapped[str] = mapped_column(String(160))
    kind: Mapped[str] = mapped_column(String(20))  # ngo|buyer|feed|biogas
    accepts_rungs: Mapped[list] = mapped_column(JSON, default=list)
    acceptance_rate: Mapped[float] = mapped_column(Float, default=0.7)  # historical, statistical
    capacity_kg: Mapped[float] = mapped_column(Float, default=500)
    distance_km: Mapped[float] = mapped_column(Float, default=10)
    city: Mapped[str] = mapped_column(String(80), default="")
    phone: Mapped[str] = mapped_column(String(32), default="")
    status: Mapped[str] = mapped_column(String(20), default="active")


class User(Entity):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(24), index=True)
    org_id: Mapped[uuid.UUID | None] = fk("organizations.id", nullable=True)
    recipient_id: Mapped[uuid.UUID | None] = fk("recipients.id", nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_platform_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    language: Mapped[str] = mapped_column(String(5), default="en")
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    # Account lifecycle. `status` is authoritative; `is_active` is kept in sync (status == ACTIVE) for older code paths.
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE", server_default="ACTIVE", index=True)  # ACTIVE|PENDING|REJECTED|DISABLED
    email_verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    requested_role: Mapped[str | None] = mapped_column(String(24), nullable=True)  # what a PENDING user asked for; grants nothing
    decided_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    decision_note: Mapped[str | None] = mapped_column(String(200), nullable=True)


class Invitation(Entity):
    """Backend-controlled invitation. Only the SHA-256 of the token is stored; the raw token is shown once."""
    __tablename__ = "invitations"
    org_id: Mapped[uuid.UUID] = fk("organizations.id")
    email: Mapped[str] = mapped_column(String(254), index=True)
    role: Mapped[str] = mapped_column(String(24))
    recipient_id: Mapped[uuid.UUID | None] = fk("recipients.id", nullable=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    max_uses: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    use_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    last_used_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)


class RefreshToken(Entity):
    __tablename__ = "refresh_tokens"
    user_id: Mapped[uuid.UUID] = fk("users.id")
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class Product(Entity):
    __tablename__ = "products"
    org_id: Mapped[uuid.UUID] = fk("organizations.id")
    name: Mapped[str] = mapped_column(String(160))
    sku: Mapped[str] = mapped_column(String(40))
    category: Mapped[str] = mapped_column(String(40))
    human_grade_eligible: Mapped[bool] = mapped_column(Boolean, default=True)
    feed_eligible: Mapped[bool] = mapped_column(Boolean, default=True)
    shelf_life_hours: Mapped[int] = mapped_column(Integer, default=48)
    meals_per_kg: Mapped[float] = mapped_column(Float, default=2.5)
    co2e_per_kg: Mapped[float] = mapped_column(Float, default=2.0)  # illustrative factor, see ASSUMPTIONS.md
    __table_args__ = (UniqueConstraint("org_id", "sku"),)


class InventoryLot(Entity):
    __tablename__ = "inventory_lots"
    org_id: Mapped[uuid.UUID] = fk("organizations.id")
    plant_id: Mapped[uuid.UUID] = fk("plants.id")
    product_id: Mapped[uuid.UUID] = fk("products.id")
    lot_code: Mapped[str] = mapped_column(String(40), unique=True)
    quantity_kg: Mapped[float] = mapped_column(Float)
    produced_at: Mapped[datetime] = mapped_column(UTCDateTime)
    safe_until: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    window_minutes: Mapped[int] = mapped_column(Integer)
    storage: Mapped[str] = mapped_column(String(12), default="chilled")
    status: Mapped[str] = mapped_column(String(16), default="available", index=True)
    last_state: Mapped[str | None] = mapped_column(String(16), nullable=True)
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    # kg currently reserved by active/completed allocations. Only changed by atomic conditional UPDATEs in services/allocations.py
    reserved_kg: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    product = relationship("Product", lazy="joined")
    plant = relationship("Plant", lazy="joined")
    __table_args__ = (Index("ix_lots_org_status", "org_id", "status"),
                      CheckConstraint("reserved_kg >= 0", name="ck_lot_reserved_nonneg"))


class FreshnessAssessment(Entity):
    __tablename__ = "freshness_assessments"
    lot_id: Mapped[uuid.UUID] = fk("inventory_lots.id")
    remaining_minutes: Mapped[int] = mapped_column(Integer)
    percent: Mapped[float] = mapped_column(Float)
    state: Mapped[str] = mapped_column(String(16))
    method: Mapped[str] = mapped_column(String(12), default="RULE")
    note: Mapped[str] = mapped_column(String(200), default="")


class RecoveryCase(Entity):
    __tablename__ = "recovery_cases"
    org_id: Mapped[uuid.UUID] = fk("organizations.id")
    lot_id: Mapped[uuid.UUID] = fk("inventory_lots.id")
    case_number: Mapped[str] = mapped_column(String(24), unique=True)
    status: Mapped[str] = mapped_column(String(24), default="pending_approval", index=True)
    selected_rung: Mapped[str | None] = mapped_column(String(2), nullable=True)
    recipient_id: Mapped[uuid.UUID | None] = fk("recipients.id", nullable=True)
    quantity_kg: Mapped[float] = mapped_column(Float)
    recovered_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    plan_version: Mapped[int] = mapped_column(Integer, default=1)
    replan_count: Mapped[int] = mapped_column(Integer, default=0)
    pickup_delay_min: Mapped[int] = mapped_column(Integer, default=30)
    handover_buffer_min: Mapped[int] = mapped_column(Integer, default=20)
    excluded_rungs: Mapped[list] = mapped_column(JSON, default=list)
    excluded_recipients: Mapped[list] = mapped_column(JSON, default=list)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    lot = relationship("InventoryLot", lazy="joined")
    recipient = relationship("Recipient", lazy="joined")


class RecoveryOption(Entity):
    __tablename__ = "recovery_options"
    case_id: Mapped[uuid.UUID] = fk("recovery_cases.id")
    plan_version: Mapped[int] = mapped_column(Integer, default=1)
    rung: Mapped[str] = mapped_column(String(2))
    eligible: Mapped[bool] = mapped_column(Boolean)
    reason: Mapped[str] = mapped_column(String(300))
    confidence: Mapped[float] = mapped_column(Float, default=0)
    p_success: Mapped[float] = mapped_column(Float, default=0)
    est_recovery_kg: Mapped[float] = mapped_column(Float, default=0)
    recipient_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    recipient_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    method: Mapped[str] = mapped_column(String(12), default="RULE")
    is_recommended: Mapped[bool] = mapped_column(Boolean, default=False)
    is_hedge: Mapped[bool] = mapped_column(Boolean, default=False)
    factors: Mapped[dict] = mapped_column(JSON, default=dict)
    __table_args__ = (Index("ix_options_case_ver", "case_id", "plan_version"),)


class RecoveryDecision(Entity):
    __tablename__ = "recovery_decisions"
    case_id: Mapped[uuid.UUID] = fk("recovery_cases.id")
    decided_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    decision: Mapped[str] = mapped_column(String(24))
    rung: Mapped[str | None] = mapped_column(String(2), nullable=True)
    recipient_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")


class Pickup(Entity):
    __tablename__ = "pickups"
    org_id: Mapped[uuid.UUID] = fk("organizations.id")
    case_id: Mapped[uuid.UUID] = fk("recovery_cases.id")
    status: Mapped[str] = mapped_column(String(16), default="scheduled", index=True)
    logistics_user_id: Mapped[uuid.UUID | None] = fk("users.id", nullable=True)
    scheduled_for: Mapped[datetime] = mapped_column(UTCDateTime)
    eta: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    delay_minutes: Mapped[int] = mapped_column(Integer, default=0)
    delay_reason: Mapped[str] = mapped_column(String(200), default="")
    handed_over_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    received_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    case = relationship("RecoveryCase", lazy="joined")
    logistics_user = relationship("User", lazy="joined")


class Evidence(Entity):
    __tablename__ = "evidence"
    org_id: Mapped[uuid.UUID] = fk("organizations.id")
    case_id: Mapped[uuid.UUID] = fk("recovery_cases.id")
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    kind: Mapped[str] = mapped_column(String(20))  # photo|temperature_log|label|lab_report|other
    original_name: Mapped[str] = mapped_column(String(200))
    stored_name: Mapped[str] = mapped_column(String(80), unique=True)
    content_type: Mapped[str] = mapped_column(String(80))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))


class ComplianceDocument(Entity):
    __tablename__ = "compliance_documents"
    org_id: Mapped[uuid.UUID] = fk("organizations.id")
    title: Mapped[str] = mapped_column(String(200))
    doc_type: Mapped[str] = mapped_column(String(30))  # license|label|certificate|sop|other
    issuer: Mapped[str] = mapped_column(String(160), default="")
    reference: Mapped[str] = mapped_column(String(80), default="")
    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    stored_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    original_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)


class AuditEvent(Base):
    """Append-only, hash-chained per organization (tamper-evident, not a blockchain)."""

    __tablename__ = "audit_events"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = fk("organizations.id")
    seq: Mapped[int] = mapped_column(Integer)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    actor_label: Mapped[str] = mapped_column(String(160))
    action: Mapped[str] = mapped_column(String(60), index=True)
    resource_type: Mapped[str] = mapped_column(String(40))
    resource_id: Mapped[str] = mapped_column(String(60), index=True)
    case_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    summary: Mapped[str] = mapped_column(String(300), default="")
    meta: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    __table_args__ = (UniqueConstraint("org_id", "seq", name="uq_audit_org_seq"),)


class Notification(Entity):
    __tablename__ = "notifications"
    org_id: Mapped[uuid.UUID | None] = fk("organizations.id", nullable=True)
    user_id: Mapped[uuid.UUID] = fk("users.id")
    type: Mapped[str] = mapped_column(String(30))
    severity: Mapped[str] = mapped_column(String(10), default="info")
    title: Mapped[str] = mapped_column(String(160))
    body: Mapped[str] = mapped_column(String(300), default="")
    resource_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(60), nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    __table_args__ = (Index("ix_notif_user_read", "user_id", "read_at"),)


class ScenarioRun(Entity):
    __tablename__ = "scenario_runs"
    org_id: Mapped[uuid.UUID] = fk("organizations.id")
    kind: Mapped[str] = mapped_column(String(30))
    target_type: Mapped[str] = mapped_column(String(20))
    target_id: Mapped[str] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(12), default="active")
    impact: Mapped[dict] = mapped_column(JSON, default=dict)
    changes: Mapped[list] = mapped_column(JSON, default=list)
    created: Mapped[list] = mapped_column(JSON, default=list)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    reverted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class EventOutbox(Base):
    """Cross-process event feed read by the SSE endpoint."""

    __tablename__ = "event_outbox"
    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    org_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    recipient_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    type: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)


class PlantMetric(Entity):
    __tablename__ = "plant_metrics"
    plant_id: Mapped[uuid.UUID] = fk("plants.id")
    day: Mapped[date] = mapped_column(Date)
    line: Mapped[str] = mapped_column(String(30))
    production_kg: Mapped[float] = mapped_column(Float)
    oee: Mapped[float] = mapped_column(Float)
    energy_kwh: Mapped[float] = mapped_column(Float)
    downtime_min: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (UniqueConstraint("plant_id", "day", "line"),)


class Anomaly(Entity):
    __tablename__ = "anomalies"
    plant_id: Mapped[uuid.UUID] = fk("plants.id")
    line: Mapped[str] = mapped_column(String(30), default="")
    kind: Mapped[str] = mapped_column(String(30))
    severity: Mapped[str] = mapped_column(String(10), default="medium")
    description: Mapped[str] = mapped_column(String(300))
    detected_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    affected_lot_ids: Mapped[list] = mapped_column(JSON, default=list)
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=False)


class SustainabilityMetric(Entity):
    __tablename__ = "sustainability_metrics"
    org_id: Mapped[uuid.UUID] = fk("organizations.id")
    case_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    recorded_on: Mapped[date] = mapped_column(Date, index=True)
    rung: Mapped[str] = mapped_column(String(2))
    kg: Mapped[float] = mapped_column(Float)
    meals: Mapped[float] = mapped_column(Float, default=0)
    co2e_kg: Mapped[float] = mapped_column(Float, default=0)
    source: Mapped[str] = mapped_column(String(20), default="recovery")  # recovery|demo_history


class DemandForecast(Entity):
    __tablename__ = "demand_forecasts"
    org_id: Mapped[uuid.UUID] = fk("organizations.id")
    product_id: Mapped[uuid.UUID] = fk("products.id")
    day: Mapped[date] = mapped_column(Date)
    p50: Mapped[float] = mapped_column(Float)
    p80: Mapped[float] = mapped_column(Float)
    actual: Mapped[float | None] = mapped_column(Float, nullable=True)
    surplus_kg: Mapped[float] = mapped_column(Float, default=0)
    drivers: Mapped[list] = mapped_column(JSON, default=list)
    __table_args__ = (UniqueConstraint("product_id", "day"),)


ACTIVE_ALLOCATION = ("proposed", "offered", "accepted")


class Allocation(Entity):
    """A slice of a lot reserved for one recipient. Lifecycle:
    proposed -> offered -> accepted -> completed; proposed/offered/accepted -> rejected | cancelled | failed.
    Quantity is reserved against InventoryLot.reserved_kg while proposed/offered/accepted/completed."""

    __tablename__ = "allocations"
    org_id: Mapped[uuid.UUID] = fk("organizations.id")
    case_id: Mapped[uuid.UUID] = fk("recovery_cases.id")
    lot_id: Mapped[uuid.UUID] = fk("inventory_lots.id")
    recipient_id: Mapped[uuid.UUID] = fk("recipients.id")
    rung: Mapped[str] = mapped_column(String(2))
    quantity_kg: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(12), default="proposed", index=True)
    plan_version: Mapped[int] = mapped_column(Integer, default=1)
    strategy: Mapped[str] = mapped_column(String(24), default="max_recovery")
    engine_version: Mapped[str] = mapped_column(String(24), default="")
    needed_minutes: Mapped[int] = mapped_column(Integer, default=0)
    eta: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    delay_minutes: Mapped[int] = mapped_column(Integer, default=0)
    why: Mapped[str] = mapped_column(String(300), default="")
    response_reason: Mapped[str] = mapped_column(String(300), default="")
    responded_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    received_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)  # optimistic version, bumped on every transition
    recipient = relationship("Recipient", lazy="joined")
    __table_args__ = (
        CheckConstraint("quantity_kg > 0", name="ck_alloc_qty_pos"),
        # one live allocation per recipient per case (prevents duplicate commits of the same slice)
        Index("uq_alloc_live_recipient", "case_id", "recipient_id", unique=True,
              sqlite_where=text("status IN ('proposed','offered','accepted')"),
              postgresql_where=text("status IN ('proposed','offered','accepted')")),
    )
