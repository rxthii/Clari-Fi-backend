from datetime import datetime, timezone

from app.services.common import as_utc, days_remaining, month_bounds, now_utc
from app.repositories.alerts import update_alert, update_all_alerts
from decimal import Decimal
from app.services.banking import account_balance, spending_for_month, transaction_details
from app.services.common import money_num


async def create_alert(db, user_id: str, *, title: str, description: str, severity: str, dedupe_key: str, action_screen="", action_text=""):
    date = now_utc()
    await db.alerts.update_one({"user_id": user_id, "dedupe_key": dedupe_key}, {"$setOnInsert": {"id": f"alt-{int(date.timestamp() * 1000)}", "user_id": user_id, "title": title, "description": description, "date": date, "severity": severity, "read": False, "actionScreen": action_screen, "actionText": action_text, "dedupe_key": dedupe_key}}, upsert=True)


async def run_budget_alerts(db, user_id: str, spent_by: dict | None = None):
    start, end = month_bounds()
    categories = await db.baseline_categories.find({"user_id": user_id}).to_list(200)
    for category in categories:
        spent = float((spent_by or {}).get(category.get("title"), 0))
        threshold = float(category.get("allocated", 0))
        if not threshold: continue
        ratio = spent / threshold
        label = category.get("title", "Budget")
        if ratio >= 1:
            await create_alert(db, user_id, title=f"{label} budget reached", description=f"You've reached your {label} spending limit this month.", severity="high", dedupe_key=f"budget:{category['id']}:{start:%Y-%m}:100")
        elif ratio >= .8:
            await create_alert(db, user_id, title=f"{label} budget is at 80%", description=f"You're close to your {label} spending limit this month.", severity="medium", dedupe_key=f"budget:{category['id']}:{start:%Y-%m}:80")


async def alerts_for_user(db, user_id: str, unread_only=False):
    query = {"user_id": user_id}
    if unread_only: query["read"] = False
    alerts = await db.alerts.find(query).sort("date", -1).limit(100).to_list(100)
    unread = await db.alerts.count_documents({"user_id": user_id, "read": False})
    return {"unreadCount": unread, "alerts": [{"id": a["id"], "title": a["title"], "description": a["description"], "date": as_utc(a["date"]).isoformat(), "severity": a.get("severity", "low"), "read": a.get("read", False), "actionScreen": a.get("actionScreen", ""), "actionText": a.get("actionText", "")} for a in alerts]}


async def mark_alert_read(db, user_id: str, alert_id: str):
    from app.core.errors import AppError
    result = await update_alert(db, user_id, alert_id)
    if not result.matched_count: raise AppError("ALERT_NOT_FOUND", "Alert was not found.", 404)
    return {"id": alert_id, "read": True}


async def mark_all_alerts_read(db, user_id: str):
    await update_all_alerts(db, user_id)
    return {"success": True}


async def refresh_alert_engine(db, obp, user, request_id=None):
    import logging
    uid = str(user["_id"])
    spent = await spending_for_month(db, obp, user)
    await run_budget_alerts(db, uid, spent)
    try:
        recent = await obp.transactions(user, limit=50)
        categories = await db.baseline_categories.find({"user_id": uid}).to_list(200)
        allocated = sum(money_num(c["allocated"]) for c in categories)
        large_limit = max(Decimal("5000"), Decimal(str(allocated)) * Decimal("0.25"))
        for tx in recent:
            txid, _, _, amount, _, _ = transaction_details(tx)
            if txid and abs(amount) >= large_limit:
                await create_alert(db, uid, title="Unusually large transaction", description=f"A transaction of {money_num(abs(amount)):.2f} may need your attention.", severity="medium", dedupe_key=f"large-transaction:{txid}", action_screen="transactions", action_text="Review transaction")
        account_json = await obp.account(user)
        balance, _ = account_balance(account_json)
        if allocated and balance < Decimal(str(allocated * .1)):
            await create_alert(db, uid, title="Low account balance", description="Your account balance is below 10% of your monthly planned budget.", severity="medium", dedupe_key=f"low-balance:{now_utc():%Y-%m}", action_screen="home", action_text="Review balance")
    except Exception as exc:
        logging.getLogger(__name__).info("Alert refresh skipped error_type=%s request_id=%s", type(exc).__name__, request_id)
