"""add operational history, receipts, billing lineage, and work-order metadata

Revision ID: e7f9a1b3c5d7
Revises: d4e6f8a1b2c3
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e7f9a1b3c5d7"
down_revision: Union[str, None] = "d4e6f8a1b2c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for name, column in (
        ("work_orders", sa.Column("scheduled_for", sa.DateTime(timezone=True))),
        ("work_orders", sa.Column("started_at", sa.DateTime(timezone=True))),
        ("work_orders", sa.Column("completed_at", sa.DateTime(timezone=True))),
        ("work_orders", sa.Column("archived_at", sa.DateTime(timezone=True))),
        ("work_orders", sa.Column("labor_hours", sa.Integer())),
        ("work_orders", sa.Column("repair_notes", sa.Text())),
        ("operational_notifications", sa.Column("recipient_user_id", sa.Integer())),
        ("notification_deliveries", sa.Column("error_code", sa.String(length=80))),
        ("notification_deliveries", sa.Column("error_message", sa.String(length=500))),
        ("notification_deliveries", sa.Column("attempt", sa.Integer(), nullable=False, server_default="1")),
        ("notification_deliveries", sa.Column("delivered_at", sa.DateTime(timezone=True))),
    ):
        op.add_column(name, column)

    op.create_index("ix_operational_notifications_recipient_user_id", "operational_notifications", ["recipient_user_id"])
    op.create_table(
        "vehicle_assignments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("vehicle_id", sa.Integer(), nullable=False),
        sa.Column("driver_id", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["vehicle_id"], ["vehicles.id"]),
        sa.ForeignKeyConstraint(["driver_id"], ["users.id"]),
    )
    op.create_table(
        "odometer_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("vehicle_id", sa.Integer(), nullable=False),
        sa.Column("driver_id", sa.Integer()),
        sa.Column("reading_km", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("is_flagged", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["vehicle_id"], ["vehicles.id"]),
        sa.ForeignKeyConstraint(["driver_id"], ["users.id"]),
    )
    op.create_table(
        "purchase_order_receipts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("purchase_order_id", sa.Integer(), nullable=False),
        sa.Column("part_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("damaged_quantity", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("backordered_quantity", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("variance_reason", sa.Text()),
        sa.Column("unit_cost_paise", sa.Integer(), nullable=False),
        sa.Column("invoice_number", sa.String(length=120)),
        sa.Column("location_id", sa.Integer()),
        sa.Column("received_by", sa.Integer(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["purchase_order_id"], ["purchase_orders.id"]),
        sa.ForeignKeyConstraint(["part_id"], ["parts.id"]),
        sa.ForeignKeyConstraint(["location_id"], ["stock_locations.id"]),
        sa.ForeignKeyConstraint(["received_by"], ["users.id"]),
    )
    for table, column in (
        ("vehicle_assignments", "organization_id"),
        ("vehicle_assignments", "vehicle_id"),
        ("vehicle_assignments", "driver_id"),
        ("odometer_logs", "organization_id"),
        ("odometer_logs", "vehicle_id"),
        ("purchase_order_receipts", "organization_id"),
        ("purchase_order_receipts", "purchase_order_id"),
        ("purchase_order_receipts", "part_id"),
    ):
        op.create_index(f"ix_{table}_{column}", table, [column])

    op.create_table(
        "billing_invoices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("period_start", sa.String(length=20), nullable=False),
        sa.Column("period_end", sa.String(length=20), nullable=False),
        sa.Column("plan", sa.String(length=32), nullable=False),
        sa.Column("total_paise", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="draft"),
        sa.Column("external_invoice_id", sa.String(length=160)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
    )
    op.create_table(
        "billing_payments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("invoice_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False, server_default="razorpay"),
        sa.Column("provider_payment_id", sa.String(length=160)),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("amount_paise", sa.Integer(), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True)),
        sa.Column("failure_reason", sa.String(length=500)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["invoice_id"], ["billing_invoices.id"]),
    )


def downgrade() -> None:
    op.drop_table("billing_payments")
    op.drop_table("billing_invoices")
    for table in ("purchase_order_receipts", "odometer_logs", "vehicle_assignments"):
        op.drop_table(table)
    op.drop_index("ix_operational_notifications_recipient_user_id", table_name="operational_notifications")
    for name, table in (
        ("delivered_at", "notification_deliveries"),
        ("attempt", "notification_deliveries"),
        ("error_message", "notification_deliveries"),
        ("error_code", "notification_deliveries"),
        ("recipient_user_id", "operational_notifications"),
        ("repair_notes", "work_orders"),
        ("labor_hours", "work_orders"),
        ("archived_at", "work_orders"),
        ("completed_at", "work_orders"),
        ("started_at", "work_orders"),
        ("scheduled_for", "work_orders"),
    ):
        op.drop_column(table, name)
