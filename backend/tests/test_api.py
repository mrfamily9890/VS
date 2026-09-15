import os
from pathlib import Path
import sys
from uuid import uuid4

os.environ["VAHANA_DATABASE_URL"] = "sqlite:///./test-vahana.db"
os.environ["VAHANA_SEED_ADMIN_EMAIL"] = "test-admin@example.com"
os.environ["VAHANA_SEED_ADMIN_PASSWORD"] = "TestPassword!123"
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fastapi.testclient import TestClient

from backend.app.database import Base, engine
from backend.app.main import app


def test_health_and_vehicle_lifecycle(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as client:
        assert client.get("/health").json()["status"] == "ok"
        response = client.post("/api/v1/auth/login", json={"email": "test-admin@example.com", "password": "TestPassword!123"})
        assert response.status_code == 200
        token = response.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        identity = client.get("/api/v1/auth/identity-provider")
        assert identity.status_code == 200
        assert identity.json()["local_login_available"] is True
        registration_number = f"DL 01 {uuid4().hex[:4].upper()}"
        created = client.post("/api/v1/vehicles", headers=headers, json={
            "registration_number": registration_number,
            "model": "Tata Signa 4825",
            "vehicle_type": "Heavy truck",
            "depot": "Delhi Hub",
        })
        assert created.status_code == 201
        assert created.json()["registration_number"] == registration_number
        vehicle_id = created.json()["id"]
        listed = client.get("/api/v1/vehicles", headers=headers)
        assert listed.status_code == 200
        assert any(vehicle["registration_number"] == registration_number for vehicle in listed.json())
        component = client.post("/api/v1/components", headers=headers, json={
            "vehicle_id": vehicle_id,
            "name": "Front axle brake pads",
            "component_type": "Brakes",
            "installed_at_km": 0,
            "service_interval_km": 1000,
        })
        assert component.status_code == 201
        assert component.json()["next_service_km"] == 1000
        odometer_update = client.patch(
            f"/api/v1/vehicles/{vehicle_id}",
            headers=headers,
            json={"odometer_km": 1000},
        )
        assert odometer_update.status_code == 200
        assert odometer_update.json()["odometer_km"] == 1000
        backwards_update = client.patch(
            f"/api/v1/vehicles/{vehicle_id}",
            headers=headers,
            json={"odometer_km": 999},
        )
        assert backwards_update.status_code == 400
        service_complete = client.post(
            f"/api/v1/components/{component.json()['id']}/service-complete?odometer_km=1000",
            headers=headers,
        )
        assert service_complete.status_code == 200
        assert service_complete.json()["last_service_km"] == 1000
        assert service_complete.json()["next_service_km"] == 2000
        work_order = client.post("/api/v1/work-orders", headers=headers, json={
            "vehicle_id": vehicle_id,
            "title": "Initial inspection",
            "priority": "High",
        })
        assert work_order.status_code == 201
        idempotency_headers = {**headers, "Idempotency-Key": f"work-order-{uuid4().hex}"}
        first_idempotent_order = client.post("/api/v1/work-orders", headers=idempotency_headers, json={
            "vehicle_id": vehicle_id,
            "title": "Idempotent inspection",
            "priority": "Low",
        })
        assert first_idempotent_order.status_code == 201
        duplicate_idempotent_order = client.post("/api/v1/work-orders", headers=idempotency_headers, json={
            "vehicle_id": vehicle_id,
            "title": "Idempotent inspection",
            "priority": "Low",
        })
        assert duplicate_idempotent_order.status_code == 409
        second_org = client.post("/api/v1/auth/signup", json={
            "organization_name": f"Second Fleet {uuid4().hex[:6]}",
            "full_name": "Second Owner",
            "email": f"second-{uuid4().hex[:8]}@example.com",
            "password": "SecondPassword!123",
        })
        assert second_org.status_code == 201
        second_headers = {"Authorization": f"Bearer {second_org.json()['access_token']}"}
        assert client.get("/api/v1/vehicles", headers=second_headers).json() == []
        assert client.patch(
            f"/api/v1/vehicles/{vehicle_id}",
            headers=second_headers,
            json={"model": "Cross tenant attempt"},
        ).status_code == 404
        work_notifications = client.get("/api/v1/notifications", headers=headers)
        assert work_notifications.status_code == 200
        assert any(item["notification_type"] == "work_order_assigned" for item in work_notifications.json())
        updated_order = client.patch(f"/api/v1/work-orders/{work_order.json()['id']}", headers=headers, json={"status": "In progress"})
        assert updated_order.status_code == 200
        assert updated_order.json()["status"] == "In progress"
        edited_order = client.patch(
            f"/api/v1/work-orders/{work_order.json()['id']}",
            headers=headers,
            json={"title": "Updated inspection", "description": "Check brakes and lights", "due_date": "2027-01-31"},
        )
        assert edited_order.status_code == 200
        assert edited_order.json()["title"] == "Updated inspection"
        assert edited_order.json()["description"] == "Check brakes and lights"
        plan = client.post("/api/v1/maintenance-plans", headers=headers, json={
            "vehicle_id": vehicle_id,
            "name": "Quarterly inspection",
            "interval_km": 15000,
            "next_due_km": 15000,
        })
        assert plan.status_code == 201
        part = client.post("/api/v1/parts", headers=headers, json={
            "sku": f"TEST-{uuid4().hex[:6].upper()}",
            "name": "Test oil filter",
            "category": "Filters",
            "quantity_on_hand": 2,
            "reorder_level": 4,
            "unit_cost_paise": 125000,
        })
        assert part.status_code == 201
        transaction = client.post("/api/v1/inventory/transactions", headers=headers, json={
            "part_id": part.json()["id"],
            "transaction_type": "receipt",
            "quantity": 3,
            "reference": "GRN-001",
        })
        assert transaction.status_code == 200
        assert transaction.json()["quantity_on_hand"] == 5
        location = client.post("/api/v1/stock-locations", headers=headers, json={
            "name": "Delhi workshop",
            "code": f"DEL-{uuid4().hex[:4].upper()}",
        })
        assert location.status_code == 201
        movement = client.post("/api/v1/inventory/movements", headers=headers, json={
            "part_id": part.json()["id"],
            "location_id": location.json()["id"],
            "transaction_type": "issue",
            "quantity": 1,
            "reference": "WO-1",
        })
        assert movement.status_code == 201
        assert client.get("/api/v1/inventory/transactions", headers=headers).status_code == 200
        document = client.post("/api/v1/documents", headers=headers, json={
            "vehicle_id": vehicle_id,
            "name": "Fitness certificate",
            "document_type": "Fitness",
            "issued_by": "Transport Department",
            "expires_on": "2027-06-18",
        })
        assert document.status_code == 201
        document_file = client.post(
            f"/api/v1/documents/{document.json()['id']}/file",
            headers=headers,
            files={"file": ("fitness.txt", b"fitness-certificate", "text/plain")},
        )
        assert document_file.status_code == 201
        assert document_file.json()["size_bytes"] == len(b"fitness-certificate")
        downloaded_file = client.get(f"/api/v1/documents/{document.json()['id']}/file", headers=headers)
        assert downloaded_file.status_code == 200
        assert downloaded_file.content == b"fitness-certificate"
        expense = client.post("/api/v1/expenses", headers=headers, json={
            "vehicle_id": vehicle_id,
            "category": "Maintenance",
            "description": "Brake service",
            "amount_paise": 970000,
            "gst_amount_paise": 18000,
            "cgst_amount_paise": 9000,
            "sgst_amount_paise": 9000,
            "incurred_on": "2027-01-15",
            "vendor": "Workshop partner",
        })
        assert expense.status_code == 201
        assert expense.json()["cgst_amount_paise"] == 9000
        invalid_gst = client.post("/api/v1/expenses", headers=headers, json={
            "category": "Maintenance",
            "description": "Invalid tax split",
            "amount_paise": 100000,
            "gst_amount_paise": 18000,
            "igst_amount_paise": 18000,
            "cgst_amount_paise": 9000,
            "incurred_on": "2027-01-15",
        })
        assert invalid_gst.status_code == 422
        assert client.get("/api/v1/expenses", headers=headers).json()[0]["description"] == "Brake service"
        approved_expense = client.patch(
            f"/api/v1/expenses/{expense.json()['id']}",
            headers=headers,
            json={"status": "Approved"},
        )
        assert approved_expense.status_code == 200
        assert approved_expense.json()["approved_by"] is not None
        fuel = client.post("/api/v1/fuel-transactions", headers=headers, json={
            "vehicle_id": vehicle_id,
            "station": "HPCL Delhi",
            "fuel_type": "Diesel",
            "litres_milli": 125000,
            "price_per_litre_paise": 9250,
            "odometer_km": 12500,
            "incurred_on": "2027-01-15",
            "reference": "FUEL-001",
        })
        assert fuel.status_code == 201
        assert fuel.json()["total_amount_paise"] == 1156250
        toll = client.post("/api/v1/toll-transactions", headers=headers, json={
            "vehicle_id": vehicle_id,
            "plaza": "Yamuna Expressway",
            "amount_paise": 185000,
            "incurred_on": "2027-01-15",
            "tag_reference": "FASTAG-001",
        })
        assert toll.status_code == 201
        assert client.get("/api/v1/fuel-transactions", headers=headers).json()[0]["id"] == fuel.json()["id"]
        assert client.get("/api/v1/toll-transactions", headers=headers).json()[0]["id"] == toll.json()["id"]
        finance = client.get("/api/v1/finance/summary", headers=headers)
        assert finance.status_code == 200
        assert finance.json()[0]["fuel_amount_paise"] == fuel.json()["total_amount_paise"]
        device = client.post("/api/v1/telematics/devices", headers=headers, json={
            "vehicle_id": vehicle_id,
            "provider": "FleetTrack",
            "device_identifier": f"FT-{uuid4().hex[:8]}",
        })
        assert device.status_code == 201
        reading = client.post(
            f"/api/v1/telematics/devices/{device.json()['id']}/readings",
            headers=headers,
            json={
                "recorded_at": "2027-01-15T10:00:00Z",
                "odometer_km": 12540,
                "latitude_e6": 28361300,
                "longitude_e6": 77192600,
                "speed_kph": 54,
                "fuel_level_percent": 62,
                "engine_on": True,
            },
        )
        assert reading.status_code == 201
        latest = client.get(f"/api/v1/telematics/vehicles/{vehicle_id}/latest", headers=headers)
        assert latest.status_code == 200
        assert latest.json()["speed_kph"] == 54
        vehicle_after_telemetry = client.get("/api/v1/vehicles", headers=headers)
        assert next(item for item in vehicle_after_telemetry.json() if item["id"] == vehicle_id)["odometer_km"] == 12540
        analytics = client.get("/api/v1/fleet/analytics", headers=headers)
        assert analytics.status_code == 200
        assert any(item["vehicle_id"] == vehicle_id for item in analytics.json()["vehicles"])
        vendor = client.post("/api/v1/vendors", headers=headers, json={
            "name": "TVS Autoparts",
            "vendor_type": "Parts supplier",
            "gstin": "27ABCDE1234F1Z5",
        })
        assert vendor.status_code == 201
        purchase_order = client.post("/api/v1/purchase-orders", headers=headers, json={
            "vendor_id": vendor.json()["id"],
            "expected_on": "2027-02-01",
            "lines": [{"part_id": part.json()["id"], "quantity": 4, "unit_cost_paise": 130000}],
        })
        assert purchase_order.status_code == 201
        assert purchase_order.json()["total_paise"] == 520000
        updated_po = client.patch(f"/api/v1/purchase-orders/{purchase_order.json()['id']}", headers=headers, json={"status": "Submitted"})
        assert updated_po.status_code == 200
        assert updated_po.json()["status"] == "Submitted"
        receipt = client.post(
            f"/api/v1/purchase-orders/{purchase_order.json()['id']}/receipts",
            headers=headers,
            json={
                "part_id": part.json()["id"],
                "quantity": 3,
                "damaged_quantity": 1,
                "backordered_quantity": 1,
                "unit_cost_paise": 130000,
            },
        )
        assert receipt.status_code == 201
        over_receipt = client.post(
            f"/api/v1/purchase-orders/{purchase_order.json()['id']}/receipts",
            headers=headers,
            json={"part_id": part.json()["id"], "quantity": 2, "unit_cost_paise": 130000},
        )
        assert over_receipt.status_code == 422
        assert client.get("/api/v1/alerts", headers=headers).status_code == 200
        contact = client.patch("/api/v1/users/me/contact", headers=headers, json={"mobile_phone": "+919999999999"})
        assert contact.status_code == 200
        profile = client.patch(
            "/api/v1/users/me",
            headers=headers,
            json={"full_name": "Updated Test Admin", "mobile_phone": "+919888888888"},
        )
        assert profile.status_code == 200
        assert profile.json()["full_name"] == "Updated Test Admin"
        assert profile.json()["mobile_phone"] == "+919888888888"
        notifications = client.get("/api/v1/notifications", headers=headers)
        assert notifications.status_code == 200
        assert notifications.json()
        deliveries = client.get("/api/v1/notification-deliveries", headers=headers)
        assert deliveries.status_code == 200
        assert any(delivery["channel"] == "in_app" for delivery in deliveries.json())
        assert any(delivery["channel"] == "sms" and delivery["status"] == "queued" for delivery in deliveries.json())
        notification_id = notifications.json()[0]["id"]
        updated_notification = client.patch(
            f"/api/v1/notifications/{notification_id}",
            headers=headers,
            json={"status": "read"},
        )
        assert updated_notification.status_code == 200
        assert updated_notification.json()["status"] == "read"
        integration = client.post("/api/v1/telematics/integrations", headers=headers, json={
            "provider": "Intangles",
            "base_url": "https://gps.example.test",
            "sync_path": "/readings",
            "sync_interval_minutes": 1440,
        })
        assert integration.status_code == 201
        synced = client.post(
            f"/api/v1/telematics/integrations/{integration.json()['id']}/sync",
            headers=headers,
        )
        assert synced.status_code == 200
        assert synced.json()["status"] == "missing_credentials"
        assert client.post("/api/v1/auth/logout", headers=headers).status_code == 204
        assert client.get("/api/v1/auth/me", headers=headers).status_code == 401


def test_execution_and_finance_parity_workflows(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as client:
        login_response = client.post("/api/v1/auth/login", json={"email": "test-admin@example.com", "password": "TestPassword!123"})
        headers = {"Authorization": f"Bearer {login_response.json()['access_token']}"}
        vehicle = client.post("/api/v1/vehicles", headers=headers, json={
            "registration_number": f"MH 12 {uuid4().hex[:4].upper()}",
            "model": "Ashok Leyland",
            "vehicle_type": "Bus",
            "depot": "Aurangabad",
        }).json()
        work_order = client.post("/api/v1/work-orders", headers=headers, json={
            "vehicle_id": vehicle["id"],
            "title": "Brake inspection",
            "priority": "High",
        }).json()
        checklist = client.put(
            f"/api/v1/work-orders/{work_order['id']}/checklist",
            headers=headers,
            json={"items": [{"title": "Inspect brake pads", "completed": True}, {"title": "Road test", "completed": True}]},
        )
        assert checklist.status_code == 200
        started = client.post(f"/api/v1/work-orders/{work_order['id']}/start", headers=headers)
        assert started.status_code == 200
        completed = client.post(f"/api/v1/work-orders/{work_order['id']}/complete", headers=headers)
        assert completed.status_code == 200
        assert completed.json()["status"] == "Ready for review"
        approved = client.post(f"/api/v1/work-orders/{work_order['id']}/approve", headers=headers)
        assert approved.status_code == 200
        assert approved.json()["status"] == "Completed"

        part = client.post("/api/v1/parts", headers=headers, json={
            "sku": f"PAD-{uuid4().hex[:6].upper()}",
            "name": "Brake pad",
            "category": "Brakes",
            "quantity_on_hand": 4,
            "reorder_level": 1,
            "unit_cost_paise": 50000,
        }).json()
        usage = client.post(
            f"/api/v1/work-orders/{work_order['id']}/parts",
            headers=headers,
            json={"part_id": part["id"], "quantity": 2},
        )
        assert usage.status_code == 201
        assert client.get(f"/api/v1/work-orders/{work_order['id']}/parts", headers=headers).json()[0]["quantity"] == 2

        expense = client.post("/api/v1/expenses", headers=headers, json={
            "vehicle_id": vehicle["id"],
            "category": "Workshop",
            "description": "Brake inspection",
            "amount_paise": 250000,
            "incurred_on": "2027-02-01",
        }).json()
        reconciled = client.post(f"/api/v1/expenses/{expense['id']}/reconcile", headers=headers)
        assert reconciled.status_code == 200
        assert reconciled.json()["status"] == "Approved"
        reversed_expense = client.post(
            f"/api/v1/expenses/{expense['id']}/reverse",
            headers=headers,
            json={"reason": "Duplicate workshop bill"},
        )
        assert reversed_expense.status_code == 200
        assert reversed_expense.json()["status"] == "Rejected"
