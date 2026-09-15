"""add organization onboarding invitations and assignments

Revision ID: 8e4f1a2b3c5d
Revises: 7d2f9a1c8e4b
"""

from typing import Sequence, Union

from alembic import op
from alembic import context
import sqlalchemy as sa


revision: str = "8e4f1a2b3c5d"
down_revision: Union[str, None] = "7d2f9a1c8e4b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    vehicle_columns = {column["name"] for column in inspector.get_columns("vehicles")}
    work_order_columns = {column["name"] for column in inspector.get_columns("work_orders")}
    if context.get_context().dialect.name == "postgresql":
        if "assigned_driver_id" not in vehicle_columns:
            op.add_column("vehicles", sa.Column("assigned_driver_id", sa.Integer(), nullable=True))
        if "fk_vehicles_assigned_driver_id_users" not in {
            foreign_key["name"] for foreign_key in inspector.get_foreign_keys("vehicles")
        }:
            op.create_foreign_key("fk_vehicles_assigned_driver_id_users", "vehicles", "users", ["assigned_driver_id"], ["id"])
        if "assigned_user_id" not in work_order_columns:
            op.add_column("work_orders", sa.Column("assigned_user_id", sa.Integer(), nullable=True))
        if "fk_work_orders_assigned_user_id_users" not in {
            foreign_key["name"] for foreign_key in inspector.get_foreign_keys("work_orders")
        }:
            op.create_foreign_key("fk_work_orders_assigned_user_id_users", "work_orders", "users", ["assigned_user_id"], ["id"])
    else:
        if "assigned_driver_id" not in vehicle_columns:
            with op.batch_alter_table("vehicles", schema=None, recreate="always") as batch_op:
                batch_op.add_column(sa.Column("assigned_driver_id", sa.Integer(), nullable=True))
                batch_op.create_foreign_key("fk_vehicles_assigned_driver_id_users", "users", ["assigned_driver_id"], ["id"])
        if "assigned_user_id" not in work_order_columns:
            with op.batch_alter_table("work_orders", schema=None, recreate="always") as batch_op:
                batch_op.add_column(sa.Column("assigned_user_id", sa.Integer(), nullable=True))
                batch_op.create_foreign_key("fk_work_orders_assigned_user_id_users", "users", ["assigned_user_id"], ["id"])
    if "organization_invitations" not in inspector.get_table_names():
        op.create_table(
            "organization_invitations",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
            sa.Column("invited_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("email", sa.String(length=255), nullable=False),
            sa.Column("full_name", sa.String(length=160), nullable=False),
            sa.Column("role", sa.String(length=48), nullable=False),
            sa.Column("token_hash", sa.String(length=64), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
    existing_indexes = {
        index["name"] for index in sa.inspect(op.get_bind()).get_indexes("organization_invitations")
    }
    if "ix_organization_invitations_organization_id" not in existing_indexes:
        op.create_index("ix_organization_invitations_organization_id", "organization_invitations", ["organization_id"])
    if "ix_organization_invitations_email" not in existing_indexes:
        op.create_index("ix_organization_invitations_email", "organization_invitations", ["email"])
    if "ix_organization_invitations_token_hash" not in existing_indexes:
        op.create_index("ix_organization_invitations_token_hash", "organization_invitations", ["token_hash"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_organization_invitations_token_hash", table_name="organization_invitations")
    op.drop_index("ix_organization_invitations_email", table_name="organization_invitations")
    op.drop_index("ix_organization_invitations_organization_id", table_name="organization_invitations")
    op.drop_table("organization_invitations")
    if context.get_context().dialect.name == "postgresql":
        op.drop_constraint("fk_work_orders_assigned_user_id_users", "work_orders", type_="foreignkey")
        op.drop_column("work_orders", "assigned_user_id")
        op.drop_constraint("fk_vehicles_assigned_driver_id_users", "vehicles", type_="foreignkey")
        op.drop_column("vehicles", "assigned_driver_id")
    else:
        with op.batch_alter_table("work_orders", schema=None, recreate="always") as batch_op:
            batch_op.drop_constraint("fk_work_orders_assigned_user_id_users", type_="foreignkey")
            batch_op.drop_column("assigned_user_id")
        with op.batch_alter_table("vehicles", schema=None, recreate="always") as batch_op:
            batch_op.drop_constraint("fk_vehicles_assigned_driver_id_users", type_="foreignkey")
            batch_op.drop_column("assigned_driver_id")
