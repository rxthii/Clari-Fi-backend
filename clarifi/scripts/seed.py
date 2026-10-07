import asyncio
import os
import uuid
from datetime import timezone

from motor.motor_asyncio import AsyncIOMotorClient

from app.core.config import get_settings
from app.core.security import encrypt_secret, hash_secret
from app.services.auth import DEFAULT_CATEGORIES
from app.services.common import now_utc


async def seed():
    settings = get_settings()
    missing = settings.missing_required()
    if missing:
        raise RuntimeError("Missing required environment variables: " + ", ".join(missing))
    mongo = AsyncIOMotorClient(settings.mongo_uri)
    db = mongo[settings.mongo_db]
    email, password = os.getenv("DEMO_EMAIL", "").lower(), os.getenv("DEMO_PASSWORD", "")
    if not email or not password:
        mongo.close()
        raise RuntimeError("Set DEMO_EMAIL and DEMO_PASSWORD in .env before seeding the demo user.")
    user = await db.users.find_one({"email": email})
    if not user:
        user = {"_id": str(uuid.uuid4()), "name": "Clari-Fi Demo", "email": email, "password_hash": hash_secret(password), "pin_hash": None, "age": None, "position": None, "avatar_url": None, "profile_completed": False, "obp_link": {"bank_id": settings.obp_bank_id, "account_id": settings.obp_account_id, "view_id": settings.obp_view_id, "obp_username": settings.obp_username, "obp_password_enc": encrypt_secret(settings.obp_password, settings.encryption_key)}, "pin_failed_attempts": 0, "pin_locked_until": None, "created_at": now_utc(), "updated_at": now_utc()}
        await db.users.insert_one(user)
    for index, (title, allocated, icon, color, keywords) in enumerate(DEFAULT_CATEGORIES, 1):
        await db.baseline_categories.update_one({"user_id": str(user["_id"]), "id": f"base-{index}"}, {"$setOnInsert": {"user_id": str(user["_id"]), "id": f"base-{index}", "title": title, "allocated": allocated, "icon": icon, "color": color, "keywords": keywords}}, upsert=True)
    recipient = {"phone": "9876543210", "vpa": "priya@upi", "name": "Priya Sharma", "verified": True, "bank_id": settings.obp_bank_id, "account_id": "f9c6159a-68a3-4779-80e0-a4c1c4bae55c"}
    await db.recipients.update_one({"vpa": recipient["vpa"]}, {"$set": recipient}, upsert=True)
    await db.recipients.update_one({"phone": recipient["phone"]}, {"$set": recipient}, upsert=True)
    await db.payment_drafts.create_index("expires_at", expireAfterSeconds=0)
    await db.token_blacklist.create_index("expires_at", expireAfterSeconds=0)
    print("Seeded default budget categories and mock recipient; demo account is ready.")
    mongo.close()


if __name__ == "__main__":
    asyncio.run(seed())
