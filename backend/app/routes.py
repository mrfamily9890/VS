import hashlib
import hmac
import csv
import io
import ipaddress
import json
import os
import re
import secrets
import socket
from html import escape
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .config import get_settings
from .database import get_db
from .dependencies import get_current_user, require_permission, require_roles
from .models import AuditLog, BillingInvoice, BillingPayment, ComplianceDocument, DocumentAsset, DocumentVersion, DriverInspection, Expense, FuelTransaction, IdempotencyRecord, InventoryMovement, InventoryTransaction, MaintenancePlan, NotificationPreference, NotificationDelivery, OdometerLog, OperationalNotification, Organization, OrganizationInvitation, Part, PurchaseOrder, PurchaseOrderLine, PurchaseOrderReceipt, StockLocation, TelematicsDevice, TelematicsIntegration, TelemetryReading, TollTransaction, User, Vehicle, VehicleAssignment, VehicleComponent, VehicleIssue, Vendor, WorkOrder, WorkOrderChecklistItem, WorkOrderEvidence, WorkOrderPartUsage, utc_now
from .security import create_access_token, hash_password, provision_supabase_user, verify_password
from .schemas import (
    ComponentCreate,
    ComponentRead,
    ComponentUpdate,
    DriverInspectionCreate,
    DriverInspectionRead,
    DocumentCreate,
    DocumentAssetRead,
    DocumentVersionRead,
    DocumentRead,
    DocumentUpdate,
    ExpenseCreate,
    ExpenseRead,
    ExpenseStatusUpdate,
    ExpenseReversal,
    FinanceSummaryRead,
    FleetAnalyticsRead,
    FleetAnalyticsVehicleRead,
    FleetOperationsSummaryRead,
    FuelTransactionCreate,
    FuelTransactionRead,
    IdentityProviderMetadata,
    InvitationAccept,
    InvitationAcceptRead,
    InvitationCreate,
    InvitationRead,
    InventoryTransactionCreate,
    InventoryTransactionRead,
    InventoryMovementCreate,
    InventoryMovementRead,
    LoginRequest,
    OrganizationSignup,
    OrganizationSignupRead,
    MaintenancePlanCreate,
    MaintenancePlanRead,
    NotificationRead,
    NotificationPreferenceRead,
    NotificationPreferenceUpdate,
    NotificationDeliveryRead,
    NotificationStatusUpdate,
    PartCreate,
    PartRead,
    PurchaseOrderCreate,
    PurchaseOrderReceiptCreate,
    PurchaseOrderReceiptRead,
    PurchaseOrderRead,
    PurchaseOrderStatusUpdate,
    StockLocationCreate,
    StockLocationRead,
    TollTransactionCreate,
    TollTransactionRead,
    TelematicsDeviceCreate,
    TelematicsDeviceRead,
    TelematicsHealthRead,
    TelematicsIntegrationCreate,
    TelematicsIntegrationRead,
    TelemetryReadingCreate,
    TelemetryReadingRead,
    Token,
    SubscriptionChange,
    SubscriptionPlanRead,
    SubscriptionRead,
    SubscriptionCheckoutRead,
    RazorpaySubscriptionVerify,
    UserRead,
    UserCreate,
    UserContactUpdate,
    UserProfileUpdate,
    UserRoleUpdate,
    AuditLogRead,
    BillingInvoiceRead,
    BillingPaymentRead,
    VehicleCreate,
    VehicleAssignmentCreate,
    VehicleAssignmentRead,
    VehicleRead,
    VehicleUpdate,
    VendorCreate,
    VendorRead,
    WorkOrderCreate,
    WorkOrderChecklistItemRead,
    WorkOrderChecklistUpdate,
    WorkOrderEvidenceRead,
    WorkOrderPartUsageCreate,
    WorkOrderPartUsageRead,
    WorkOrderRead,
    WorkOrderUpdate,
    OdometerLogRead,
    VehicleIssueCreate,
    VehicleIssueRead,
)
from .storage import download_object, resolve_object, save_upload

router = APIRouter(prefix="/api/v1")
MAX_IMPORT_BYTES = 2_000_000
MAX_IMPORT_ROWS = 10_000


def validate_telematics_url(value: str, *, resolve_host: bool = False) -> None:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Telematics URL must be an HTTP(S) URL without embedded credentials")
    hostname = parsed.hostname.lower().rstrip(".")
    if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith(".local"):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Telematics URL cannot target a local host")
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(hostname, parsed.port, type=socket.SOCK_STREAM)}
    except socket.gaierror as error:
        if resolve_host:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Telematics host could not be resolved") from error
        return
    for address in addresses:
        parsed_address = ipaddress.ip_address(address)
        if (
            parsed_address.is_private
            or parsed_address.is_loopback
            or parsed_address.is_link_local
            or parsed_address.is_multicast
            or parsed_address.is_reserved
            or parsed_address.is_unspecified
        ):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Telematics URL cannot target a private or reserved network")


def reserve_idempotency_key(request: Request, user: User, database: Session) -> None:
    key = request.headers.get("Idempotency-Key")
    if not key:
        return
    if len(key) > 160:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Idempotency-Key is too long")
    method = request.method.upper()
    path = request.url.path
    existing = database.scalar(select(IdempotencyRecord).where(
        IdempotencyRecord.organization_id == user.organization_id,
        IdempotencyRecord.user_id == user.id,
        IdempotencyRecord.idempotency_key == key,
        IdempotencyRecord.method == method,
        IdempotencyRecord.path == path,
    ))
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Idempotency-Key has already been used")
    database.add(IdempotencyRecord(
        organization_id=user.organization_id,
        user_id=user.id,
        idempotency_key=key,
        method=method,
        path=path,
    ))
    database.flush()

SUBSCRIPTION_PLANS = {
    "starter": {
        "code": "starter",
        "name": "Starter",
        "monthly_price_paise": 299900,
        "included_vehicles": 3,
        "overage_vehicle_fee_paise": 50000,
        "min_vehicles": 1,
        "max_vehicles": 10,
        "included_users": 999999,
        "description": "For small operators and pilots.",
        "features": ["Fleet register", "Maintenance", "Compliance vault", "Basic finance", "3 vehicles included"],
    },
    "growth": {
        "code": "growth",
        "name": "Growth",
        "monthly_price_paise": 999900,
        "included_vehicles": 15,
        "overage_vehicle_fee_paise": 45000,
        "min_vehicles": 11,
        "max_vehicles": 49,
        "included_users": 999999,
        "description": "For growing regional fleets.",
        "features": ["Everything in Starter", "15 vehicles included", "Workshop inventory", "Procurement", "Fuel and toll", "Notifications"],
    },
    "scale": {
        "code": "scale",
        "name": "Scale",
        "monthly_price_paise": 2499900,
        "included_vehicles": 50,
        "overage_vehicle_fee_paise": 35000,
        "min_vehicles": 50,
        "max_vehicles": 99,
        "included_users": 999999,
        "description": "For multi-depot operators.",
        "features": ["Everything in Growth", "50 vehicles included", "Telematics", "Advanced finance", "Multi-depot controls", "Priority support"],
    },
    "enterprise": {
        "code": "enterprise",
        "name": "Enterprise",
        "monthly_price_paise": None,
        "included_vehicles": 100,
        "overage_vehicle_fee_paise": 30000,
        "min_vehicles": 100,
        "max_vehicles": 999999,
        "included_users": 999999,
        "description": "For large fleets with custom service and integrations.",
        "features": ["Custom fleet volume", "SSO", "Dedicated onboarding", "Custom integrations", "SLA"],
    },
}


def calculate_monthly_bill(plan: dict, vehicle_count: int) -> dict[str, int]:
    billable_vehicles = max(0, vehicle_count)
    included_vehicles = int(plan["included_vehicles"])
    overage_vehicles = max(0, billable_vehicles - included_vehicles)
    platform_fee = int(plan["monthly_price_paise"] or 0)
    overage = overage_vehicles * int(plan["overage_vehicle_fee_paise"])
    return {
        "billable_vehicles": billable_vehicles,
        "overage_vehicles": overage_vehicles,
        "platform_fee_paise": platform_fee,
        "overage_paise": overage,
        "estimated_subtotal_paise": platform_fee + overage,
    }


def organization_slug(name: str, database: Session) -> str:
    base = "-".join("".join(character.lower() if character.isalnum() else "-" for character in name).split("-"))
    base = base.strip("-") or "organization"
    slug = base
    suffix = 2
    while database.scalar(select(Organization).where(Organization.slug == slug)) is not None:
        slug = f"{base}-{suffix}"
        suffix += 1
    return slug


def normalize_mobile_phone(value: str | None) -> str | None:
    if not value:
        return None
    compact = re.sub(r"[\s().-]", "", value)
    if compact.startswith("00"):
        compact = f"+{compact[2:]}"
    if compact.isdigit() and len(compact) == 10 and compact[0] in "6789":
        compact = f"+91{compact}"
    if not re.fullmatch(r"\+[1-9]\d{7,14}", compact):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Mobile number must be in international format, for example +919876543210",
        )
    return compact


def invitation_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def invitation_is_active(invitation: OrganizationInvitation) -> bool:
    expires_at = invitation.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return invitation.accepted_at is None and invitation.revoked_at is None and expires_at > datetime.now(timezone.utc)


def trial_end_date() -> str:
    return (datetime.now(timezone.utc).date() + timedelta(days=14)).isoformat()


@router.post("/auth/signup", response_model=OrganizationSignupRead, status_code=status.HTTP_201_CREATED)
def signup(payload: OrganizationSignup, database: Session = Depends(get_db)) -> OrganizationSignupRead:
    email = payload.email.lower()
    if database.scalar(select(User).where(User.email == email)) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A user with this email already exists")
    organization = Organization(
        name=payload.organization_name.strip(),
        slug=organization_slug(payload.organization_name, database),
        subscription_status="trialing",
        trial_ends_on=trial_end_date(),
    )
    database.add(organization)
    database.flush()
    try:
        supabase_user_id = provision_supabase_user(email, payload.password, payload.full_name.strip())
    except ValueError as error:
        detail = str(error)
        code = status.HTTP_409_CONFLICT if "already exists" in detail else status.HTTP_503_SERVICE_UNAVAILABLE
        raise HTTPException(status_code=code, detail=detail) from error
    user = User(
        organization_id=organization.id,
        email=email,
        full_name=payload.full_name.strip(),
        mobile_phone=normalize_mobile_phone(payload.mobile_phone),
        password_hash=hash_password(payload.password),
        supabase_user_id=supabase_user_id,
        role="owner",
    )
    database.add(user)
    database.flush()
    database.add(AuditLog(
        organization_id=organization.id,
        actor_user_id=user.id,
        action="organization.created",
        entity_type="organization",
        entity_id=str(organization.id),
        request_id=str(uuid4()),
        changes=json.dumps({"name": organization.name, "slug": organization.slug}),
    ))
    database.commit()
    return OrganizationSignupRead(
        organization_id=organization.id,
        organization_name=organization.name,
        organization_slug=organization.slug,
        user=user,
        access_token=create_access_token(str(user.id), user.token_version),
    )


@router.post("/auth/login", response_model=Token)
def login(payload: LoginRequest, database: Session = Depends(get_db)) -> Token:
    settings = get_settings()
    if settings.auth_provider == "supabase" and settings.environment.lower() != "development":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Use Supabase Auth to sign in",
        )
    user = database.scalar(select(User).where(User.email == payload.email.lower()))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Email or password is incorrect")
    return Token(access_token=create_access_token(str(user.id), user.token_version))


@router.get("/auth/identity-provider", response_model=IdentityProviderMetadata)
def identity_provider_metadata() -> IdentityProviderMetadata:
    settings = get_settings()
    return IdentityProviderMetadata(
        enabled=settings.identity_provider_enabled,
        issuer=settings.identity_provider_issuer,
        client_id=settings.identity_provider_client_id,
        local_login_available=not (
            settings.auth_provider == "supabase"
            and settings.environment.lower() != "development"
        ),
    )


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(user: User = Depends(get_current_user), database: Session = Depends(get_db)) -> None:
    user.token_version += 1
    database.commit()


@router.get("/auth/me", response_model=UserRead)
def current_user(user: User = Depends(get_current_user)) -> User:
    return user


@router.get("/audit-log", response_model=list[AuditLogRead])
def list_audit_log(
    actor_role: str | None = None,
    entity_type: str | None = None,
    action: str | None = None,
    outcome: str | None = None,
    limit: int = 100,
    user: User = Depends(require_roles("owner")),
    database: Session = Depends(get_db),
) -> list[AuditLog]:
    statement = select(AuditLog).where(AuditLog.organization_id == user.organization_id)
    if actor_role:
        statement = statement.join(User, User.id == AuditLog.actor_user_id).where(User.role == actor_role)
    if entity_type:
        statement = statement.where(AuditLog.entity_type == entity_type)
    if action:
        statement = statement.where(AuditLog.action.ilike(f"%{action}%"))
    if outcome:
        statement = statement.where(AuditLog.changes.ilike(f"%{outcome}%"))
    return list(database.scalars(statement.order_by(AuditLog.created_at.desc()).limit(max(1, min(limit, 200)))).all())


@router.get("/fleet/operations-summary", response_model=FleetOperationsSummaryRead)
def fleet_operations_summary(
    user: User = Depends(require_roles("owner", "fleet_manager")),
    database: Session = Depends(get_db),
) -> FleetOperationsSummaryRead:
    vehicles = list(database.scalars(select(Vehicle).where(Vehicle.organization_id == user.organization_id)).all())
    work_orders = list(database.scalars(select(WorkOrder).where(WorkOrder.organization_id == user.organization_id)).all())
    components = list(database.scalars(select(VehicleComponent).where(VehicleComponent.organization_id == user.organization_id)).all())
    documents = list(database.scalars(select(ComplianceDocument).where(ComplianceDocument.organization_id == user.organization_id)).all())
    parts = list(database.scalars(select(Part).where(Part.organization_id == user.organization_id)).all())
    today = date.today().isoformat()
    return FleetOperationsSummaryRead(
        active_vehicles=sum(vehicle.status not in ("Out of service", "Retired") for vehicle in vehicles),
        total_vehicles=len(vehicles),
        open_work_orders=sum(order.status not in ("Completed", "Cancelled") for order in work_orders),
        overdue_work_orders=sum(order.status not in ("Completed", "Cancelled") and order.due_date is not None and order.due_date < today for order in work_orders),
        due_components=sum(component.next_service_km is not None and next((vehicle.odometer_km for vehicle in vehicles if vehicle.id == component.vehicle_id), 0) >= component.next_service_km for component in components),
        compliance_due=sum(document.expires_on <= (date.today() + timedelta(days=30)).isoformat() for document in documents),
        low_stock_parts=sum(part.quantity_on_hand <= part.reorder_level for part in parts),
        unassigned_vehicles=sum(vehicle.assigned_driver_id is None for vehicle in vehicles),
    )


@router.get("/fleet/analytics", response_model=FleetAnalyticsRead)
def fleet_analytics(
    user: User = Depends(require_roles("owner", "fleet_manager")),
    database: Session = Depends(get_db),
) -> FleetAnalyticsRead:
    vehicles = list(database.scalars(select(Vehicle).where(Vehicle.organization_id == user.organization_id)).all())
    expenses = list(database.scalars(select(Expense).where(Expense.organization_id == user.organization_id)).all())
    fuel = list(database.scalars(select(FuelTransaction).where(FuelTransaction.organization_id == user.organization_id)).all())
    tolls = list(database.scalars(select(TollTransaction).where(TollTransaction.organization_id == user.organization_id)).all())
    work_orders = list(database.scalars(select(WorkOrder).where(WorkOrder.organization_id == user.organization_id)).all())
    now = utc_now()
    analytics = []
    for vehicle in vehicles:
        maintenance_cost = sum(
            expense.amount_paise
            for expense in expenses
            if expense.vehicle_id == vehicle.id
            and any(term in expense.category.lower() for term in ("maintenance", "repair", "service"))
            and expense.status != "Rejected"
        )
        maintenance_cost += sum(item.total_amount_paise for item in fuel if item.vehicle_id == vehicle.id)
        maintenance_cost += sum(item.amount_paise for item in tolls if item.vehicle_id == vehicle.id and item.status != "Rejected")
        downtime_days = 0
        for order in work_orders:
            if order.vehicle_id != vehicle.id or order.status in {"Completed", "Closed", "Archived", "Cancelled"}:
                continue
            started_at = order.created_at or now
            if started_at.tzinfo is None:
                started_at = started_at.replace(tzinfo=timezone.utc)
            downtime_days += max(0, (now - started_at).days)
        analytics.append(FleetAnalyticsVehicleRead(
            vehicle_id=vehicle.id,
            maintenance_cost_paise=maintenance_cost,
            cost_per_km_paise=maintenance_cost // max(vehicle.odometer_km, 1),
            downtime_days=downtime_days,
            odometer_km=vehicle.odometer_km,
        ))
    anomalies = len(list(database.scalars(select(OdometerLog).where(
        OdometerLog.organization_id == user.organization_id,
        OdometerLog.is_flagged.is_(True),
    )).all()))
    return FleetAnalyticsRead(vehicles=analytics, odometer_anomalies=anomalies)


