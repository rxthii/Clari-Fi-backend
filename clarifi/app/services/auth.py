from datetime import timedelta
import uuid
from app.core.errors import AppError
from app.core.security import create_access_token, hash_secret, new_reset_token, verify_secret
from app.repositories.users import blacklist_token
from app.services.common import clean_user, now_utc

def auth_user(user: dict) -> dict:
    return {"id": str(user.get("_id")), "name": user.get("name", ""), "email": user.get("email", "")}


async def register(db, data, settings):
    email = data.email.lower()
    if await db.users.find_one({"email": email}): raise AppError("EMAIL_EXISTS", "An account with this email already exists.", 409)
    now = now_utc()
    user = {"_id": str(uuid.uuid4()), "name": data.name.strip(), "email": email, "password_hash": hash_secret(data.password), "pin_hash": None, "age": None, "position": None, "avatar_url": None, "profile_completed": False, "obp_link": None, "pin_failed_attempts": 0, "pin_locked_until": None, "created_at": now, "updated_at": now}
    await db.users.insert_one(user)
    token, _, _ = create_access_token(user["_id"], settings)
    return {"token": token, "user": auth_user(user)}


async def login(db, data, settings, request_id=None):
    ident = data.identifier.strip().lower()
    user = await db.users.find_one({"$or": [{"email": ident}, {"username": ident}]})
    if not user or not verify_secret(data.password, user.get("password_hash", "")):
        raise AppError("INVALID_CREDENTIALS", "Email or password is incorrect.", 401)
    token, _, _ = create_access_token(str(user["_id"]), settings)
    await db.audit_log.insert_one({"user_id": str(user["_id"]), "event": "login", "details": {}, "request_id": request_id, "timestamp": now_utc()})
    return {"token": token, "user": auth_user(user)}


async def complete_profile(db, user, data):
    await db.users.update_one({"_id": user["_id"]}, {"$set": {"name": data.name.strip(), "age": data.age, "position": data.position.strip(), "profile_completed": True, "updated_at": now_utc()}})
    updated = await db.users.find_one({"_id": user["_id"]})
    return {"user": clean_user(updated), "profileCompleted": True}


async def change_password(db, user, data):
    if not verify_secret(data.oldPassword, user.get("password_hash", "")):
        raise AppError("INVALID_CREDENTIALS", "Current password is incorrect.", 400)
    await db.users.update_one({"_id": user["_id"]}, {"$set": {"password_hash": hash_secret(data.newPassword), "updated_at": now_utc()}})
    return {"success": True, "message": "Password updated"}


async def forgot_password(db, email, settings):
    user = await db.users.find_one({"email": email.lower()})
    if user:
        raw = new_reset_token()
        # Only the token digest is stored. In dev, log the raw token for local hackathon use.
        import hashlib, logging
        await db.password_resets.insert_one({"user_id": str(user["_id"]), "token_hash": hashlib.sha256(raw.encode()).hexdigest(), "expires_at": now_utc() + timedelta(minutes=20), "created_at": now_utc()})
        if settings.environment == "development": logging.getLogger(__name__).info("development password reset token issued user_id=%s token=%s", user["_id"], raw)
    return {"message": "Reset instructions sent"}


async def logout(db, user, token_payload, request_id=None):
    from datetime import datetime, timezone
    expires = datetime.fromtimestamp(token_payload["exp"], tz=timezone.utc)
    await blacklist_token(db, token_payload["jti"], expires)
    await db.audit_log.insert_one({"user_id": str(user["_id"]), "event": "logout", "details": {}, "request_id": request_id, "timestamp": now_utc()})
    return {"success": True}
