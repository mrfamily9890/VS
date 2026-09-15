"""add durable mutation idempotency records

Revision ID: b8c9d0e1f2a3
Revises: a2b3c4d5e6f7
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, None] = "a2b3c4d5e6f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "idempotency_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("method", sa.String(length=12), nullable=False),
        sa.Column("path", sa.String(length=240), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "user_id",
            "idempotency_key",
            "method",
            "path",
            name="uq_idempotency_scope",
        ),
    )
    op.create_index("ix_idempotency_records_organization_id", "idempotency_records", ["organization_id"])
    op.create_index("ix_idempotency_records_user_id", "idempotency_records", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_idempotency_records_user_id", table_name="idempotency_records")
    op.drop_index("ix_idempotency_records_organization_id", table_name="idempotency_records")
    op.drop_table("idempotency_records")
