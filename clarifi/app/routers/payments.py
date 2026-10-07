from fastapi import APIRouter, Depends, Header, Query, Request
from app.core.limits import limiter
from app.core.deps import get_current_user, get_db
from app.models.schemas import QRDecodeIn, TransferIn
from app.services.payments import lookup_recipient, frequent_contacts, decode_qr, execute_transfer, cancel_draft

router = APIRouter(prefix="/api/v1/payments", tags=["payments"])


@router.get("/recipients/lookup")
async def recipient_lookup(query: str = Query(..., min_length=1, max_length=200), user=Depends(get_current_user), db=Depends(get_db)):
    return await lookup_recipient(db, query)


@router.get("/recipients/frequent")
async def recipients_frequent(user=Depends(get_current_user), db=Depends(get_db)):
    return await frequent_contacts(db, str(user["_id"]))


@router.post("/qr/decode")
async def qr_decode(data: QRDecodeIn, user=Depends(get_current_user)):
    return await decode_qr(data.qrRawString)


@router.post("/transfer")
@limiter.limit("8/minute")
async def transfer(data: TransferIn, request: Request, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=200), user=Depends(get_current_user), db=Depends(get_db)):
    return await execute_transfer(db, request.app.state.obp, request.app.state.settings, user, data, idempotency_key, getattr(request.state, "request_id", None))


@router.post("/drafts/{draft_id}/cancel")
async def draft_cancel(draft_id: str, user=Depends(get_current_user), db=Depends(get_db)):
    return await cancel_draft(db, str(user["_id"]), draft_id)
