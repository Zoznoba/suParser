from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import select

from app.api.deps import CurrentUser, SessionDep
from app.core.config import settings
from app.core.security import create_session, delete_session, verify_password
from app.models import User
from app.schemas.auth import LoginIn
from app.schemas.common import UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=UserOut)
async def login(data: LoginIn, response: Response, session: SessionDep) -> User:
    user = await session.scalar(select(User).where(User.login == data.login))
    if user is None or not user.is_active or not verify_password(data.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный логин или пароль")
    response.set_cookie(
        settings.session_cookie_name,
        await create_session(user.id),
        max_age=settings.session_ttl_seconds,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
    )
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, response: Response) -> None:
    if token := request.cookies.get(settings.session_cookie_name):
        await delete_session(token)
    response.delete_cookie(settings.session_cookie_name)


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> User:
    return user
