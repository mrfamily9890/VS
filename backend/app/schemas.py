from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class IdentityProviderMetadata(BaseModel):
    enabled: bool
    issuer: str | None
    client_id: str | None
    local_login_available: bool = True


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)


class OrganizationSignup(BaseModel):
    organization_name: str = Field(min_length=2, max_length=160)
    full_name: str = Field(min_length=2, max_length=160)
    email: EmailStr
    mobile_phone: str | None = Field(default=None, max_length=32)
    password: str = Field(min_length=8)


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    full_name: str
    mobile_phone: str | None = None
    role: str
    organization_id: int
    organization_name: str
    assigned_driver_id: int | None = None


class OrganizationSignupRead(BaseModel):
    organization_id: int
    organization_name: str
    organization_slug: str
    user: UserRead
    access_token: str
    token_type: str = "bearer"


class InvitationCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=160)
    mobile_phone: str | None = Field(default=None, max_length=32)
    role: str = Field(pattern=r"^(fleet_manager|inventory_manager|driver|mechanic|technician|accountant)$")
    expires_in_days: int = Field(default=7, ge=1, le=30)


class InvitationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    full_name: str
    role: str
    expires_at: datetime
    accepted_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


class InvitationAccept(BaseModel):
    token: str = Field(min_length=32)
    password: str = Field(min_length=8)
    full_name: str | None = Field(default=None, min_length=2, max_length=160)
    mobile_phone: str | None = Field(default=None, max_length=32)


class InvitationPreview(BaseModel):
    organization_name: str
    email: EmailStr
    full_name: str
    mobile_phone: str | None
    role: str
    expires_at: datetime


class InvitationAcceptRead(BaseModel):
    organization_name: str
    user: UserRead
    access_token: str
    token_type: str = "bearer"


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=160)
    mobile_phone: str | None = Field(default=None, max_length=32)
    password: str = Field(min_length=8)
    role: str = Field(pattern=r"^(fleet_manager|inventory_manager|driver|mechanic|technician|accountant)$")


class UserRoleUpdate(BaseModel):
    role: str = Field(pattern=r"^(fleet_manager|inventory_manager|driver|mechanic|technician|accountant)$")


class AuditLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    actor_user_id: int
    action: str
    entity_type: str
    entity_id: str
    request_id: str | None
    changes: str | None
    created_at: datetime


class FleetOperationsSummaryRead(BaseModel):
    active_vehicles: int
    total_vehicles: int
    open_work_orders: int
    overdue_work_orders: int
    due_components: int
    compliance_due: int
    low_stock_parts: int
    unassigned_vehicles: int


class FleetAnalyticsVehicleRead(BaseModel):
    vehicle_id: int
    maintenance_cost_paise: int
    cost_per_km_paise: int
    downtime_days: int
    odometer_km: int


class FleetAnalyticsRead(BaseModel):
    vehicles: list[FleetAnalyticsVehicleRead]
    odometer_anomalies: int


class UserContactUpdate(BaseModel):
    mobile_phone: str | None = Field(default=None, max_length=32)


class UserProfileUpdate(BaseModel):
    full_name: str = Field(min_length=2, max_length=160)
    mobile_phone: str | None = Field(default=None, max_length=32)


class NotificationPreferenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    notification_type: str
    in_app: bool
    email: bool
    sms: bool
    whatsapp: bool
    push: bool


class NotificationPreferenceUpdate(BaseModel):
    notification_type: str = Field(min_length=2, max_length=80)
    in_app: bool = True
    email: bool = False
    sms: bool = False
    whatsapp: bool = False
    push: bool = False


class NotificationDeliveryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    notification_id: int
    user_id: int
    channel: str
    status: str
    provider_message_id: str | None
    error_code: str | None
    error_message: str | None
    attempt: int
    sent_at: datetime | None
    delivered_at: datetime | None


