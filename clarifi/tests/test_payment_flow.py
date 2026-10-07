from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from mongomock_motor import AsyncMongoMockClient

from app.core.errors import AppError
from app.core.security import hash_secret
from app.models.schemas import TransferIn
from app.services.common import now_utc
from app.services.payments import create_draft, execute_transfer, verify_pin


class FakeBank:
    def __init__(self, amount="1000.00", result=None, failure=None):
        self.settings = SimpleNamespace(display_currency="")
        self.balance = Decimal(amount)
        self.result = result or {"id": "request-1", "status": "COMPLETED", "transaction_ids": "obp-tx-123"}
        self.failure = failure
        self.posts = 0
        self.answers = 0

    async def account(self, user):
        return {"balance": {"amount": str(self.balance), "currency": "INR"}}

    async def create_transfer(self, user, recipient, amount, currency, note):
        self.posts += 1
        if self.failure: raise self.failure
        self.balance -= amount
        return self.result

    async def answer_challenge(self, user, result):
        self.answers += 1
        return {"id": result["id"], "status": "COMPLETED", "transaction_ids": "obp-tx-challenge"}


@pytest.fixture
async def payment_setup():
    client = AsyncMongoMockClient()
    db = client["payment-tests"]
    user = {"_id": "user-1", "pin_hash": hash_secret("1234"), "password_hash": hash_secret("password1"), "pin_failed_attempts": 0, "pin_locked_until": None, "obp_link": {"bank_id": "gh.29.fi", "account_id": "sender", "view_id": "owner"}}
    await db.users.insert_one(user)
    await db.recipients.insert_one({"phone": "9876543210", "vpa": "priya@upi", "name": "Priya Sharma", "verified": True, "bank_id": "gh.29.fi", "account_id": "recipient"})
    yield db, user, client
    client.close()


@pytest.mark.asyncio
async def test_successful_transfer_uses_draft_and_returns_obp_transaction(payment_setup):
    db, user, _ = payment_setup
    bank = FakeBank()
    draft = await create_draft(db, user["_id"], "9876543210", Decimal("650.00"), "Lunch")
    result = await execute_transfer(db, bank, SimpleNamespace(per_txn_limit=50000), user, TransferIn(recipient="wrong@upi", amount=999, note="changed", pin="1234", draftId=draft["_id"]), "key-success")
    assert result["transactionId"] == "obp-tx-123"
    assert result["amount"] == 650.0
    assert result["newBalance"] == 350.0
    assert bank.posts == 1
    saved = await db.payment_drafts.find_one({"_id": draft["_id"]})
    assert saved["state"] == "EXECUTED"
    payment = await db.payments.find_one({"user_id": "user-1", "idempotency_key": "key-success"})
    assert payment["status"] == "completed"
    assert len(payment["utr"]) == 11


@pytest.mark.asyncio
async def test_idempotent_replay_returns_original_and_never_posts_twice(payment_setup):
    db, user, _ = payment_setup
    bank = FakeBank()
    draft = await create_draft(db, user["_id"], "priya@upi", Decimal("50"), "")
    data = TransferIn(recipient="priya@upi", amount=50, note="", pin="1234", draftId=draft["_id"])
    first = await execute_transfer(db, bank, SimpleNamespace(per_txn_limit=50000), user, data, "stable-key")
    second = await execute_transfer(db, bank, SimpleNamespace(per_txn_limit=50000), user, data, "stable-key")
    assert second == first
    assert bank.posts == 1


@pytest.mark.asyncio
async def test_insufficient_funds_preserves_spec_message(payment_setup):
    db, user, _ = payment_setup
    bank = FakeBank("20")
    with pytest.raises(AppError) as exc:
        await execute_transfer(db, bank, SimpleNamespace(per_txn_limit=50000), user, TransferIn(recipient="priya@upi", amount=30, note="", pin="1234"), "insufficient")
    assert (exc.value.code, exc.value.message, exc.value.status) == ("INSUFFICIENT_FUNDS", "Transaction amount exceeds available balance.", 400)
    assert bank.posts == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(("amount", "expected"), [(0, "INVALID_AMOUNT"), (-2, "INVALID_AMOUNT"), (50001, "LIMIT_EXCEEDED")])
