"""add component service odometer fields

Revision ID: a1c7e9d2f4b6
Revises: 9f5a2b7c4d1e
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1c7e9d2f4b6"
down_revision: Union[str, None] = "9f5a2b7c4d1e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("vehicle_components", recreate="always") as batch:
        batch.add_column(sa.Column("last_service_km", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("service_interval_km", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("vehicle_components", recreate="always") as batch:
        batch.drop_column("service_interval_km")
        batch.drop_column("last_service_km")
