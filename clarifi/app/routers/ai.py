from fastapi import APIRouter, Depends, Query, Request
from app.core.limits import limiter
from app.core.deps import get_current_user, get_db
from app.models.schemas import ChatIn
from app.services.ai_agent import chat, history

router = APIRouter(prefix="/api/v1/ai", tags=["ai"])


@router.post("/chat")
@limiter.limit("10/minute")
async def send_chat(request: Request, data: ChatIn, user=Depends(get_current_user), db=Depends(get_db)):
    return await chat(db, user, data.message, request.app.state.llm, request.app.state.obp, request.app.state.settings, request.app.state.tavily, getattr(request.state, "request_id", None))


@router.get("/chat/history")
async def get_history(page: int = Query(1, ge=1), limit: int = Query(50, ge=1, le=100), user=Depends(get_current_user), db=Depends(get_db)):
    return await history(db, str(user["_id"]), page, limit)


@router.delete("/chat/history")
async def clear_history(user=Depends(get_current_user), db=Depends(get_db)):
    await db.chat_messages.delete_many({"user_id": str(user["_id"])})
    return {"success": True}
