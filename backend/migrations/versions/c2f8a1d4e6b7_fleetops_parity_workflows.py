"""add execution, driver, and document parity workflows

Revision ID: c2f8a1d4e6b7
Revises: b7d4e6f8a912
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c2f8a1d4e6b7"
down_revision: Union[str, None] = "b7d4e6f8a912"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _index(name: str, table: str, column: str) -> None:
    op.create_index(name, table, [column])


def upgrade() -> None:
    op.create_table(
        "work_order_checklist_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("work_order_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("completed", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("completed_by", sa.Integer(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["work_order_id"], ["work_orders.id"]),
        sa.ForeignKeyConstraint(["completed_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    _index("ix_work_order_checklist_items_organization_id", "work_order_checklist_items", "organization_id")
    _index("ix_work_order_checklist_items_work_order_id", "work_order_checklist_items", "work_order_id")

    op.create_table(
        "work_order_part_usage",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("work_order_id", sa.Integer(), nullable=False),
        sa.Column("part_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_cost_paise", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["work_order_id"], ["work_orders.id"]),
        sa.ForeignKeyConstraint(["part_id"], ["parts.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    _index("ix_work_order_part_usage_organization_id", "work_order_part_usage", "organization_id")
    _index("ix_work_order_part_usage_work_order_id", "work_order_part_usage", "work_order_id")
    _index("ix_work_order_part_usage_part_id", "work_order_part_usage", "part_id")

    op.create_table(
        "work_order_evidence",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("work_order_id", sa.Integer(), nullable=False),
        sa.Column("object_key", sa.String(length=500), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=160), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("uploaded_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["work_order_id"], ["work_orders.id"]),
        sa.ForeignKeyConstraint(["uploaded_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("object_key"),
    )
    _index("ix_work_order_evidence_organization_id", "work_order_evidence", "organization_id")
    _index("ix_work_order_evidence_work_order_id", "work_order_evidence", "work_order_id")

    op.create_table(
        "driver_inspections",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("vehicle_id", sa.Integer(), nullable=False),
        sa.Column("driver_id", sa.Integer(), nullable=False),
        sa.Column("inspection_type", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("odometer_km", sa.Integer(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["vehicle_id"], ["vehicles.id"]),
        sa.ForeignKeyConstraint(["driver_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    _index("ix_driver_inspections_organization_id", "driver_inspections", "organization_id")
    _index("ix_driver_inspections_vehicle_id", "driver_inspections", "vehicle_id")
    _index("ix_driver_inspections_driver_id", "driver_inspections", "driver_id")

    op.create_table(
        "vehicle_issues",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("vehicle_id", sa.Integer(), nullable=False),
        sa.Column("driver_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("priority", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["vehicle_id"], ["vehicles.id"]),
        sa.ForeignKeyConstraint(["driver_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    _index("ix_vehicle_issues_organization_id", "vehicle_issues", "organization_id")
    _index("ix_vehicle_issues_vehicle_id", "vehicle_issues", "vehicle_id")
    _index("ix_vehicle_issues_driver_id", "vehicle_issues", "driver_id")

    op.create_table(
        "document_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("document_type", sa.String(length=80), nullable=False),
        sa.Column("expires_on", sa.String(length=20), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["document_id"], ["compliance_documents.id"]),
        sa.ForeignKeyConstraint(["asset_id"], ["document_assets.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    _index("ix_document_versions_organization_id", "document_versions", "organization_id")
    _index("ix_document_versions_document_id", "document_versions", "document_id")


def downgrade() -> None:
    for index_name, table in (
        ("ix_document_versions_document_id", "document_versions"),
        ("ix_document_versions_organization_id", "document_versions"),
        ("ix_vehicle_issues_driver_id", "vehicle_issues"),
        ("ix_vehicle_issues_vehicle_id", "vehicle_issues"),
        ("ix_vehicle_issues_organization_id", "vehicle_issues"),
        ("ix_driver_inspections_driver_id", "driver_inspections"),
        ("ix_driver_inspections_vehicle_id", "driver_inspections"),
        ("ix_driver_inspections_organization_id", "driver_inspections"),
        ("ix_work_order_evidence_work_order_id", "work_order_evidence"),
        ("ix_work_order_evidence_organization_id", "work_order_evidence"),
        ("ix_work_order_part_usage_part_id", "work_order_part_usage"),
        ("ix_work_order_part_usage_work_order_id", "work_order_part_usage"),
        ("ix_work_order_part_usage_organization_id", "work_order_part_usage"),
        ("ix_work_order_checklist_items_work_order_id", "work_order_checklist_items"),
        ("ix_work_order_checklist_items_organization_id", "work_order_checklist_items"),
    ):
        op.drop_index(index_name, table_name=table)
    for table in ("document_versions", "vehicle_issues", "driver_inspections", "work_order_evidence", "work_order_part_usage", "work_order_checklist_items"):
        op.drop_table(table)
