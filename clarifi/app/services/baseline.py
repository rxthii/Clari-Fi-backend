from app.core.errors import AppError
from app.repositories.categories import delete_category as delete_repo, insert_category, list_categories, update_category as update_repo
from app.services.banking import spending_for_month
from app.services.common import days_remaining, money_num


async def get_baseline(db, obp, user, month=None):
    uid = str(user["_id"])
    docs = await list_categories(db, uid)
    spent = await spending_for_month(db, obp, user, month)
    categories = [{"id": x["id"], "title": x["title"], "allocated": money_num(x["allocated"]), "spent": money_num(spent.get(x["title"], 0)), "icon": x.get("icon", "payments"), "color": x.get("color", "#777777")} for x in docs]
    return {"totalAllocated": sum(c["allocated"] for c in categories), "totalSpent": sum(c["spent"] for c in categories), "daysRemaining": days_remaining(), "categories": categories}


async def add_category(db, user, data):
    uid = str(user["_id"])
    existing = await list_categories(db, uid)
    used = {x.get("id") for x in existing}
    suffix = 1
    while f"base-{suffix}" in used: suffix += 1
    if any(x.get("title", "").lower() == data.title.strip().lower() for x in existing):
        raise AppError("CATEGORY_EXISTS", "A category with this title already exists.", 409)
    category_id = f"base-{suffix}"
    doc = {"user_id": uid, "id": category_id, "title": data.title.strip(), "allocated": format(data.allocated, ".2f"), "icon": "payments", "color": "#777777", "keywords": []}
    await insert_category(db, doc)
    return {"category": {"id": category_id, "title": doc["title"], "allocated": money_num(data.allocated), "spent": 0}}


async def update_limit(db, user, category_id, data):
    result = await update_repo(db, str(user["_id"]), category_id, {"allocated": format(data.allocated, ".2f")})
    if not result: raise AppError("CATEGORY_NOT_FOUND", "Category was not found.", 404)
    return {"category": {"id": result["id"], "title": result["title"], "allocated": money_num(data.allocated), "spent": 0}, "message": "Limit updated"}


async def remove_category(db, user, category_id):
    result = await delete_repo(db, str(user["_id"]), category_id)
    if not result.deleted_count: raise AppError("CATEGORY_NOT_FOUND", "Category was not found.", 404)
    return {"success": True}
