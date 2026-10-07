from fastapi import APIRouter, Request
router = APIRouter(prefix="/api/v1", tags=["health"])

@router.get("/health")
async def health(request: Request):
    return {"status": "ok", "database": bool(getattr(request.app.state, "db", None)), "timestamp": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()}
