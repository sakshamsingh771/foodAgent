"""multi-recipient allocations + lot reservation counter

Additive only: new table and one new column with a server default. No data is modified or dropped.

Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

LIVE = "status IN ('proposed','offered','accepted')"


def upgrade() -> None:
    with op.batch_alter_table("inventory_lots") as b:
        b.add_column(sa.Column("reserved_kg", sa.Float(), nullable=False, server_default="0"))
        b.create_check_constraint("ck_lot_reserved_nonneg", "reserved_kg >= 0")
    op.create_table(
        "allocations",
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("lot_id", sa.Uuid(), nullable=False),
        sa.Column("recipient_id", sa.Uuid(), nullable=False),
        sa.Column("rung", sa.String(length=2), nullable=False),
        sa.Column("quantity_kg", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("plan_version", sa.Integer(), nullable=False),
        sa.Column("strategy", sa.String(length=24), nullable=False),
        sa.Column("engine_version", sa.String(length=24), nullable=False),
        sa.Column("needed_minutes", sa.Integer(), nullable=False),
        sa.Column("eta", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delay_minutes", sa.Integer(), nullable=False),
        sa.Column("why", sa.String(length=300), nullable=False),
        sa.Column("response_reason", sa.String(length=300), nullable=False),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("received_kg", sa.Float(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("quantity_kg > 0", name="ck_alloc_qty_pos"),
        sa.ForeignKeyConstraint(["case_id"], ["recovery_cases.id"]),
        sa.ForeignKeyConstraint(["lot_id"], ["inventory_lots.id"]),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["recipient_id"], ["recipients.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for col in ("org_id", "case_id", "lot_id", "recipient_id", "status"):
        op.create_index(op.f(f"ix_allocations_{col}"), "allocations", [col], unique=False)
    op.create_index("uq_alloc_live_recipient", "allocations", ["case_id", "recipient_id"], unique=True,
                    sqlite_where=sa.text(LIVE), postgresql_where=sa.text(LIVE))


def downgrade() -> None:
    op.drop_index("uq_alloc_live_recipient", table_name="allocations")
    op.drop_table("allocations")
    with op.batch_alter_table("inventory_lots") as b:
        b.drop_constraint("ck_lot_reserved_nonneg", type_="check")
        b.drop_column("reserved_kg")
