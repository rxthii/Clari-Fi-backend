from fastapi import APIRouter, Depends, File, Request, UploadFile
from app.core.deps import get_current_user, get_db
from app.core.errors import AppError
from app.core.limits import limiter
from app.models.schemas import ProfileUpdateIn, PinIn
from app.services.common import clean_user
from app.services.profile import update_profile as update_profile_service, save_avatar, set_pin as set_pin_service

router = APIRouter(prefix="/api/v1/users", tags=["users"])
MIME_EXT = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}


@router.get("/me")
async def get_profile(user=Depends(get_current_user)):
    return clean_user(user)


@router.put("/me")
async def update_profile(data: ProfileUpdateIn, user=Depends(get_current_user), db=Depends(get_db)):
    return await update_profile_service(db, user, data.model_dump(exclude_unset=True))


@router.post("/me/avatar")
async def upload_avatar(request: Request, avatar: UploadFile = File(...), user=Depends(get_current_user), db=Depends(get_db)):
    ext = MIME_EXT.get(avatar.content_type or "")
    if not ext: raise AppError("INVALID_AVATAR", "Avatar must be PNG, JPG, or WEBP.", 422)
    contents = await avatar.read(2 * 1024 * 1024 + 1)
    if len(contents) > 2 * 1024 * 1024: raise AppError("INVALID_AVATAR", "Avatar file must be 2 MB or smaller.", 413)
    if not contents: raise AppError("INVALID_AVATAR", "Avatar file is empty.", 422)
    signatures = {"image/png": contents.startswith(b"\x89PNG\r\n\x1a\n"), "image/jpeg": contents.startswith(b"\xff\xd8\xff"), "image/webp": len(contents) >= 12 and contents[:4] == b"RIFF" and contents[8:12] == b"WEBP"}
    if not signatures.get(avatar.content_type or "", False): raise AppError("INVALID_AVATAR", "Avatar content does not match its image type.", 422)
    return await save_avatar(db, user, request.app.state.upload_dir, contents, ext)


@router.post("/me/pin")
@limiter.limit("8/minute")
async def set_pin(data: PinIn, request: Request, user=Depends(get_current_user), db=Depends(get_db)):
    return await set_pin_service(db, user, data.pin, data.currentPin, getattr(request.state, "request_id", None))
