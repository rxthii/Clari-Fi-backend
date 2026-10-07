from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.security import HTTPAuthorizationCredentials
from mongomock_motor import AsyncMongoMockClient

from app.core.config import Settings
from app.core.deps import get_current_user
from app.core.errors import AppError
from app.core.security import decode_access_token
from app.models.schemas import LoginIn, RegisterIn
from app.services.auth import login, register
from app.services.banking import get_transactions, transaction_summary


def test_settings_accept_documented_environment_aliases():
    settings = Settings(BASE_URL="https://bank.example", CONSUMER_KEY="consumer", OBP_USERNAME="demo", OBP_PASSWORD="secret", OBP_BANK_ID="gh.29.fi", OBP_ACCOUNT_ID="account", OPENROUTER_API_KEY="router", MONGO_URI="mongodb://db", JWT_SECRET="j" * 48, ENCRYPTION_KEY="a" * 44)
    assert settings.base_url == "https://bank.example"
    assert settings.consumer_key == "consumer"
    assert settings.missing_required() == []


@pytest.mark.asyncio
async def test_register_login_wrong_password_and_logout_blacklist():
    client = AsyncMongoMockClient()
    db = client["auth-tests"]
    settings = Settings(CONSUMER_KEY="consumer", OBP_USERNAME="demo", OBP_PASSWORD="secret", OBP_BANK_ID="gh.29.fi", OBP_ACCOUNT_ID="account", OPENROUTER_API_KEY="router", MONGO_URI="mongodb://db", JWT_SECRET="j" * 48, ENCRYPTION_KEY="c" * 44)
    from cryptography.fernet import Fernet
    settings.encryption_key = Fernet.generate_key().decode()
    created = await register(db, RegisterIn(name="Asha", email="ASHA@example.com", password="strong-password"), settings)
    assert created["user"]["email"] == "asha@example.com"
    assert created["user"]["id"]
    authenticated = await login(db, LoginIn(identifier="asha@example.com", password="strong-password"), settings)
    assert authenticated["user"]["id"] == created["user"]["id"]
    with pytest.raises(AppError) as wrong:
        await login(db, LoginIn(identifier="asha@example.com", password="incorrect-password"), settings)
    assert wrong.value.code == "INVALID_CREDENTIALS"
    payload = decode_access_token(authenticated["token"], settings)
    app = FastAPI()
    app.state.db = db
    app.state.settings = settings
    from starlette.requests import Request
    request = Request({"type": "http", "headers": [], "app": app})
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=authenticated["token"])
    found = await get_current_user(request, credentials)
    assert found["email"] == "asha@example.com"
    await db.token_blacklist.insert_one({"jti": payload["jti"], "expires_at": datetime.fromtimestamp(payload["exp"], tz=timezone.utc)})
    with pytest.raises(AppError) as logged_out:
        await get_current_user(request, credentials)
    assert logged_out.value.code == "UNAUTHORIZED"
    client.close()


class FakeTransactions:
    settings = SimpleNamespace(display_currency="")
    def __init__(self, rows): self.rows = rows; self.calls = []
    async def transactions(self, user, **kwargs):
        self.calls.append(kwargs)
        return self.rows


def row(txid, description, amount, date, recipient):
    return {"id": txid, "details": {"description": description, "value": {"amount": amount, "currency": "INR"}, "completed": date, "other_account": {"holder": {"name": recipient}}}}


@pytest.mark.asyncio
async def test_transaction_type_filter_pagination_and_month_summary():
    client = AsyncMongoMockClient()
    db = client["transaction-tests"]
    user = {"_id": "user-1", "obp_link": {}}
    bank = FakeTransactions([
        row("tx1", "Cafe purchase", "-250.00", "2026-10-02T10:20:00Z", "Cafe"),
        row("tx2", "Salary payroll", "5000.00", "2026-10-01T09:00:00Z", "Employer"),
        row("tx3", "Grocery market", "-600.00", "2026-10-01T08:00:00Z", "Market"),
    ])
    spending = await get_transactions(db, bank, user, "spending", 2, 1)
    assert spending["pagination"] == {"page": 2, "totalPages": 2, "totalCount": 2}
    assert spending["transactions"][0]["category"] == "Groceries"
    income = await get_transactions(db, bank, user, "income", 1, 1)
    assert income["transactions"][0]["type"] == "income"
    summary = await transaction_summary(db, bank, user, "2026-10")
    assert summary == {"totalIncome": 5000.0, "totalSpending": 850.0, "currency": "INR"}
    client.close()


@pytest.mark.asyncio
async def test_empty_transactions_have_zero_pages_and_totals():
    client = AsyncMongoMockClient()
    db = client["empty-transactions"]
    bank = FakeTransactions([])
    result = await get_transactions(db, bank, {"_id": "user-1"}, "all", 1, 20)
    assert result == {"transactions": [], "pagination": {"page": 1, "totalPages": 0, "totalCount": 0}}
    summary = await transaction_summary(db, bank, {"_id": "user-1"}, "2026-10")
    assert summary == {"totalIncome": 0.0, "totalSpending": 0.0, "currency": "INR"}
    client.close()
