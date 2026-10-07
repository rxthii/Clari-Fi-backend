from datetime import timedelta
from decimal import Decimal, InvalidOperation
import re
import uuid
import logging

from app.clients.obp import amount_and_currency
from app.core.errors import AppError
from app.core.security import hash_secret, stable_reference, verify_secret
from app.services.alerts import create_alert
from app.services.banking import account_balance
from app.services.common import as_utc, money_num, now_utc

logger = logging.getLogger(__name__)

PHONE_RE = re.compile(r"^\d{10}$")
VPA_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,80}@[A-Za-z0-9][A-Za-z0-9.-]{1,60}$")


def normalize_query(query: str) -> tuple[str | None, str | None]:
    value = query.strip()
    if PHONE_RE.fullmatch(value): return value, f"{value}@upi"
    if VPA_RE.fullmatch(value): return None, value.lower()
    return None, None


async def lookup_recipient(db, query: str):
    phone, vpa = normalize_query(query)
    if not vpa: return {"valid": False, "name": "", "upiId": "", "verified": False}
    recipient = await db.recipients.find_one({"$or": ([{"phone": phone}, {"vpa": vpa}] if phone else [{"vpa": vpa}])})
    if not recipient: return {"valid": False, "name": "", "upiId": vpa, "verified": False}
    return {"valid": True, "name": recipient.get("name", ""), "upiId": recipient.get("vpa") or vpa, "verified": bool(recipient.get("verified", False))}


async def resolve_recipient(db, query: str):
    phone, vpa = normalize_query(query)
    if not vpa: raise AppError("RECIPIENT_NOT_FOUND", "Recipient could not be verified.", 400)
    rec = await db.recipients.find_one({"$or": ([{"phone": phone}, {"vpa": vpa}] if phone else [{"vpa": vpa}])})
    if not rec or not rec.get("bank_id") or not rec.get("account_id"):
        raise AppError("RECIPIENT_NOT_FOUND", "Recipient could not be verified.", 400)
    return rec


async def create_draft(db, user_id: str, recipient: str, amount: Decimal, note="", source="manual", currency=""):
    if amount <= 0: raise AppError("INVALID_AMOUNT", "Amount must be greater than zero.", 400)
    rec = await resolve_recipient(db, recipient)
    draft_id = str(uuid.uuid4())
    now = now_utc()
    doc = {"_id": draft_id, "user_id": user_id, "recipient": recipient, "resolved_recipient": {"bank_id": rec["bank_id"], "account_id": rec["account_id"], "name": rec.get("name", ""), "vpa": rec.get("vpa", "")}, "amount": format(amount, ".2f"), "currency": currency, "note": note[:140], "state": "PENDING", "source": source, "expires_at": now + timedelta(minutes=10), "created_at": now}
    await db.payment_drafts.insert_one(doc)
    if hasattr(db, "audit_log"):
        await db.audit_log.insert_one({"user_id": user_id, "event": "payment_draft_created", "details": {"draft_id": draft_id, "amount": format(amount, ".2f"), "source": source}, "request_id": None, "timestamp": now})
    return doc


async def cancel_draft(db, user_id: str, draft_id: str):
    result = await db.payment_drafts.update_one({"_id": draft_id, "user_id": user_id, "state": "PENDING"}, {"$set": {"state": "CANCELLED"}})
    if not result.modified_count: raise AppError("DRAFT_NOT_FOUND", "Pending payment draft was not found.", 404)
    return {"success": True}


async def verify_pin(db, user: dict, supplied: str):
    now = now_utc()
    locked_until = user.get("pin_locked_until")
    if locked_until and as_utc(locked_until) > now: raise AppError("PIN_LOCKED", "PIN verification is locked. Try again in 15 minutes.", 423)
    expected = user.get("pin_hash") or user.get("password_hash", "")
    if not verify_secret(supplied, expected):
        attempts = int(user.get("pin_failed_attempts", 0)) + 1
        update = {"pin_failed_attempts": attempts}
        if attempts >= 5:
            update["pin_locked_until"] = now + timedelta(minutes=15)
            update["pin_failed_attempts"] = 0
        await db.users.update_one({"_id": user["_id"]}, {"$set": update})
        if hasattr(db, "audit_log"):
            await db.audit_log.insert_one({"user_id": str(user["_id"]), "event": "pin_verification_failed", "details": {"attempt": attempts, "locked": attempts >= 5}, "request_id": None, "timestamp": now})
        if attempts >= 5: raise AppError("PIN_LOCKED", "PIN verification is locked. Try again in 15 minutes.", 423)
        raise AppError("INVALID_PIN", "PIN is incorrect.", 401)
    await db.users.update_one({"_id": user["_id"]}, {"$set": {"pin_failed_attempts": 0, "pin_locked_until": None}})


def transfer_idempotent_response(payment: dict):
    timestamp = payment.get("timestamp")
    return {"status": "completed", "transactionId": payment.get("obp_transaction_id"), "amount": money_num(payment.get("amount", 0)), "newBalance": money_num(payment.get("new_balance", 0)), "timestamp": as_utc(timestamp).isoformat() if hasattr(timestamp, "isoformat") else timestamp, "utr": payment.get("utr")}