async def test_amount_validation(payment_setup, amount, expected):
    db, user, _ = payment_setup
    with pytest.raises(AppError) as exc:
        await execute_transfer(db, FakeBank(), SimpleNamespace(per_txn_limit=50000), user, TransferIn(recipient="priya@upi", amount=amount, note="", pin="1234"), "bad-amount")
    assert exc.value.code == expected


@pytest.mark.asyncio
async def test_wrong_pin_unknown_recipient_and_expired_draft(payment_setup):
    db, user, _ = payment_setup
    with pytest.raises(AppError) as wrong:
        await execute_transfer(db, FakeBank(), SimpleNamespace(per_txn_limit=50000), user, TransferIn(recipient="priya@upi", amount=10, note="", pin="0000"), "wrong-pin")
    assert wrong.value.code == "INVALID_PIN"
    with pytest.raises(AppError) as unknown:
        await execute_transfer(db, FakeBank(), SimpleNamespace(per_txn_limit=50000), user, TransferIn(recipient="absent@upi", amount=10, note="", pin="1234"), "unknown")
    assert unknown.value.code == "RECIPIENT_NOT_FOUND"
    old = now_utc() - timedelta(minutes=11)
    await db.payment_drafts.insert_one({"_id": "expired", "user_id": "user-1", "state": "PENDING", "expires_at": old})
    with pytest.raises(AppError) as expired:
        await execute_transfer(db, FakeBank(), SimpleNamespace(per_txn_limit=50000), user, TransferIn(recipient="priya@upi", amount=10, note="", pin="1234", draftId="expired"), "expired")
    assert expired.value.code == "DRAFT_EXPIRED"


@pytest.mark.asyncio
async def test_pin_lockout_after_five_consecutive_failures(payment_setup):
    db, _, _ = payment_setup
    for _ in range(5):
        current = await db.users.find_one({"_id": "user-1"})
        with pytest.raises(AppError): await verify_pin(db, current, "0000")
    current = await db.users.find_one({"_id": "user-1"})
    with pytest.raises(AppError) as locked: await verify_pin(db, current, "1234")
    assert locked.value.code == "PIN_LOCKED"


@pytest.mark.asyncio
async def test_sandbox_challenge_is_answered_after_pin(payment_setup):
    db, user, _ = payment_setup
    bank = FakeBank(amount="2000", result={"id": "request-challenge", "status": "INITIATED", "challenge": {"id": "challenge-1"}})
    draft = await create_draft(db, user["_id"], "priya@upi", Decimal("1200"))
    result = await execute_transfer(db, bank, SimpleNamespace(per_txn_limit=50000), user, TransferIn(recipient="priya@upi", amount=1200, note="", pin="1234", draftId=draft["_id"]), "challenge-key")
    assert result["transactionId"] == "obp-tx-challenge"
    assert bank.posts == 1 and bank.answers == 1


@pytest.mark.asyncio
async def test_upstream_timeout_marks_draft_failed_without_retry(payment_setup):
    db, user, _ = payment_setup
    bank = FakeBank(failure=AppError("UPSTREAM_TIMEOUT", "The bank service timed out.", 504))
    draft = await create_draft(db, user["_id"], "priya@upi", Decimal("12"))
    with pytest.raises(AppError) as exc:
        await execute_transfer(db, bank, SimpleNamespace(per_txn_limit=50000), user, TransferIn(recipient="priya@upi", amount=12, note="", pin="1234", draftId=draft["_id"]), "timeout")
    assert exc.value.code == "UPSTREAM_TIMEOUT"
    assert bank.posts == 1
    assert (await db.payment_drafts.find_one({"_id": draft["_id"]}))["state"] == "FAILED"
