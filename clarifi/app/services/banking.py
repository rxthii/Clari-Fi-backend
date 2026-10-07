from datetime import datetime, timedelta, timezone
from decimal import Decimal
from app.clients.obp import amount_and_currency
from app.core.errors import AppError
from app.core.security import stable_reference
from app.services.categorizer import categorize, ICONS
from app.services.common import month_bounds, parse_obp_date, money_num


def account_balance(account: dict) -> tuple[Decimal, str]:
    details = account.get("account") or account
    bal = details.get("balance") or details.get("account_balance") or {}
    try: value = Decimal(str(bal.get("amount", "0")))
    except Exception: value = Decimal("0")
    return value, str(bal.get("currency") or "INR")


def transaction_details(tx: dict) -> tuple[str, str, str, Decimal, str, datetime]:
    details = tx.get("details") or {}
    amount, currency = amount_and_currency(tx)
    desc = str(details.get("description") or tx.get("description") or "Transaction")
    other = details.get("other_account") or tx.get("other_account") or {}
    holder = other.get("holder") or {}
    recipient = str(holder.get("name") or other.get("number") or "")
    txid = str(tx.get("id") or tx.get("transaction_id") or "")
    date = parse_obp_date(details.get("completed") or details.get("posted") or tx.get("completed") or tx.get("posted"))
    return txid, desc, recipient, amount, currency, date


async def map_transaction(db, user_id: str, tx: dict, cache: bool = True) -> dict:
    txid, desc, recipient, amount, currency, when = transaction_details(tx)
    metadata = await db.transaction_meta.find_one({"user_id": user_id, "obp_transaction_id": txid}) if txid else None
    category = metadata.get("category") if metadata else categorize(desc, recipient)
    if txid and not metadata and cache:
        await db.transaction_meta.update_one({"user_id": user_id, "obp_transaction_id": txid}, {"$setOnInsert": {"user_id": user_id, "obp_transaction_id": txid, "category": category, "icon": ICONS.get(category, "payments")}}, upsert=True)
    return {"id": txid, "title": desc[:160], "category": category, "type": "income" if amount >= 0 else "spending", "amount": money_num(abs(amount)), "date": when.date().isoformat(), "time": when.strftime("%H:%M"), "recipient": recipient, "status": (tx.get("details") or {}).get("type") or "completed", "icon": (metadata or {}).get("icon", ICONS.get(category, "payments")), "currency": currency, "_when": when, "_signed": amount}


async def get_transactions(db, obp, user: dict, type_: str = "all", page: int = 1, limit: int = 20):
    rows, offset = [], 0
    while offset < 10_000:
        batch = await obp.transactions(user, limit=1000, offset=offset)
        rows.extend(batch)
        if len(batch) < 1000: break
        offset += len(batch)
    mapped = [await map_transaction(db, str(user["_id"]), tx) for tx in rows]
    if type_ in ("income", "spending"): mapped = [x for x in mapped if x["type"] == type_]
    total = len(mapped)
    start = (page - 1) * limit
    for x in mapped: x.pop("_when", None); x.pop("_signed", None); x.pop("currency", None)
    return {"transactions": mapped[start:start + limit], "pagination": {"page": page, "totalPages": (total + limit - 1) // limit, "totalCount": total}}


async def transaction_summary(db, obp, user, month: str):
    start, end = month_bounds(month)
    rows = await obp.transactions(user, from_date=start.strftime("%Y-%m-%dT%H:%M:%S.000Z"), to_date=end.strftime("%Y-%m-%dT%H:%M:%S.000Z"), limit=1000, sort_direction="DESC")
    income, spending, currency = Decimal("0"), Decimal("0"), "INR"
    for tx in rows:
        amount, currency = amount_and_currency(tx)
        if amount >= 0: income += amount
        else: spending += abs(amount)
    return {"totalIncome": money_num(income), "totalSpending": money_num(spending), "currency": obp.settings.display_currency or currency}


async def spending_for_month(db, obp, user, month=None):
    start, end = month_bounds(month)
    rows = await obp.transactions(user, from_date=start.strftime("%Y-%m-%dT%H:%M:%S.000Z"), to_date=end.strftime("%Y-%m-%dT%H:%M:%S.000Z"), limit=1000)
    spent = {}
    for tx in rows:
        amount, _ = amount_and_currency(tx)
        if amount >= 0: continue
        txid, desc, recipient, _, _, _ = transaction_details(tx)
        meta = await db.transaction_meta.find_one({"user_id": str(user["_id"]), "obp_transaction_id": txid}) if txid else None
        category = meta["category"] if meta else categorize(desc, recipient)
        spent[category] = spent.get(category, Decimal("0")) + abs(amount)
    return spent


async def account_overview(obp, user):
    raw = await obp.account(user)
    balance, currency = account_balance(raw)
    currency = obp.settings.display_currency or currency
    now = datetime.now(timezone.utc)
    start, end = month_bounds()
    rows = await obp.transactions(user, from_date=start.strftime("%Y-%m-%dT%H:%M:%S.000Z"), to_date=now.strftime("%Y-%m-%dT%H:%M:%S.000Z"), limit=1000)
    income, spend = Decimal("0"), Decimal("0")
    for tx in rows:
        a, _ = amount_and_currency(tx)
        if a >= 0: income += a
        else: spend += abs(a)
    start_balance = balance - income + spend
    growth = ((income - spend) / start_balance * 100) if start_balance else Decimal("0")
    account = raw.get("account") or raw
    number = str(account.get("number") or account.get("id") or (user.get("obp_link") or {}).get("account_id") or "")
    return {"balance": money_num(balance), "currency": currency, "monthlyGrowthRate": round(float(growth), 1), "accountNumberMasked": "•••• " + number[-4:] if number else ""}


async def transaction_receipt(db, obp, user, transaction_id: str):
    raw = await obp.transaction(user, transaction_id)
    txid, desc, recipient, amount, _, when = transaction_details(raw)
    if not txid: raise AppError("TRANSACTION_NOT_FOUND", "Transaction was not found.", 404)
    payment = await db.payments.find_one({"user_id": str(user["_id"]), "obp_transaction_id": txid, "status": "completed"})
    account = raw.get("this_account") or raw.get("account") or {}
    sender = (account.get("holder") or {}).get("name") or "You"
    fallback_utr = f"UTR{int(stable_reference(txid), 16) % 100_000_000:08d}"
    return {"id": txid, "title": desc, "amount": money_num(abs(amount)), "status": (raw.get("details") or {}).get("type") or "completed", "referenceNo": payment.get("reference_no") if payment else stable_reference(txid), "utr": payment.get("utr") if payment else fallback_utr, "timestamp": parse_obp_date(when).isoformat(), "sender": sender, "recipient": recipient}
