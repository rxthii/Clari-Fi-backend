from typing import Annotated
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.errors import AppError
from app.core.security import decode_access_token
from app.repositories.users import get_user, token_is_blacklisted

bearer = HTTPBearer(auto_error=False)


def get_db(request: Request):
    return request.app.state.db


def get_settings(request: Request):
    return request.app.state.settings


async def get_current_user(request: Request, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
    if not credentials:
        raise AppError("UNAUTHORIZED", "Authentication is required.", 401)
    payload = decode_access_token(credentials.credentials, request.app.state.settings)
    db = request.app.state.db
    if await token_is_blacklisted(db, payload.get("jti")):
        raise AppError("UNAUTHORIZED", "This session has been logged out.", 401)
    user = await get_user(db, payload.get("sub"))
    if not user:
        raise AppError("UNAUTHORIZED", "User account was not found.", 401)
    request.state.jwt_payload = payload
    return user
