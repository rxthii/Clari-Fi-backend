import asyncio
from datetime import datetime, timezone
from decimal import Decimal
import logging
from urllib.parse import quote

import httpx

from app.core.errors import AppError

logger = logging.getLogger(__name__)


class OBPClient:
    def __init__(self, http: httpx.AsyncClient, settings):
        self.http, self.settings = http, settings
        self._tokens: dict[str, str] = {}
        self._token_locks: dict[str, asyncio.Lock] = {}

    @staticmethod
    def _require_link(user: dict) -> dict:
        link = user.get("obp_link")
        if not link:
            raise AppError("BANK_NOT_LINKED", "Connect a bank account before using this feature.", 409)
        return link

    async def login(self, username: str, password: str, force: bool = False) -> str:
        if not force and username in self._tokens:
            return self._tokens[username]
        lock = self._token_locks.setdefault(username, asyncio.Lock())
        async with lock:
            if not force and username in self._tokens:
                return self._tokens[username]
            header = f"username={username}, password={password}, consumer_key={self.settings.consumer_key}"
            try:
                response = await self.http.post(f"{self.settings.base_url}/my/logins/direct", headers={"DirectLogin": header})
                response.raise_for_status()
                token = response.json().get("token")
                if not token:
                    raise AppError("UPSTREAM_BANK_ERROR", "Bank authentication returned an invalid response.", 502)
                self._tokens[username] = token
                return token
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                raise AppError("UPSTREAM_TIMEOUT", "The bank service timed out.", 504) from exc
            except httpx.HTTPStatusError as exc:
                logger.warning("OBP login failed status=%s", exc.response.status_code)
                raise AppError("UPSTREAM_BANK_ERROR", "The bank service could not authenticate the linked account.", 502) from exc

    async def request(self, method: str, path: str, *, username: str, password: str, params=None, json=None, retry_get=True):
        for attempt in range(2 if method.upper() == "GET" and retry_get else 1):
            token = await self.login(username, password, force=attempt > 0)
            try:
                response = await self.http.request(method, f"{self.settings.base_url}{path}", headers={"Authorization": f"DirectLogin token={token}"}, params=params, json=json)
                if response.status_code == 401 and attempt == 0:
                    self._tokens.pop(username, None)
                    continue
                response.raise_for_status()
                return response.json() if response.content else {}
            except httpx.TimeoutException as exc:
                raise AppError("UPSTREAM_TIMEOUT", "The bank service timed out.", 504) from exc
            except httpx.HTTPStatusError as exc:
                logger.warning("OBP call failed method=%s status=%s", method, exc.response.status_code)
                raise AppError("UPSTREAM_BANK_ERROR", "The bank service could not complete the request.", 502) from exc
            except httpx.ConnectError as exc:
                raise AppError("UPSTREAM_TIMEOUT", "The bank service is unavailable.", 504) from exc
        raise AppError("UPSTREAM_BANK_ERROR", "The linked bank session expired.", 502)

    def account_path(self, link: dict) -> str:
        v = self.settings.obp_api_version
        return f"/obp/{v}/my/banks/{quote(link['bank_id'], safe='')}/accounts/{quote(link['account_id'], safe='')}/account"

    def tx_path(self, link: dict, transaction_id: str | None = None) -> str:
        v = self.settings.obp_api_version
        base = f"/obp/{v}/banks/{quote(link['bank_id'], safe='')}/accounts/{quote(link['account_id'], safe='')}/{quote(link['view_id'], safe='')}/transactions"
        return f"{base}/{quote(transaction_id, safe='')}/transaction" if transaction_id else base

    async def account(self, user: dict) -> dict:
        link = user.get("obp_link")
        if not link:
            return {"account": {"balance": {"amount": "0", "currency": self.settings.display_currency or "INR"}}}
        return await self.request("GET", self.account_path(link), username=link["obp_username"], password=self._password(user))

    async def transactions(self, user: dict, *, from_date=None, to_date=None, limit=100, offset=0, sort_direction="DESC") -> list[dict]:
        link = user.get("obp_link")
        if not link:
            return []
        params = {"limit": min(int(limit), 1000), "offset": max(int(offset), 0), "sort_direction": sort_direction}
        if from_date: params["from_date"] = from_date
        if to_date: params["to_date"] = to_date
        payload = await self.request("GET", self.tx_path(link), username=link["obp_username"], password=self._password(user), params=params)
        return payload.get("transactions", []) if isinstance(payload, dict) else []

    async def transaction(self, user: dict, transaction_id: str) -> dict:
        link = self._require_link(user)
        payload = await self.request("GET", self.tx_path(link, transaction_id), username=link["obp_username"], password=self._password(user))
        return payload.get("transaction", payload) if isinstance(payload, dict) else {}

    async def create_transfer(self, user: dict, recipient: dict, amount: Decimal, currency: str, note: str) -> dict:
        link = self._require_link(user)
        path = f"/obp/{self.settings.obp_api_version}/banks/{quote(link['bank_id'], safe='')}/accounts/{quote(link['account_id'], safe='')}/{quote(link['view_id'], safe='')}/transaction-request-types/SANDBOX_TAN/transaction-requests"
        body = {"to": {"bank_id": recipient["bank_id"], "account_id": recipient["account_id"]}, "value": {"currency": currency, "amount": format(amount, ".2f")}, "description": note[:140]}
        # Payment POST is never retried. A timeout is an ambiguous upstream result and must be reconciled manually.
        return await self.request("POST", path, username=link["obp_username"], password=self._password(user), json=body, retry_get=False)

    async def answer_challenge(self, user: dict, transaction_request: dict) -> dict:
        link = self._require_link(user)
        tr_id = transaction_request.get("id")
        challenge_id = (transaction_request.get("challenge") or {}).get("id")
        if not tr_id or not challenge_id:
            raise AppError("UPSTREAM_BANK_ERROR", "The bank returned an invalid transaction challenge.", 502)
        path = f"/obp/{self.settings.obp_api_version}/banks/{quote(link['bank_id'], safe='')}/accounts/{quote(link['account_id'], safe='')}/{quote(link['view_id'], safe='')}/transaction-request-types/SANDBOX_TAN/transaction-requests/{quote(str(tr_id), safe='')}/challenge"
        return await self.request("POST", path, username=link["obp_username"], password=self._password(user), json={"id": challenge_id, "answer": "123"}, retry_get=False)

    def _password(self, user: dict) -> str:
        from app.core.security import decrypt_secret
        try:
            link = self._require_link(user)
            return decrypt_secret(link["obp_password_enc"], self.settings.encryption_key)
        except Exception as exc:
            raise AppError("BANK_CREDENTIALS_UNAVAILABLE", "The linked bank credentials are unavailable.", 503) from exc


def amount_and_currency(tx: dict) -> tuple[Decimal, str]:
    details = tx.get("details") or {}
    value = details.get("value") or tx.get("value") or {}
    try: amount = Decimal(str(value.get("amount", "0")))
    except Exception: amount = Decimal("0")
    return amount, str(value.get("currency") or "INR")
