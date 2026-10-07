from fastapi import APIRouter, Depends, Request
from app.core.limits import limiter

from app.core.deps import get_current_user, get_db
from app.models.schemas import RegisterIn, LoginIn, CompleteProfileIn, ForgotPasswordIn, ChangePasswordIn
from app.services.auth import register, login, complete_profile, forgot_password, change_password, logout
from app.services.common import now_utc

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/register")
@limiter.limit("5/minute")
async def register_route(request: Request, data: RegisterIn, db=Depends(get_db)):
    return await register(db, data, request.app.state.settings)


@router.post("/login")
@limiter.limit("10/minute")
async def login_route(request: Request, data: LoginIn, db=Depends(get_db)):
    return await login(db, data, request.app.state.settings, getattr(request.state, "request_id", None))


@router.post("/complete-profile")
async def complete_profile_route(data: CompleteProfileIn, request: Request, user=Depends(get_current_user), db=Depends(get_db)):
    return await complete_profile(db, user, data)


@router.post("/forgot-password")
@limiter.limit("5/minute")
async def forgot_password_route(request: Request, data: ForgotPasswordIn, db=Depends(get_db)):
    return await forgot_password(db, data.email, request.app.state.settings)


@router.post("/change-password")
async def change_password_route(data: ChangePasswordIn, user=Depends(get_current_user), db=Depends(get_db)):
    return await change_password(db, user, data)


@router.post("/logout")
async def logout_route(request: Request, user=Depends(get_current_user), db=Depends(get_db)):
    return await logout(db, user, request.state.jwt_payload, getattr(request.state, "request_id", None))
