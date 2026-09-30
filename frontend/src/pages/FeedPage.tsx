import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router";

import { useCandidates, useProfiles } from "../api/hooks";
import type { Candidate, CandidateFilters, CandidateStatus, Freshness, Source } from "../api/types";
import { ActiveFilters, FeedFilters, type FeedFilterValues, type SetFilter, countActive } from "../components/FeedFilters";
import { Comments } from "../components/Comments";
import { ChatIcon, ChevronIcon, CloseIcon, FilterIcon } from "../components/icons";
import { ImportByLink } from "../components/ImportByLink";
import { SourceBadges } from "../components/SourceBadges";
import { StatusPicker } from "../components/StatusPicker";
import { Avatar, Skeleton } from "../components/ui";
import { Viewers } from "../components/Viewers";
import { STATUS_LABELS, formatDate, formatSalary } from "../lib/format";
import { useViewing } from "../realtime/viewing";

const PAGE_SIZE = 50;
const URL_KEYS = ["q", "status", "source", "profile", "freshness"] as const;

export function FeedPage() {
  // фильтры живут в URL: ссылкой на отфильтрованную ленту можно поделиться с коллегой
  const [params, setParams] = useSearchParams();
  const values: FeedFilterValues = {
    q: params.get("q") || undefined,
    status: (params.get("status") as CandidateStatus) || undefined,
    source: (params.get("source") as Source) || undefined,
    profile: Number(params.get("profile")) || undefined,
    freshness: (params.get("freshness") as Freshness) || undefined,
  };
  const filters: CandidateFilters = {
    status: values.status,
    profile_id: values.profile,
    source: values.source,
    q: values.q,
    freshness: values.freshness,
    offset: Number(params.get("offset")) || 0,
    limit: PAGE_SIZE,
  };
  const { data, isPending, isFetching } = useCandidates(filters);
  const { data: profiles = [] } = useProfiles();
  const [drawer, setDrawer] = useState(false);

  const update = (key: string, value: string | number | undefined) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, String(value));
    else next.delete(key);
    if (key !== "offset") next.delete("offset");
    setParams(next, { replace: true });
  };
  const set: SetFilter = (key, value) => update(key, value);
  const reset = () => {
    const next = new URLSearchParams(params);
    for (const k of [...URL_KEYS, "offset"]) next.delete(k);
    setParams(next, { replace: true });
  };

  // мобильная шторка: блокируем прокрутку страницы, Escape закрывает
  useEffect(() => {
    if (!drawer) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setDrawer(false);
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = prev;
      window.removeEventListener("keydown", onKey);
    };
  }, [drawer]);

  const offset = filters.offset ?? 0;
  const total = data?.total ?? 0;
  const active = countActive(values);

  return (
    <div className="flex gap-4">
      {drawer && (
        <button
          type="button"
          aria-label="Закрыть фильтры"
          onClick={() => setDrawer(false)}
          className="enter fixed inset-0 z-40 cursor-pointer bg-black/50 backdrop-blur-sm lg:hidden"
          style={{ animationDuration: "0.2s" }}
        />
      )}

      <aside
        className={`fixed inset-y-0 left-0 z-50 flex w-[86%] max-w-sm flex-col bg-canvas transition-transform duration-300 ease-out lg:sticky lg:top-[82px] lg:z-0 lg:h-[calc(100vh-106px)] lg:w-72 lg:max-w-none lg:shrink-0 lg:translate-x-0 lg:bg-transparent ${
          drawer ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <div className="flex items-center justify-end border-b border-black px-3 py-2 lg:hidden">
          <button type="button" aria-label="Закрыть" className="btn-ghost btn p-2" onClick={() => setDrawer(false)}>
            <CloseIcon className="size-4" />
          </button>
        </div>
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden bg-white lg:rounded-3xl lg:border lg:border-black/50">
          <div className="scroll-slim flex-1 overflow-y-auto">
            <FeedFilters filters={values} set={set} onReset={reset} profiles={profiles} />
          </div>
        </div>
        <div className="border-t border-black p-3 lg:hidden">
          <button type="button" className="btn btn-primary nums w-full py-2.5" onClick={() => setDrawer(false)}>
            Показать {total.toLocaleString("ru-RU")}
          </button>
        </div>
      </aside>

      <section className="min-w-0 flex-1 space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-lg font-bold tracking-tight uppercase">Анкеты</h1>
          <span className="nums text-[13px] text-black/50">{isFetching ? "обновление…" : `найдено: ${total}`}</span>
          <div className="ml-auto flex items-center gap-2">
            <Pager offset={offset} total={total} onPage={(o) => update("offset", o)} />
            <ImportByLink />
            <button type="button" className="btn lg:hidden" onClick={() => setDrawer(true)}>
              <FilterIcon className="size-4" />
              Фильтры
              {active > 0 && (
                <span className="nums grid min-w-5 place-items-center rounded-full bg-black px-1 text-[11px] font-semibold text-white">
                  {active}
                </span>
              )}
            </button>
          </div>
        </div>

        <ActiveFilters filters={values} set={set} onReset={reset} profiles={profiles} />

        {isPending ? (
          <Skeleton />
        ) : total === 0 ? (
          <div className="card p-10 text-center">
            <p className="text-sm font-medium">
              {active ? "Под эти фильтры анкет нет." : "Анкет пока нет. Настройте профиль поиска на вкладке «Поиск»."}
            </p>
            {active > 0 ? (
              <button type="button" className="btn mt-3" onClick={reset}>
                Сбросить фильтры
              </button>
            ) : (
              <Link to="/profiles" className="btn btn-primary mt-3">
                К профилям поиска
              </Link>
            )}
          </div>
        ) : (
          <ul className={`space-y-2 transition-opacity ${isFetching ? "opacity-60" : ""}`}>
            {data?.items.map((c, i) => (
              <CandidateRow key={c.id} candidate={c} index={i} />
            ))}
          </ul>
        )}

        {total > PAGE_SIZE && (
          <div className="flex justify-center pt-2">
            <Pager offset={offset} total={total} onPage={(o) => update("offset", o)} />
          </div>
        )}
      </section>
    </div>
  );
}

function Pager({ offset, total, onPage }: { offset: number; total: number; onPage: (offset: number) => void }) {
  if (total <= PAGE_SIZE) return null;
  return (
    <div className="flex items-center gap-1">
      <button
        type="button"
        className="btn size-8 p-0"
        aria-label="Назад"
        disabled={offset === 0}
        onClick={() => onPage(offset - PAGE_SIZE)}
      >
        ‹
      </button>
      <span className="nums px-2 text-[12px] text-black/60">
        {offset + 1}–{Math.min(offset + PAGE_SIZE, total)} из {total}
      </span>
      <button
        type="button"
        className="btn size-8 p-0"
        aria-label="Вперёд"
        disabled={offset + PAGE_SIZE >= total}
        onClick={() => onPage(offset + PAGE_SIZE)}
      >
        ›
      </button>
    </div>
  );
}

function CandidateRow({ candidate: c, index }: { candidate: Candidate; index: number }) {
  const salary = formatSalary(c.salary, c.currency);
  const rejected = c.status === "rejected";
  // тред раскрывается прямо под анкетой; «Начать тред» сразу ставит курсор в поле
  const [thread, setThread] = useState<"closed" | "open" | "start">("closed");
  const toggleThread = () => setThread(thread !== "closed" ? "closed" : c.comments_count ? "open" : "start");
  useViewing(thread !== "closed" ? c.id : null); // раскрытый тред — тоже «смотрит»
  return (
    <li
      className="enter card group relative overflow-hidden transition-colors hover:border-black"
      style={{ animationDelay: `${Math.min(index, 12) * 30}ms` }}
    >
      {/* приглушаем содержимое, а не li: у .enter анимация opacity с fill-mode both */}
      <Link
        to={`/candidates/${c.id}`}
        className={`group/link flex gap-3 p-4 pb-3 transition-opacity ${rejected ? "opacity-45 group-hover:opacity-100" : ""}`}
      >
        <Avatar name={c.full_name} src={c.photo_url} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="truncate text-[15px] font-semibold group-hover/link:underline group-hover/link:underline-offset-2">
              {c.full_name ?? "Без имени"}
            </span>
            {c.status === "new" && (
              <span className="rounded-md bg-black px-1.5 py-0.5 text-[10px] font-bold tracking-wide text-white uppercase">
                {STATUS_LABELS.new}
              </span>
            )}
            {c.stale_since && (
              <span
                className="rounded-md border border-black/50 px-1.5 py-0.5 text-[10px] font-bold tracking-wide uppercase"
                title={`Неактуальна с ${formatDate(c.stale_since)}: резюме снято или давно не попадается в поиске`}
              >
                неактуальна
              </span>
            )}
          </div>
          <div className="truncate text-[13px] text-black/70">{c.title}</div>
          <div className="nums mt-1 text-[12px] text-black/50">
            {[c.city, c.age && `${c.age} лет`].filter(Boolean).join(" · ")}
          </div>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1.5 text-right">
          {salary && <span className="nums text-[15px] font-semibold">{salary}</span>}
          <SourceBadges sources={c.sources} />
          <time className="nums text-[12px] text-black/50">{formatDate(c.created_at)}</time>
        </div>
      </Link>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-t border-black/10 px-4 py-2.5">
        <StatusPicker candidate={c} />
        {c.status_changed_by && (
          <span className="nums text-[12px] text-black/50">
            {c.status_changed_by.name}, {formatDate(c.status_changed_at)}
          </span>
        )}
        <Viewers candidateId={c.id} compact />
        <button
          type="button"
          aria-expanded={thread !== "closed"}
          className={`chip ml-auto px-2.5 py-1 ${thread !== "closed" ? "chip-on" : ""}`}
          onClick={toggleThread}
        >
          <ChatIcon className="size-3.5" />
          {c.comments_count > 0 ? (
            <>
              Тред <span className="nums">· {c.comments_count}</span>
            </>
          ) : (
            "Начать тред"
          )}
          <ChevronIcon className={`size-3 transition-transform ${thread !== "closed" ? "rotate-180" : ""}`} />
        </button>
      </div>
      {thread !== "closed" && <Comments candidateId={c.id} variant="inline" autoFocus={thread === "start"} />}
    </li>
  );
}