@router.patch("/users/me", response_model=UserRead)
def update_my_profile(
    payload: UserProfileUpdate,
    request: Request,
    user: User = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> User:
    changes = {
        "full_name": payload.full_name.strip(),
        "mobile_phone": normalize_mobile_phone(payload.mobile_phone),
    }
    user.full_name = changes["full_name"]
    user.mobile_phone = changes["mobile_phone"]
    database.add(AuditLog(
        organization_id=user.organization_id,
        actor_user_id=user.id,
        action="user.profile_updated",
        entity_type="user",
        entity_id=str(user.id),
        request_id=request.headers.get("x-request-id", str(uuid4())),
        changes=json.dumps(changes),
    ))
    database.commit()
    database.refresh(user)
    return user


@router.patch("/users/me/contact", response_model=UserRead)
def update_my_contact(
    payload: UserContactUpdate,
    user: User = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> User:
    user.mobile_phone = normalize_mobile_phone(payload.mobile_phone)
    database.commit()
    database.refresh(user)
    return user


@router.get("/invitations", response_model=list[InvitationRead])
def list_invitations(
    user: User = Depends(require_roles("owner")),
    database: Session = Depends(get_db),
) -> list[OrganizationInvitation]:
    return list(database.scalars(
        select(OrganizationInvitation)
        .where(OrganizationInvitation.organization_id == user.organization_id)
        .order_by(OrganizationInvitation.created_at.desc())
    ).all())


@router.post("/invitations", response_model=dict, status_code=status.HTTP_201_CREATED)
def create_invitation(
    payload: InvitationCreate,
    request: Request,
    user: User = Depends(require_roles("owner")),
    database: Session = Depends(get_db),
) -> dict:
    email = payload.email.lower()
    if database.scalar(select(User).where(User.email == email)) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A user with this email already exists")
    active_invitation = database.scalar(select(OrganizationInvitation).where(
        OrganizationInvitation.organization_id == user.organization_id,
        OrganizationInvitation.email == email,
        OrganizationInvitation.accepted_at.is_(None),
        OrganizationInvitation.revoked_at.is_(None),
    ))
    if active_invitation and invitation_is_active(active_invitation):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An active invitation already exists for this email")
    raw_token = secrets.token_urlsafe(32)
    invitation = OrganizationInvitation(
        organization_id=user.organization_id,
        invited_by=user.id,
        email=email,
        full_name=payload.full_name.strip(),
        mobile_phone=normalize_mobile_phone(payload.mobile_phone),
        role=payload.role,
        token_hash=invitation_token_hash(raw_token),
        expires_at=datetime.now(timezone.utc) + timedelta(days=payload.expires_in_days),
    )
    database.add(invitation)
    database.flush()
    database.add(AuditLog(
        organization_id=user.organization_id,
        actor_user_id=user.id,
        action="organization.invitation_created",
        entity_type="organization_invitation",
        entity_id=str(invitation.id),
        request_id=request.headers.get("x-request-id", str(uuid4())),
        changes=json.dumps({"email": email, "role": payload.role}),
    ))
    database.commit()
    return {
        "id": invitation.id,
        "email": invitation.email,
        "role": invitation.role,
        "expires_at": invitation.expires_at,
        "invite_token": raw_token,
        "invite_path": f"/invite/{raw_token}",
    }


@router.post("/invitations/{invitation_id}/revoke", response_model=InvitationRead)
def revoke_invitation(
    invitation_id: int,
    request: Request,
    user: User = Depends(require_roles("owner")),
    database: Session = Depends(get_db),
) -> OrganizationInvitation:
    invitation = database.scalar(select(OrganizationInvitation).where(
        OrganizationInvitation.id == invitation_id,
        OrganizationInvitation.organization_id == user.organization_id,
    ))
    if invitation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invitation not found")
    if invitation.accepted_at is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Accepted invitations cannot be revoked")
    invitation.revoked_at = utc_now()
    database.add(AuditLog(
        organization_id=user.organization_id,
        actor_user_id=user.id,
        action="organization.invitation_revoked",
        entity_type="organization_invitation",
        entity_id=str(invitation.id),
        request_id=request.headers.get("x-request-id", str(uuid4())),
    ))
    database.commit()
    database.refresh(invitation)
    return invitation


@router.post("/auth/invitations/accept", response_model=InvitationAcceptRead)
def accept_invitation(payload: InvitationAccept, database: Session = Depends(get_db)) -> InvitationAcceptRead:
    invitation = database.scalar(select(OrganizationInvitation).where(
        OrganizationInvitation.token_hash == invitation_token_hash(payload.token)
    ))
    if invitation is None or not invitation_is_active(invitation):
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="This invitation is invalid or expired")
    if database.scalar(select(User).where(User.email == invitation.email)) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A user with this email already exists")
    organization = database.get(Organization, invitation.organization_id)
    try:
        supabase_user_id = provision_supabase_user(invitation.email, payload.password, invitation.full_name)
    except ValueError as error:
        detail = str(error)
        code = status.HTTP_409_CONFLICT if "already exists" in detail else status.HTTP_503_SERVICE_UNAVAILABLE
        raise HTTPException(status_code=code, detail=detail) from error
    member = User(
        organization_id=invitation.organization_id,
        email=invitation.email,
        full_name=invitation.full_name,
        mobile_phone=invitation.mobile_phone,
        password_hash=hash_password(payload.password),
        supabase_user_id=supabase_user_id,
        role=invitation.role,
    )
    database.add(member)
    invitation.accepted_at = utc_now()
    database.flush()
    database.add(AuditLog(
        organization_id=invitation.organization_id,
        actor_user_id=member.id,
        action="organization.invitation_accepted",
        entity_type="user",
        entity_id=str(member.id),
        request_id=str(uuid4()),
        changes=json.dumps({"role": member.role}),
    ))
    database.commit()
    return InvitationAcceptRead(
        organization_name=organization.name,
        user=member,
        access_token=create_access_token(str(member.id), member.token_version),
    )


@router.get("/users", response_model=list[UserRead])
def list_users(
    user: User = Depends(require_roles("owner")),
    database: Session = Depends(get_db),
) -> list[User]:
    return list(database.scalars(select(User).where(User.organization_id == user.organization_id).order_by(User.full_name.asc())).all())


@router.post("/users", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate,
    request: Request,
    user: User = Depends(require_roles("owner")),
    database: Session = Depends(get_db),
) -> User:
    email = payload.email.lower()
    if database.scalar(select(User).where(User.email == email)) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A user with this email already exists")
    try:
        supabase_user_id = provision_supabase_user(email, payload.password, payload.full_name.strip())
    except ValueError as error:
        detail = str(error)
        code = status.HTTP_409_CONFLICT if "already exists" in detail else status.HTTP_503_SERVICE_UNAVAILABLE
        raise HTTPException(status_code=code, detail=detail) from error
    member = User(
        organization_id=user.organization_id,
        email=email,
        full_name=payload.full_name.strip(),
        mobile_phone=normalize_mobile_phone(payload.mobile_phone),
        password_hash=hash_password(payload.password),
        supabase_user_id=supabase_user_id,
        role=payload.role,
    )
    database.add(member)
    database.flush()
    database.add(AuditLog(
        organization_id=user.organization_id,
        actor_user_id=user.id,
        action="user.created",
        entity_type="user",
        entity_id=str(member.id),
        request_id=request.headers.get("x-request-id", str(uuid4())),
        changes=json.dumps({"email": member.email, "role": member.role}),
    ))
    database.commit()
    database.refresh(member)
    return member


@router.patch("/users/{user_id}", response_model=UserRead)
def update_user_role(
    user_id: int,
    payload: UserRoleUpdate,
    request: Request,
    user: User = Depends(require_roles("owner")),
    database: Session = Depends(get_db),
) -> User:
    member = database.scalar(select(User).where(User.id == user_id, User.organization_id == user.organization_id))
    if member is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    member.role = payload.role
    database.add(AuditLog(
        organization_id=user.organization_id,
        actor_user_id=user.id,
        action="user.role_updated",
        entity_type="user",
        entity_id=str(member.id),
        request_id=request.headers.get("x-request-id", str(uuid4())),
        changes=json.dumps({"role": member.role}),
    ))
    database.commit()
    database.refresh(member)
    return member


@router.get("/subscription/plans", response_model=list[SubscriptionPlanRead])
def list_subscription_plans() -> list[dict]:
    return list(SUBSCRIPTION_PLANS.values())


@router.get("/subscription", response_model=SubscriptionRead)
def get_subscription(user: User = Depends(get_current_user), database: Session = Depends(get_db)) -> SubscriptionRead:
    organization = database.get(Organization, user.organization_id)
    plan = SUBSCRIPTION_PLANS.get(organization.subscription_plan, SUBSCRIPTION_PLANS["starter"])
    vehicle_count = database.query(Vehicle).filter(Vehicle.organization_id == user.organization_id).count()
    bill = calculate_monthly_bill(plan, vehicle_count)
    return SubscriptionRead(
        plan=plan,
        status=organization.subscription_status,
        trial_ends_on=organization.trial_ends_on,
        renews_on=organization.subscription_renews_on,
        vehicle_count=vehicle_count,
        user_count=database.query(User).filter(User.organization_id == user.organization_id).count(),
        overage_vehicles=bill["overage_vehicles"],
        estimated_subtotal_paise=bill["estimated_subtotal_paise"],
    )


@router.patch("/subscription", response_model=SubscriptionRead)
def change_subscription(
    payload: SubscriptionChange,
    request: Request,
    user: User = Depends(require_roles("owner")),
    database: Session = Depends(get_db),
) -> SubscriptionRead:
    organization = database.get(Organization, user.organization_id)
    vehicle_count = database.query(Vehicle).filter(Vehicle.organization_id == user.organization_id).count()
    plan = SUBSCRIPTION_PLANS[payload.plan_code]
    if vehicle_count < plan["min_vehicles"] or vehicle_count > plan["max_vehicles"]:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{plan['name']} supports {plan['min_vehicles']} to {plan['max_vehicles']} vehicles; this organization has {vehicle_count}",
        )
    organization.subscription_plan = payload.plan_code
    organization.subscription_status = "pending_activation"
    database.add(AuditLog(
        organization_id=user.organization_id,
        actor_user_id=user.id,
        action="subscription.plan_changed",
        entity_type="organization_subscription",
        entity_id=str(organization.id),
        request_id=request.headers.get("x-request-id", str(uuid4())),
        changes=json.dumps({"plan": payload.plan_code}),
    ))
    database.commit()
    return get_subscription(user, database)


@router.post("/subscription/checkout", response_model=SubscriptionCheckoutRead)
def create_subscription_checkout(
    payload: SubscriptionChange,
    user: User = Depends(require_roles("owner")),
    database: Session = Depends(get_db),
) -> SubscriptionCheckoutRead:
    settings = get_settings()
    plan_id = {
        "starter": settings.razorpay_plan_starter,
        "growth": settings.razorpay_plan_growth,
        "scale": settings.razorpay_plan_scale,
        "enterprise": settings.razorpay_plan_enterprise,
    }[payload.plan_code]
    if not settings.razorpay_key_id or not settings.razorpay_key_secret or not plan_id:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Razorpay subscription plans are not configured")
    response = httpx.post(
        "https://api.razorpay.com/v1/subscriptions",
        auth=(settings.razorpay_key_id, settings.razorpay_key_secret),
        json={"plan_id": plan_id, "total_count": 120, "customer_notify": 1},
        timeout=30,
    )
    if response.is_error:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Razorpay could not create the subscription")
    subscription = response.json()
    organization = database.get(Organization, user.organization_id)
    organization.subscription_plan = payload.plan_code
    organization.subscription_status = "pending_activation"
    organization.razorpay_subscription_id = subscription["id"]
    database.add(AuditLog(
        organization_id=organization.id,
        actor_user_id=user.id,
        action="subscription.checkout_created",
        entity_type="organization",
        entity_id=str(organization.id),
        request_id=str(uuid4()),
        changes=json.dumps({"plan_code": payload.plan_code, "razorpay_subscription_id": subscription["id"]}),
    ))
    database.commit()
    return SubscriptionCheckoutRead(
        subscription_id=subscription["id"],
        plan_code=payload.plan_code,
        razorpay_key_id=settings.razorpay_key_id,
        short_url=subscription.get("short_url"),
    )


