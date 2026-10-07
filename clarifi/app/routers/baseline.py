from fastapi import APIRouter, Depends, Query, Request

from app.core.deps import get_current_user, get_db
from app.models.schemas import CategoryCreateIn, CategoryUpdateIn
from app.services.baseline import get_baseline as get_baseline_service, add_category as add_category_service, update_limit, remove_category

router = APIRouter(prefix="/api/v1/baseline-spending", tags=["baseline-spending"])


@router.get("")
async def get_baseline(request: Request, month: str | None = Query(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"), user=Depends(get_current_user), db=Depends(get_db)):
    return await get_baseline_service(db, request.app.state.obp, user, month)


@router.post("/categories")
async def add_category(data: CategoryCreateIn, user=Depends(get_current_user), db=Depends(get_db)):
    return await add_category_service(db, user, data)


@router.put("/categories/{category_id}")
async def update_category(category_id: str, data: CategoryUpdateIn, user=Depends(get_current_user), db=Depends(get_db)):
    return await update_limit(db, user, category_id, data)


@router.delete("/categories/{category_id}")
async def delete_category(category_id: str, user=Depends(get_current_user), db=Depends(get_db)):
    return await remove_category(db, user, category_id)
