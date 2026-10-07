from motor.motor_asyncio import AsyncIOMotorClient


async def initialize_database(uri: str, db_name: str):
    client = AsyncIOMotorClient(uri, serverSelectionTimeoutMS=5000)
    await client.admin.command("ping")
    db = client[db_name]
    await db.users.create_index("email", unique=True)
    await db.chat_messages.create_index([("user_id", 1), ("timestamp", 1)])
    await db.payment_drafts.create_index("expires_at", expireAfterSeconds=0)
    await db.payments.create_index([("user_id", 1), ("idempotency_key", 1)], unique=True, sparse=True)
    await db.baseline_categories.create_index([("user_id", 1), ("id", 1)], unique=True)
    await db.alerts.create_index([("user_id", 1), ("dedupe_key", 1)], unique=True)
    await db.token_blacklist.create_index("expires_at", expireAfterSeconds=0)
    await db.password_resets.create_index("expires_at", expireAfterSeconds=0)
    await db.recipients.create_index("phone", unique=True, sparse=True)
    await db.recipients.create_index("vpa", unique=True, sparse=True)
    await db.transaction_meta.create_index([("user_id", 1), ("obp_transaction_id", 1)], unique=True)
    return client, db
