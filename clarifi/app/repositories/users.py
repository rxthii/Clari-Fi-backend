async def get_user(db, user_id: str):
    return await db.users.find_one({"_id": user_id})


async def find_email(db, email: str, exclude_user_id: str | None = None):
    query = {"email": email}
    if exclude_user_id: query["_id"] = {"$ne": exclude_user_id}
    return await db.users.find_one(query)


async def update_user(db, user_id: str, fields: dict):
    return await db.users.update_one({"_id": user_id}, {"$set": fields})


async def blacklist_token(db, jti: str, expires_at):
    return await db.token_blacklist.update_one({"jti": jti}, {"$setOnInsert": {"jti": jti, "expires_at": expires_at}}, upsert=True)


async def token_is_blacklisted(db, jti: str):
    return await db.token_blacklist.find_one({"jti": jti}) is not None
