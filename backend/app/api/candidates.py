import secrets
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.api.deps import CurrentUser, SessionDep
from app.models import Candidate, CandidateSource, CandidateStatus, Comment, Source
from app.parsers.hh.mapper import parse_resume_link
from app.realtime.events import EventType, publish
from app.schemas.candidate import (
    CandidateDetail,
    CandidateOut,
    CandidatePage,
    CommentIn,
    CommentOut,
    DuplicateOut,
    ImportIn,
    ImportOut,
    MergeIn,
    StatusIn,
)
from app.services import candidates as service
from app.services.stale import refresh_stale
from app.tasks.collect import import_resume

router = APIRouter(prefix="/candidates", tags=["candidates"])

STATUS_LABELS = {
    CandidateStatus.NEW: "новая",
    CandidateStatus.INTERESTING: "интересно",
    CandidateStatus.REJECTED: "мимо",
    CandidateStatus.CONTACTED: "на связи",
    CandidateStatus.IN_PROGRESS: "в работе",
}


@router.get("", response_model=CandidatePage)
async def list_candidates(
    session: SessionDep,
    _: CurrentUser,
    status_: CandidateStatus | None = Query(None, alias="status"),
    profile_id: int | None = None,
    source: Source | None = None,
    q: str | None = None,
    freshness: Literal["actual", "stale", "all"] = "actual",
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> CandidatePage:
    stale = {"actual": False, "stale": True, "all": None}[freshness]
    items, total = await service.list_candidates(
        session, status=status_, profile_id=profile_id, source=source, q=q, stale=stale, offset=offset, limit=limit
    )
    return CandidatePage(items=items, total=total)


@router.post("/import", response_model=ImportOut, status_code=status.HTTP_202_ACCEPTED)
async def import_by_link(data: ImportIn, session: SessionDep, user: CurrentUser) -> ImportOut:
    """Ручной импорт резюме hh по ссылке. Браузер открывает его в фоне; итог — событие import.finished."""
    resume_hash = parse_resume_link(data.url)
    if resume_hash is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Нужна ссылка на резюме hh.ru: https://hh.ru/resume/…"
        )
    request_id = secrets.token_hex(8)
    existing = await session.scalar(
        select(CandidateSource.candidate_id).where(
            CandidateSource.source == Source.HH, CandidateSource.external_id == resume_hash
        )
    )
    if existing:
        return ImportOut(request_id=request_id, candidate_id=existing)
    await import_resume.kiq(request_id, resume_hash, data.url.strip(), user.id)
    return ImportOut(request_id=request_id)


@router.get("/{candidate_id}", response_model=CandidateDetail)
async def get_candidate(candidate_id: int, session: SessionDep, _: CurrentUser) -> CandidateOut:
    candidate = await service.get_candidate(session, candidate_id)
    if candidate is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return candidate


@router.get("/{candidate_id}/duplicates", response_model=list[DuplicateOut])
async def list_duplicates(candidate_id: int, session: SessionDep, _: CurrentUser) -> list[DuplicateOut]:
    candidate = await session.get(Candidate, candidate_id)
    if candidate is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return await service.find_possible_duplicates(session, candidate)


@router.post("/{candidate_id}/merge", response_model=CandidateDetail)
async def merge(candidate_id: int, data: MergeIn, session: SessionDep, _: CurrentUser) -> CandidateOut:
    """Вливает карточку other_id в эту: резюме, комментарии, профили; other_id удаляется."""
    if data.other_id == candidate_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Нельзя объединить карточку саму с собой")
    target = await session.get(Candidate, candidate_id)
    other = await session.get(Candidate, data.other_id)
    if target is None or other is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    await service.merge_candidates(session, target, other)
    await refresh_stale(session)
    out = await service.get_candidate(session, candidate_id)
    await publish(EventType.CANDIDATE_MERGED, {"id": data.other_id, "into": candidate_id})
    await publish(EventType.CANDIDATE_UPDATED, service.to_out(target, out.comments_count))
    return out


@router.patch("/{candidate_id}/status", response_model=CandidateOut)
async def set_status(candidate_id: int, data: StatusIn, session: SessionDep, user: CurrentUser) -> CandidateOut:
    changed = await service.set_status(session, candidate_id, data.status, user, data.expected)
    out = await service.get_candidate(session, candidate_id, detail=False)
    if out is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if not changed:
        who = f" ({out.status_changed_by.name})" if out.status_changed_by else ""
        label = STATUS_LABELS[out.status]
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Статус уже сменили{who}: «{label}». Проверьте и выберите заново"
        )
    await publish(EventType.CANDIDATE_UPDATED, out)
    return out


@router.get("/{candidate_id}/comments", response_model=list[CommentOut])
async def list_comments(candidate_id: int, session: SessionDep, _: CurrentUser) -> list[Comment]:
    rows = await session.scalars(
        select(Comment).where(Comment.candidate_id == candidate_id).order_by(Comment.created_at, Comment.id)
    )
    return list(rows)


@router.post("/{candidate_id}/comments", response_model=CommentOut, status_code=status.HTTP_201_CREATED)
async def add_comment(candidate_id: int, data: CommentIn, session: SessionDep, user: CurrentUser) -> CommentOut:
    if await session.get(Candidate, candidate_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    comment = CommentOut.model_validate(await service.add_comment(session, candidate_id, user, data.text.strip()))
    await publish(EventType.COMMENT_CREATED, comment)
    return comment


async def _own_comment(session: SessionDep, candidate_id: int, comment_id: int, user: CurrentUser) -> Comment:
    comment = await session.get(Comment, comment_id)
    if comment is None or comment.candidate_id != candidate_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if comment.author_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Менять и удалять можно только свои комментарии")
    return comment


@router.patch("/{candidate_id}/comments/{comment_id}", response_model=CommentOut)
async def edit_comment(
    candidate_id: int, comment_id: int, data: CommentIn, session: SessionDep, user: CurrentUser
) -> CommentOut:
    comment = await _own_comment(session, candidate_id, comment_id, user)
    out = CommentOut.model_validate(await service.edit_comment(session, comment, data.text.strip()))
    await publish(EventType.COMMENT_UPDATED, out)
    return out


@router.delete("/{candidate_id}/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_comment(candidate_id: int, comment_id: int, session: SessionDep, user: CurrentUser) -> None:
    comment = await _own_comment(session, candidate_id, comment_id, user)
    await service.delete_comment(session, comment)
    await publish(EventType.COMMENT_DELETED, {"id": comment_id, "candidate_id": candidate_id})
