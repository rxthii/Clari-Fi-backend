async def update_alert(db, user_id: str, alert_id: str):
    return await db.alerts.update_one({"user_id": user_id, "id": alert_id}, {"$set": {"read": True}})


async def update_all_alerts(db, user_id: str):
    return await db.alerts.update_many({"user_id": user_id}, {"$set": {"read": True}})
