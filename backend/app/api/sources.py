from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, SessionDep
from app.models import Source, SourceHealth
from app.parsers.browser.login import ACTIVE, LoginChannel, LoginState, LoginStatus, LoginStep
from app.parsers.registry import UI_LOGIN_SOURCES
from app.schemas.source import LoginInput, SourceStateOut
from app.services.sources import get_state, set_health, to_out
from app.tasks.login import login_browser

router = APIRouter(prefix="/sources", tags=["sources"])


@router.get("", response_model=list[SourceStateOut])
async def list_sources(session: SessionDep, _: CurrentUser) -> list[SourceStateOut]:
    states = [await get_state(session, source) for source in Source]
    await session.commit()
    return [to_out(s) for s in states]


@router.post("/{source}/resume", response_model=SourceStateOut)
async def resume_source(source: Source, session: SessionDep, _: CurrentUser) -> SourceStateOut:
    """Снять флаг needs_attention после того, как человек прошёл капчу / перелогинился."""
    await set_health(session, source, SourceHealth.OK)
    return to_out(await get_state(session, source))


# --- вход в аккаунт площадки из интерфейса ---


def _channel(source: Source) -> LoginChannel:
    if source not in UI_LOGIN_SOURCES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Для этой площадки вход из интерфейса не поддерживается")
    return LoginChannel(source)


@router.get("/{source}/login", response_model=LoginState | None)
async def get_login(source: Source, _: CurrentUser) -> LoginState | None:
    return await _channel(source).get()


@router.post("/{source}/login", response_model=LoginState)
async def start_login(source: Source, user: CurrentUser) -> LoginState:
    """Запускает вход в браузер-воркере. Если вход уже идёт (например, начал коллега) — возвращает его."""
    channel = _channel(source)
    current = await channel.get()
    if current and current.status in ACTIVE:
        return current
    state = await channel.update(LoginStatus.QUEUED, prompt="Ждём браузер…", started_by=user.name)
    await login_browser.kiq(source)
    return state


@router.post("/{source}/login/input", response_model=LoginState)
async def login_input(source: Source, body: LoginInput, _: CurrentUser) -> LoginState:
    channel = _channel(source)
    state = await channel.get()
    if state is None or state.status != LoginStatus.NEED_INPUT:
        raise HTTPException(status.HTTP_409_CONFLICT, "Вход сейчас не ждёт ответа")
    if state.step == LoginStep.LOGIN and not (body.login or "").strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Укажите почту или телефон")
    if state.step in (LoginStep.CODE, LoginStep.CAPTCHA) and not (body.value or "").strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Введите ответ")
    await channel.answer(body.model_dump(exclude_none=True))
    return state


@router.post("/{source}/login/cancel", response_model=LoginState | None)
async def cancel_login(source: Source, _: CurrentUser) -> LoginState | None:
    return await _channel(source).cancel()
