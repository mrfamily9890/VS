import os
from pathlib import Path
import sys
from types import SimpleNamespace
from datetime import date, timedelta

os.environ["VAHANA_DATABASE_URL"] = "sqlite:///./test-pricing-and-messaging.db"
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fastapi.testclient import TestClient

from backend.app.database import Base, engine
from backend.app.main import app
from backend.app import routes


def test_fleetops_pricing_catalog_and_mobile_normalization(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as client:
        plans = client.get("/api/v1/subscription/plans")
        assert plans.status_code == 200
        catalog = {plan["code"]: plan for plan in plans.json()}
        assert catalog["starter"]["monthly_price_paise"] == 299900
        assert catalog["starter"]["included_vehicles"] == 3
        assert catalog["starter"]["overage_vehicle_fee_paise"] == 50000
        assert catalog["growth"]["monthly_price_paise"] == 999900
        assert catalog["scale"]["monthly_price_paise"] == 2499900
        assert catalog["enterprise"]["min_vehicles"] == 100
        assert {plan["included_users"] for plan in catalog.values()} == {999999}

        signup = client.post("/api/v1/auth/signup", json={
            "organization_name": "Mobile Ready Fleet",
            "full_name": "Owner One",
            "email": "owner@mobile-ready.example",
            "mobile_phone": "9876543210",
            "password": "OwnerPassword!123",
        })
        assert signup.status_code == 201
        assert signup.json()["user"]["mobile_phone"] == "+919876543210"
        assert signup.json()["user"]["organization_name"] == "Mobile Ready Fleet"
        headers = {"Authorization": f"Bearer {signup.json()['access_token']}"}
        subscription = client.get("/api/v1/subscription", headers=headers)
        assert subscription.status_code == 200
        assert subscription.json()["status"] == "trialing"
        assert subscription.json()["trial_ends_on"] == (date.today() + timedelta(days=14)).isoformat()

        invalid = client.patch(
            "/api/v1/users/me/contact",
            headers=headers,
            json={"mobile_phone": "not-a-number"},
        )
        assert invalid.status_code == 422


def test_twilio_sms_and_whatsapp_use_server_side_provider_boundaries(monkeypatch):
    calls = []

    class Response:
        is_error = False
        headers = {"x-request-id": "provider-message"}

        def json(self):
            return {}

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return Response()

    monkeypatch.setattr(routes.httpx, "post", post)
    monkeypatch.setattr(
        routes,
        "get_settings",
        lambda: SimpleNamespace(
            sms_provider="twilio",
            sms_api_url=None,
            sms_auth_token="sms-token",
            sms_account_sid="AC123",
            sms_from_number="+15550000000",
            sms_sender_id=None,
            sms_template_id=None,
            whatsapp_provider="twilio",
            whatsapp_api_url=None,
            whatsapp_auth_token="whatsapp-token",
            whatsapp_account_sid=None,
            whatsapp_from_number="whatsapp:+15550000001",
            whatsapp_sender_id=None,
            whatsapp_template_id=None,
        ),
    )
    recipient = SimpleNamespace(mobile_phone="+919876543210")
    notification = SimpleNamespace(title="Vehicle alert", detail="Service due")
    sms_delivery = SimpleNamespace(status="queued", provider_message_id=None, sent_at=None)
    whatsapp_delivery = SimpleNamespace(status="queued", provider_message_id=None, sent_at=None)

    routes.dispatch_sms(sms_delivery, notification, recipient)
    routes.dispatch_whatsapp(whatsapp_delivery, notification, recipient)

    assert sms_delivery.status == "delivered"
    assert whatsapp_delivery.status == "delivered"
    assert calls[0][0].endswith("/Accounts/AC123/Messages.json")
    assert calls[0][1]["data"]["To"] == "+919876543210"
    assert calls[1][1]["data"]["To"] == "whatsapp:+919876543210"
