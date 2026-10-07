from datetime import datetime, timezone
from decimal import Decimal
from bson import ObjectId


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime | None) -> datetime | None:
    if value is None: return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def str_id(value) -> str:
    return str(value) if isinstance(value, ObjectId) else value


def clean_user(user: dict) -> dict:
    return {"id": str_id(user.get("_id")), "name": user.get("name", ""), "email": user.get("email", ""), "age": user.get("age"), "position": user.get("position"), "avatarUrl": user.get("avatar_url")}


def money_num(value) -> float:
    try: return float(Decimal(str(value)))
    except Exception: return 0.0


def parse_obp_date(value) -> datetime:
    if not value: return now_utc()
    try:
        text = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return now_utc()


def month_bounds(month: str | None = None):
    now = now_utc()
    if month:
        year, mon = map(int, month.split("-"))
        start = datetime(year, mon, 1, tzinfo=timezone.utc)
    else:
        start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    if start.month == 12: end = datetime(start.year + 1, 1, 1, tzinfo=timezone.utc)
    else: end = datetime(start.year, start.month + 1, 1, tzinfo=timezone.utc)
    return start, end


def days_remaining() -> int:
    now = now_utc()
    next_month = datetime(now.year + (now.month == 12), now.month % 12 + 1, 1, tzinfo=timezone.utc)
    return (next_month.date() - now.date()).days
