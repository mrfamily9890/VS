"""normalize legacy roles into the six-role model

Revision ID: 9f5a2b7c4d1e
Revises: 8e4f1a2b3c5d
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9f5a2b7c4d1e"
down_revision: Union[str, None] = "8e4f1a2b3c5d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    users = sa.table("users", sa.column("role", sa.String(length=48)))
    connection = op.get_bind()
    connection.execute(users.update().where(users.c.role.in_(("manager", "operator", "compliance_officer"))).values(role="fleet_manager"))
    connection.execute(users.update().where(users.c.role == "workshop_manager").values(role="technician"))
    connection.execute(users.update().where(users.c.role == "admin").values(role="fleet_manager"))


def downgrade() -> None:
    pass
