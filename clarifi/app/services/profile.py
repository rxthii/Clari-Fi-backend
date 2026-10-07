import uuid
from pathlib import Path
from app.core.errors import AppError
from app.core.security import hash_secret, verify_secret
from app.repositories.users import find_email, update_user
from app.services.common import clean_user, now_utc


async def update_profile(db, user, fields):
    changes = {k: v for k, v in fields.items() if v is not None}
    if "email" in changes:
        changes["email"] = changes["email"].lower()
        if await find_email(db, changes["email"], str(user["_id"])):
            raise AppError("EMAIL_EXISTS", "An account with this email already exists.", 409)
    changes["updated_at"] = now_utc()
    await update_user(db, str(user["_id"]), changes)
    updated = await db.users.find_one({"_id": user["_id"]})
    return {"user": clean_user(updated), "updatedAt": updated["updated_at"].isoformat()}


async def save_avatar(db, user, upload_dir: str, contents: bytes, extension: str):
    name = f"{uuid.uuid4().hex}{extension}"
    Path(upload_dir, name).write_bytes(contents)
    url = f"/uploads/{name}"
    await update_user(db, str(user["_id"]), {"avatar_url": url, "updated_at": now_utc()})
    return {"avatarUrl": url}


async def set_pin(db, user, pin: str, current_pin: str | None, request_id=None):
    if user.get("pin_hash") and (not current_pin or not verify_secret(current_pin, user["pin_hash"])):
        raise AppError("INVALID_PIN", "Current PIN is incorrect.", 401)
    await update_user(db, str(user["_id"]), {"pin_hash": hash_secret(pin), "pin_failed_attempts": 0, "pin_locked_until": None, "updated_at": now_utc()})
    await db.audit_log.insert_one({"user_id": str(user["_id"]), "event": "pin_set", "details": {}, "request_id": request_id, "timestamp": now_utc()})
    return {"success": True}