@router.post("/webhooks/razorpay", status_code=status.HTTP_204_NO_CONTENT)
async def razorpay_webhook(request: Request, database: Session = Depends(get_db)) -> None:
    settings = get_settings()
    if not settings.razorpay_webhook_secret:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Razorpay webhook verification is not configured")
    body = await request.body()
    signature = request.headers.get("x-razorpay-signature", "")
    expected = hmac.new(settings.razorpay_webhook_secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Razorpay webhook signature")
    event = json.loads(body)
    subscription_entity = event.get("payload", {}).get("subscription", {}).get("entity", {})
    subscription_id = subscription_entity.get("id")
    if not subscription_id:
        return
    organization = database.scalar(select(Organization).where(Organization.razorpay_subscription_id == subscription_id))
    if organization is None:
        return
    event_name = event.get("event", "")
    if event_name in {"subscription.activated", "subscription.charged"}:
        organization.subscription_status = "active"
    elif event_name in {"subscription.halted", "subscription.cancelled", "subscription.completed"}:
        organization.subscription_status = event_name.split(".", 1)[1]
    database.add(AuditLog(
        organization_id=organization.id,
        action=f"razorpay.{event_name}",
        entity_type="subscription",
        entity_id=subscription_id,
        request_id=request.headers.get("x-request-id", str(uuid4())),
        changes=json.dumps({"event": event_name}),
    ))
    database.commit()


@router.post("/subscription/verify", response_model=SubscriptionRead)
def verify_subscription_payment(
    payload: RazorpaySubscriptionVerify,
    user: User = Depends(require_roles("owner")),
    database: Session = Depends(get_db),
) -> SubscriptionRead:
    settings = get_settings()
    if not settings.razorpay_key_secret:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Razorpay verification is not configured")
    message = f"{payload.razorpay_payment_id}|{payload.razorpay_subscription_id}".encode()
    expected = hmac.new(settings.razorpay_key_secret.encode(), message, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(payload.razorpay_signature, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Razorpay payment signature")
    organization = database.get(Organization, user.organization_id)
    if organization.razorpay_subscription_id != payload.razorpay_subscription_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Subscription does not belong to this organization")
    organization.subscription_status = "active"
    database.add(AuditLog(
        organization_id=organization.id,
        actor_user_id=user.id,
        action="subscription.payment_verified",
        entity_type="subscription",
        entity_id=payload.razorpay_subscription_id,
        request_id=str(uuid4()),
        changes=json.dumps({"razorpay_payment_id": payload.razorpay_payment_id}),
    ))
    database.commit()
    return get_subscription(user, database)


@router.get("/billing/invoices", response_model=list[BillingInvoiceRead])
def list_billing_invoices(
    user: User = Depends(require_roles("owner")),
    database: Session = Depends(get_db),
) -> list[BillingInvoice]:
    return list(database.scalars(select(BillingInvoice).where(
        BillingInvoice.organization_id == user.organization_id,
    ).order_by(BillingInvoice.id.desc())).all())


@router.get("/billing/invoices/{invoice_id}/payments", response_model=list[BillingPaymentRead])
def list_billing_payments(
    invoice_id: int,
    user: User = Depends(require_roles("owner")),
    database: Session = Depends(get_db),
) -> list[BillingPayment]:
    invoice = database.scalar(select(BillingInvoice).where(
        BillingInvoice.id == invoice_id,
        BillingInvoice.organization_id == user.organization_id,
    ))
    if invoice is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found")
    return list(database.scalars(select(BillingPayment).where(
        BillingPayment.invoice_id == invoice_id,
        BillingPayment.organization_id == user.organization_id,
    ).order_by(BillingPayment.id.desc())).all())


@router.get("/notification-preferences", response_model=list[NotificationPreferenceRead])
def list_notification_preferences(user: User = Depends(get_current_user), database: Session = Depends(get_db)) -> list[NotificationPreference]:
    return list(database.scalars(select(NotificationPreference).where(
        NotificationPreference.organization_id == user.organization_id,
        NotificationPreference.user_id == user.id,
    ).order_by(NotificationPreference.notification_type)).all())


@router.put("/notification-preferences", response_model=NotificationPreferenceRead)
def update_notification_preference(
    payload: NotificationPreferenceUpdate,
    user: User = Depends(require_permission("notifications")),
    database: Session = Depends(get_db),
) -> NotificationPreference:
    preference = database.scalar(select(NotificationPreference).where(
        NotificationPreference.organization_id == user.organization_id,
        NotificationPreference.user_id == user.id,
        NotificationPreference.notification_type == payload.notification_type,
    ))
    if preference is None:
        preference = NotificationPreference(
            organization_id=user.organization_id,
            user_id=user.id,
            notification_type=payload.notification_type,
        )
        database.add(preference)
    preference.in_app = payload.in_app
    preference.email = payload.email
    preference.sms = payload.sms
    preference.whatsapp = payload.whatsapp
    preference.push = payload.push
    database.commit()
    database.refresh(preference)
    return preference


@router.get("/notification-deliveries", response_model=list[NotificationDeliveryRead])
def list_notification_deliveries(
    user: User = Depends(require_permission("notifications")),
    database: Session = Depends(get_db),
) -> list[NotificationDelivery]:
    return list(database.scalars(select(NotificationDelivery).where(
        NotificationDelivery.organization_id == user.organization_id,
        NotificationDelivery.user_id == user.id,
    ).order_by(NotificationDelivery.id.desc()).limit(100)).all())


@router.post("/notification-deliveries/dispatch")
def dispatch_queued_notifications(
    user: User = Depends(require_roles("owner")),
    database: Session = Depends(get_db),
) -> dict[str, int]:
    deliveries = database.scalars(
        select(NotificationDelivery)
        .where(
            NotificationDelivery.organization_id == user.organization_id,
            NotificationDelivery.channel.in_(("sms", "whatsapp")),
            NotificationDelivery.status.in_(("queued", "failed")),
        )
        .order_by(NotificationDelivery.id)
        .limit(100)
    ).all()
    processed = 0
    for delivery in deliveries:
        notification = database.get(OperationalNotification, delivery.notification_id)
        recipient = database.get(User, delivery.user_id)
        if notification is None or recipient is None:
            continue
        if delivery.channel == "whatsapp":
            dispatch_whatsapp(delivery, notification, recipient)
        else:
            dispatch_sms(delivery, notification, recipient)
        processed += 1
    database.commit()
    return {"processed": processed}


@router.get("/vehicles", response_model=list[VehicleRead])
def list_vehicles(user: User = Depends(get_current_user), database: Session = Depends(get_db)) -> list[Vehicle]:
    statement = select(Vehicle).where(Vehicle.organization_id == user.organization_id)
    if user.role == "driver":
        statement = statement.where(Vehicle.assigned_driver_id == user.id)
    elif user.role in ("technician", "mechanic"):
        statement = statement.where(Vehicle.id.in_(
            select(WorkOrder.vehicle_id).where(
                WorkOrder.organization_id == user.organization_id,
                WorkOrder.assigned_user_id == user.id,
            )
        ))
    elif user.role not in ("owner", "fleet_manager"):
        statement = statement.where(Vehicle.id == -1)
    return list(database.scalars(statement.order_by(Vehicle.id.desc())).all())


@router.post("/vehicles", response_model=VehicleRead, status_code=status.HTTP_201_CREATED)
def create_vehicle(
    payload: VehicleCreate,
    request: Request,
    user: User = Depends(require_permission("fleet")),
    database: Session = Depends(get_db),
) -> Vehicle:
    registration_number = payload.registration_number.strip().upper()
    existing = database.scalar(select(Vehicle).where(Vehicle.organization_id == user.organization_id, Vehicle.registration_number == registration_number))
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A vehicle with this registration number already exists")
    if payload.assigned_driver_id is not None:
        driver = database.scalar(select(User).where(
            User.id == payload.assigned_driver_id,
            User.organization_id == user.organization_id,
            User.role == "driver",
        ))
        if driver is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Assigned user must be a driver in this organization")
        driver_name = driver.full_name
    else:
        driver_name = payload.driver_name.strip() if payload.driver_name else None

    vehicle = Vehicle(
        organization_id=user.organization_id,
        registration_number=registration_number,
        model=payload.model.strip(),
        vehicle_type=payload.vehicle_type.strip(),
        depot=payload.depot.strip(),
        status=payload.status,
        health=payload.health,
        odometer_km=payload.odometer_km,
        driver_name=driver_name,
        assigned_driver_id=payload.assigned_driver_id,
    )
    database.add(vehicle)
    database.flush()
    if vehicle.assigned_driver_id is not None:
        database.add(VehicleAssignment(
            organization_id=user.organization_id,
            vehicle_id=vehicle.id,
            driver_id=vehicle.assigned_driver_id,
        ))
    if vehicle.odometer_km:
        database.add(OdometerLog(
            organization_id=user.organization_id,
            vehicle_id=vehicle.id,
            reading_km=vehicle.odometer_km,
            source="vehicle_creation",
            is_flagged=False,
        ))
    database.add(AuditLog(
        organization_id=user.organization_id,
        actor_user_id=user.id,
        action="vehicle.created",
        entity_type="vehicle",
        entity_id=str(vehicle.id),
        request_id=request.headers.get("x-request-id", str(uuid4())),
        changes=json.dumps({"registration_number": registration_number}),
    ))
    database.commit()
    database.refresh(vehicle)
    return vehicle


@router.patch("/vehicles/{vehicle_id}", response_model=VehicleRead)
def update_vehicle(
    vehicle_id: int,
    payload: VehicleUpdate,
    request: Request,
    user: User = Depends(require_permission("fleet")),
    database: Session = Depends(get_db),
) -> Vehicle:
    vehicle = database.scalar(select(Vehicle).where(
        Vehicle.id == vehicle_id,
        Vehicle.organization_id == user.organization_id,
    ))
    if vehicle is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle not found")
    changes = payload.model_dump(exclude_unset=True)
    if "odometer_km" in changes and changes["odometer_km"] < vehicle.odometer_km:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Odometer reading cannot be lower than the current vehicle reading",
        )
    if "assigned_driver_id" in changes and changes["assigned_driver_id"] is not None:
        driver = database.scalar(select(User).where(
            User.id == changes["assigned_driver_id"],
            User.organization_id == user.organization_id,
            User.role == "driver",
        ))
        if driver is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Assigned user must be a driver in this organization")
        changes["driver_name"] = driver.full_name
    elif changes.get("assigned_driver_id") is None and "assigned_driver_id" in changes:
        changes["driver_name"] = None
    previous_driver_id = vehicle.assigned_driver_id
    previous_odometer = vehicle.odometer_km
    for key, value in changes.items():
        setattr(vehicle, key, value)
    if "assigned_driver_id" in changes and changes["assigned_driver_id"] != previous_driver_id:
        active_assignment = database.scalar(select(VehicleAssignment).where(
            VehicleAssignment.organization_id == user.organization_id,
            VehicleAssignment.vehicle_id == vehicle.id,
            VehicleAssignment.active.is_(True),
        ))
        if active_assignment is not None:
            active_assignment.active = False
            active_assignment.ended_at = utc_now()
        if changes["assigned_driver_id"] is not None:
            database.add(VehicleAssignment(
                organization_id=user.organization_id,
                vehicle_id=vehicle.id,
                driver_id=changes["assigned_driver_id"],
            ))
    if "odometer_km" in changes and changes["odometer_km"] != previous_odometer:
        database.add(OdometerLog(
            organization_id=user.organization_id,
            vehicle_id=vehicle.id,
            reading_km=changes["odometer_km"],
            source="vehicle_update",
            is_flagged=False,
        ))
    database.add(AuditLog(
        organization_id=user.organization_id,
        actor_user_id=user.id,
        action="vehicle.updated",
        entity_type="vehicle",
        entity_id=str(vehicle.id),
        request_id=request.headers.get("x-request-id", str(uuid4())),
        changes=json.dumps(changes),
    ))
    database.commit()
    database.refresh(vehicle)
    return vehicle


@router.get("/vehicles/{vehicle_id}/assignments", response_model=list[VehicleAssignmentRead])
def list_vehicle_assignments(
    vehicle_id: int,
    user: User = Depends(require_permission("fleet")),
    database: Session = Depends(get_db),
) -> list[VehicleAssignment]:
    vehicle = database.scalar(select(Vehicle).where(
        Vehicle.id == vehicle_id,
        Vehicle.organization_id == user.organization_id,
    ))
    if vehicle is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle not found")
    return list(database.scalars(select(VehicleAssignment).where(
        VehicleAssignment.organization_id == user.organization_id,
        VehicleAssignment.vehicle_id == vehicle_id,
    ).order_by(VehicleAssignment.id.desc())).all())


@router.get("/vehicles/{vehicle_id}/odometer", response_model=list[OdometerLogRead])
def list_vehicle_odometer(
    vehicle_id: int,
    user: User = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> list[OdometerLog]:
    vehicle = database.scalar(select(Vehicle).where(
        Vehicle.id == vehicle_id,
        Vehicle.organization_id == user.organization_id,
    ))
    if vehicle is None or (user.role == "driver" and vehicle.assigned_driver_id != user.id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle not found")
    return list(database.scalars(select(OdometerLog).where(
        OdometerLog.organization_id == user.organization_id,
        OdometerLog.vehicle_id == vehicle_id,
    ).order_by(OdometerLog.id.desc()).limit(100)).all())


@router.get("/components", response_model=list[ComponentRead])
def list_components(user: User = Depends(get_current_user), database: Session = Depends(get_db)) -> list[VehicleComponent]:
    statement = select(VehicleComponent).where(VehicleComponent.organization_id == user.organization_id)
    if user.role == "driver":
        statement = statement.where(VehicleComponent.vehicle_id.in_(
            select(Vehicle.id).where(Vehicle.assigned_driver_id == user.id)
        ))
    elif user.role in ("technician", "mechanic"):
        statement = statement.where(VehicleComponent.vehicle_id.in_(
            select(WorkOrder.vehicle_id).where(
                WorkOrder.organization_id == user.organization_id,
                WorkOrder.assigned_user_id == user.id,
            )
        ))
    elif user.role not in ("owner", "fleet_manager"):
        statement = statement.where(VehicleComponent.id == -1)
    return list(database.scalars(statement.order_by(VehicleComponent.id.desc())).all())


@router.post("/components", response_model=ComponentRead, status_code=status.HTTP_201_CREATED)
def create_component(
    payload: ComponentCreate,
    request: Request,
    user: User = Depends(require_permission("maintenance")),
    database: Session = Depends(get_db),
) -> VehicleComponent:
    vehicle = database.scalar(select(Vehicle).where(Vehicle.id == payload.vehicle_id, Vehicle.organization_id == user.organization_id))
    if vehicle is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle not found in this organization")
    component_data = payload.model_dump()
    if (
        component_data["next_service_km"] is None
        and component_data["service_interval_km"] is not None
    ):
        component_data["next_service_km"] = (
            component_data["installed_at_km"] + component_data["service_interval_km"]
        )
    component = VehicleComponent(organization_id=user.organization_id, **component_data)
    database.add(component)
    database.flush()
    database.add(AuditLog(
        organization_id=user.organization_id,
        actor_user_id=user.id,
        action="component.created",
        entity_type="vehicle_component",
        entity_id=str(component.id),
        request_id=request.headers.get("x-request-id", str(uuid4())),
        changes=json.dumps({"vehicle_id": vehicle.id, "name": component.name}),
    ))
    database.commit()
    database.refresh(component)
    return component


@router.patch("/components/{component_id}", response_model=ComponentRead)
def update_component(
    component_id: int,
    payload: ComponentUpdate,
    request: Request,
    user: User = Depends(require_permission("maintenance")),
    database: Session = Depends(get_db),
) -> VehicleComponent:
    statement = select(VehicleComponent).where(
        VehicleComponent.id == component_id,
        VehicleComponent.organization_id == user.organization_id,
    )
    if user.role in ("technician", "mechanic"):
        statement = statement.where(VehicleComponent.vehicle_id.in_(
            select(WorkOrder.vehicle_id).where(
                WorkOrder.organization_id == user.organization_id,
                WorkOrder.assigned_user_id == user.id,
            )
        ))
    component = database.scalar(statement)
    if component is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Component not found")
    changes = payload.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(component, key, value)
    if component.service_interval_km and component.last_service_km is not None and "next_service_km" not in changes:
        component.next_service_km = component.last_service_km + component.service_interval_km
    database.add(AuditLog(
        organization_id=user.organization_id,
        actor_user_id=user.id,
        action="component.updated",
        entity_type="vehicle_component",
        entity_id=str(component.id),
        request_id=request.headers.get("x-request-id", str(uuid4())),
        changes=json.dumps(changes),
    ))
    database.commit()
    database.refresh(component)
    return component


@router.post("/components/{component_id}/service-complete", response_model=ComponentRead)
def complete_component_service(
    component_id: int,
    odometer_km: int,
    request: Request,
    user: User = Depends(require_permission("maintenance")),
    database: Session = Depends(get_db),
) -> VehicleComponent:
    statement = select(VehicleComponent).where(
        VehicleComponent.id == component_id,
        VehicleComponent.organization_id == user.organization_id,
    )
    if user.role in ("technician", "mechanic"):
        statement = statement.where(VehicleComponent.vehicle_id.in_(
            select(WorkOrder.vehicle_id).where(
                WorkOrder.organization_id == user.organization_id,
                WorkOrder.assigned_user_id == user.id,
            )
        ))
    component = database.scalar(statement)
    if component is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Component not found")
    vehicle = database.get(Vehicle, component.vehicle_id)
    if vehicle is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle not found")
    if odometer_km < vehicle.odometer_km:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Service odometer cannot be lower than the vehicle's current reading",
        )
    component.last_service_km = odometer_km
    component.next_service_km = odometer_km + component.service_interval_km if component.service_interval_km else None
    component.status = "Healthy"
    database.add(AuditLog(
        organization_id=user.organization_id,
        actor_user_id=user.id,
        action="component.service_completed",
        entity_type="vehicle_component",
        entity_id=str(component.id),
        request_id=request.headers.get("x-request-id", str(uuid4())),
        changes=json.dumps({"last_service_km": odometer_km, "next_service_km": component.next_service_km}),
    ))
    database.commit()
    database.refresh(component)
    return component


@router.get("/work-orders", response_model=list[WorkOrderRead])
def list_work_orders(user: User = Depends(get_current_user), database: Session = Depends(get_db)) -> list[WorkOrder]:
    statement = select(WorkOrder).where(WorkOrder.organization_id == user.organization_id)
    if user.role in ("technician", "mechanic"):
        statement = statement.where(WorkOrder.assigned_user_id == user.id)
    elif user.role not in ("owner", "fleet_manager"):
        statement = statement.where(WorkOrder.id == -1)
    return list(database.scalars(statement.order_by(WorkOrder.id.desc())).all())


@router.get("/driver/inspections", response_model=list[DriverInspectionRead])
def list_driver_inspections(
    user: User = Depends(require_roles("driver")),
    database: Session = Depends(get_db),
) -> list[DriverInspection]:
    return list(database.scalars(select(DriverInspection).where(
        DriverInspection.organization_id == user.organization_id,
        DriverInspection.driver_id == user.id,
    ).order_by(DriverInspection.id.desc()).limit(100)).all())


@router.post("/driver/inspections", response_model=DriverInspectionRead, status_code=status.HTTP_201_CREATED)
def create_driver_inspection(
    payload: DriverInspectionCreate,
    request: Request,
    user: User = Depends(require_roles("driver")),
    database: Session = Depends(get_db),
) -> DriverInspection:
    reserve_idempotency_key(request, user, database)
    vehicle = database.scalar(select(Vehicle).where(
        Vehicle.id == payload.vehicle_id,
        Vehicle.organization_id == user.organization_id,
        Vehicle.assigned_driver_id == user.id,
    ))
    if vehicle is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle is not assigned to this driver")
    if payload.odometer_km < vehicle.odometer_km:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Inspection odometer cannot move backwards")
    vehicle.odometer_km = max(vehicle.odometer_km, payload.odometer_km)
    if payload.status == "UNSAFE":
        vehicle.status = "Out of service"
    database.add(OdometerLog(
        organization_id=user.organization_id,
        vehicle_id=vehicle.id,
        driver_id=user.id,
        reading_km=payload.odometer_km,
        source=f"driver_{payload.inspection_type}",
        is_flagged=False,
    ))
    inspection = DriverInspection(
        organization_id=user.organization_id,
        driver_id=user.id,
        **payload.model_dump(),
    )
    database.add(inspection)
    database.add(AuditLog(
        organization_id=user.organization_id,
        actor_user_id=user.id,
        action="driver.inspection_submitted",
        entity_type="vehicle",
        entity_id=str(vehicle.id),
        request_id=request.headers.get("x-request-id", str(uuid4())),
        changes=json.dumps({"status": payload.status, "odometer_km": payload.odometer_km}),
    ))
    database.commit()
    database.refresh(inspection)
    return inspection


@router.get("/driver/issues", response_model=list[VehicleIssueRead])
def list_driver_issues(
    user: User = Depends(require_roles("driver")),
    database: Session = Depends(get_db),
) -> list[VehicleIssue]:
    return list(database.scalars(select(VehicleIssue).where(
        VehicleIssue.organization_id == user.organization_id,
        VehicleIssue.driver_id == user.id,
    ).order_by(VehicleIssue.id.desc()).limit(100)).all())


@router.post("/driver/issues", response_model=VehicleIssueRead, status_code=status.HTTP_201_CREATED)
def create_driver_issue(
    payload: VehicleIssueCreate,
    request: Request,
    user: User = Depends(require_roles("driver")),
    database: Session = Depends(get_db),
) -> VehicleIssue:
    reserve_idempotency_key(request, user, database)
    vehicle = database.scalar(select(Vehicle).where(
        Vehicle.id == payload.vehicle_id,
        Vehicle.organization_id == user.organization_id,
        Vehicle.assigned_driver_id == user.id,
    ))
    if vehicle is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle is not assigned to this driver")
    issue = VehicleIssue(organization_id=user.organization_id, driver_id=user.id, **payload.model_dump())
    database.add(issue)
    database.flush()
    database.add(AuditLog(
        organization_id=user.organization_id,
        actor_user_id=user.id,
        action="driver.vehicle_issue_reported",
        entity_type="vehicle_issue",
        entity_id=str(vehicle.id),
        request_id=request.headers.get("x-request-id", str(uuid4())),
        changes=json.dumps({"title": payload.title, "priority": payload.priority}),
    ))
    queue_role_notification(
        database,
        organization_id=user.organization_id,
        notification_type="driver_issue",
        severity="danger" if payload.priority in {"High", "Critical"} else "warning",
        title=f"Driver issue: {payload.title}",
        detail=f"{vehicle.registration_number}: {payload.detail}",
        entity_type="vehicle_issue",
        entity_id=str(issue.id),
        roles={"owner", "fleet_manager"},
    )
    database.commit()
    database.refresh(issue)
    return issue


@router.post("/work-orders", response_model=WorkOrderRead, status_code=status.HTTP_201_CREATED)
def create_work_order(
    payload: WorkOrderCreate,
    request: Request,
    user: User = Depends(require_permission("maintenance")),
    database: Session = Depends(get_db),
) -> WorkOrder:
    reserve_idempotency_key(request, user, database)
    vehicle = database.scalar(select(Vehicle).where(Vehicle.id == payload.vehicle_id, Vehicle.organization_id == user.organization_id))
    if vehicle is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle not found in this organization")
    if payload.assigned_user_id is not None:
        assignee = database.scalar(select(User).where(
            User.id == payload.assigned_user_id,
            User.organization_id == user.organization_id,
            User.role.in_(("technician", "mechanic")),
        ))
        if assignee is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Assigned user must be a workshop user in this organization")
    work_order = WorkOrder(organization_id=user.organization_id, **payload.model_dump())
    database.add(work_order)
    database.flush()
    database.add(AuditLog(
        organization_id=user.organization_id,
        actor_user_id=user.id,
        action="work_order.created",
        entity_type="work_order",
        entity_id=str(work_order.id),
        request_id=request.headers.get("x-request-id", str(uuid4())),
        changes=json.dumps({"vehicle_id": vehicle.id, "title": work_order.title}),
    ))
    queue_role_notification(
        database,
        organization_id=user.organization_id,
        notification_type="work_order_assigned",
        severity="danger" if work_order.priority in {"High", "Critical"} else "warning",
        title=f"Work order assigned: {work_order.title}",
        detail=f"{vehicle.registration_number} · {work_order.priority} priority",
        entity_type="work_order",
        entity_id=str(work_order.id),
        roles={"owner", "fleet_manager", "technician"},
        user_ids={work_order.assigned_user_id} if work_order.assigned_user_id is not None else set(),
    )
    database.commit()
    database.refresh(work_order)
    return work_order


@router.patch("/work-orders/{work_order_id}", response_model=WorkOrderRead)
def update_work_order(
    work_order_id: int,
    payload: WorkOrderUpdate,
    request: Request,
    user: User = Depends(require_permission("maintenance")),
    database: Session = Depends(get_db),
) -> WorkOrder:
    statement = select(WorkOrder).where(WorkOrder.id == work_order_id, WorkOrder.organization_id == user.organization_id)
    if user.role in ("technician", "mechanic"):
        statement = statement.where(WorkOrder.assigned_user_id == user.id)
    work_order = database.scalar(statement)
    if work_order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Work order not found")
    changes = payload.model_dump(exclude_unset=True)
    if user.role not in ("owner", "fleet_manager", "technician", "mechanic"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only fleet or workshop roles can update work orders")
    if user.role in ("technician", "mechanic"):
        changes = {key: value for key, value in changes.items() if key in {"description"}}
    else:
        if "assigned_user_id" in changes and changes["assigned_user_id"] is not None:
            assignee = database.scalar(select(User).where(
                User.id == changes["assigned_user_id"],
                User.organization_id == user.organization_id,
                User.role.in_(("technician", "mechanic")),
            ))
            if assignee is None:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Assigned user must be a workshop user in this organization")
        if "status" in changes:
            transitions = {
                "Draft": {"Open", "Assigned", "Archived"},
                "Open": {"Assigned", "Scheduled", "In progress", "Archived"},
                "Assigned": {"Scheduled", "In progress", "Archived"},
                "Scheduled": {"In progress", "Archived"},
                "In progress": {"Ready for review"},
                "Ready for review": {"Completed"},
                "Completed": {"Closed", "Archived"},
                "Closed": set(),
                "Archived": set(),
            }
            target_status = changes["status"]
            if target_status != work_order.status and target_status not in transitions.get(work_order.status, set()):
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Invalid work-order transition: {work_order.status} to {target_status}")
    for key, value in changes.items():
        setattr(work_order, key, value)
    if "status" in changes:
        transitioned_at = utc_now()
        if changes["status"] == "In progress" and work_order.started_at is None:
            work_order.started_at = transitioned_at
        elif changes["status"] == "Ready for review" and work_order.completed_at is None:
            work_order.completed_at = transitioned_at
        elif changes["status"] == "Archived":
            work_order.archived_at = transitioned_at
    database.add(AuditLog(
        organization_id=user.organization_id,
        actor_user_id=user.id,
        action="work_order.updated",
        entity_type="work_order",
        entity_id=str(work_order.id),
        request_id=request.headers.get("x-request-id", str(uuid4())),
        changes=json.dumps(changes),
    ))
    database.commit()
    database.refresh(work_order)
    return work_order


@router.get("/work-orders/{work_order_id}/checklist", response_model=list[WorkOrderChecklistItemRead])
def list_work_order_checklist(
    work_order_id: int,
    user: User = Depends(require_permission("maintenance")),
    database: Session = Depends(get_db),
) -> list[WorkOrderChecklistItem]:
    statement = select(WorkOrder).where(
        WorkOrder.id == work_order_id,
        WorkOrder.organization_id == user.organization_id,
    )
    if user.role in ("technician", "mechanic"):
        statement = statement.where(WorkOrder.assigned_user_id == user.id)
    if database.scalar(statement) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Work order not found")
    return list(database.scalars(select(WorkOrderChecklistItem).where(
        WorkOrderChecklistItem.organization_id == user.organization_id,
        WorkOrderChecklistItem.work_order_id == work_order_id,
    ).order_by(WorkOrderChecklistItem.sort_order, WorkOrderChecklistItem.id)).all())


@router.put("/work-orders/{work_order_id}/checklist", response_model=list[WorkOrderChecklistItemRead])
def update_work_order_checklist(
    work_order_id: int,
    payload: WorkOrderChecklistUpdate,
    request: Request,
    user: User = Depends(require_permission("maintenance")),
    database: Session = Depends(get_db),
) -> list[WorkOrderChecklistItem]:
    reserve_idempotency_key(request, user, database)
    statement = select(WorkOrder).where(
        WorkOrder.id == work_order_id,
        WorkOrder.organization_id == user.organization_id,
    )
    if user.role in ("technician", "mechanic"):
        statement = statement.where(WorkOrder.assigned_user_id == user.id)
    work_order = database.scalar(statement)
    if work_order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Work order not found")
    existing = database.scalars(select(WorkOrderChecklistItem).where(
        WorkOrderChecklistItem.organization_id == user.organization_id,
        WorkOrderChecklistItem.work_order_id == work_order_id,
    )).all()
    for item in existing:
        database.delete(item)
    database.flush()
    now = utc_now()
    items = [
        WorkOrderChecklistItem(
            organization_id=user.organization_id,
            work_order_id=work_order_id,
            title=item.title.strip(),
            completed=item.completed,
            sort_order=item.sort_order,
            completed_by=user.id if item.completed else None,
            completed_at=now if item.completed else None,
        )
        for item in payload.items
    ]
    database.add_all(items)
    database.add(AuditLog(
        organization_id=user.organization_id,
        actor_user_id=user.id,
        action="work_order.checklist_updated",
        entity_type="work_order",
        entity_id=str(work_order_id),
        request_id=request.headers.get("x-request-id", str(uuid4())),
        changes=json.dumps({"count": len(items), "completed": sum(item.completed for item in items)}),
    ))
    database.commit()
    for item in items:
        database.refresh(item)
    return items


@router.post("/work-orders/{work_order_id}/start", response_model=WorkOrderRead)
def start_work_order(
    work_order_id: int,
    request: Request,
    user: User = Depends(require_permission("maintenance")),
    database: Session = Depends(get_db),
) -> WorkOrder:
    reserve_idempotency_key(request, user, database)
    statement = select(WorkOrder).where(
        WorkOrder.id == work_order_id,
        WorkOrder.organization_id == user.organization_id,
    )
    if user.role in ("technician", "mechanic"):
        statement = statement.where(WorkOrder.assigned_user_id == user.id)
    work_order = database.scalar(statement)
    if work_order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Work order not found")
    if work_order.status not in {"Open", "Assigned"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only open or assigned work orders can be started")
    work_order.status = "In progress"
    work_order.started_at = utc_now()
    database.add(AuditLog(
        organization_id=user.organization_id,
        actor_user_id=user.id,
        action="work_order.started",
        entity_type="work_order",
        entity_id=str(work_order.id),
        request_id=request.headers.get("x-request-id", str(uuid4())),
    ))
    database.commit()
    database.refresh(work_order)
    return work_order


@router.post("/work-orders/{work_order_id}/complete", response_model=WorkOrderRead)
def complete_work_order(
    work_order_id: int,
    request: Request,
    user: User = Depends(require_permission("maintenance")),
    database: Session = Depends(get_db),
) -> WorkOrder:
    reserve_idempotency_key(request, user, database)
    statement = select(WorkOrder).where(
        WorkOrder.id == work_order_id,
        WorkOrder.organization_id == user.organization_id,
    )
    if user.role in ("technician", "mechanic"):
        statement = statement.where(WorkOrder.assigned_user_id == user.id)
    work_order = database.scalar(statement)
    if work_order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Work order not found")
    if work_order.status != "In progress":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only in-progress work orders can be completed")
    checklist = database.scalars(select(WorkOrderChecklistItem).where(
        WorkOrderChecklistItem.organization_id == user.organization_id,
        WorkOrderChecklistItem.work_order_id == work_order_id,
    )).all()
    if checklist and any(not item.completed for item in checklist):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Complete every checklist item before completing the work order")
    work_order.status = "Ready for review"
    work_order.completed_at = utc_now()
    database.add(AuditLog(
        organization_id=user.organization_id,
        actor_user_id=user.id,
        action="work_order.ready_for_review",
        entity_type="work_order",
        entity_id=str(work_order.id),
        request_id=request.headers.get("x-request-id", str(uuid4())),
    ))
    database.commit()
    database.refresh(work_order)
    return work_order


@router.post("/work-orders/{work_order_id}/approve", response_model=WorkOrderRead)
def approve_work_order(
    work_order_id: int,
    request: Request,
    user: User = Depends(require_roles("owner", "fleet_manager")),
    database: Session = Depends(get_db),
) -> WorkOrder:
    reserve_idempotency_key(request, user, database)
    work_order = database.scalar(select(WorkOrder).where(
        WorkOrder.id == work_order_id,
        WorkOrder.organization_id == user.organization_id,
    ))
    if work_order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Work order not found")
    if work_order.status != "Ready for review":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only work orders ready for review can be approved")
    work_order.status = "Completed"
    database.add(AuditLog(
        organization_id=user.organization_id,
        actor_user_id=user.id,
        action="work_order.approved",
        entity_type="work_order",
        entity_id=str(work_order.id),
        request_id=request.headers.get("x-request-id", str(uuid4())),
    ))
    database.commit()
    database.refresh(work_order)
    return work_order


@router.post("/work-orders/{work_order_id}/archive", response_model=WorkOrderRead)
def archive_work_order(
    work_order_id: int,
    request: Request,
    user: User = Depends(require_roles("owner", "fleet_manager")),
    database: Session = Depends(get_db),
) -> WorkOrder:
    reserve_idempotency_key(request, user, database)
    work_order = database.scalar(select(WorkOrder).where(
        WorkOrder.id == work_order_id,
        WorkOrder.organization_id == user.organization_id,
    ))
    if work_order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Work order not found")
    if work_order.status not in {"Completed", "Closed"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only completed or closed work orders can be archived")
    work_order.status = "Archived"
    work_order.archived_at = utc_now()
    database.add(AuditLog(
        organization_id=user.organization_id,
        actor_user_id=user.id,
        action="work_order.archived",
        entity_type="work_order",
        entity_id=str(work_order.id),
        request_id=request.headers.get("x-request-id", str(uuid4())),
    ))
    database.commit()
    database.refresh(work_order)
    return work_order


@router.get("/work-orders/{work_order_id}/parts", response_model=list[WorkOrderPartUsageRead])
def list_work_order_parts(
    work_order_id: int,
    user: User = Depends(require_permission("maintenance")),
    database: Session = Depends(get_db),
) -> list[WorkOrderPartUsage]:
    work_order = database.scalar(select(WorkOrder).where(
        WorkOrder.id == work_order_id,
        WorkOrder.organization_id == user.organization_id,
    ))
    if work_order is None or (user.role in ("technician", "mechanic") and work_order.assigned_user_id != user.id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Work order not found")
    return list(database.scalars(select(WorkOrderPartUsage).where(
        WorkOrderPartUsage.organization_id == user.organization_id,
        WorkOrderPartUsage.work_order_id == work_order_id,
    ).order_by(WorkOrderPartUsage.id)).all())


@router.get("/work-orders/{work_order_id}/timeline", response_model=list[AuditLogRead])
def work_order_timeline(
    work_order_id: int,
    user: User = Depends(require_permission("maintenance")),
    database: Session = Depends(get_db),
) -> list[AuditLog]:
    statement = select(WorkOrder).where(
        WorkOrder.id == work_order_id,
        WorkOrder.organization_id == user.organization_id,
    )
    if user.role in ("technician", "mechanic"):
        statement = statement.where(WorkOrder.assigned_user_id == user.id)
    if database.scalar(statement) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Work order not found")
    return list(database.scalars(select(AuditLog).where(
        AuditLog.organization_id == user.organization_id,
        AuditLog.entity_type == "work_order",
        AuditLog.entity_id == str(work_order_id),
    ).order_by(AuditLog.created_at.asc(), AuditLog.id.asc())).all())


@router.get("/work-orders/{work_order_id}/evidence", response_model=list[WorkOrderEvidenceRead])
def list_work_order_evidence(
    work_order_id: int,
    user: User = Depends(require_permission("maintenance")),
    database: Session = Depends(get_db),
) -> list[WorkOrderEvidence]:
    work_order = database.scalar(select(WorkOrder).where(
        WorkOrder.id == work_order_id,
        WorkOrder.organization_id == user.organization_id,
    ))
    if work_order is None or (user.role in ("technician", "mechanic") and work_order.assigned_user_id != user.id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Work order not found")
    return list(database.scalars(select(WorkOrderEvidence).where(
        WorkOrderEvidence.organization_id == user.organization_id,
        WorkOrderEvidence.work_order_id == work_order_id,
    ).order_by(WorkOrderEvidence.id.desc())).all())


@router.post("/work-orders/{work_order_id}/evidence", response_model=WorkOrderEvidenceRead, status_code=status.HTTP_201_CREATED)
def upload_work_order_evidence(
    work_order_id: int,
    request: Request,
    file: UploadFile = File(...),
    user: User = Depends(require_permission("maintenance")),
    database: Session = Depends(get_db),
) -> WorkOrderEvidence:
    statement = select(WorkOrder).where(
        WorkOrder.id == work_order_id,
        WorkOrder.organization_id == user.organization_id,
    )
    if user.role in ("technician", "mechanic"):
        statement = statement.where(WorkOrder.assigned_user_id == user.id)
    work_order = database.scalar(statement)
    if work_order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Work order not found")
    if not file.filename:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="A file name is required")
    try:
        object_key, size_bytes, _ = save_upload(file, f"organizations/{user.organization_id}/work-orders/{work_order_id}")
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(error)) from error
    evidence = WorkOrderEvidence(
        organization_id=user.organization_id,
        work_order_id=work_order_id,
        object_key=object_key,
        file_name=file.filename[:255],
        content_type=file.content_type or "application/octet-stream",
        size_bytes=size_bytes,
        uploaded_by=user.id,
    )
    database.add(evidence)
    database.add(AuditLog(
        organization_id=user.organization_id,
        actor_user_id=user.id,
        action="work_order.evidence_uploaded",
        entity_type="work_order",
        entity_id=str(work_order_id),
        request_id=request.headers.get("x-request-id", str(uuid4())),
        changes=json.dumps({"file_name": evidence.file_name, "size_bytes": size_bytes}),
    ))
    database.commit()
    database.refresh(evidence)
    return evidence


@router.post("/work-orders/{work_order_id}/parts", response_model=WorkOrderPartUsageRead, status_code=status.HTTP_201_CREATED)
def record_work_order_part(
    work_order_id: int,
    payload: WorkOrderPartUsageCreate,
    request: Request,
    user: User = Depends(require_permission("inventory")),
    database: Session = Depends(get_db),
) -> WorkOrderPartUsage:
    reserve_idempotency_key(request, user, database)
    work_order = database.scalar(select(WorkOrder).where(
        WorkOrder.id == work_order_id,
        WorkOrder.organization_id == user.organization_id,
    ))
    part = database.scalar(select(Part).where(
        Part.id == payload.part_id,
        Part.organization_id == user.organization_id,
    ))
    if work_order is None or part is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Work order or part not found")
    if part.quantity_on_hand < payload.quantity:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Insufficient stock for this work order")
    part.quantity_on_hand -= payload.quantity
    usage = WorkOrderPartUsage(
        organization_id=user.organization_id,
        work_order_id=work_order_id,
        part_id=part.id,
        quantity=payload.quantity,
        unit_cost_paise=part.unit_cost_paise,
        created_by=user.id,
    )
    database.add(usage)
    database.add(AuditLog(
        organization_id=user.organization_id,
        actor_user_id=user.id,
        action="work_order.part_issued",
        entity_type="work_order",
        entity_id=str(work_order_id),
        request_id=request.headers.get("x-request-id", str(uuid4())),
        changes=json.dumps({"part_id": part.id, "quantity": payload.quantity}),
    ))
    database.commit()
    database.refresh(usage)
    return usage


@router.get("/work-orders/{work_order_id}/download")
def download_work_order(
    work_order_id: int,
    user: User = Depends(require_permission("maintenance")),
    database: Session = Depends(get_db),
) -> Response:
    statement = select(WorkOrder).where(
        WorkOrder.id == work_order_id,
        WorkOrder.organization_id == user.organization_id,
    )
    if user.role in ("technician", "mechanic"):
        statement = statement.where(WorkOrder.assigned_user_id == user.id)
    work_order = database.scalar(statement)
    if work_order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Work order not found")
    vehicle = database.scalar(select(Vehicle).where(Vehicle.id == work_order.vehicle_id))
    body = f"""<!doctype html><html><head><meta charset="utf-8"><title>WO-{work_order.id}</title>
    <style>body{{font-family:Arial;max-width:800px;margin:40px auto}}h1{{color:#123}}</style></head>
    <body><h1>Work order WO-{work_order.id}</h1><p><b>Vehicle:</b> {escape(vehicle.registration_number if vehicle else 'Unknown')}</p>
    <p><b>Title:</b> {escape(work_order.title)}</p><p><b>Status:</b> {escape(work_order.status)}</p>
    <p><b>Priority:</b> {escape(work_order.priority)}</p><p><b>Due:</b> {escape(work_order.due_date or 'Unscheduled')}</p>
    <h2>Instructions</h2><p>{escape(work_order.description or 'No additional instructions')}</p></body></html>"""
    return Response(
        content=body,
        media_type="text/html",
        headers={"Content-Disposition": f'attachment; filename="WO-{work_order.id}.html"'},
    )


@router.get("/maintenance-plans", response_model=list[MaintenancePlanRead])
def list_maintenance_plans(user: User = Depends(get_current_user), database: Session = Depends(get_db)) -> list[MaintenancePlan]:
    return list(database.scalars(select(MaintenancePlan).where(MaintenancePlan.organization_id == user.organization_id).order_by(MaintenancePlan.id.desc())).all())


@router.post("/maintenance-plans", response_model=MaintenancePlanRead, status_code=status.HTTP_201_CREATED)
def create_maintenance_plan(
    payload: MaintenancePlanCreate,
    request: Request,
    user: User = Depends(require_permission("maintenance")),
    database: Session = Depends(get_db),
) -> MaintenancePlan:
    vehicle = database.scalar(select(Vehicle).where(Vehicle.id == payload.vehicle_id, Vehicle.organization_id == user.organization_id))
    if vehicle is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle not found in this organization")
    if payload.interval_km is None and payload.interval_days is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="An interval in kilometres or days is required")
    plan = MaintenancePlan(organization_id=user.organization_id, **payload.model_dump())
    database.add(plan)
    database.flush()
    database.add(AuditLog(
        organization_id=user.organization_id,
        actor_user_id=user.id,
        action="maintenance_plan.created",
        entity_type="maintenance_plan",
        entity_id=str(plan.id),
        request_id=request.headers.get("x-request-id", str(uuid4())),
        changes=json.dumps({"vehicle_id": vehicle.id, "name": plan.name}),
    ))
    database.commit()
    database.refresh(plan)
    return plan


@router.get("/parts", response_model=list[PartRead])
def list_parts(user: User = Depends(get_current_user), database: Session = Depends(get_db)) -> list[Part]:
    return list(database.scalars(select(Part).where(Part.organization_id == user.organization_id).order_by(Part.id.desc())).all())


@router.post("/parts", response_model=PartRead, status_code=status.HTTP_201_CREATED)
def create_part(
    payload: PartCreate,
    request: Request,
    user: User = Depends(require_permission("inventory")),
    database: Session = Depends(get_db),
) -> Part:
    existing = database.scalar(select(Part).where(Part.organization_id == user.organization_id, Part.sku == payload.sku.strip().upper()))
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A part with this SKU already exists")
    part = Part(organization_id=user.organization_id, sku=payload.sku.strip().upper(), **{key: value for key, value in payload.model_dump().items() if key != "sku"})
    database.add(part)
    database.flush()
    database.add(AuditLog(
        organization_id=user.organization_id,
        actor_user_id=user.id,
        action="part.created",
        entity_type="part",
        entity_id=str(part.id),
        request_id=request.headers.get("x-request-id", str(uuid4())),
        changes=json.dumps({"sku": part.sku, "quantity_on_hand": part.quantity_on_hand}),
    ))
    database.commit()
    database.refresh(part)
    return part


@router.post("/inventory/transactions", response_model=PartRead)
def create_inventory_transaction(
    payload: InventoryTransactionCreate,
    request: Request,
    user: User = Depends(require_permission("inventory")),
    database: Session = Depends(get_db),
) -> Part:
    part = database.scalar(select(Part).where(Part.id == payload.part_id, Part.organization_id == user.organization_id))
    if part is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Part not found in this organization")
    delta = payload.quantity if payload.transaction_type == "receipt" else -payload.quantity
    if payload.transaction_type == "adjustment":
        delta = payload.quantity
    if part.quantity_on_hand + delta < 0:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Insufficient stock for this issue")
    part.quantity_on_hand += delta
    database.add(InventoryTransaction(organization_id=user.organization_id, created_by=user.id, **payload.model_dump()))
    database.add(AuditLog(
        organization_id=user.organization_id,
        actor_user_id=user.id,
        action=f"inventory.{payload.transaction_type}",
        entity_type="part",
        entity_id=str(part.id),
        request_id=request.headers.get("x-request-id", str(uuid4())),
        changes=json.dumps({"delta": delta, "quantity_on_hand": part.quantity_on_hand}),
    ))
    database.commit()
    database.refresh(part)
    return part


@router.get("/inventory/transactions", response_model=list[InventoryTransactionRead])
def list_inventory_transactions(user: User = Depends(get_current_user), database: Session = Depends(get_db)) -> list[InventoryTransaction]:
    return list(database.scalars(select(InventoryTransaction).where(InventoryTransaction.organization_id == user.organization_id).order_by(InventoryTransaction.id.desc())).all())


@router.get("/stock-locations", response_model=list[StockLocationRead])
def list_stock_locations(user: User = Depends(get_current_user), database: Session = Depends(get_db)) -> list[StockLocation]:
    return list(database.scalars(select(StockLocation).where(StockLocation.organization_id == user.organization_id).order_by(StockLocation.name.asc())).all())


@router.post("/stock-locations", response_model=StockLocationRead, status_code=status.HTTP_201_CREATED)
def create_stock_location(
    payload: StockLocationCreate,
    request: Request,
    user: User = Depends(require_permission("inventory")),
    database: Session = Depends(get_db),
) -> StockLocation:
    code = payload.code.strip().upper()
    existing = database.scalar(select(StockLocation).where(StockLocation.organization_id == user.organization_id, StockLocation.code == code))
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A stock location with this code already exists")
    location = StockLocation(organization_id=user.organization_id, code=code, **{key: value for key, value in payload.model_dump().items() if key != "code"})
    database.add(location)
    database.flush()
    database.add(AuditLog(
        organization_id=user.organization_id,
        actor_user_id=user.id,
        action="stock_location.created",
        entity_type="stock_location",
        entity_id=str(location.id),
        request_id=request.headers.get("x-request-id", str(uuid4())),
        changes=json.dumps({"code": location.code}),
    ))
    database.commit()
    database.refresh(location)
    return location


@router.get("/inventory/movements", response_model=list[InventoryMovementRead])
def list_inventory_movements(user: User = Depends(get_current_user), database: Session = Depends(get_db)) -> list[InventoryMovement]:
    return list(database.scalars(select(InventoryMovement).where(InventoryMovement.organization_id == user.organization_id).order_by(InventoryMovement.id.desc())).all())


@router.post("/inventory/movements", response_model=InventoryMovementRead, status_code=status.HTTP_201_CREATED)
def create_inventory_movement(
    payload: InventoryMovementCreate,
    request: Request,
    user: User = Depends(require_permission("inventory")),
    database: Session = Depends(get_db),
) -> InventoryMovement:
    part = database.scalar(select(Part).where(Part.id == payload.part_id, Part.organization_id == user.organization_id))
    location = database.scalar(select(StockLocation).where(StockLocation.id == payload.location_id, StockLocation.organization_id == user.organization_id))
    if part is None or location is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Part or stock location not found in this organization")
    delta = payload.quantity if payload.transaction_type == "receipt" else -payload.quantity
    if payload.transaction_type == "adjustment":
        delta = payload.quantity
    if part.quantity_on_hand + delta < 0:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Insufficient stock for this issue")
    part.quantity_on_hand += delta
    movement = InventoryMovement(organization_id=user.organization_id, created_by=user.id, **payload.model_dump())
    database.add(movement)
    database.flush()
    database.add(AuditLog(
        organization_id=user.organization_id,
        actor_user_id=user.id,
        action=f"inventory_movement.{payload.transaction_type}",
        entity_type="inventory_movement",
        entity_id=str(movement.id),
        request_id=request.headers.get("x-request-id", str(uuid4())),
        changes=json.dumps({"part_id": part.id, "location_id": location.id, "delta": delta}),
    ))
    database.commit()
    database.refresh(movement)
    return movement


@router.get("/documents", response_model=list[DocumentRead])
def list_documents(user: User = Depends(get_current_user), database: Session = Depends(get_db)) -> list[ComplianceDocument]:
    statement = select(ComplianceDocument).where(ComplianceDocument.organization_id == user.organization_id)
    if user.role == "driver":
        statement = statement.where(ComplianceDocument.vehicle_id.in_(
            select(Vehicle.id).where(Vehicle.assigned_driver_id == user.id)
        ))
    elif user.role not in ("owner", "fleet_manager", "driver"):
        statement = statement.where(ComplianceDocument.id == -1)
    documents = list(database.scalars(statement.order_by(ComplianceDocument.expires_on.asc())).all())
    today = date.today().isoformat()
    for document in documents:
        if document.expires_on < today:
            document.status = "Expired"
    return documents


@router.post("/documents", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
def create_document(
    payload: DocumentCreate,
    request: Request,
    user: User = Depends(require_permission("compliance")),
    database: Session = Depends(get_db),
) -> ComplianceDocument:
    if payload.vehicle_id is not None:
        vehicle = database.scalar(select(Vehicle).where(Vehicle.id == payload.vehicle_id, Vehicle.organization_id == user.organization_id))
        if vehicle is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle not found in this organization")
    document = ComplianceDocument(organization_id=user.organization_id, **payload.model_dump())
    database.add(document)
    database.flush()
    database.add(AuditLog(
        organization_id=user.organization_id,
        actor_user_id=user.id,
        action="document.created",
        entity_type="compliance_document",
        entity_id=str(document.id),
        request_id=request.headers.get("x-request-id", str(uuid4())),
        changes=json.dumps({"name": document.name, "expires_on": document.expires_on}),
    ))
    database.commit()
    database.refresh(document)
    return document


@router.patch("/documents/{document_id}", response_model=DocumentRead)
def update_document(
    document_id: int,
    payload: DocumentUpdate,
    request: Request,
    user: User = Depends(require_permission("compliance")),
    database: Session = Depends(get_db),
) -> ComplianceDocument:
    document = database.scalar(select(ComplianceDocument).where(ComplianceDocument.id == document_id, ComplianceDocument.organization_id == user.organization_id))
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    changes = payload.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(document, key, value)
    database.add(AuditLog(
        organization_id=user.organization_id,
        actor_user_id=user.id,
        action="document.updated",
        entity_type="compliance_document",
        entity_id=str(document.id),
        request_id=request.headers.get("x-request-id", str(uuid4())),
        changes=json.dumps(changes),
    ))
    database.commit()
    database.refresh(document)
    return document


@router.post("/documents/{document_id}/file", response_model=DocumentAssetRead, status_code=status.HTTP_201_CREATED)
def upload_document_file(
    document_id: int,
    request: Request,
    file: UploadFile = File(...),
    user: User = Depends(require_permission("compliance")),
    database: Session = Depends(get_db),
) -> DocumentAsset:
    document = database.scalar(select(ComplianceDocument).where(ComplianceDocument.id == document_id, ComplianceDocument.organization_id == user.organization_id))
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    if not file.filename:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="A file name is required")
    try:
        object_key, size_bytes, checksum = save_upload(file, f"organizations/{user.organization_id}")
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(error)) from error
    asset = DocumentAsset(
        organization_id=user.organization_id,
        document_id=document.id,
        object_key=object_key,
        file_name=file.filename[:255],
        content_type=file.content_type or "application/octet-stream",
        size_bytes=size_bytes,
        checksum_sha256=checksum,
        uploaded_by=user.id,
    )
    document.file_key = object_key
    database.add(asset)
    database.flush()
    latest_version = database.scalar(select(DocumentVersion).where(
        DocumentVersion.document_id == document.id,
        DocumentVersion.organization_id == user.organization_id,
    ).order_by(DocumentVersion.version_number.desc()))
    database.add(DocumentVersion(
        organization_id=user.organization_id,
        document_id=document.id,
        version_number=(latest_version.version_number + 1) if latest_version else 1,
        name=document.name,
        document_type=document.document_type,
        expires_on=document.expires_on,
        asset_id=asset.id,
        created_by=user.id,
    ))
    database.add(AuditLog(
        organization_id=user.organization_id,
        actor_user_id=user.id,
        action="document.file_uploaded",
        entity_type="compliance_document",
        entity_id=str(document.id),
        request_id=request.headers.get("x-request-id", str(uuid4())),
        changes=json.dumps({"asset_id": asset.id, "object_key": object_key, "size_bytes": size_bytes}),
    ))
    database.commit()
    database.refresh(asset)
    return asset


@router.get("/documents/{document_id}/versions", response_model=list[DocumentVersionRead])
def list_document_versions(
    document_id: int,
    user: User = Depends(require_permission("compliance")),
    database: Session = Depends(get_db),
) -> list[DocumentVersion]:
    document = database.scalar(select(ComplianceDocument).where(
        ComplianceDocument.id == document_id,
        ComplianceDocument.organization_id == user.organization_id,
    ))
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return list(database.scalars(select(DocumentVersion).where(
        DocumentVersion.document_id == document_id,
        DocumentVersion.organization_id == user.organization_id,
    ).order_by(DocumentVersion.version_number.desc())).all())


@router.get("/documents/{document_id}/file")
def download_document_file(
    document_id: int,
    user: User = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> Response:
    asset = database.scalar(
        select(DocumentAsset)
        .where(DocumentAsset.document_id == document_id, DocumentAsset.organization_id == user.organization_id)
        .order_by(DocumentAsset.id.desc())
    )
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document file not found")
    try:
        if get_settings().storage_backend == "local":
            path = resolve_object(asset.object_key)
            if not path.is_file():
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document file not found")
            return FileResponse(path, media_type=asset.content_type, filename=asset.file_name)
        content = download_object(asset.object_key)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    return Response(
        content=content,
        media_type=asset.content_type,
        headers={"Content-Disposition": f'attachment; filename="{asset.file_name}"'},
    )


def build_alerts(user: User, database: Session) -> list[dict[str, str | int]]:
    today = date.today()
    alerts: list[dict[str, str | int]] = []
    documents = database.scalars(select(ComplianceDocument).where(ComplianceDocument.organization_id == user.organization_id)).all()
    for document in documents:
        expires_on = date.fromisoformat(document.expires_on)
        days_until_expiry = (expires_on - today).days
        if days_until_expiry <= 30:
            alerts.append({
                "type": "document_expiry",
                "severity": "danger" if days_until_expiry < 0 else "warning",
                "entity_id": document.id,
                "title": f"{document.name} {'expired' if days_until_expiry < 0 else 'expires soon'}",
                "detail": f"{abs(days_until_expiry)} days {'overdue' if days_until_expiry < 0 else 'remaining'}",
            })
    parts = database.scalars(select(Part).where(Part.organization_id == user.organization_id)).all()
    for part in parts:
        if part.quantity_on_hand <= part.reorder_level:
            alerts.append({
                "type": "stock_reorder",
                "severity": "warning",
                "entity_id": part.id,
                "title": f"Reorder {part.name}",
                "detail": f"{part.quantity_on_hand} on hand, minimum {part.reorder_level}",
            })
    vehicles = database.scalars(select(Vehicle).where(Vehicle.organization_id == user.organization_id)).all()
    for vehicle in vehicles:
        components = database.scalars(select(VehicleComponent).where(
            VehicleComponent.organization_id == user.organization_id,
            VehicleComponent.vehicle_id == vehicle.id,
        )).all()
        for component in components:
            if component.next_service_km is not None and vehicle.odometer_km >= component.next_service_km:
                alerts.append({
                    "type": "component_due",
                    "severity": "danger",
                    "entity_id": component.id,
                    "title": f"{component.name} service due",
                    "detail": f"{vehicle.registration_number} has reached {vehicle.odometer_km} km; service threshold {component.next_service_km} km",
                })
        if vehicle.status == "Out of service":
            alerts.append({
                "type": "driver_safety",
                "severity": "danger",
                "entity_id": vehicle.id,
                "title": f"{vehicle.registration_number} is out of service",
                "detail": "A driver inspection marked this vehicle unsafe.",
            })
    work_orders = database.scalars(select(WorkOrder).where(
        WorkOrder.organization_id == user.organization_id,
        WorkOrder.status.in_(["Open", "In progress", "Ready for review"]),
    )).all()
    for work_order in work_orders:
        if work_order.due_date and work_order.due_date < date.today().isoformat():
            alerts.append({
                "type": "maintenance_due",
                "severity": "danger",
                "entity_id": work_order.id,
                "title": f"Work order {work_order.id} is overdue",
                "detail": f"Due {work_order.due_date}; current status is {work_order.status}",
            })
    return alerts


@router.get("/alerts")
def list_alerts(user: User = Depends(get_current_user), database: Session = Depends(get_db)) -> list[dict[str, str | int]]:
    return build_alerts(user, database)


def dispatch_sms(delivery: NotificationDelivery, notification: OperationalNotification, recipient: User) -> None:
    settings = get_settings()
    if not recipient.mobile_phone:
        delivery.status = "skipped"
        return
    if not settings.sms_provider or not settings.sms_auth_token:
        delivery.status = "queued"
        return
    try:
        if settings.sms_provider.lower() == "twilio":
            account_sid = settings.sms_account_sid
            from_number = settings.sms_from_number or settings.sms_sender_id
            if not account_sid or not from_number:
                delivery.status = "queued"
                return
            response = httpx.post(
                settings.sms_api_url or f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json",
                auth=httpx.BasicAuth(settings.sms_account_sid or "", settings.sms_auth_token),
                data={
                    "To": recipient.mobile_phone,
                    "From": from_number,
                    "Body": f"{notification.title}: {notification.detail}",
                },
                timeout=10,
            )
        else:
            if not settings.sms_api_url:
                delivery.status = "queued"
                return
            response = httpx.post(
                settings.sms_api_url,
                headers={
                    "Authorization": settings.sms_auth_token,
                    "Content-Type": "application/json",
                },
                json={
                    "sender": settings.sms_sender_id,
                    "template_id": settings.sms_template_id,
                    "recipients": [{"mobiles": recipient.mobile_phone, "title": notification.title, "detail": notification.detail}],
                },
                timeout=10,
            )
        if response.is_error:
            delivery.status = "failed"
            return
        delivery.status = "delivered"
        delivery.provider_message_id = str(response.json().get("message_id") or response.headers.get("x-request-id") or "")
        delivery.sent_at = utc_now()
    except (httpx.HTTPError, ValueError):
        delivery.status = "failed"


def dispatch_whatsapp(delivery: NotificationDelivery, notification: OperationalNotification, recipient: User) -> None:
    settings = get_settings()
    if not recipient.mobile_phone:
        delivery.status = "skipped"
        return
    if not settings.whatsapp_provider or not settings.whatsapp_auth_token:
        delivery.status = "queued"
        return
    try:
        if settings.whatsapp_provider.lower() == "twilio":
            account_sid = settings.whatsapp_account_sid or settings.sms_account_sid
            from_number = settings.whatsapp_from_number or settings.whatsapp_sender_id
            if not account_sid or not from_number:
                delivery.status = "queued"
                return
            response = httpx.post(
                settings.whatsapp_api_url or f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json",
                auth=httpx.BasicAuth(account_sid, settings.whatsapp_auth_token),
                data={
                    "To": f"whatsapp:{recipient.mobile_phone}",
                    "From": from_number if from_number.startswith("whatsapp:") else f"whatsapp:{from_number}",
                    "Body": f"{notification.title}: {notification.detail}",
                },
                timeout=10,
            )
        else:
            if not settings.whatsapp_api_url:
                delivery.status = "queued"
                return
            response = httpx.post(
                settings.whatsapp_api_url,
                headers={
                    "Authorization": f"Bearer {settings.whatsapp_auth_token}",
                    "Content-Type": "application/json",
                },
                json={
                    "sender": settings.whatsapp_sender_id,
                    "template_id": settings.whatsapp_template_id,
                    "recipient": recipient.mobile_phone,
                    "variables": {
                        "title": notification.title,
                        "detail": notification.detail,
                    },
                },
                timeout=10,
            )
        if response.is_error:
            delivery.status = "failed"
            return
        delivery.status = "delivered"
        delivery.provider_message_id = str(response.json().get("message_id") or response.headers.get("x-request-id") or "")
        delivery.sent_at = utc_now()
    except (httpx.HTTPError, ValueError):
        delivery.status = "failed"


def queue_role_notification(
    database: Session,
    organization_id: int,
    notification_type: str,
    severity: str,
    title: str,
    detail: str,
    entity_type: str,
    entity_id: str,
    roles: set[str],
    user_ids: set[int] | None = None,
) -> None:
    dedupe_key = f"{notification_type}:{entity_id}"
    existing = database.scalar(select(OperationalNotification).where(
        OperationalNotification.organization_id == organization_id,
        OperationalNotification.dedupe_key == dedupe_key,
    ))
    if existing is not None:
        return
    notification = OperationalNotification(
        organization_id=organization_id,
        notification_type=notification_type,
        severity=severity,
        title=title,
        detail=detail,
        entity_type=entity_type,
        entity_id=entity_id,
        dedupe_key=dedupe_key,
        status="unread",
    )
    database.add(notification)
    database.flush()
    recipients = database.scalars(select(User).where(
        User.organization_id == organization_id,
        User.role.in_(roles),
    )).all()
    if user_ids:
        recipients.extend(database.scalars(select(User).where(
            User.organization_id == organization_id,
            User.id.in_(user_ids),
        )).all())
    unique_recipients = {recipient.id: recipient for recipient in recipients}.values()
    for recipient in unique_recipients:
        preference = database.scalar(select(NotificationPreference).where(
            NotificationPreference.organization_id == organization_id,
            NotificationPreference.user_id == recipient.id,
            NotificationPreference.notification_type == notification_type,
        ))
        channels = ["in_app"]
        if recipient.mobile_phone:
            channels.append("sms")
        if preference is not None:
            if preference.email:
                channels.append("email")
            if preference.sms and "sms" not in channels:
                channels.append("sms")
            if preference.whatsapp:
                channels.append("whatsapp")
            if preference.push:
                channels.append("push")
        for channel in channels:
            database.add(NotificationDelivery(
                organization_id=organization_id,
                notification_id=notification.id,
                user_id=recipient.id,
                channel=channel,
                status="queued" if channel != "in_app" else "delivered",
                sent_at=utc_now() if channel == "in_app" else None,
            ))


def sync_notifications(user: User, database: Session) -> None:
    for alert in build_alerts(user, database):
        if alert["type"] == "document_expiry":
            entity_type = "compliance_document"
        elif alert["type"] == "stock_reorder":
            entity_type = "part"
        elif alert["type"] in {"component_due", "driver_safety"}:
            entity_type = "vehicle"
        else:
            entity_type = "work_order"
        entity_id = str(alert["entity_id"])
        dedupe_key = f"{alert['type']}:{entity_id}:{alert['detail']}"
        existing = database.scalar(
            select(OperationalNotification).where(
                OperationalNotification.organization_id == user.organization_id,
                OperationalNotification.dedupe_key == dedupe_key,
            )
        )
        if existing is not None:
            if existing.status == "dismissed":
                continue
            existing.title = str(alert["title"])
            existing.detail = str(alert["detail"])
            existing.severity = str(alert["severity"])
            continue
        notification = OperationalNotification(
            organization_id=user.organization_id,
            notification_type=str(alert["type"]),
            severity=str(alert["severity"]),
            title=str(alert["title"]),
            detail=str(alert["detail"]),
            entity_type=entity_type,
            entity_id=entity_id,
            dedupe_key=dedupe_key,
            status="unread",
        )
        database.add(notification)
        database.flush()
        recipients = database.scalars(select(User).where(User.organization_id == user.organization_id)).all()
        for recipient in recipients:
            preference = database.scalar(select(NotificationPreference).where(
                NotificationPreference.organization_id == user.organization_id,
                NotificationPreference.user_id == recipient.id,
                NotificationPreference.notification_type == str(alert["type"]),
            ))
            channels = ["in_app"]
            if recipient.mobile_phone:
                channels.append("sms")
            if preference is not None:
                if preference.email:
                    channels.append("email")
                if preference.sms:
                    if "sms" not in channels:
                        channels.append("sms")
                if preference.whatsapp:
                    channels.append("whatsapp")
                if preference.push:
                    channels.append("push")
            for channel in channels:
                existing_delivery = database.scalar(select(NotificationDelivery).where(
                    NotificationDelivery.notification_id == notification.id,
                    NotificationDelivery.user_id == recipient.id,
                    NotificationDelivery.channel == channel,
                ))
                if existing_delivery is None:
                    delivery = NotificationDelivery(
                        organization_id=user.organization_id,
                        notification_id=notification.id,
                        user_id=recipient.id,
                        channel=channel,
                        status="queued" if channel != "in_app" else "delivered",
                        sent_at=utc_now() if channel == "in_app" else None,
                    )
                    database.add(delivery)
                    database.flush()
                    if channel == "sms":
                        dispatch_sms(delivery, notification, recipient)
                    elif channel == "whatsapp":
                        dispatch_whatsapp(delivery, notification, recipient)
    database.commit()


@router.get("/notifications", response_model=list[NotificationRead])
def list_notifications(user: User = Depends(get_current_user), database: Session = Depends(get_db)) -> list[OperationalNotification]:
    sync_notifications(user, database)
    return list(database.scalars(
        select(OperationalNotification).join(
            NotificationDelivery,
            NotificationDelivery.notification_id == OperationalNotification.id,
        )
        .where(
            OperationalNotification.organization_id == user.organization_id,
            NotificationDelivery.organization_id == user.organization_id,
            NotificationDelivery.user_id == user.id,
            NotificationDelivery.channel == "in_app",
        )
        .distinct()
        .order_by(OperationalNotification.id.desc())
    ).all())


@router.patch("/notifications/{notification_id}", response_model=NotificationRead)
def update_notification(
    notification_id: int,
    payload: NotificationStatusUpdate,
    request: Request,
    user: User = Depends(require_permission("notifications")),
    database: Session = Depends(get_db),
) -> OperationalNotification:
    notification = database.scalar(select(OperationalNotification).where(
        OperationalNotification.id == notification_id,
        OperationalNotification.organization_id == user.organization_id,
    ))
    if notification is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    delivery = database.scalar(select(NotificationDelivery).where(
        NotificationDelivery.notification_id == notification_id,
        NotificationDelivery.user_id == user.id,
        NotificationDelivery.channel == "in_app",
    ))
    if delivery is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    notification.status = payload.status
    notification.resolved_at = utc_now() if payload.status in {"dismissed", "resolved"} else None
    database.add(AuditLog(
        organization_id=user.organization_id,
        actor_user_id=user.id,
        action="notification.status_updated",
        entity_type="operational_notification",
        entity_id=str(notification.id),
        request_id=request.headers.get("x-request-id", str(uuid4())),
        changes=json.dumps({"status": notification.status}),
    ))
    database.commit()
    database.refresh(notification)
    return notification


@router.post("/notifications/{notification_id}/resolve", response_model=NotificationRead)
def resolve_notification(
    notification_id: int,
    request: Request,
    user: User = Depends(require_permission("notifications")),
    database: Session = Depends(get_db),
) -> OperationalNotification:
    notification = database.scalar(select(OperationalNotification).where(
        OperationalNotification.id == notification_id,
        OperationalNotification.organization_id == user.organization_id,
    ))
    if notification is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    delivery = database.scalar(select(NotificationDelivery).where(
        NotificationDelivery.notification_id == notification_id,
        NotificationDelivery.user_id == user.id,
        NotificationDelivery.channel == "in_app",
    ))
    if delivery is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    notification.status = "resolved"
    notification.resolved_at = utc_now()
    database.add(AuditLog(
        organization_id=user.organization_id,
        actor_user_id=user.id,
        action="notification.resolved",
        entity_type="operational_notification",
        entity_id=str(notification.id),
        request_id=request.headers.get("x-request-id", str(uuid4())),
    ))
    database.commit()
    database.refresh(notification)
    return notification


@router.get("/expenses", response_model=list[ExpenseRead])
def list_expenses(user: User = Depends(get_current_user), database: Session = Depends(get_db)) -> list[Expense]:
    statement = select(Expense).where(Expense.organization_id == user.organization_id)
    if user.role not in ("owner", "accountant"):
        statement = statement.where(Expense.id == -1)
    return list(database.scalars(statement.order_by(Expense.incurred_on.desc(), Expense.id.desc())).all())


@router.post("/expenses", response_model=ExpenseRead, status_code=status.HTTP_201_CREATED)
def create_expense(
    payload: ExpenseCreate,
    request: Request,
    user: User = Depends(require_permission("finance")),
    database: Session = Depends(get_db),
) -> Expense:
    reserve_idempotency_key(request, user, database)
    if payload.vehicle_id is not None:
        vehicle = database.scalar(select(Vehicle).where(Vehicle.id == payload.vehicle_id, Vehicle.organization_id == user.organization_id))
        if vehicle is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle not found in this organization")
    gst_components = payload.cgst_amount_paise + payload.sgst_amount_paise + payload.igst_amount_paise
    if gst_components and gst_components != payload.gst_amount_paise:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="GST components must equal the GST amount")
    if payload.igst_amount_paise and (payload.cgst_amount_paise or payload.sgst_amount_paise):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="IGST cannot be combined with CGST or SGST")
    expense = Expense(organization_id=user.organization_id, **payload.model_dump())
    if expense.status == "Approved":
        expense.approved_by = user.id
        expense.approved_at = utc_now()
    database.add(expense)
    database.flush()
    database.add(AuditLog(
        organization_id=user.organization_id,
        actor_user_id=user.id,
        action="expense.created",
        entity_type="expense",
        entity_id=str(expense.id),
        request_id=request.headers.get("x-request-id", str(uuid4())),
        changes=json.dumps({"category": expense.category, "amount_paise": expense.amount_paise}),
    ))
    database.commit()
    database.refresh(expense)
    return expense


@router.patch("/expenses/{expense_id}", response_model=ExpenseRead)
def update_expense_status(
    expense_id: int,
    payload: ExpenseStatusUpdate,
    request: Request,
    user: User = Depends(require_permission("finance")),
    database: Session = Depends(get_db),
) -> Expense:
    expense = database.scalar(select(Expense).where(
        Expense.id == expense_id,
        Expense.organization_id == user.organization_id,
    ))
    if expense is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Expense not found")
    expense.status = payload.status
    expense.approved_by = user.id if payload.status == "Approved" else None
    expense.approved_at = utc_now() if payload.status == "Approved" else None
    database.add(AuditLog(
        organization_id=user.organization_id,
        actor_user_id=user.id,
        action="expense.status_updated",
        entity_type="expense",
        entity_id=str(expense.id),
        request_id=request.headers.get("x-request-id", str(uuid4())),
        changes=json.dumps({"status": expense.status}),
    ))
    database.commit()
    database.refresh(expense)
    return expense


@router.post("/expenses/{expense_id}/reconcile", response_model=ExpenseRead)
def reconcile_expense(
    expense_id: int,
    request: Request,
    user: User = Depends(require_roles("owner", "accountant")),
    database: Session = Depends(get_db),
) -> Expense:
    expense = database.scalar(select(Expense).where(
        Expense.id == expense_id,
        Expense.organization_id == user.organization_id,
    ))
    if expense is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Expense not found")
    if expense.status == "Rejected":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Rejected expenses cannot be reconciled")
    expense.status = "Approved"
    expense.approved_by = user.id
    expense.approved_at = utc_now()
    database.add(AuditLog(
        organization_id=user.organization_id,
        actor_user_id=user.id,
        action="expense.reconciled",
        entity_type="expense",
        entity_id=str(expense.id),
        request_id=request.headers.get("x-request-id", str(uuid4())),
    ))
    database.commit()
    database.refresh(expense)
    return expense


@router.post("/expenses/{expense_id}/reverse", response_model=ExpenseRead)
def reverse_expense(
    expense_id: int,
    payload: ExpenseReversal,
    request: Request,
    user: User = Depends(require_roles("owner", "accountant")),
    database: Session = Depends(get_db),
) -> Expense:
    expense = database.scalar(select(Expense).where(
        Expense.id == expense_id,
        Expense.organization_id == user.organization_id,
    ))
    if expense is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Expense not found")
    if expense.status == "Rejected":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Expense is already reversed")
    expense.status = "Rejected"
    database.add(AuditLog(
        organization_id=user.organization_id,
        actor_user_id=user.id,
        action="expense.reversed",
        entity_type="expense",
        entity_id=str(expense.id),
        request_id=request.headers.get("x-request-id", str(uuid4())),
        changes=json.dumps({"reason": payload.reason}),
    ))
    database.commit()
    database.refresh(expense)
    return expense


@router.get("/finance/summary", response_model=list[FinanceSummaryRead])
def finance_summary(user: User = Depends(get_current_user), database: Session = Depends(get_db)) -> list[FinanceSummaryRead]:
    totals: dict[str, dict[str, int]] = {}
    expenses = database.scalars(select(Expense).where(Expense.organization_id == user.organization_id)).all()
    for expense in expenses:
        period = expense.incurred_on[:7]
        bucket = totals.setdefault(period, {"expense": 0, "fuel": 0, "toll": 0, "gst": 0})
        bucket["expense"] += expense.amount_paise
        bucket["gst"] += expense.gst_amount_paise
    fuels = database.scalars(select(FuelTransaction).where(FuelTransaction.organization_id == user.organization_id)).all()
    for fuel in fuels:
        totals.setdefault(fuel.incurred_on[:7], {"expense": 0, "fuel": 0, "toll": 0, "gst": 0})["fuel"] += fuel.total_amount_paise
    tolls = database.scalars(select(TollTransaction).where(TollTransaction.organization_id == user.organization_id)).all()
    for toll in tolls:
        totals.setdefault(toll.incurred_on[:7], {"expense": 0, "fuel": 0, "toll": 0, "gst": 0})["toll"] += toll.amount_paise
    return [
        FinanceSummaryRead(
            period=period,
            expense_amount_paise=values["expense"],
            fuel_amount_paise=values["fuel"],
            toll_amount_paise=values["toll"],
            total_amount_paise=values["expense"] + values["fuel"] + values["toll"],
            gst_amount_paise=values["gst"],
        )
        for period, values in sorted(totals.items(), reverse=True)
    ]


@router.get("/fuel-transactions", response_model=list[FuelTransactionRead])
def list_fuel_transactions(user: User = Depends(get_current_user), database: Session = Depends(get_db)) -> list[FuelTransaction]:
    return list(database.scalars(
        select(FuelTransaction)
        .where(FuelTransaction.organization_id == user.organization_id)
        .order_by(FuelTransaction.incurred_on.desc(), FuelTransaction.id.desc())
    ).all())


@router.post("/fuel-transactions", response_model=FuelTransactionRead, status_code=status.HTTP_201_CREATED)
def create_fuel_transaction(
    payload: FuelTransactionCreate,
    request: Request,
    user: User = Depends(require_permission("finance")),
    database: Session = Depends(get_db),
) -> FuelTransaction:
    vehicle = database.scalar(select(Vehicle).where(Vehicle.id == payload.vehicle_id, Vehicle.organization_id == user.organization_id))
    if vehicle is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle not found in this organization")
    total_amount_paise = (payload.litres_milli * payload.price_per_litre_paise) // 1000
    fuel = FuelTransaction(
        organization_id=user.organization_id,
        total_amount_paise=total_amount_paise,
        created_by=user.id,
        **payload.model_dump(),
    )
    database.add(fuel)
    database.flush()
    database.add(AuditLog(
        organization_id=user.organization_id,
        actor_user_id=user.id,
        action="fuel_transaction.created",
        entity_type="fuel_transaction",
        entity_id=str(fuel.id),
        request_id=request.headers.get("x-request-id", str(uuid4())),
        changes=json.dumps({"vehicle_id": vehicle.id, "total_amount_paise": total_amount_paise}),
    ))
    database.commit()
    database.refresh(fuel)
    return fuel


@router.get("/toll-transactions", response_model=list[TollTransactionRead])
def list_toll_transactions(user: User = Depends(get_current_user), database: Session = Depends(get_db)) -> list[TollTransaction]:
    return list(database.scalars(
        select(TollTransaction)
        .where(TollTransaction.organization_id == user.organization_id)
        .order_by(TollTransaction.incurred_on.desc(), TollTransaction.id.desc())
    ).all())


@router.post("/toll-transactions", response_model=TollTransactionRead, status_code=status.HTTP_201_CREATED)
def create_toll_transaction(
    payload: TollTransactionCreate,
    request: Request,
    user: User = Depends(require_permission("finance")),
    database: Session = Depends(get_db),
) -> TollTransaction:
    vehicle = database.scalar(select(Vehicle).where(Vehicle.id == payload.vehicle_id, Vehicle.organization_id == user.organization_id))
    if vehicle is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle not found in this organization")
    toll = TollTransaction(organization_id=user.organization_id, created_by=user.id, **payload.model_dump())
    database.add(toll)
    database.flush()
    database.add(AuditLog(
        organization_id=user.organization_id,
        actor_user_id=user.id,
        action="toll_transaction.created",
        entity_type="toll_transaction",
        entity_id=str(toll.id),
        request_id=request.headers.get("x-request-id", str(uuid4())),
        changes=json.dumps({"vehicle_id": vehicle.id, "amount_paise": toll.amount_paise}),
    ))
    database.commit()
    database.refresh(toll)
    return toll


@router.get("/telematics/devices", response_model=list[TelematicsDeviceRead])
def list_telematics_devices(user: User = Depends(get_current_user), database: Session = Depends(get_db)) -> list[TelematicsDevice]:
    return list(database.scalars(
        select(TelematicsDevice)
        .where(TelematicsDevice.organization_id == user.organization_id)
        .order_by(TelematicsDevice.id.desc())
    ).all())


def integration_credential(integration: TelematicsIntegration) -> str | None:
    if not integration.credential_ref:
        return None
    env_name = f"VAHANA_TELEMATICS_TOKEN_{integration.credential_ref.upper().replace('-', '_')}"
    return os.getenv(env_name) or os.getenv(integration.credential_ref)


def normalize_external_reading(item: dict) -> dict:
    return {
        "device_identifier": item.get("device_identifier") or item.get("imei") or item.get("device_id"),
        "recorded_at": item.get("recorded_at") or item.get("timestamp") or item.get("recordedAt"),
        "odometer_km": item.get("odometer_km") if item.get("odometer_km") is not None else item.get("odometer"),
        "latitude_e6": item.get("latitude_e6") if item.get("latitude_e6") is not None else (
            round(float(item["latitude"]) * 1_000_000) if item.get("latitude") is not None else None
        ),
        "longitude_e6": item.get("longitude_e6") if item.get("longitude_e6") is not None else (
            round(float(item["longitude"]) * 1_000_000) if item.get("longitude") is not None else None
        ),
        "speed_kph": item.get("speed_kph") if item.get("speed_kph") is not None else item.get("speed"),
        "fuel_level_percent": item.get("fuel_level_percent") if item.get("fuel_level_percent") is not None else item.get("fuel_level"),
        "engine_on": item.get("engine_on"),
    }


def sync_telematics_integration(integration: TelematicsIntegration, database: Session) -> dict[str, int | str]:
    try:
        token = integration_credential(integration)
        if not token:
            integration.last_sync_status = "missing_credentials"
            database.commit()
            return {"integration_id": integration.id, "status": "missing_credentials", "readings": 0, "vehicles_updated": 0}
        validate_telematics_url(integration.base_url, resolve_host=True)
        response = httpx.get(
            f"{integration.base_url.rstrip('/')}/{integration.sync_path.lstrip('/')}",
            headers={"Authorization": f"Bearer {token}", "X-Provider": integration.provider},
            timeout=get_settings().telematics_default_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        readings = payload.get("readings", payload) if isinstance(payload, dict) else payload
        if not isinstance(readings, list):
            raise ValueError("GPS provider response must contain a readings list")
        created = 0
        updated = 0
        for raw_item in readings:
            if not isinstance(raw_item, dict):
                continue
            item = normalize_external_reading(raw_item)
            identifier = item["device_identifier"]
            recorded_at = item["recorded_at"]
            if not identifier or not recorded_at:
                continue
            device = database.scalar(select(TelematicsDevice).where(
                TelematicsDevice.organization_id == integration.organization_id,
                TelematicsDevice.device_identifier == str(identifier),
                TelematicsDevice.active.is_(True),
            ))
            if device is None:
                continue
            recorded_datetime = datetime.fromisoformat(str(recorded_at).replace("Z", "+00:00"))
            exists = database.scalar(select(TelemetryReading).where(
                TelemetryReading.device_id == device.id,
                TelemetryReading.recorded_at == recorded_datetime,
            ))
            if exists is not None:
                continue
            vehicle = database.get(Vehicle, device.vehicle_id)
            if vehicle is None:
                continue
            reading = TelemetryReading(
                organization_id=integration.organization_id,
                vehicle_id=device.vehicle_id,
                device_id=device.id,
                recorded_at=recorded_datetime,
                odometer_km=item["odometer_km"],
                latitude_e6=item["latitude_e6"],
                longitude_e6=item["longitude_e6"],
                speed_kph=item["speed_kph"],
                fuel_level_percent=item["fuel_level_percent"],
                engine_on=item["engine_on"],
            )
            database.add(reading)
            if item["odometer_km"] is not None and item["odometer_km"] > vehicle.odometer_km:
                vehicle.odometer_km = item["odometer_km"]
                updated += 1
            device.last_seen_at = recorded_datetime
            created += 1
        integration.last_synced_at = utc_now()
        integration.last_sync_status = "success"
        database.commit()
        return {"integration_id": integration.id, "status": "success", "readings": created, "vehicles_updated": updated}
    except (httpx.HTTPError, HTTPException, ValueError, TypeError, KeyError):
        integration.last_synced_at = utc_now()
        integration.last_sync_status = "failed"
        database.commit()
        return {"integration_id": integration.id, "status": "failed", "readings": 0, "vehicles_updated": 0}


@router.get("/telematics/integrations", response_model=list[TelematicsIntegrationRead])
def list_telematics_integrations(
    user: User = Depends(require_permission("fleet")),
    database: Session = Depends(get_db),
) -> list[TelematicsIntegration]:
    return list(database.scalars(select(TelematicsIntegration).where(
        TelematicsIntegration.organization_id == user.organization_id,
    ).order_by(TelematicsIntegration.id.desc())).all())


@router.get("/telematics/health", response_model=TelematicsHealthRead)
def telematics_health(
    user: User = Depends(require_permission("fleet")),
    database: Session = Depends(get_db),
) -> TelematicsHealthRead:
    now = utc_now()
    integrations = list(database.scalars(select(TelematicsIntegration).where(
        TelematicsIntegration.organization_id == user.organization_id,
    )).all())
    devices = list(database.scalars(select(TelematicsDevice).where(
        TelematicsDevice.organization_id == user.organization_id,
    )).all())
    vehicles = {
        vehicle.id: vehicle.odometer_km
        for vehicle in database.scalars(select(Vehicle).where(
            Vehicle.organization_id == user.organization_id,
        )).all()
    }
    readings = list(database.scalars(select(TelemetryReading).where(
        TelemetryReading.organization_id == user.organization_id,
        TelemetryReading.recorded_at >= now - timedelta(hours=24),
    )).all())
    return TelematicsHealthRead(
        active_integrations=sum(item.active for item in integrations),
        stale_integrations=sum(item.active and (item.last_synced_at is None or item.last_synced_at < now - timedelta(hours=48)) for item in integrations),
        active_devices=sum(item.active for item in devices),
        stale_devices=sum(item.active and (item.last_seen_at is None or item.last_seen_at < now - timedelta(hours=48)) for item in devices),
        readings_last_24h=len(readings),
        flagged_odometer_readings=sum(
            reading.odometer_km is not None
            and reading.vehicle_id in vehicles
            and reading.odometer_km < vehicles[reading.vehicle_id]
            for reading in readings
        ),
    )


@router.post("/telematics/integrations", response_model=TelematicsIntegrationRead, status_code=status.HTTP_201_CREATED)
def create_telematics_integration(
    payload: TelematicsIntegrationCreate,
    request: Request,
    user: User = Depends(require_roles("owner", "fleet_manager")),
    database: Session = Depends(get_db),
) -> TelematicsIntegration:
    validate_telematics_url(payload.base_url)
    integration = TelematicsIntegration(organization_id=user.organization_id, **payload.model_dump())
    database.add(integration)
    database.flush()
    database.add(AuditLog(
        organization_id=user.organization_id,
        actor_user_id=user.id,
        action="telematics_integration.created",
        entity_type="telematics_integration",
        entity_id=str(integration.id),
        request_id=request.headers.get("x-request-id", str(uuid4())),
        changes=json.dumps({"provider": integration.provider, "credential_ref": integration.credential_ref}),
    ))
    database.commit()
    database.refresh(integration)
    return integration


@router.patch("/telematics/integrations/{integration_id}", response_model=TelematicsIntegrationRead)
def update_telematics_integration(
    integration_id: int,
    payload: TelematicsIntegrationCreate,
    user: User = Depends(require_roles("owner", "fleet_manager")),
    database: Session = Depends(get_db),
) -> TelematicsIntegration:
    validate_telematics_url(payload.base_url)
    integration = database.scalar(select(TelematicsIntegration).where(
        TelematicsIntegration.id == integration_id,
        TelematicsIntegration.organization_id == user.organization_id,
    ))
    if integration is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Telematics integration not found")
    integration.provider = payload.provider
    integration.base_url = payload.base_url
    integration.sync_path = payload.sync_path
    integration.credential_ref = payload.credential_ref
    integration.active = payload.active
    integration.sync_interval_minutes = payload.sync_interval_minutes
    database.commit()
    database.refresh(integration)
    return integration


@router.delete("/telematics/integrations/{integration_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_telematics_integration(
    integration_id: int,
    user: User = Depends(require_roles("owner", "fleet_manager")),
    database: Session = Depends(get_db),
) -> Response:
    integration = database.scalar(select(TelematicsIntegration).where(
        TelematicsIntegration.id == integration_id,
        TelematicsIntegration.organization_id == user.organization_id,
    ))
    if integration is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Telematics integration not found")
    database.delete(integration)
    database.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/telematics/integrations/{integration_id}/sync")
def sync_telematics(
    integration_id: int,
    user: User = Depends(require_permission("fleet")),
    database: Session = Depends(get_db),
) -> dict[str, int | str]:
    integration = database.scalar(select(TelematicsIntegration).where(
        TelematicsIntegration.id == integration_id,
        TelematicsIntegration.organization_id == user.organization_id,
        TelematicsIntegration.active.is_(True),
    ))
    if integration is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Active telematics integration not found")
    return sync_telematics_integration(integration, database)


@router.post("/telematics/sync-due")
def sync_due_telematics(
    user: User = Depends(require_permission("fleet")),
    database: Session = Depends(get_db),
) -> list[dict[str, int | str]]:
    now = utc_now()
    integrations = database.scalars(select(TelematicsIntegration).where(
        TelematicsIntegration.organization_id == user.organization_id,
        TelematicsIntegration.active.is_(True),
    )).all()
    results = []
    for integration in integrations:
        if integration.last_synced_at is not None and (
            now - integration.last_synced_at
        ).total_seconds() < integration.sync_interval_minutes * 60:
            continue
        results.append(sync_telematics_integration(integration, database))
    return results


@router.post("/telematics/devices", response_model=TelematicsDeviceRead, status_code=status.HTTP_201_CREATED)
def create_telematics_device(
    payload: TelematicsDeviceCreate,
    request: Request,
    user: User = Depends(require_permission("fleet")),
    database: Session = Depends(get_db),
) -> TelematicsDevice:
    vehicle = database.scalar(select(Vehicle).where(Vehicle.id == payload.vehicle_id, Vehicle.organization_id == user.organization_id))
    if vehicle is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle not found in this organization")
    existing = database.scalar(select(TelematicsDevice).where(
        TelematicsDevice.organization_id == user.organization_id,
        TelematicsDevice.device_identifier == payload.device_identifier,
    ))
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A telematics device with this identifier already exists")
    device = TelematicsDevice(organization_id=user.organization_id, **payload.model_dump())
    database.add(device)
    database.flush()
    database.add(AuditLog(
        organization_id=user.organization_id,
        actor_user_id=user.id,
        action="telematics_device.created",
        entity_type="telematics_device",
        entity_id=str(device.id),
        request_id=request.headers.get("x-request-id", str(uuid4())),
        changes=json.dumps({"vehicle_id": vehicle.id, "provider": device.provider}),
    ))
    database.commit()
    database.refresh(device)
    return device


@router.post("/telematics/devices/{device_id}/readings", response_model=TelemetryReadingRead, status_code=status.HTTP_201_CREATED)
def ingest_telemetry(
    device_id: int,
    payload: TelemetryReadingCreate,
    request: Request,
    user: User = Depends(require_permission("fleet")),
    database: Session = Depends(get_db),
) -> TelemetryReading:
    device = database.scalar(select(TelematicsDevice).where(
        TelematicsDevice.id == device_id,
        TelematicsDevice.organization_id == user.organization_id,
        TelematicsDevice.active.is_(True),
    ))
    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Active telematics device not found")
    vehicle = database.get(Vehicle, device.vehicle_id)
    if vehicle is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle not found")
    if payload.odometer_km > vehicle.odometer_km:
        vehicle.odometer_km = payload.odometer_km
    reading = TelemetryReading(
        organization_id=user.organization_id,
        vehicle_id=device.vehicle_id,
        device_id=device.id,
        **payload.model_dump(),
    )
    device.last_seen_at = payload.recorded_at
    database.add(reading)
    database.flush()
    database.add(AuditLog(
        organization_id=user.organization_id,
        actor_user_id=user.id,
        action="telemetry_reading.ingested",
        entity_type="telemetry_reading",
        entity_id=str(reading.id),
        request_id=request.headers.get("x-request-id", str(uuid4())),
        changes=json.dumps({"device_id": device.id, "vehicle_id": device.vehicle_id}),
    ))
    database.commit()
    database.refresh(reading)
    return reading


@router.get("/telematics/vehicles/{vehicle_id}/latest", response_model=TelemetryReadingRead)
def latest_vehicle_telemetry(
    vehicle_id: int,
    user: User = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> TelemetryReading:
    reading = database.scalar(
        select(TelemetryReading)
        .where(TelemetryReading.vehicle_id == vehicle_id, TelemetryReading.organization_id == user.organization_id)
        .order_by(TelemetryReading.recorded_at.desc(), TelemetryReading.id.desc())
    )
    if reading is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No telemetry available for this vehicle")
    return reading


@router.get("/vendors", response_model=list[VendorRead])
def list_vendors(user: User = Depends(get_current_user), database: Session = Depends(get_db)) -> list[Vendor]:
    return list(database.scalars(select(Vendor).where(Vendor.organization_id == user.organization_id).order_by(Vendor.name.asc())).all())


@router.post("/vendors", response_model=VendorRead, status_code=status.HTTP_201_CREATED)
def create_vendor(
    payload: VendorCreate,
    request: Request,
    user: User = Depends(require_permission("procurement")),
    database: Session = Depends(get_db),
) -> Vendor:
    vendor = Vendor(organization_id=user.organization_id, **payload.model_dump())
    database.add(vendor)
    database.flush()
    database.add(AuditLog(
        organization_id=user.organization_id,
        actor_user_id=user.id,
        action="vendor.created",
        entity_type="vendor",
        entity_id=str(vendor.id),
        request_id=request.headers.get("x-request-id", str(uuid4())),
        changes=json.dumps({"name": vendor.name, "vendor_type": vendor.vendor_type}),
    ))
    database.commit()
    database.refresh(vendor)
    return vendor


@router.get("/purchase-orders", response_model=list[PurchaseOrderRead])
def list_purchase_orders(user: User = Depends(get_current_user), database: Session = Depends(get_db)) -> list[PurchaseOrder]:
    statement = select(PurchaseOrder).options(selectinload(PurchaseOrder.lines)).where(PurchaseOrder.organization_id == user.organization_id).order_by(PurchaseOrder.id.desc())
    return list(database.scalars(statement).unique().all())


@router.post("/purchase-orders", response_model=PurchaseOrderRead, status_code=status.HTTP_201_CREATED)
def create_purchase_order(
    payload: PurchaseOrderCreate,
    request: Request,
    user: User = Depends(require_permission("procurement")),
    database: Session = Depends(get_db),
) -> PurchaseOrder:
    vendor = database.scalar(select(Vendor).where(Vendor.id == payload.vendor_id, Vendor.organization_id == user.organization_id, Vendor.active.is_(True)))
    if vendor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Active vendor not found in this organization")
    part_ids = [line.part_id for line in payload.lines]
    parts = list(database.scalars(select(Part).where(Part.id.in_(part_ids), Part.organization_id == user.organization_id)).all())
    parts_by_id = {part.id: part for part in parts}
    if len(parts_by_id) != len(set(part_ids)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="One or more parts were not found in this organization")
    total_paise = sum(line.quantity * line.unit_cost_paise for line in payload.lines)
    order = PurchaseOrder(
        organization_id=user.organization_id,
        vendor_id=vendor.id,
        order_number=f"PO-{date.today().strftime('%Y%m%d')}-{uuid4().hex[:6].upper()}",
        expected_on=payload.expected_on,
        notes=payload.notes,
        total_paise=total_paise,
        created_by=user.id,
    )
    order.lines = [
        PurchaseOrderLine(
            organization_id=user.organization_id,
            part_id=line.part_id,
            quantity=line.quantity,
            unit_cost_paise=line.unit_cost_paise,
            line_total_paise=line.quantity * line.unit_cost_paise,
        )
        for line in payload.lines
    ]
    database.add(order)
    database.flush()
    database.add(AuditLog(
        organization_id=user.organization_id,
        actor_user_id=user.id,
        action="purchase_order.created",
        entity_type="purchase_order",
        entity_id=str(order.id),
        request_id=request.headers.get("x-request-id", str(uuid4())),
        changes=json.dumps({"vendor_id": vendor.id, "total_paise": total_paise}),
    ))
    database.commit()
    statement = select(PurchaseOrder).options(selectinload(PurchaseOrder.lines)).where(PurchaseOrder.id == order.id)
    return database.scalar(statement)


@router.patch("/purchase-orders/{purchase_order_id}", response_model=PurchaseOrderRead)
def update_purchase_order_status(
    purchase_order_id: int,
    payload: PurchaseOrderStatusUpdate,
    request: Request,
    user: User = Depends(require_permission("procurement")),
    database: Session = Depends(get_db),
) -> PurchaseOrder:
    order = database.scalar(select(PurchaseOrder).where(PurchaseOrder.id == purchase_order_id, PurchaseOrder.organization_id == user.organization_id))
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Purchase order not found")
    order.status = payload.status
    database.add(AuditLog(
        organization_id=user.organization_id,
        actor_user_id=user.id,
        action="purchase_order.status_updated",
        entity_type="purchase_order",
        entity_id=str(order.id),
        request_id=request.headers.get("x-request-id", str(uuid4())),
        changes=json.dumps({"status": order.status}),
    ))
    database.commit()
    statement = select(PurchaseOrder).options(selectinload(PurchaseOrder.lines)).where(PurchaseOrder.id == order.id)
    return database.scalar(statement)


@router.get("/purchase-orders/{purchase_order_id}/receipts", response_model=list[PurchaseOrderReceiptRead])
def list_purchase_order_receipts(
    purchase_order_id: int,
    user: User = Depends(require_permission("procurement")),
    database: Session = Depends(get_db),
) -> list[PurchaseOrderReceipt]:
    order = database.scalar(select(PurchaseOrder).where(
        PurchaseOrder.id == purchase_order_id,
        PurchaseOrder.organization_id == user.organization_id,
    ))
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Purchase order not found")
    return list(database.scalars(select(PurchaseOrderReceipt).where(
        PurchaseOrderReceipt.organization_id == user.organization_id,
        PurchaseOrderReceipt.purchase_order_id == purchase_order_id,
    ).order_by(PurchaseOrderReceipt.id.desc())).all())


@router.post("/purchase-orders/{purchase_order_id}/receipts", response_model=PurchaseOrderReceiptRead, status_code=status.HTTP_201_CREATED)
def receive_purchase_order(
    purchase_order_id: int,
    payload: PurchaseOrderReceiptCreate,
    request: Request,
    user: User = Depends(require_permission("procurement")),
    database: Session = Depends(get_db),
) -> PurchaseOrderReceipt:
    reserve_idempotency_key(request, user, database)
    order = database.scalar(select(PurchaseOrder).where(
        PurchaseOrder.id == purchase_order_id,
        PurchaseOrder.organization_id == user.organization_id,
    ))
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Purchase order not found")
    part = database.scalar(select(Part).where(
        Part.id == payload.part_id,
        Part.organization_id == user.organization_id,
    ))
    if part is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Part not found in this organization")
    line = database.scalar(select(PurchaseOrderLine).where(
        PurchaseOrderLine.organization_id == user.organization_id,
        PurchaseOrderLine.purchase_order_id == order.id,
        PurchaseOrderLine.part_id == payload.part_id,
    ))
    if line is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Part is not included in this purchase order")
    if payload.damaged_quantity > payload.quantity:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Damaged quantity cannot exceed received quantity")
    prior_receipts = list(database.scalars(select(PurchaseOrderReceipt).where(
        PurchaseOrderReceipt.organization_id == user.organization_id,
        PurchaseOrderReceipt.purchase_order_id == order.id,
        PurchaseOrderReceipt.part_id == payload.part_id,
    )).all())
    if sum(receipt.quantity for receipt in prior_receipts) + payload.quantity > line.quantity:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Receipt quantity exceeds the ordered quantity")
    if payload.location_id is not None and database.scalar(select(StockLocation).where(
        StockLocation.id == payload.location_id,
        StockLocation.organization_id == user.organization_id,
    )) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Receiving location not found")
    receipt = PurchaseOrderReceipt(
        organization_id=user.organization_id,
        purchase_order_id=order.id,
        received_by=user.id,
        **payload.model_dump(),
    )
    part.quantity_on_hand += payload.quantity - payload.damaged_quantity
    order.status = "Partially received"
    database.add(receipt)
    database.add(InventoryTransaction(
        organization_id=user.organization_id,
        part_id=part.id,
        transaction_type="receipt",
        quantity=payload.quantity - payload.damaged_quantity,
        reference=order.order_number,
        created_by=user.id,
    ))
    database.add(AuditLog(
        organization_id=user.organization_id,
        actor_user_id=user.id,
        action="purchase_order.received",
        entity_type="purchase_order",
        entity_id=str(order.id),
        request_id=request.headers.get("x-request-id", str(uuid4())),
        changes=json.dumps({"part_id": part.id, "quantity": payload.quantity, "damaged_quantity": payload.damaged_quantity}),
    ))
    database.commit()
    database.refresh(receipt)
    return receipt


@router.get("/purchase-orders/{purchase_order_id}/download")
def download_purchase_order(
    purchase_order_id: int,
    user: User = Depends(require_permission("procurement")),
    database: Session = Depends(get_db),
) -> Response:
    order = database.scalar(select(PurchaseOrder).options(selectinload(PurchaseOrder.lines)).where(
        PurchaseOrder.id == purchase_order_id,
        PurchaseOrder.organization_id == user.organization_id,
    ))
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Purchase order not found")
    vendor = database.scalar(select(Vendor).where(Vendor.id == order.vendor_id))
    rows = ["Order number,Vendor,Status,Expected on,Part ID,Quantity,Unit cost paise,Line total paise"]
    for line in order.lines:
        rows.append(",".join(map(str, [
            order.order_number,
            (vendor.name if vendor else ""),
            order.status,
            order.expected_on or "",
            line.part_id,
            line.quantity,
            line.unit_cost_paise,
            line.line_total_paise,
        ])))
    return Response(
        content="\n".join(rows),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{order.order_number}.csv"'},
    )


@router.get("/export/{resource}")
def export_resource(
    resource: str,
    user: User = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> Response:
    required_roles = {
        "vehicles": {"owner", "fleet_manager"},
        "components": {"owner", "fleet_manager"},
        "parts": {"owner", "inventory_manager"},
        "vendors": {"owner", "inventory_manager"},
    }
    if user.role not in required_roles.get(resource, set()):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Role cannot export this resource")
    if resource == "vehicles":
        rows = database.scalars(select(Vehicle).where(Vehicle.organization_id == user.organization_id)).all()
        headers = ["registration_number", "model", "vehicle_type", "depot", "status", "health", "odometer_km"]
        data = [[row.registration_number, row.model, row.vehicle_type, row.depot, row.status, row.health, row.odometer_km] for row in rows]
    elif resource == "components":
        rows = database.scalars(select(VehicleComponent).where(VehicleComponent.organization_id == user.organization_id)).all()
        headers = ["vehicle_id", "name", "component_type", "serial_number", "installed_at_km", "last_service_km", "service_interval_km", "next_service_km", "status"]
        data = [[row.vehicle_id, row.name, row.component_type, row.serial_number or "", row.installed_at_km, row.last_service_km or "", row.service_interval_km or "", row.next_service_km or "", row.status] for row in rows]
    elif resource == "parts":
        rows = database.scalars(select(Part).where(Part.organization_id == user.organization_id)).all()
        headers = ["sku", "name", "category", "quantity_on_hand", "reorder_level", "unit_cost_paise", "supplier"]
        data = [[row.sku, row.name, row.category, row.quantity_on_hand, row.reorder_level, row.unit_cost_paise, row.supplier or ""] for row in rows]
    elif resource == "vendors":
        rows = database.scalars(select(Vendor).where(Vendor.organization_id == user.organization_id)).all()
        headers = ["name", "vendor_type", "gstin", "phone", "email", "active"]
        data = [[row.name, row.vendor_type, row.gstin or "", row.phone or "", row.email or "", row.active] for row in rows]
    else:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unsupported export resource")
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(headers)
    writer.writerows(data)
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{resource}.csv"'},
    )


@router.post("/import/vehicles", status_code=status.HTTP_201_CREATED)
async def import_vehicles(
    file: UploadFile = File(...),
    user: User = Depends(require_permission("fleet")),
    database: Session = Depends(get_db),
) -> dict[str, int]:
    content = (await file.read(MAX_IMPORT_BYTES + 1)).decode("utf-8-sig")
    if len(content.encode("utf-8")) > MAX_IMPORT_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Import file is too large")
    imported = 0
    for row_number, row in enumerate(csv.DictReader(io.StringIO(content)), start=1):
        if row_number > MAX_IMPORT_ROWS:
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Import contains too many rows")
        registration = row["registration_number"].strip().upper()
        if database.scalar(select(Vehicle).where(Vehicle.organization_id == user.organization_id, Vehicle.registration_number == registration)):
            continue
        database.add(Vehicle(
            organization_id=user.organization_id,
            registration_number=registration,
            model=row["model"].strip(),
            vehicle_type=row.get("vehicle_type", "Heavy truck").strip(),
            depot=row.get("depot", "Unassigned").strip(),
            status=row.get("status", "Idle / parked").strip(),
            health=int(row.get("health") or 100),
            odometer_km=int(row.get("odometer_km") or 0),
        ))
        imported += 1
    database.commit()
    return {"imported": imported}


@router.post("/import/parts", status_code=status.HTTP_201_CREATED)
async def import_parts(
    file: UploadFile = File(...),
    user: User = Depends(require_permission("inventory")),
    database: Session = Depends(get_db),
) -> dict[str, int]:
    content = (await file.read(MAX_IMPORT_BYTES + 1)).decode("utf-8-sig")
    if len(content.encode("utf-8")) > MAX_IMPORT_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Import file is too large")
    imported = 0
    for row_number, row in enumerate(csv.DictReader(io.StringIO(content)), start=1):
        if row_number > MAX_IMPORT_ROWS:
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Import contains too many rows")
        sku = row["sku"].strip().upper()
        if database.scalar(select(Part).where(Part.organization_id == user.organization_id, Part.sku == sku)):
            continue
        database.add(Part(
            organization_id=user.organization_id,
            sku=sku,
            name=row["name"].strip(),
            category=row.get("category", "General").strip(),
            quantity_on_hand=int(row.get("quantity_on_hand") or 0),
            reorder_level=int(row.get("reorder_level") or 0),
            unit_cost_paise=int(row.get("unit_cost_paise") or 0),
            supplier=row.get("supplier") or None,
        ))
        imported += 1
    database.commit()
    return {"imported": imported}


def seed_database() -> None:
    from .database import Base, engine

    settings = get_settings()
    if settings.environment.lower() == "development":
        Base.metadata.create_all(bind=engine)
    with next(get_db()) as database:
        if database.scalar(select(User).where(User.email == settings.seed_admin_email.lower())):
            return
        organization = database.scalar(select(Organization).where(Organization.slug == "rajput-logistics"))
        if organization is None:
            organization = Organization(name="Rajput Logistics", slug="rajput-logistics")
            database.add(organization)
            database.flush()
        database.add(User(
            organization_id=organization.id,
            email=settings.seed_admin_email.lower(),
            full_name="Arjun Mehta",
            password_hash=hash_password(settings.seed_admin_password),
            role="owner",
        ))
        if database.scalar(select(Vehicle).where(Vehicle.organization_id == organization.id)) is None:
            database.add_all([
                Vehicle(organization_id=organization.id, registration_number="MH 12 QX 4821", model="Ashok Leyland 3520", vehicle_type="Heavy truck", depot="Pune Central", status="On route", health=92, odometer_km=84920, driver_name="Amit Kulkarni"),
                Vehicle(organization_id=organization.id, registration_number="KA 03 MN 7712", model="Tata Prima 5530", vehicle_type="Heavy truck", depot="Bengaluru Yard", status="In workshop", health=68, odometer_km=142860),
            ])
        if database.scalar(select(Part).where(Part.organization_id == organization.id)) is None:
            database.add_all([
                Part(organization_id=organization.id, sku="BP-AL-3520-F", name="Brake pad set · Front axle", category="Brakes", quantity_on_hand=8, reorder_level=5, unit_cost_paise=485000, supplier="TVS Autoparts"),
                Part(organization_id=organization.id, sku="OIL-15W40-20L", name="15W40 Diesel engine oil", category="Lubricants", quantity_on_hand=12, reorder_level=10, unit_cost_paise=326000, supplier="Castrol India"),
            ])
        database.commit()
