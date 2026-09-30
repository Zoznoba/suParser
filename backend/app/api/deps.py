from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_session
from app.core.security import get_session_user_id
from app.models import User

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def user_from_cookie(session: AsyncSession, token: str | None) -> User | None:
    if not token:
        return None
    user_id = await get_session_user_id(token)
    user = await session.get(User, user_id) if user_id else None
    return user if user and user.is_active else None


async def get_current_user(request: Request, session: SessionDep) -> User:
    user = await user_from_cookie(session, request.cookies.get(settings.session_cookie_name))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Не авторизован")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
