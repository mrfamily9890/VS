from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    subscription_plan: Mapped[str] = mapped_column(String(32), default="starter", nullable=False)
    subscription_status: Mapped[str] = mapped_column(String(24), default="trialing", nullable=False)
    trial_ends_on: Mapped[Optional[str]] = mapped_column(String(20))
    subscription_renews_on: Mapped[Optional[str]] = mapped_column(String(20))
    razorpay_subscription_id: Mapped[Optional[str]] = mapped_column(String(120))
    razorpay_last_order_id: Mapped[Optional[str]] = mapped_column(String(120))
    users: Mapped[list["User"]] = relationship(back_populates="organization")
    vehicles: Mapped[list["Vehicle"]] = relationship(back_populates="organization")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(160), nullable=False)
    mobile_phone: Mapped[Optional[str]] = mapped_column(String(32))
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    supabase_user_id: Mapped[Optional[str]] = mapped_column(String(80), unique=True, index=True)
    role: Mapped[str] = mapped_column(String(48), default="owner", nullable=False)
    token_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    organization: Mapped[Organization] = relationship(back_populates="users")

    @property
    def organization_name(self) -> str:
        return self.organization.name


class OrganizationInvitation(Base):
    __tablename__ = "organization_invitations"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    invited_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(160), nullable=False)
    mobile_phone: Mapped[Optional[str]] = mapped_column(String(32))
    role: Mapped[str] = mapped_column(String(48), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class Vehicle(Base):
    __tablename__ = "vehicles"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    registration_number: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(160), nullable=False)
    vehicle_type: Mapped[str] = mapped_column(String(80), nullable=False)
    depot: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="Idle / parked", nullable=False)
    health: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    odometer_km: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    driver_name: Mapped[Optional[str]] = mapped_column(String(160))
    assigned_driver_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    organization: Mapped[Organization] = relationship(back_populates="vehicles")


