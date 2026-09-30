from datetime import UTC, datetime

from sqlalchemy import delete, func, literal, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Candidate, CandidateSource, CandidateStatus, Comment, Source, User, candidate_profiles
from app.parsers.base import ParsedResume, ResumeData
from app.schemas.candidate import CandidateDetail, CandidateOut, DuplicateOut
from app.services.matching import Person, compare, similar_stmt

comments_count = (
    select(func.count(Comment.id)).where(Comment.candidate_id == Candidate.id).correlate(Candidate).scalar_subquery()
)


def to_out(candidate: Candidate, count: int, detail: bool = False) -> CandidateOut:
    schema = CandidateDetail if detail else CandidateOut
    return schema.model_validate(candidate).model_copy(update={"comments_count": count})


async def list_candidates(
    session: AsyncSession,
    *,
    status: CandidateStatus | None = None,
    profile_id: int | None = None,
    source: Source | None = None,
    q: str | None = None,
    stale: bool | None = False,
    offset: int = 0,
    limit: int = 50,
) -> tuple[list[CandidateOut], int]:
    """stale: False — только актуальные анкеты, True — только неактуальные, None — все."""
    stmt = select(Candidate)
    if stale is not None:
        stmt = stmt.where(Candidate.stale_since.is_not(None) if stale else Candidate.stale_since.is_(None))
    if status:
        stmt = stmt.where(Candidate.status == status)
    if profile_id:
        stmt = stmt.where(
            Candidate.id.in_(
                select(candidate_profiles.c.candidate_id).where(candidate_profiles.c.profile_id == profile_id)
            )
        )
    if source:
        stmt = stmt.where(Candidate.sources.any(CandidateSource.source == source))
    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(or_(Candidate.full_name.ilike(pattern), Candidate.title.ilike(pattern)))

    total = await session.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = await session.execute(
        stmt.add_columns(comments_count)
        .order_by(Candidate.created_at.desc(), Candidate.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return [to_out(c, n) for c, n in rows.all()], total or 0


async def get_candidate(session: AsyncSession, candidate_id: int, detail: bool = True) -> CandidateOut | None:
    row = (await session.execute(select(Candidate, comments_count).where(Candidate.id == candidate_id))).first()
    return to_out(row[0], row[1], detail) if row else None


async def set_status(
    session: AsyncSession,
    candidate_id: int,
    status: CandidateStatus,
    user: User,
    expected: CandidateStatus | None = None,
) -> bool:
    """Меняет статус одним UPDATE. С expected — только если статус всё ещё тот, что видел человек:
    двое одновременно нажали «на связи» — второй получит False (409), а не молча перезапишет первого."""
    stmt = update(Candidate).where(Candidate.id == candidate_id)
    if expected is not None:
        stmt = stmt.where(Candidate.status == expected)
    result = await session.execute(
        stmt.values(status=status, status_changed_by_id=user.id, status_changed_at=datetime.now(UTC))
        .returning(Candidate.id)
        .execution_options(synchronize_session=False)
    )
    changed = result.scalar() is not None
    await session.commit()
    return changed


CARD_FIELDS = ("full_name", "title", "city", "age", "birth_date", "salary", "currency", "photo_url")


def _empty(value: object) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _apply(candidate: Candidate, data: ResumeData, only_source: bool) -> None:
    """Резюме единственной площадки карточки переписывает её целиком. Если площадок несколько —
    пустые поля нового резюме не затирают данные другой (SuperJob не отдаёт ФИО, hh — отдаёт)."""
    resume = data.model_dump(mode="json")
    if only_source:
        for name in CARD_FIELDS:
            setattr(candidate, name, getattr(data, name))
        candidate.resume = resume
        return
    for name in CARD_FIELDS:
        if not _empty(value := getattr(data, name)):
            setattr(candidate, name, value)
    candidate.resume = {**(candidate.resume or {}), **{k: v for k, v in resume.items() if not _empty(v)}}


async def find_duplicate(session: AsyncSession, resume: ParsedResume) -> Candidate | None:
    """Карточка того же человека: по аккаунту соискателя на площадке, иначе по эвристике (services.matching).

    Эвристикой склеиваем только с карточками без резюме с этой площадки: внутри площадки надёжнее
    id аккаунта, а совпадения «ФИО + компания» там чаще оказываются однофамильцами. Остальное — вручную.
    """
    if resume.owner_id:
        candidate = await session.scalar(
            select(Candidate)
            .join(CandidateSource)
            .where(CandidateSource.source == resume.source, CandidateSource.owner_id == resume.owner_id)
            .limit(1)
        )
        if candidate:
            return candidate

    person = Person.of_resume(resume.data)
    if (stmt := similar_stmt(person)) is None:
        return None
    stmt = stmt.where(~Candidate.sources.any(CandidateSource.source == resume.source))
    for candidate in await session.scalars(stmt):
        if compare(person, Person.of_candidate(candidate)).sure:
            return candidate
    return None


async def find_possible_duplicates(session: AsyncSession, candidate: Candidate) -> list[DuplicateOut]:
    person = Person.of_candidate(candidate)
    if (stmt := similar_stmt(person)) is None:
        return []
    rows = await session.execute(stmt.where(Candidate.id != candidate.id).add_columns(comments_count))
    result = []
    for other, count in rows.all():
        if (match := compare(person, Person.of_candidate(other))).reasons:
            result.append(DuplicateOut(candidate=to_out(other, count), reasons=list(match.reasons), sure=match.sure))
    return result


async def merge_candidates(session: AsyncSession, target: Candidate, other: Candidate) -> None:
    """Переносит в target резюме, комментарии и профили other и удаляет other.

    Пустые поля target заполняются из other; статус берётся у other, если target ещё «новый».
    """
    for name in CARD_FIELDS:
        if _empty(getattr(target, name)):
            setattr(target, name, getattr(other, name))
    target.resume = {**(other.resume or {}), **{k: v for k, v in (target.resume or {}).items() if not _empty(v)}}
    if target.status == CandidateStatus.NEW and other.status != CandidateStatus.NEW:
        target.status = other.status
        target.status_changed_by_id = other.status_changed_by_id
        target.status_changed_at = other.status_changed_at
    target.created_at = min(target.created_at, other.created_at)
    if other.stale_since is None:  # актуальное резюме второй карточки делает актуальной и объединённую
        target.stale_since = None

    await session.execute(
        update(CandidateSource).where(CandidateSource.candidate_id == other.id).values(candidate_id=target.id)
    )
    await session.execute(update(Comment).where(Comment.candidate_id == other.id).values(candidate_id=target.id))
    await session.execute(
        pg_insert(candidate_profiles)
        .from_select(
            ["candidate_id", "profile_id"],
            select(literal(target.id), candidate_profiles.c.profile_id).where(
                candidate_profiles.c.candidate_id == other.id
            ),
        )
        .on_conflict_do_nothing()
    )
    await session.execute(delete(Candidate).where(Candidate.id == other.id))
    await session.commit()
    session.expunge(other)
    session.expire(target)


async def upsert_resume(
    session: AsyncSession, resume: ParsedResume, profile_id: int | None, imported_by: User | None = None
) -> tuple[Candidate, bool]:
    """Сохраняет резюме. Статус и комментарии существующей карточки не трогает. Возвращает (карточка, создана ли).

    profile_id — профиль поиска, в выдаче которого нашлось резюме; None и imported_by — добавлено вручную по ссылке.
    Актуальность карточки (stale_since) пересчитывает services.stale.refresh_stale после сбора.
    """
    src = await session.scalar(
        select(CandidateSource).where(
            CandidateSource.source == resume.source, CandidateSource.external_id == resume.external_id
        )
    )
    created = False
    if src:
        candidate = await session.get_one(Candidate, src.candidate_id)
    else:
        candidate = await find_duplicate(session, resume)
        if candidate is None:
            candidate = Candidate(status=CandidateStatus.NEW)
            session.add(candidate)
            created = True
        src = CandidateSource(
            candidate=candidate, source=resume.source, external_id=resume.external_id, imported_by=imported_by
        )
        session.add(src)

    _apply(candidate, resume.data, only_source=all(s is src for s in candidate.sources))
    src.owner_id = resume.owner_id
    src.url = resume.url
    src.raw = resume.raw
    src.published_at = resume.published_at
    src.last_seen_at = datetime.now(UTC)
    src.gone_at = None
    await session.flush()

    if profile_id is not None:
        await session.execute(
            pg_insert(candidate_profiles)
            .values(candidate_id=candidate.id, profile_id=profile_id)
            .on_conflict_do_nothing()
        )
    return candidate, created


async def add_comment(session: AsyncSession, candidate_id: int, author: User, text: str) -> Comment:
    comment = Comment(candidate_id=candidate_id, author=author, text=text)
    session.add(comment)
    await session.commit()
    await session.refresh(comment)
    return comment


async def edit_comment(session: AsyncSession, comment: Comment, text: str) -> Comment:
    comment.text = text
    comment.edited_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(comment)
    return comment


async def delete_comment(session: AsyncSession, comment: Comment) -> None:
    await session.delete(comment)
    await session.commit()