class SubscriptionPlanRead(BaseModel):
    code: str
    name: str
    monthly_price_paise: int | None
    included_vehicles: int | None
    included_users: int | None
    overage_vehicle_fee_paise: int
    min_vehicles: int
    max_vehicles: int
    description: str
    features: list[str]


class SubscriptionRead(BaseModel):
    plan: SubscriptionPlanRead
    status: str
    trial_ends_on: str | None
    renews_on: str | None
    vehicle_count: int
    user_count: int
    overage_vehicles: int
    estimated_subtotal_paise: int


class SubscriptionChange(BaseModel):
    plan_code: str = Field(pattern=r"^(starter|growth|scale|enterprise)$")


class SubscriptionCheckoutRead(BaseModel):
    subscription_id: str
    plan_code: str
    razorpay_key_id: str
    short_url: str | None = None


class RazorpaySubscriptionVerify(BaseModel):
    razorpay_payment_id: str
    razorpay_subscription_id: str
    razorpay_signature: str


class BillingInvoiceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organization_id: int
    period_start: str
    period_end: str
    plan: str
    total_paise: int
    status: str
    external_invoice_id: str | None
    created_at: datetime


class BillingPaymentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organization_id: int
    invoice_id: int
    provider: str
    provider_payment_id: str | None
    status: str
    amount_paise: int
    paid_at: datetime | None
    failure_reason: str | None
    created_at: datetime


class RazorpayWebhookPayload(BaseModel):
    event: str


class VehicleCreate(BaseModel):
    registration_number: str = Field(min_length=3, max_length=32)
    model: str = Field(min_length=2, max_length=160)
    vehicle_type: str = Field(min_length=2, max_length=80)
    depot: str = Field(min_length=2, max_length=120)
    status: str = "Idle / parked"
    health: int = Field(default=100, ge=0, le=100)
    odometer_km: int = Field(default=0, ge=0)
    driver_name: str | None = None
    assigned_driver_id: int | None = None


