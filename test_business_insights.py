import os
import tempfile
import sys
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app, get_db
from app.database import Base
from app.models import User, Profile
from app.security import hash_password, create_token


@pytest.fixture
def client_with_user():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    with TestingSession() as db:
        user = User(full_name="Demo Owner", email="demo@example.com", phone="0712345678",
                    role="business_owner", password_hash=hash_password("DemoPassword123!"),
                    email_verified=True, is_active=True)
        db.add(user)
        db.commit()
        db.refresh(user)
        db.add(Profile(user_id=user.id, data_json='{"location":"Demo","business_name":"Demo Shop","business_type":"Retail"}', completed=True))
        db.commit()
        user_id = user.id

    client = TestClient(app)
    client.cookies.set("mali_mode_session", create_token(user_id))
    try:
        yield client
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
        if os.path.exists(db_path):
            os.unlink(db_path)


def test_health_and_branding(client_with_user):
    assert client_with_user.get("/health").json()["app"] == "MALI MODE"
    assert "MALI MODE" in client_with_user.get("/").text


def test_insights_use_saved_history(client_with_user):
    client = client_with_user
    today = date.today().isoformat()
    for tx_type, description, amount, category in [
        ("Sale", "Spinach bundles", 150, "Sales"),
        ("Expense", "Taxi to market", 35, "Transport"),
    ]:
        response = client.post("/api/transactions", json={
            "transaction_date": today, "transaction_type": tx_type,
            "description": description, "category": category, "amount": amount,
            "quantity": 1, "payment_method": "Cash", "source": "typed",
        })
        assert response.status_code == 200, response.text

    response = client.get("/api/business-insights")
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["records_analysed"] == 2
    assert result["current_period"]["sales"] == 150
    assert result["current_period"]["costs"] == 35
    assert result["advice"]
    assert "rule-based" in result["method"].lower()


def test_duplicate_blocked_and_transaction_edit_delete_audited(client_with_user):
    client = client_with_user
    payload = {
        "transaction_date": date.today().isoformat(), "transaction_type": "Sale",
        "description": "Custom dress order", "category": "Sales", "amount": 1800,
        "quantity": 1, "payment_method": "Bank Transfer", "source": "typed",
    }
    first = client.post("/api/transactions", json=payload, headers={"X-Mali-Raw-Input": "I made a dress for R1800"})
    assert first.status_code == 200, first.text
    duplicate = client.post("/api/transactions", json=payload)
    assert duplicate.status_code == 409
    record_id = first.json()["transaction"]["id"]

    edited = {**payload, "amount": 1900, "category": "Custom Orders"}
    update = client.put(f"/api/transactions/{record_id}", json=edited)
    assert update.status_code == 200, update.text
    assert update.json()["transaction"]["amount"] == 1900

    audit = client.get("/api/transactions/audit")
    assert audit.status_code == 200
    assert {x["action"] for x in audit.json()} >= {"created", "duplicate_blocked", "updated"}
    assert any(x["raw_input"] == "I made a dress for R1800" for x in audit.json())

    deleted = client.delete(f"/api/transactions/{record_id}")
    assert deleted.status_code == 200
    assert "deleted successfully" in deleted.json()["message"].lower()
    assert any(x["action"] == "deleted" for x in client.get("/api/transactions/audit").json())
