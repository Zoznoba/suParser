import { useEffect, useState } from "react";

import type { CandidateStatus, Freshness, Profile, Source } from "../api/types";
import { SOURCES, SOURCE_LABELS, STATUSES, STATUS_LABELS } from "../lib/format";
import { CheckIcon, CloseIcon, SearchIcon } from "./icons";

export interface FeedFilterValues {
  q?: string;
  status?: CandidateStatus;
  source?: Source;
  profile?: number;
  freshness?: Freshness;
}

const FRESHNESS: readonly Freshness[] = ["actual", "stale", "all"];
const FRESHNESS_LABELS: Record<Freshness, string> = { actual: "актуальные", stale: "неактуальные", all: "все" };

export type SetFilter = <K extends keyof FeedFilterValues>(key: K, value: FeedFilterValues[K]) => void;

export function countActive(f: FeedFilterValues): number {
  return [f.q, f.status, f.source, f.profile, f.freshness].filter(Boolean).length;
}

/** Панель фильтров ленты: на десктопе — колонка слева, на мобильном — выезжающая шторка. */
export function FeedFilters({
  filters,
  set,
  onReset,
  profiles,
}: {
  filters: FeedFilterValues;
  set: SetFilter;
  onReset: () => void;
  profiles: Profile[];
}) {
  const active = countActive(filters);
  return (
    <div>
      <div className="sticky top-0 z-10 flex items-center justify-between border-b border-black bg-white px-4 py-3">
        <h2 className="section-title">Фильтры</h2>
        <button type="button" className="btn-ghost btn px-2 py-1 text-[12px]" disabled={!active} onClick={onReset}>
          Сбросить{active ? ` · ${active}` : ""}
        </button>
      </div>

      <div className="space-y-5 p-4">
        <SearchField value={filters.q ?? ""} onChange={(q) => set("q", q || undefined)} />

        <ChipGroup
          label="Статус"
          options={STATUSES}
          labels={STATUS_LABELS}
          value={filters.status}
          onChange={(v) => set("status", v)}
        />
        <ChipGroup
          label="Источник"
          options={SOURCES}
          labels={SOURCE_LABELS}
          value={filters.source}
          onChange={(v) => set("source", v)}
        />
        {/* неактуальные: резюме снято с площадки или 2 дня не попадается в поиске; по умолчанию скрыты */}
        <ChipGroup
          label="Актуальность"
          options={FRESHNESS}
          labels={FRESHNESS_LABELS}
          value={filters.freshness ?? "actual"}
          onChange={(v) => set("freshness", v === "actual" ? undefined : v)}
        />

        {profiles.length > 0 && (
          <div>
            <span className="label">Профиль поиска</span>
            <div className="scroll-slim max-h-60 space-y-0.5 overflow-y-auto pr-1">
              {profiles.map((p) => {
                const on = filters.profile === p.id;
                return (
                  <button
                    key={p.id}
                    type="button"
                    aria-pressed={on}
                    onClick={() => set("profile", on ? undefined : p.id)}
                    className={`flex w-full cursor-pointer items-center gap-2 rounded-lg px-2 py-1.5 text-left text-[13px] transition-colors ${
                      on ? "bg-black text-white" : "hover:bg-black/5"
                    }`}
                  >
                    <span
                      className={`grid size-4 shrink-0 place-items-center rounded-full ${
                        on ? "bg-white text-black" : "border border-black/50"
                      }`}
                    >
                      {on && <CheckIcon className="size-3" />}
                    </span>
                    <span className="min-w-0 flex-1 truncate">{p.title}</span>
                    {!p.is_active && <span className={`text-[11px] ${on ? "text-white/60" : "text-black/40"}`}>выкл</span>}
                  </button>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

/** Печатаем сразу, а фильтруем через 300 мс после последней клавиши — без запроса на каждую букву. */
function SearchField({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const [text, setText] = useState(value);
  // внешний сброс (крестик в чипе, «Сбросить», навигация) — синхронизируем поле
  useEffect(() => setText(value), [value]);
  useEffect(() => {
    if (text === value) return;
    const id = setTimeout(() => onChange(text.trim()), 300);
    return () => clearTimeout(id);
  }, [text]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <label className="block">
      <span className="label">Поиск</span>
      <span className="relative block">
        <SearchIcon className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-black/50" />
        <input
          type="search"
          className="field pl-9"
          placeholder="Имя или должность"
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
      </span>
    </label>
  );
}

function ChipGroup<T extends string>({
  label,
  options,
  labels,
  value,
  onChange,
}: {
  label: string;
  options: readonly T[];
  labels: Record<T, string>;
  value: T | undefined;
  onChange: (v: T | undefined) => void;
}) {
  return (
    <div role="group" aria-label={`Фильтр: ${label}`}>
      <span className="label">{label}</span>
      <div className="flex flex-wrap gap-1.5">
        {options.map((o) => (
          <button
            key={o}
            type="button"
            className="chip"
            aria-pressed={value === o}
            onClick={() => onChange(value === o ? undefined : o)}
          >
            {labels[o]}
          </button>
        ))}
      </div>
    </div>
  );
}

/** Строка «Фильтр: …» с крестиками над списком. */
export function ActiveFilters({
  filters,
  set,
  onReset,
  profiles,
}: {
  filters: FeedFilterValues;
  set: SetFilter;
  onReset: () => void;
  profiles: Profile[];
}) {
  const chips: { cat: string; value: string; remove: () => void }[] = [];
  if (filters.q) chips.push({ cat: "Поиск", value: `«${filters.q}»`, remove: () => set("q", undefined) });
  if (filters.status)
    chips.push({ cat: "Статус", value: STATUS_LABELS[filters.status], remove: () => set("status", undefined) });
  if (filters.source)
    chips.push({ cat: "Источник", value: SOURCE_LABELS[filters.source], remove: () => set("source", undefined) });
  if (filters.freshness)
    chips.push({
      cat: "Актуальность",
      value: FRESHNESS_LABELS[filters.freshness],
      remove: () => set("freshness", undefined),
    });
  if (filters.profile)
    chips.push({
      cat: "Профиль",
      value: profiles.find((p) => p.id === filters.profile)?.title ?? `#${filters.profile}`,
      remove: () => set("profile", undefined),
    });
  if (!chips.length) return null;

  return (
    <div className="enter card flex flex-wrap items-center gap-2 p-3">
      <span className="pl-1 text-[12px] font-medium text-black/50">Фильтр</span>
      {chips.map((c) => (
        <button
          key={c.cat}
          type="button"
          onClick={c.remove}
          aria-label={`Убрать фильтр ${c.cat}: ${c.value}`}
          className="group flex cursor-pointer items-center gap-1.5 rounded-full border border-black/50 bg-white py-1 pr-1 pl-2.5 text-[12px] transition-colors hover:bg-black/5 active:scale-[0.96]"
        >
          <span className="font-medium text-black/50">{c.cat}</span>
          <span className="max-w-[180px] truncate font-medium">{c.value}</span>
          <span className="grid size-4 place-items-center rounded-full text-black/50 group-hover:bg-black group-hover:text-white">
            <CloseIcon className="size-2.5" />
          </span>
        </button>
      ))}
      <button
        type="button"
        onClick={onReset}
        className="ml-auto cursor-pointer rounded-full px-2.5 py-1 text-[12px] font-medium transition-colors hover:bg-black hover:text-white"
      >
        Сбросить всё
      </button>
    </div>
  );
}
