from fastapi import APIRouter, Depends, Query, Request
from app.core.deps import get_current_user, get_db
from app.services.banking import get_transactions, transaction_summary, transaction_receipt

router = APIRouter(prefix="/api/v1/transactions", tags=["transactions"])


@router.get("")
async def list_transactions(request: Request, type: str = Query("all", pattern="^(all|income|spending)$"), page: int = Query(1, ge=1), limit: int = Query(20, ge=1, le=100), user=Depends(get_current_user), db=Depends(get_db)):
    return await get_transactions(db, request.app.state.obp, user, type, page, limit)


@router.get("/summary")
async def summary(request: Request, month: str = Query(..., pattern=r"^\d{4}-(0[1-9]|1[0-2])$"), user=Depends(get_current_user), db=Depends(get_db)):
    return await transaction_summary(db, request.app.state.obp, user, month)


@router.get("/{transaction_id}")
async def transaction_detail(transaction_id: str, request: Request, user=Depends(get_current_user), db=Depends(get_db)):
    return await transaction_receipt(db, request.app.state.obp, user, transaction_id)
