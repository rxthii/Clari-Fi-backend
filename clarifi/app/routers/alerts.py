from fastapi import APIRouter, Depends, Query, Request

from app.core.deps import get_current_user, get_db
from app.services.alerts import alerts_for_user, refresh_alert_engine, mark_alert_read, mark_all_alerts_read

router = APIRouter(prefix="/api/v1/alerts", tags=["alerts"])


@router.get("")
async def get_alerts(request: Request, unreadOnly: bool = Query(False), user=Depends(get_current_user), db=Depends(get_db)):
    await refresh_alert_engine(db, request.app.state.obp, user, getattr(request.state, "request_id", None))
    return await alerts_for_user(db, str(user["_id"]), unreadOnly)


@router.patch("/{alert_id}/read")
async def mark_read(alert_id: str, user=Depends(get_current_user), db=Depends(get_db)):
    return await mark_alert_read(db, str(user["_id"]), alert_id)


@router.post("/mark-all-read")
async def mark_all_read(user=Depends(get_current_user), db=Depends(get_db)):
    return await mark_all_alerts_read(db, str(user["_id"]))
