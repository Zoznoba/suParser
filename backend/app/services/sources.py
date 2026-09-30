from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Source, SourceHealth, SourceState
from app.parsers.registry import ENABLED_SOURCES, UI_LOGIN_SOURCES
from app.realtime.events import EventType, publish
from app.schemas.source import SourceStateOut


async def get_state(session: AsyncSession, source: Source) -> SourceState:
    state = await session.get(SourceState, source)
    if state is None:
        state = SourceState(source=source, health=SourceHealth.OK)
        session.add(state)
        await session.flush()
    return state


def to_out(state: SourceState) -> SourceStateOut:
    return SourceStateOut(
        source=state.source,
        enabled=state.source in ENABLED_SOURCES,
        ui_login=state.source in UI_LOGIN_SOURCES,
        health=state.health,
        message=state.message,
        last_success_at=state.last_success_at,
    )


async def set_health(
    session: AsyncSession, source: Source, health: SourceHealth, message: str | None = None, success: bool = False
) -> None:
    state = await get_state(session, source)
    changed = state.health != health or state.message != message
    state.health = health
    state.message = message
    if success:
        state.last_success_at = datetime.now(UTC)
    await session.commit()
    if changed:
        await publish(EventType.SOURCE_UPDATED, to_out(state))
