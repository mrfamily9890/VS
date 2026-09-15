"""backfill fourteen day organisation trials

Revision ID: d4e6f8a1b2c3
Revises: c2f8a1d4e6b7
"""

from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa


revision: str = "d4e6f8a1b2c3"
down_revision: Union[str, None] = "c2f8a1d4e6b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if context.get_context().dialect.name == "postgresql":
        op.execute(
            sa.text(
                "UPDATE organizations "
                "SET trial_ends_on = (CURRENT_DATE + INTERVAL '14 days')::text "
                "WHERE trial_ends_on IS NULL AND subscription_status = 'trialing'"
            )
        )
    else:
        op.execute(
            sa.text(
                "UPDATE organizations "
                "SET trial_ends_on = date('now', '+14 day') "
                "WHERE trial_ends_on IS NULL AND subscription_status = 'trialing'"
            )
        )


def downgrade() -> None:
    pass