class VehicleRead(VehicleCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organization_id: int
    created_at: datetime


class ComponentCreate(BaseModel):
    vehicle_id: int
    name: str = Field(min_length=2, max_length=160)
    component_type: str = Field(min_length=2, max_length=80)
    serial_number: str | None = None
    installed_at_km: int = Field(default=0, ge=0)
    last_service_km: int | None = Field(default=None, ge=0)
    service_interval_km: int | None = Field(default=None, gt=0)
    next_service_km: int | None = Field(default=None, ge=0)
    status: str = "Healthy"


class ComponentRead(ComponentCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organization_id: int
    created_at: datetime


class ComponentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    component_type: str | None = Field(default=None, min_length=2, max_length=80)
    serial_number: str | None = None
    installed_at_km: int | None = Field(default=None, ge=0)
    last_service_km: int | None = Field(default=None, ge=0)
    service_interval_km: int | None = Field(default=None, gt=0)
    next_service_km: int | None = Field(default=None, ge=0)
    status: str | None = None


class VehicleUpdate(BaseModel):
    model: str | None = Field(default=None, min_length=2, max_length=160)
    vehicle_type: str | None = Field(default=None, min_length=2, max_length=80)
    depot: str | None = Field(default=None, min_length=2, max_length=120)
    status: str | None = None
    health: int | None = Field(default=None, ge=0, le=100)
    odometer_km: int | None = Field(default=None, ge=0)
    driver_name: str | None = None
    assigned_driver_id: int | None = None


class VehicleAssignmentCreate(BaseModel):
    vehicle_id: int
    driver_id: int


class VehicleAssignmentRead(VehicleAssignmentCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organization_id: int
    active: bool
    created_at: datetime
    ended_at: datetime | None


class OdometerLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organization_id: int
    vehicle_id: int
    driver_id: int | None
    reading_km: int
    source: str
    is_flagged: bool
    created_at: datetime


class WorkOrderCreate(BaseModel):
    vehicle_id: int
    title: str = Field(min_length=2, max_length=200)
    description: str | None = None
    priority: str = "Medium"
    status: str = Field(default="Open", pattern=r"^(Draft|Open|Assigned|Scheduled|In progress|Ready for review|Completed|Closed|Archived)$")
    due_date: str | None = None
    assigned_to: str | None = None
    assigned_user_id: int | None = None
    scheduled_for: datetime | None = None
    labor_hours: int | None = Field(default=None, ge=0)
    repair_notes: str | None = None


class WorkOrderRead(WorkOrderCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organization_id: int
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    archived_at: datetime | None


class WorkOrderUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=200)
    status: str | None = Field(default=None, pattern=r"^(Draft|Open|Assigned|Scheduled|In progress|Ready for review|Completed|Closed|Archived)$")
    priority: str | None = None
    due_date: str | None = None
    assigned_to: str | None = None
    description: str | None = None
    scheduled_for: datetime | None = None
    labor_hours: int | None = Field(default=None, ge=0)
    repair_notes: str | None = None


class WorkOrderChecklistItemCreate(BaseModel):
    title: str = Field(min_length=2, max_length=240)
    completed: bool = False
    sort_order: int = Field(default=0, ge=0)


class WorkOrderChecklistItemRead(WorkOrderChecklistItemCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    work_order_id: int
    completed_by: int | None
    completed_at: datetime | None


class WorkOrderChecklistUpdate(BaseModel):
    items: list[WorkOrderChecklistItemCreate] = Field(min_length=1, max_length=50)


class WorkOrderPartUsageCreate(BaseModel):
    part_id: int
    quantity: int = Field(gt=0)


class WorkOrderPartUsageRead(WorkOrderPartUsageCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    work_order_id: int
    unit_cost_paise: int
    created_by: int
    created_at: datetime


class WorkOrderEvidenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organization_id: int
    work_order_id: int
    object_key: str
    file_name: str
    content_type: str
    size_bytes: int
    uploaded_by: int
    created_at: datetime


class DriverInspectionCreate(BaseModel):
    vehicle_id: int
    inspection_type: str = Field(default="pre_trip", pattern=r"^(pre_trip|post_trip)$")
    status: str = Field(default="SAFE", pattern=r"^(SAFE|UNSAFE|REVIEW)$")
    odometer_km: int = Field(ge=0)
    notes: str | None = Field(default=None, max_length=2000)


class DriverInspectionRead(DriverInspectionCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organization_id: int
    driver_id: int
    created_at: datetime


class VehicleIssueCreate(BaseModel):
    vehicle_id: int
    title: str = Field(min_length=2, max_length=200)
    detail: str = Field(min_length=3, max_length=5000)
    priority: str = Field(default="Medium", pattern=r"^(Low|Medium|High|Critical)$")


class VehicleIssueRead(VehicleIssueCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organization_id: int
    driver_id: int
    status: str
    created_at: datetime
    resolved_at: datetime | None


class NotificationResolve(BaseModel):
    status: str = Field(pattern=r"^(read|resolved)$")


class ExpenseReversal(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class MaintenancePlanCreate(BaseModel):
    vehicle_id: int
    name: str = Field(min_length=2, max_length=200)
    interval_km: int | None = Field(default=None, gt=0)
    interval_days: int | None = Field(default=None, gt=0)
    next_due_km: int | None = Field(default=None, ge=0)
    next_due_on: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    active: bool = True


class MaintenancePlanRead(MaintenancePlanCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organization_id: int
    created_at: datetime


class PartCreate(BaseModel):
    sku: str = Field(min_length=2, max_length=80)
    name: str = Field(min_length=2, max_length=200)
    category: str = Field(min_length=2, max_length=80)
    quantity_on_hand: int = Field(default=0, ge=0)
    reorder_level: int = Field(default=0, ge=0)
    unit_cost_paise: int = Field(default=0, ge=0)
    supplier: str | None = None


class PartRead(PartCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organization_id: int
    created_at: datetime


class InventoryTransactionCreate(BaseModel):
    part_id: int
    transaction_type: str = Field(pattern="^(receipt|issue|adjustment)$")
    quantity: int = Field(gt=0)
    reference: str | None = None


class InventoryTransactionRead(InventoryTransactionCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organization_id: int
    created_by: int
    created_at: datetime


class StockLocationCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    code: str = Field(min_length=2, max_length=40)
    address: str | None = None
    active: bool = True


class StockLocationRead(StockLocationCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organization_id: int
    created_at: datetime


class InventoryMovementCreate(InventoryTransactionCreate):
    location_id: int


class InventoryMovementRead(InventoryMovementCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organization_id: int
    created_by: int
    created_at: datetime


class DocumentCreate(BaseModel):
    vehicle_id: int | None = None
    name: str = Field(min_length=2, max_length=200)
    document_type: str = Field(min_length=2, max_length=80)
    issued_by: str | None = None
    expires_on: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    file_key: str | None = None
    status: str = "Valid"


class DocumentRead(DocumentCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organization_id: int
    created_at: datetime


class DocumentAssetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organization_id: int
    document_id: int
    object_key: str
    file_name: str
    content_type: str
    size_bytes: int
    checksum_sha256: str
    uploaded_by: int
    created_at: datetime


class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organization_id: int
    recipient_user_id: int | None
    notification_type: str
    severity: str
    title: str
    detail: str
    entity_type: str
    entity_id: str
    dedupe_key: str
    status: str
    created_at: datetime
    resolved_at: datetime | None


class NotificationStatusUpdate(BaseModel):
    status: str = Field(pattern="^(unread|read|dismissed|resolved)$")


class ExpenseCreate(BaseModel):
    vehicle_id: int | None = None
    category: str = Field(min_length=2, max_length=80)
    description: str = Field(min_length=2, max_length=240)
    amount_paise: int = Field(gt=0)
    gst_amount_paise: int = Field(default=0, ge=0)
    cgst_amount_paise: int = Field(default=0, ge=0)
    sgst_amount_paise: int = Field(default=0, ge=0)
    igst_amount_paise: int = Field(default=0, ge=0)
    incurred_on: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    vendor: str | None = None
    gstin: str | None = Field(default=None, max_length=20)
    tax_category: str | None = Field(default=None, max_length=40)
    invoice_number: str | None = Field(default=None, max_length=80)
    tds_amount_paise: int = Field(default=0, ge=0)
    cost_center: str | None = Field(default=None, max_length=120)
    payment_mode: str | None = Field(default=None, max_length=40)
    payment_reference: str | None = Field(default=None, max_length=120)
    status: str = Field(default="Pending", pattern="^(Pending|Approved|Rejected)$")


class ExpenseRead(ExpenseCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organization_id: int
    approved_by: int | None
    approved_at: datetime | None
    created_at: datetime


class ExpenseStatusUpdate(BaseModel):
    status: str = Field(pattern="^(Pending|Approved|Rejected)$")


class FinanceSummaryRead(BaseModel):
    period: str
    expense_amount_paise: int
    fuel_amount_paise: int
    toll_amount_paise: int
    total_amount_paise: int
    gst_amount_paise: int


class FuelTransactionCreate(BaseModel):
    vehicle_id: int
    station: str | None = None
    fuel_type: str = Field(min_length=2, max_length=40)
    litres_milli: int = Field(gt=0)
    price_per_litre_paise: int = Field(gt=0)
    odometer_km: int = Field(ge=0)
    incurred_on: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    reference: str | None = None


class FuelTransactionRead(FuelTransactionCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organization_id: int
    total_amount_paise: int
    created_by: int
    created_at: datetime


class TollTransactionCreate(BaseModel):
    vehicle_id: int
    toll_operator: str | None = None
    plaza: str = Field(min_length=2, max_length=160)
    amount_paise: int = Field(gt=0)
    incurred_on: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    tag_reference: str | None = None
    status: str = Field(default="Approved", pattern="^(Pending|Approved|Rejected)$")


class TollTransactionRead(TollTransactionCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organization_id: int
    created_by: int
    created_at: datetime


class TelematicsDeviceCreate(BaseModel):
    vehicle_id: int
    provider: str = Field(min_length=2, max_length=80)
    device_identifier: str = Field(min_length=2, max_length=160)
    active: bool = True


class TelematicsDeviceRead(TelematicsDeviceCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organization_id: int
    last_seen_at: datetime | None
    created_at: datetime


class TelemetryReadingCreate(BaseModel):
    recorded_at: datetime
    odometer_km: int | None = Field(default=None, ge=0)
    latitude_e6: int | None = Field(default=None, ge=-90_000_000, le=90_000_000)
    longitude_e6: int | None = Field(default=None, ge=-180_000_000, le=180_000_000)
    speed_kph: int | None = Field(default=None, ge=0, le=300)
    fuel_level_percent: int | None = Field(default=None, ge=0, le=100)
    engine_on: bool | None = None


class TelemetryReadingRead(TelemetryReadingCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organization_id: int
    vehicle_id: int
    device_id: int
    created_at: datetime


class TelematicsIntegrationCreate(BaseModel):
    provider: str = Field(min_length=2, max_length=80)
    base_url: str = Field(min_length=8, max_length=500)
    sync_path: str = Field(default="/readings", min_length=1, max_length=500)
    credential_ref: str | None = Field(default=None, max_length=160)
    active: bool = True
    sync_interval_minutes: int = Field(default=1440, ge=15, le=10080)


class TelematicsIntegrationRead(TelematicsIntegrationCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organization_id: int
    last_synced_at: datetime | None
    last_sync_status: str | None
    created_at: datetime


class TelematicsHealthRead(BaseModel):
    active_integrations: int
    stale_integrations: int
    active_devices: int
    stale_devices: int
    readings_last_24h: int
    flagged_odometer_readings: int


class DocumentVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organization_id: int
    document_id: int
    version_number: int
    name: str
    document_type: str
    expires_on: str
    asset_id: int | None
    created_by: int
    created_at: datetime


class VendorCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    vendor_type: str = Field(min_length=2, max_length=80)
    gstin: str | None = Field(default=None, max_length=20)
    contact_name: str | None = None
    phone: str | None = None
    email: EmailStr | None = None
    address: str | None = None
    active: bool = True


class VendorRead(VendorCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organization_id: int
    created_at: datetime


class PurchaseOrderLineCreate(BaseModel):
    part_id: int
    quantity: int = Field(gt=0)
    unit_cost_paise: int = Field(gt=0)


class PurchaseOrderCreate(BaseModel):
    vendor_id: int
    expected_on: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    notes: str | None = None
    lines: list[PurchaseOrderLineCreate] = Field(min_length=1)


class PurchaseOrderLineRead(PurchaseOrderLineCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    line_total_paise: int


class PurchaseOrderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organization_id: int
    vendor_id: int
    order_number: str
    status: str
    expected_on: str | None
    notes: str | None
    total_paise: int
    created_by: int
    created_at: datetime
    lines: list[PurchaseOrderLineRead] = Field(default_factory=list)


class PurchaseOrderStatusUpdate(BaseModel):
    status: str = Field(pattern="^(Draft|Submitted|Approved|Partially received|Received|Cancelled)$")


class PurchaseOrderReceiptCreate(BaseModel):
    part_id: int
    quantity: int = Field(gt=0)
    damaged_quantity: int = Field(default=0, ge=0)
    backordered_quantity: int = Field(default=0, ge=0)
    variance_reason: str | None = None
    unit_cost_paise: int = Field(gt=0)
    invoice_number: str | None = None
    location_id: int | None = None


class PurchaseOrderReceiptRead(PurchaseOrderReceiptCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organization_id: int
    purchase_order_id: int
    received_by: int
    received_at: datetime


class DocumentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    document_type: str | None = Field(default=None, min_length=2, max_length=80)
    issued_by: str | None = None
    expires_on: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    file_key: str | None = None
    status: str | None = None
