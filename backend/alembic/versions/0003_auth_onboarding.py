"""account status lifecycle + invitations

Additive only. Existing users are backfilled safely: status defaults to ACTIVE, and users that were
already deactivated (is_active = false) become DISABLED. Nothing is dropped or rewritten.

Revision ID: 0003
Revises: 0002
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as b:
        b.add_column(sa.Column("status", sa.String(length=16), nullable=False, server_default="ACTIVE"))
        b.add_column(sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True))
        b.add_column(sa.Column("requested_role", sa.String(length=24), nullable=True))
        b.add_column(sa.Column("decided_by", sa.Uuid(), nullable=True))
        b.add_column(sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True))
        b.add_column(sa.Column("decision_note", sa.String(length=200), nullable=True))
        b.create_index("ix_users_status", ["status"])
    op.execute("UPDATE users SET status = 'DISABLED' WHERE is_active = false")
    op.create_table(
        "invitations",
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("role", sa.String(length=24), nullable=False),
        sa.Column("recipient_id", sa.Uuid(), nullable=True),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("max_uses", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("use_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("requires_approval", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("last_used_by", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["recipient_id"], ["recipients.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_invitations_org_id", "invitations", ["org_id"])
    op.create_index("ix_invitations_email", "invitations", ["email"])
    op.create_index("ix_invitations_recipient_id", "invitations", ["recipient_id"])


def downgrade() -> None:
    op.drop_table("invitations")
    with op.batch_alter_table("users") as b:
        b.drop_index("ix_users_status")
        for c in ("decision_note", "decided_at", "decided_by", "requested_role", "email_verified_at", "status"):
            b.drop_column(c)
