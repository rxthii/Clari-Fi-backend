async def list_categories(db, user_id: str):
    return await db.baseline_categories.find({"user_id": user_id}).sort("id", 1).to_list(200)


async def insert_category(db, document: dict):
    return await db.baseline_categories.insert_one(document)


async def find_category(db, user_id: str, category_id: str):
    return await db.baseline_categories.find_one({"user_id": user_id, "id": category_id})


async def update_category(db, user_id: str, category_id: str, fields: dict):
    return await db.baseline_categories.find_one_and_update({"user_id": user_id, "id": category_id}, {"$set": fields}, return_document=True)


async def delete_category(db, user_id: str, category_id: str):
    return await db.baseline_categories.delete_one({"user_id": user_id, "id": category_id})
