import os
from pathlib import Path
import sys

os.environ["VAHANA_DATABASE_URL"] = "sqlite:///./test-onboarding.db"
os.environ["VAHANA_SEED_ADMIN_EMAIL"] = "seed@example.com"
os.environ["VAHANA_SEED_ADMIN_PASSWORD"] = "SeedPassword!123"
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fastapi.testclient import TestClient

from backend.app.database import Base, engine
from backend.app.main import app


def test_organization_onboarding_invitation_and_assignment_visibility(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as client:
        signup = client.post("/api/v1/auth/signup", json={
            "organization_name": "North Star Logistics",
            "full_name": "Owner One",
            "email": "owner@northstar.example",
            "password": "OwnerPassword!123",
        })
        assert signup.status_code == 201
        owner_headers = {"Authorization": f"Bearer {signup.json()['access_token']}"}

        duplicate = client.post("/api/v1/auth/signup", json={
            "organization_name": "Another Fleet",
            "full_name": "Owner Two",
            "email": "owner@northstar.example",
            "password": "OwnerPassword!123",
        })
        assert duplicate.status_code == 409

        invitation = client.post("/api/v1/invitations", headers=owner_headers, json={
            "email": "driver@northstar.example",
            "full_name": "Driver One",
            "role": "driver",
        })
        assert invitation.status_code == 201
        driver_invite = client.post("/api/v1/auth/invitations/accept", json={
            "token": invitation.json()["invite_token"],
            "password": "DriverPassword!123",
        })
        assert driver_invite.status_code == 200
        driver_headers = {"Authorization": f"Bearer {driver_invite.json()['access_token']}"}

        driver_id = driver_invite.json()["user"]["id"]
        assigned = client.post("/api/v1/vehicles", headers=owner_headers, json={
            "registration_number": "MH 01 AA 1001",
            "model": "Tata Prima",
            "vehicle_type": "Truck",
            "depot": "Mumbai",
            "assigned_driver_id": driver_id,
        })
        assert assigned.status_code == 201
        client.post("/api/v1/vehicles", headers=owner_headers, json={
            "registration_number": "MH 01 AA 1002",
            "model": "Ashok Leyland",
            "vehicle_type": "Truck",
            "depot": "Mumbai",
        })
        driver_vehicles = client.get("/api/v1/vehicles", headers=driver_headers)
        assert driver_vehicles.status_code == 200
        assert [vehicle["registration_number"] for vehicle in driver_vehicles.json()] == ["MH 01 AA 1001"]

        invalid_role = client.post("/api/v1/invitations", headers=driver_headers, json={
            "email": "admin@northstar.example",
            "full_name": "Not Allowed",
            "role": "owner",
        })
        assert invalid_role.status_code == 403