class VehicleAssignment(Base):
    __tablename__ = "vehicle_assignments"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"), nullable=False, index=True)
    driver_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class OdometerLog(Base):
    __tablename__ = "odometer_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"), nullable=False, index=True)
    driver_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), index=True)
    reading_km: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    is_flagged: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class VehicleComponent(Base):
    __tablename__ = "vehicle_components"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    component_type: Mapped[str] = mapped_column(String(80), nullable=False)
    serial_number: Mapped[Optional[str]] = mapped_column(String(120))
    installed_at_km: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_service_km: Mapped[Optional[int]] = mapped_column(Integer)
    service_interval_km: Mapped[Optional[int]] = mapped_column(Integer)
    next_service_km: Mapped[Optional[int]] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(40), default="Healthy", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class WorkOrder(Base):
    __tablename__ = "work_orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(20), default="Medium", nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="Open", nullable=False)
    due_date: Mapped[Optional[str]] = mapped_column(String(20))
    assigned_to: Mapped[Optional[str]] = mapped_column(String(160))
    assigned_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    scheduled_for: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    labor_hours: Mapped[Optional[int]] = mapped_column(Integer)
    repair_notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class WorkOrderChecklistItem(Base):
    __tablename__ = "work_order_checklist_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    work_order_id: Mapped[int] = mapped_column(ForeignKey("work_orders.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completed_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class WorkOrderPartUsage(Base):
    __tablename__ = "work_order_part_usage"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    work_order_id: Mapped[int] = mapped_column(ForeignKey("work_orders.id"), nullable=False, index=True)
    part_id: Mapped[int] = mapped_column(ForeignKey("parts.id"), nullable=False, index=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_cost_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class WorkOrderEvidence(Base):
    __tablename__ = "work_order_evidence"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    work_order_id: Mapped[int] = mapped_column(ForeignKey("work_orders.id"), nullable=False, index=True)
    object_key: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(160), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class DriverInspection(Base):
    __tablename__ = "driver_inspections"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"), nullable=False, index=True)
    driver_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    inspection_type: Mapped[str] = mapped_column(String(40), default="pre_trip", nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="SAFE", nullable=False)
    odometer_km: Mapped[int] = mapped_column(Integer, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class VehicleIssue(Base):
    __tablename__ = "vehicle_issues"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"), nullable=False, index=True)
    driver_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[str] = mapped_column(String(20), default="Medium", nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="OPEN", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class MaintenancePlan(Base):
    __tablename__ = "maintenance_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    interval_km: Mapped[Optional[int]] = mapped_column(Integer)
    interval_days: Mapped[Optional[int]] = mapped_column(Integer)
    next_due_km: Mapped[Optional[int]] = mapped_column(Integer)
    next_due_on: Mapped[Optional[str]] = mapped_column(String(20))
    active: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class Part(Base):
    __tablename__ = "parts"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    sku: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    quantity_on_hand: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reorder_level: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    unit_cost_paise: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    supplier: Mapped[Optional[str]] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class InventoryTransaction(Base):
    __tablename__ = "inventory_transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    part_id: Mapped[int] = mapped_column(ForeignKey("parts.id"), nullable=False, index=True)
    transaction_type: Mapped[str] = mapped_column(String(20), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    reference: Mapped[Optional[str]] = mapped_column(String(160))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class StockLocation(Base):
    __tablename__ = "stock_locations"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    address: Mapped[Optional[str]] = mapped_column(String(300))
    active: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class InventoryMovement(Base):
    __tablename__ = "inventory_movements"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    part_id: Mapped[int] = mapped_column(ForeignKey("parts.id"), nullable=False, index=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("stock_locations.id"), nullable=False, index=True)
    transaction_type: Mapped[str] = mapped_column(String(20), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    reference: Mapped[Optional[str]] = mapped_column(String(160))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class ComplianceDocument(Base):
    __tablename__ = "compliance_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    vehicle_id: Mapped[Optional[int]] = mapped_column(ForeignKey("vehicles.id"), index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    document_type: Mapped[str] = mapped_column(String(80), nullable=False)
    issued_by: Mapped[Optional[str]] = mapped_column(String(160))
    expires_on: Mapped[str] = mapped_column(String(20), nullable=False)
    file_key: Mapped[Optional[str]] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(30), default="Valid", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class DocumentAsset(Base):
    __tablename__ = "document_assets"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("compliance_documents.id"), nullable=False, index=True)
    object_key: Mapped[str] = mapped_column(String(500), unique=True, nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(160), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class DocumentVersion(Base):
    __tablename__ = "document_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("compliance_documents.id"), nullable=False, index=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    document_type: Mapped[str] = mapped_column(String(80), nullable=False)
    expires_on: Mapped[str] = mapped_column(String(20), nullable=False)
    asset_id: Mapped[Optional[int]] = mapped_column(ForeignKey("document_assets.id"))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class OperationalNotification(Base):
    __tablename__ = "operational_notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    recipient_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), index=True)
    notification_type: Mapped[str] = mapped_column(String(80), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    detail: Mapped[str] = mapped_column(String(500), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(80), nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(240), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), default="unread", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class NotificationPreference(Base):
    __tablename__ = "notification_preferences"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    notification_type: Mapped[str] = mapped_column(String(80), nullable=False)
    in_app: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    email: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sms: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    whatsapp: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    push: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class NotificationDelivery(Base):
    __tablename__ = "notification_deliveries"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    notification_id: Mapped[int] = mapped_column(ForeignKey("operational_notifications.id"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="queued", nullable=False)
    provider_message_id: Mapped[Optional[str]] = mapped_column(String(160))
    error_code: Mapped[Optional[str]] = mapped_column(String(80))
    error_message: Mapped[Optional[str]] = mapped_column(String(500))
    attempt: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "user_id",
            "idempotency_key",
            "method",
            "path",
            name="uq_idempotency_scope",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    method: Mapped[str] = mapped_column(String(12), nullable=False)
    path: Mapped[str] = mapped_column(String(240), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class Expense(Base):
    __tablename__ = "expenses"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    vehicle_id: Mapped[Optional[int]] = mapped_column(ForeignKey("vehicles.id"), index=True)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str] = mapped_column(String(240), nullable=False)
    amount_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    gst_amount_paise: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cgst_amount_paise: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sgst_amount_paise: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    igst_amount_paise: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    incurred_on: Mapped[str] = mapped_column(String(20), nullable=False)
    vendor: Mapped[Optional[str]] = mapped_column(String(160))
    gstin: Mapped[Optional[str]] = mapped_column(String(20))
    tax_category: Mapped[Optional[str]] = mapped_column(String(40))
    invoice_number: Mapped[Optional[str]] = mapped_column(String(80))
    tds_amount_paise: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_center: Mapped[Optional[str]] = mapped_column(String(120))
    payment_mode: Mapped[Optional[str]] = mapped_column(String(40))
    payment_reference: Mapped[Optional[str]] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(30), default="Approved", nullable=False)
    approved_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class FuelTransaction(Base):
    __tablename__ = "fuel_transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"), nullable=False, index=True)
    station: Mapped[Optional[str]] = mapped_column(String(160))
    fuel_type: Mapped[str] = mapped_column(String(40), nullable=False)
    litres_milli: Mapped[int] = mapped_column(Integer, nullable=False)
    price_per_litre_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    total_amount_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    odometer_km: Mapped[int] = mapped_column(Integer, nullable=False)
    incurred_on: Mapped[str] = mapped_column(String(20), nullable=False)
    reference: Mapped[Optional[str]] = mapped_column(String(120))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class TollTransaction(Base):
    __tablename__ = "toll_transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"), nullable=False, index=True)
    toll_operator: Mapped[Optional[str]] = mapped_column(String(160))
    plaza: Mapped[str] = mapped_column(String(160), nullable=False)
    amount_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    incurred_on: Mapped[str] = mapped_column(String(20), nullable=False)
    tag_reference: Mapped[Optional[str]] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(30), default="Approved", nullable=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class TelematicsIntegration(Base):
    __tablename__ = "telematics_integrations"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    sync_path: Mapped[str] = mapped_column(String(500), default="/readings", nullable=False)
    credential_ref: Mapped[Optional[str]] = mapped_column(String(160))
    active: Mapped[bool] = mapped_column(default=True, nullable=False)
    sync_interval_minutes: Mapped[int] = mapped_column(Integer, default=1440, nullable=False)
    last_synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_sync_status: Mapped[Optional[str]] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class TelematicsDevice(Base):
    __tablename__ = "telematics_devices"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    device_identifier: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    active: Mapped[bool] = mapped_column(default=True, nullable=False)
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class TelemetryReading(Base):
    __tablename__ = "telemetry_readings"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"), nullable=False, index=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("telematics_devices.id"), nullable=False, index=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    odometer_km: Mapped[Optional[int]] = mapped_column(Integer)
    latitude_e6: Mapped[Optional[int]] = mapped_column(Integer)
    longitude_e6: Mapped[Optional[int]] = mapped_column(Integer)
    speed_kph: Mapped[Optional[int]] = mapped_column(Integer)
    fuel_level_percent: Mapped[Optional[int]] = mapped_column(Integer)
    engine_on: Mapped[Optional[bool]] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class Vendor(Base):
    __tablename__ = "vendors"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    vendor_type: Mapped[str] = mapped_column(String(80), nullable=False)
    gstin: Mapped[Optional[str]] = mapped_column(String(20))
    contact_name: Mapped[Optional[str]] = mapped_column(String(160))
    phone: Mapped[Optional[str]] = mapped_column(String(40))
    email: Mapped[Optional[str]] = mapped_column(String(255))
    address: Mapped[Optional[str]] = mapped_column(String(300))
    active: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    vendor_id: Mapped[int] = mapped_column(ForeignKey("vendors.id"), nullable=False, index=True)
    order_number: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), default="Draft", nullable=False)
    expected_on: Mapped[Optional[str]] = mapped_column(String(20))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    total_paise: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    lines: Mapped[list["PurchaseOrderLine"]] = relationship(back_populates="purchase_order", cascade="all, delete-orphan")


