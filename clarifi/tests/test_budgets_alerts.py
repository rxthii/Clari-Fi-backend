from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from mongomock_motor import AsyncMongoMockClient

from app.core.errors import AppError
from app.routers.baseline import delete_category
from app.services.alerts import alerts_for_user, run_budget_alerts
from app.services.common import days_remaining


@pytest.mark.asyncio
async def test_budget_alerts_trigger_at_eighty_and_one_hundred_percent_and_dedupe():
    client = AsyncMongoMockClient()
    db = client["alerts-tests"]
    await db.baseline_categories.insert_many([
        {"user_id": "u1", "id": "base-1", "title": "Dining", "allocated": "1000"},
        {"user_id": "u1", "id": "base-2", "title": "Groceries", "allocated": "1000"},
    ])
    await run_budget_alerts(db, "u1", {"Dining": 800, "Groceries": 1000})
    await run_budget_alerts(db, "u1", {"Dining": 850, "Groceries": 1100})
    result = await alerts_for_user(db, "u1")
    assert result["unreadCount"] == 2
    assert {a["severity"] for a in result["alerts"]} == {"medium", "high"}
    client.close()


def test_days_remaining_handles_month_end(monkeypatch):
    import app.services.common as common
    monkeypatch.setattr(common, "now_utc", lambda: datetime(2024, 2, 29, 12, tzinfo=timezone.utc))
    assert days_remaining() == 1
    monkeypatch.setattr(common, "now_utc", lambda: datetime(2024, 2, 28, 12, tzinfo=timezone.utc))
    assert days_remaining() == 2


@pytest.mark.asyncio
async def test_user_cannot_delete_another_users_category():
    client = AsyncMongoMockClient()
    db = client["ownership-tests"]
    await db.baseline_categories.insert_one({"user_id": "owner", "id": "base-1", "title": "Private", "allocated": "100"})
    with pytest.raises(AppError) as exc:
        await delete_category("base-1", {"_id": "other-user"}, db)
    assert exc.value.code == "CATEGORY_NOT_FOUND"
    client.close()
