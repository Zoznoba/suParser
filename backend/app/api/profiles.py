from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import CurrentUser, SessionDep
from app.models import SearchProfile, Source
from app.schemas.profile import ProfileIn, ProfileOut
from app.tasks.collect import enqueue_collect

router = APIRouter(prefix="/profiles", tags=["profiles"])


async def _get(session: SessionDep, profile_id: int) -> SearchProfile:
    profile = await session.get(SearchProfile, profile_id)
    if profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return profile


@router.get("", response_model=list[ProfileOut])
async def list_profiles(session: SessionDep, _: CurrentUser) -> list[SearchProfile]:
    return list(await session.scalars(select(SearchProfile).order_by(SearchProfile.id)))


@router.post("", response_model=ProfileOut, status_code=status.HTTP_201_CREATED)
async def create_profile(data: ProfileIn, session: SessionDep, _: CurrentUser) -> SearchProfile:
    profile = SearchProfile(**data.model_dump())
    session.add(profile)
    await session.commit()
    await session.refresh(profile)
    return profile


@router.put("/{profile_id}", response_model=ProfileOut)
async def update_profile(profile_id: int, data: ProfileIn, session: SessionDep, _: CurrentUser) -> SearchProfile:
    profile = await _get(session, profile_id)
    for key, value in data.model_dump().items():
        setattr(profile, key, value)
    await session.commit()
    await session.refresh(profile)
    return profile


@router.delete("/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_profile(profile_id: int, session: SessionDep, _: CurrentUser) -> None:
    await session.delete(await _get(session, profile_id))
    await session.commit()


@router.post("/{profile_id}/run")
async def run_profile(profile_id: int, session: SessionDep, _: CurrentUser) -> dict[str, list[Source]]:
    """Запустить сбор по профилю вне расписания."""
    return {"queued": await enqueue_collect(await _get(session, profile_id))}
