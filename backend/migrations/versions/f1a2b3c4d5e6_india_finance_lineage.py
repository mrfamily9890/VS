"""add India finance lineage fields

Revision ID: f1a2b3c4d5e6
Revises: e7f9a1b3c5d7
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, None] = "e7f9a1b3c5d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("expenses", sa.Column("tax_category", sa.String(length=40), nullable=True))
    op.add_column("expenses", sa.Column("invoice_number", sa.String(length=80), nullable=True))
    op.add_column("expenses", sa.Column("tds_amount_paise", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("expenses", sa.Column("payment_reference", sa.String(length=120), nullable=True))


def downgrade() -> None:
    op.drop_column("expenses", "payment_reference")
    op.drop_column("expenses", "tds_amount_paise")
    op.drop_column("expenses", "invoice_number")
    op.drop_column("expenses", "tax_category")