class PurchaseOrderLine(Base):
    __tablename__ = "purchase_order_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    purchase_order_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id"), nullable=False, index=True)
    part_id: Mapped[int] = mapped_column(ForeignKey("parts.id"), nullable=False, index=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_cost_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    line_total_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    purchase_order: Mapped[PurchaseOrder] = relationship(back_populates="lines")


class PurchaseOrderReceipt(Base):
    __tablename__ = "purchase_order_receipts"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    purchase_order_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id"), nullable=False, index=True)
    part_id: Mapped[int] = mapped_column(ForeignKey("parts.id"), nullable=False, index=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    damaged_quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    backordered_quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    variance_reason: Mapped[Optional[str]] = mapped_column(Text)
    unit_cost_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    invoice_number: Mapped[Optional[str]] = mapped_column(String(120))
    location_id: Mapped[Optional[int]] = mapped_column(ForeignKey("stock_locations.id"))
    received_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class BillingInvoice(Base):
    __tablename__ = "billing_invoices"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    period_start: Mapped[str] = mapped_column(String(20), nullable=False)
    period_end: Mapped[str] = mapped_column(String(20), nullable=False)
    plan: Mapped[str] = mapped_column(String(32), nullable=False)
    total_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="draft", nullable=False)
    external_invoice_id: Mapped[Optional[str]] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class BillingPayment(Base):
    __tablename__ = "billing_payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("billing_invoices.id"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(40), default="razorpay", nullable=False)
    provider_payment_id: Mapped[Optional[str]] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    amount_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    failure_reason: Mapped[Optional[str]] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    actor_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(80), nullable=False)
    request_id: Mapped[Optional[str]] = mapped_column(String(80))
    changes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
