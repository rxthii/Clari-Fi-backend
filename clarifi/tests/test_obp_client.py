from types import SimpleNamespace

import httpx
import pytest
import respx
from cryptography.fernet import Fernet

from app.clients.obp import OBPClient
from app.core.errors import AppError
from app.core.security import encrypt_secret


@pytest.mark.asyncio
async def test_get_reauthenticates_once_after_401():
    base = "https://bank.test"
    settings = SimpleNamespace(base_url=base, consumer_key="consumer")
    async with httpx.AsyncClient() as http:
        client = OBPClient(http, settings)
        with respx.mock(base_url=base) as mock:
            login = mock.post("/my/logins/direct").mock(side_effect=[httpx.Response(200, json={"token": "first"}), httpx.Response(200, json={"token": "second"})])
            endpoint = mock.get("/obp/v5.1.0/banks/x/accounts/y/owner/transactions").mock(side_effect=[httpx.Response(401), httpx.Response(200, json={"transactions": []})])
            result = await client.request("GET", "/obp/v5.1.0/banks/x/accounts/y/owner/transactions", username="demo", password="secret")
            assert result == {"transactions": []}
            assert login.call_count == 2 and endpoint.call_count == 2


@pytest.mark.asyncio
async def test_challenge_uses_sandbox_answer_contract():
    base = "https://bank.test"
    key = Fernet.generate_key().decode()
    settings = SimpleNamespace(base_url=base, consumer_key="consumer", obp_api_version="v5.1.0", encryption_key=key)
    user = {"obp_link": {"bank_id": "gh.29.fi", "account_id": "sender", "view_id": "owner", "obp_username": "demo", "obp_password_enc": encrypt_secret("secret", key)}}
    async with httpx.AsyncClient() as http:
        client = OBPClient(http, settings)
        with respx.mock(base_url=base) as mock:
            mock.post("/my/logins/direct").mock(return_value=httpx.Response(200, json={"token": "token"}))
            answer = mock.post("/obp/v5.1.0/banks/gh.29.fi/accounts/sender/owner/transaction-request-types/SANDBOX_TAN/transaction-requests/request-1/challenge").mock(return_value=httpx.Response(200, json={"status": "COMPLETED"}))
            result = await client.answer_challenge(user, {"id": "request-1", "challenge": {"id": "challenge-1"}})
            assert result["status"] == "COMPLETED"
            assert answer.calls[0].request.content == b'{"id":"challenge-1","answer":"123"}'


@pytest.mark.asyncio
async def test_payment_post_timeout_is_not_retried():
    base = "https://bank.test"
    key = Fernet.generate_key().decode()
    settings = SimpleNamespace(base_url=base, consumer_key="consumer", obp_api_version="v5.1.0", encryption_key=key)
    user = {"obp_link": {"bank_id": "bank", "account_id": "sender", "view_id": "owner", "obp_username": "demo", "obp_password_enc": encrypt_secret("secret", key)}}
    async with httpx.AsyncClient(timeout=0.01) as http:
        client = OBPClient(http, settings)
        with respx.mock(base_url=base) as mock:
            mock.post("/my/logins/direct").mock(return_value=httpx.Response(200, json={"token": "token"}))
            payment = mock.post("/obp/v5.1.0/banks/bank/accounts/sender/owner/transaction-request-types/SANDBOX_TAN/transaction-requests").mock(side_effect=httpx.ReadTimeout("timeout"))
            with pytest.raises(AppError) as exc:
                await client.create_transfer(user, {"bank_id": "bank", "account_id": "receiver"}, __import__("decimal").Decimal("10"), "INR", "test")
            assert exc.value.code == "UPSTREAM_TIMEOUT"
            assert payment.call_count == 1
