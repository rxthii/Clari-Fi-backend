from fastapi import APIRouter, Depends, Request
from app.core.deps import get_current_user
from app.services.banking import account_overview

router = APIRouter(prefix="/api/v1/account", tags=["account"])

@router.get("/overview")
async def overview(request: Request, user=Depends(get_current_user)):
    return await account_overview(request.app.state.obp, user)
