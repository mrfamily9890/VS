"""add GST component lineage fields

Revision ID: a2b3c4d5e6f7
Revises: f1a2b3c4d5e6
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a2b3c4d5e6f7"
down_revision: Union[str, None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("expenses", sa.Column("cgst_amount_paise", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("expenses", sa.Column("sgst_amount_paise", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("expenses", sa.Column("igst_amount_paise", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("expenses", "igst_amount_paise")
    op.drop_column("expenses", "sgst_amount_paise")
    op.drop_column("expenses", "cgst_amount_paise")