async def execute_transfer(db, obp, settings, user: dict, data, idempotency_key: str | None, request_id: str | None = None):
    if not user.get("obp_link"):
        raise AppError("BANK_NOT_LINKED", "Connect a bank account before making payments.", 409)
    user_id = str(user["_id"])
    if idempotency_key:
        previous = await db.payments.find_one({"user_id": user_id, "idempotency_key": idempotency_key})
        if previous and previous.get("status") == "completed": return transfer_idempotent_response(previous)
        if previous: raise AppError("PAYMENT_IN_PROGRESS", "A payment with this idempotency key is already being processed.", 409)
    draft = None
    if data.draftId:
        draft = await db.payment_drafts.find_one({"_id": data.draftId, "user_id": user_id})
        if not draft: raise AppError("DRAFT_NOT_FOUND", "Pending payment draft was not found.", 404)
        if as_utc(draft.get("expires_at")) <= now_utc():
            await db.payment_drafts.update_one({"_id": draft["_id"], "state": "PENDING"}, {"$set": {"state": "EXPIRED"}})
            raise AppError("DRAFT_EXPIRED", "Payment draft has expired.", 410)
        if draft.get("state") != "PENDING": raise AppError("DRAFT_NOT_FOUND", "Payment draft is no longer pending.", 409)
        await verify_pin(db, user, data.pin)
    else:
        # Manual/QR transfers still use a draft internally; authenticate first, then validate its inputs.
        await verify_pin(db, user, data.pin)
        if data.amount <= 0: raise AppError("INVALID_AMOUNT", "Amount must be greater than zero.", 400)
        if data.amount.as_tuple().exponent < -2: raise AppError("INVALID_AMOUNT", "Amount can have at most two decimal places.", 400)
        if data.amount > Decimal(str(settings.per_txn_limit)): raise AppError("LIMIT_EXCEEDED", "Transaction amount exceeds the per-transaction limit.", 400)
        draft = await create_draft(db, user_id, data.recipient, data.amount, data.note, "manual")
    amount = Decimal(str(draft["amount"]))
    if amount <= 0: raise AppError("INVALID_AMOUNT", "Amount must be greater than zero.", 400)
    if amount.as_tuple().exponent < -2: raise AppError("INVALID_AMOUNT", "Amount can have at most two decimal places.", 400)
    if amount > Decimal(str(settings.per_txn_limit)): raise AppError("LIMIT_EXCEEDED", "Transaction amount exceeds the per-transaction limit.", 400)
    recipient = draft["resolved_recipient"]
    link = user["obp_link"]
    if recipient.get("bank_id") == link.get("bank_id") and recipient.get("account_id") == link.get("account_id"):
        raise AppError("INVALID_RECIPIENT", "You cannot transfer money to your own account.", 400)
    account_json = await obp.account(user)
    balance, real_currency = account_balance(account_json)
    if amount > balance: raise AppError("INSUFFICIENT_FUNDS", "Transaction amount exceeds available balance.", 400)
    # Reserve the user-scoped key before contacting the bank. Duplicate callers share the stored outcome.
    key = idempotency_key or f"draft:{draft['_id']}"
    previous = await db.payments.find_one({"user_id": user_id, "idempotency_key": key})
    if previous:
        if previous.get("status") == "completed": return transfer_idempotent_response(previous)
        raise AppError("PAYMENT_IN_PROGRESS", "A payment with this idempotency key is already being processed.", 409)
    timestamp = now_utc()
    reservation = {"user_id": user_id, "draft_id": draft["_id"], "idempotency_key": key, "recipient": recipient.get("name", data.recipient), "recipient_details": recipient.get("vpa", data.recipient), "amount": format(amount, ".2f"), "note": draft.get("note", ""), "status": "processing", "timestamp": timestamp, "request_id": request_id}
    try:
        await db.payments.insert_one(reservation)
    except Exception:
        previous = await db.payments.find_one({"user_id": user_id, "idempotency_key": key})
        if previous and previous.get("status") == "completed": return transfer_idempotent_response(previous)
        raise AppError("PAYMENT_IN_PROGRESS", "A payment with this idempotency key is already being processed.", 409)
    consumed = await db.payment_drafts.find_one_and_update({"_id": draft["_id"], "user_id": user_id, "state": "PENDING", "expires_at": {"$gt": now_utc()}}, {"$set": {"state": "EXECUTED"}}, return_document=True)
    if not consumed:
        await db.payments.delete_one({"user_id": user_id, "idempotency_key": key, "status": "processing"})
        raise AppError("DRAFT_NOT_FOUND", "Payment draft is no longer pending.", 409)
    await db.audit_log.insert_one({"user_id": user_id, "event": "payment_execution_started", "details": {"draft_id": draft["_id"], "amount": format(amount, ".2f")}, "request_id": request_id, "timestamp": timestamp})
    bank_result = None
    try:
        bank_result = await obp.create_transfer(user, recipient, amount, real_currency, draft.get("note", ""))
        tr = bank_result
        if str(bank_result.get("status", "")).upper() == "INITIATED" and (bank_result.get("challenge") or {}).get("id"):
            tr = await obp.answer_challenge(user, bank_result)
        if str(tr.get("status", "COMPLETED")).upper() not in ("COMPLETED", "SUCCESS", "" ):
            raise AppError("UPSTREAM_BANK_ERROR", "The bank did not complete the transfer.", 502)
    except Exception as exc:
        await db.payment_drafts.update_one({"_id": draft["_id"], "user_id": user_id}, {"$set": {"state": "FAILED"}})
        await db.payments.update_one({"user_id": user_id, "idempotency_key": key}, {"$set": {"status": "failed", "timestamp": now_utc()}})
        await db.audit_log.insert_one({"user_id": user_id, "event": "payment_failed", "details": {"draft_id": draft["_id"], "reason": type(exc).__name__}, "request_id": request_id, "timestamp": now_utc()})
        await create_alert(db, user_id, title="Payment failed", description="Your payment could not be completed.", severity="high", dedupe_key=f"payment:{key}:failed", action_screen="payments", action_text="Try again")
        if isinstance(exc, AppError): raise
        raise AppError("UPSTREAM_BANK_ERROR", "The bank service could not complete the transfer.", 502) from exc
    txids = tr.get("transaction_ids") or tr.get("transaction_id") or tr.get("id")
    tx_id = str(txids).split(",")[0] if txids else str(uuid.uuid4())
    try:
        account_after = await obp.account(user)
        new_balance, _ = account_balance(account_after)
    except AppError:
        new_balance = balance - amount
    utr = f"UTR{uuid.uuid4().int % 100000000:08d}"
    # BSON timestamps have millisecond precision; round here so an idempotent replay
    # returns the exact timestamp sent in the original response.
    completed_at = now_utc()
    completed_at = completed_at.replace(microsecond=(completed_at.microsecond // 1000) * 1000)
    await db.payments.update_one({"user_id": user_id, "idempotency_key": key}, {"$set": {"obp_transaction_id": tx_id, "obp_transaction_request_id": bank_result.get("id"), "utr": utr, "reference_no": stable_reference(tx_id), "recipient": recipient.get("name", data.recipient), "recipient_details": recipient.get("vpa", data.recipient), "amount": format(amount, ".2f"), "note": draft.get("note", ""), "status": "completed", "timestamp": completed_at, "new_balance": format(new_balance, ".2f"), "currency": real_currency}})
    try:
        await db.audit_log.insert_one({"user_id": user_id, "event": "payment_executed", "details": {"draft_id": draft["_id"], "transaction_id": tx_id, "amount": format(amount, ".2f")}, "request_id": request_id, "timestamp": completed_at})
        await create_alert(db, user_id, title="Payment completed", description=f"Your payment to {recipient.get('name', 'the recipient')} was completed.", severity="low", dedupe_key=f"payment:{key}:completed", action_screen="transactions", action_text="View receipt")
    except Exception as exc:
        logger.warning("Payment post-processing failed error_type=%s", type(exc).__name__)
    return {"status": "completed", "transactionId": tx_id, "amount": money_num(amount), "newBalance": money_num(new_balance), "timestamp": completed_at.isoformat(), "utr": utr}


async def frequent_contacts(db, user_id: str):
    rows = await db.payments.find({"user_id": user_id, "status": "completed"}).sort("timestamp", -1).limit(100).to_list(100)
    seen, contacts = set(), []
    for row in rows:
        name = row.get("recipient", "")
        if not name or name in seen: continue
        seen.add(name)
        contacts.append({"name": name, "recipientDetails": row.get("recipient_details", name), "amount": money_num(row.get("amount", 0)), "note": row.get("note", "")})
        if len(contacts) == 10: break
    return {"contacts": contacts}


async def decode_qr(raw: str):
    from urllib.parse import parse_qs, urlparse
    if len(raw) > 4096: raise AppError("INVALID_QR", "QR payload is too large.", 422)
    parsed = urlparse(raw)
    if parsed.scheme.lower() != "upi" or parsed.netloc.lower() != "pay": raise AppError("INVALID_QR", "QR payload must be a UPI payment link.", 422)
    fields = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=False)
    vpa = (fields.get("pa") or [""])[0].strip()
    if not VPA_RE.fullmatch(vpa): raise AppError("INVALID_QR", "QR payload has an invalid payee address.", 422)
    amount_text = (fields.get("am") or [""])[0].strip()
    amount = None
    if amount_text:
        try:
            amount = Decimal(amount_text)
            if not amount.is_finite() or amount <= 0 or amount.as_tuple().exponent < -2: raise ValueError
        except (InvalidOperation, ValueError): raise AppError("INVALID_QR", "QR payload has an invalid amount.", 422)
    name = ((fields.get("pn") or [""])[0] or "").strip()[:100]
    note = ((fields.get("tn") or [""])[0] or "").strip()[:140]
    return {"merchantName": name, "vpa": vpa, "amount": money_num(amount) if amount is not None else None, "note": note}
