"""add notification contact and telematics integration configuration

Revision ID: b7d4e6f8a912
Revises: a1c7e9d2f4b6
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b7d4e6f8a912"
down_revision: Union[str, None] = "a1c7e9d2f4b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("mobile_phone", sa.String(length=32), nullable=True))
    op.add_column("organization_invitations", sa.Column("mobile_phone", sa.String(length=32), nullable=True))
    op.create_table(
        "telematics_integrations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("base_url", sa.String(length=500), nullable=False),
        sa.Column("sync_path", sa.String(length=500), nullable=False),
        sa.Column("credential_ref", sa.String(length=160), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("sync_interval_minutes", sa.Integer(), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_status", sa.String(length=40), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_telematics_integrations_organization_id",
        "telematics_integrations",
        ["organization_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_telematics_integrations_organization_id", table_name="telematics_integrations")
    op.drop_table("telematics_integrations")
    op.drop_column("organization_invitations", "mobile_phone")
    op.drop_column("users", "mobile_phone")
