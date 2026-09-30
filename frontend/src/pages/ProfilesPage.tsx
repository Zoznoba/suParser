import { type FormEvent, useState } from "react";

import { useDeleteProfile, useProfiles, useRunProfile, useSaveProfile, useSources } from "../api/hooks";
import type { Profile, ProfileInput, Source, SourceState } from "../api/types";
import { PlayIcon, PlusIcon } from "../components/icons";
import { SourceLoginButton } from "../components/SourceLogin";
import { Checkbox, ErrorText, Skeleton } from "../components/ui";
import { SOURCE_LABELS, formatDate } from "../lib/format";

const EMPTY: ProfileInput = { title: "", keywords: "", sources: ["superjob"], interval_minutes: 60, is_active: true };

export function ProfilesPage() {
  const { data: profiles = [], isPending } = useProfiles();
  const [editing, setEditing] = useState<(ProfileInput & { id?: number }) | null>(null);

  return (
    <div className="mx-auto max-w-5xl space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-lg font-bold tracking-tight uppercase">Профили поиска</h1>
        <span className="nums text-[13px] text-black/50">{profiles.length}</span>
        <button type="button" className="btn btn-primary ml-auto" onClick={() => setEditing(EMPTY)}>
          <PlusIcon className="size-4" />
          Новый профиль
        </button>
      </div>

      {editing && <ProfileForm key={editing.id ?? "new"} initial={editing} onDone={() => setEditing(null)} />}

      {isPending ? (
        <Skeleton rows={2} />
      ) : profiles.length === 0 && !editing ? (
        <div className="card p-10 text-center">
          <p className="text-sm font-medium">Профилей пока нет.</p>
          <p className="mt-1 text-[12px] text-black/50">Профиль — это позиция и ключевые слова, по которым парсер собирает анкеты.</p>
        </div>
      ) : (
        <ul className="grid gap-2 md:grid-cols-2">
          {profiles.map((p, i) => (
            <ProfileRow key={p.id} profile={p} index={i} onEdit={() => setEditing(p)} />
          ))}
        </ul>
      )}

      <SourcesTable />
    </div>
  );
}

function ProfileRow({ profile: p, index, onEdit }: { profile: Profile; index: number; onEdit: () => void }) {
  const run = useRunProfile();
  const remove = useDeleteProfile();
  return (
    <li
      className={`enter card flex flex-col p-4 ${p.is_active ? "" : "stripes-soft"}`}
      style={{ animationDelay: `${index * 45}ms` }}
    >
      <div className="flex items-start gap-2">
        <h2 className="min-w-0 flex-1 text-[15px] font-semibold">{p.title}</h2>
        <span
          className={`rounded-md px-2 py-0.5 text-[11px] font-medium ${
            p.is_active ? "bg-black text-white" : "border border-black/50 bg-white text-black/60"
          }`}
        >
          {p.is_active ? "активен" : "выключен"}
        </span>
      </div>
      <p className="mt-1 text-[13px] text-black/70">{p.keywords || "—"}</p>

      <dl className="nums mt-3 grid grid-cols-3 gap-2">
        <Stat label="Источники" value={p.sources.map((s) => SOURCE_LABELS[s]).join(", ")} />
        <Stat label="Интервал" value={`${p.interval_minutes} мин`} />
        <Stat label="Последний запуск" value={formatDate(p.last_run_at)} />
      </dl>

      {run.isPending || run.isSuccess ? (
        <div className="mt-3 h-1.5 overflow-hidden rounded-full border border-black/50" title="Задача поставлена в очередь">
          <div className="stripes h-full w-full" />
        </div>
      ) : null}

      <div className="mt-3 flex flex-wrap gap-1.5">
        <button type="button" className="btn btn-primary" disabled={run.isPending} onClick={() => run.mutate(p.id)}>
          <PlayIcon className="size-3.5" />
          {run.isSuccess ? "В очереди ✓" : "Запустить сейчас"}
        </button>
        <button type="button" className="btn" onClick={onEdit}>
          Изменить
        </button>
        <button
          type="button"
          className="btn-ghost btn ml-auto"
          onClick={() => confirm(`Удалить профиль «${p.title}»? Анкеты останутся.`) && remove.mutate(p.id)}
        >
          Удалить
        </button>
      </div>
    </li>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 rounded-lg bg-black/5 px-2 py-1.5">
      <dt className="text-[10px] tracking-wide text-black/50 uppercase">{label}</dt>
      <dd className="truncate text-[12px] font-semibold" title={value}>
        {value}
      </dd>
    </div>
  );
}

function ProfileForm({ initial, onDone }: { initial: ProfileInput & { id?: number }; onDone: () => void }) {
  const [form, setForm] = useState(initial);
  const save = useSaveProfile();
  const { data: sources = [] } = useSources();

  const toggleSource = (source: Source) =>
    setForm({
      ...form,
      sources: form.sources.includes(source) ? form.sources.filter((s) => s !== source) : [...form.sources, source],
    });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    save.mutate(form, { onSuccess: onDone });
  };

  return (
    <form className="enter card space-y-4 p-5" style={{ animationDuration: "0.25s" }} onSubmit={submit}>
      <h2 className="section-title">{initial.id ? "Изменить профиль" : "Новый профиль"}</h2>
      <div className="grid gap-4 sm:grid-cols-2">
        <label className="block">
          <span className="label">Позиция</span>
          <input
            required
            className="field"
            value={form.title}
            onChange={(e) => setForm({ ...form, title: e.target.value })}
            placeholder="Python-разработчик"
          />
        </label>
        <label className="block">
          <span className="label">Ключевые слова</span>
          <input
            className="field"
            value={form.keywords}
            onChange={(e) => setForm({ ...form, keywords: e.target.value })}
            placeholder="python, fastapi, postgresql"
          />
        </label>
      </div>

      <div className="flex flex-wrap items-end gap-x-6 gap-y-4">
        <div role="group" aria-label="Источники">
          <span className="label">Источники</span>
          <div className="flex flex-wrap gap-1.5">
            {sources.map((s) => (
              <button
                key={s.source}
                type="button"
                className="chip"
                aria-pressed={form.sources.includes(s.source)}
                disabled={!s.enabled}
                title={s.enabled ? undefined : "скоро"}
                onClick={() => toggleSource(s.source)}
              >
                {SOURCE_LABELS[s.source]}
                {!s.enabled && <span className="text-black/50">· скоро</span>}
              </button>
            ))}
          </div>
        </div>
        <label className="block w-32">
          <span className="label">Интервал, мин</span>
          <input
            type="number"
            min={15}
            className="field nums"
            value={form.interval_minutes}
            onChange={(e) => setForm({ ...form, interval_minutes: Number(e.target.value) })}
          />
        </label>
        <div className="pb-2.5">
          <Checkbox checked={form.is_active} onChange={(is_active) => setForm({ ...form, is_active })}>
            Активен
          </Checkbox>
        </div>
      </div>

      {save.error && <ErrorText>{save.error.message}</ErrorText>}
      <div className="flex gap-2">
        <button type="submit" className="btn btn-primary" disabled={save.isPending || form.sources.length === 0}>
          Сохранить
        </button>
        <button type="button" className="btn" onClick={onDone}>
          Отмена
        </button>
      </div>
    </form>
  );
}

const HEALTH: Record<SourceState["health"], { label: string; cls: string }> = {
  ok: { label: "работает", cls: "bg-black text-white" },
  needs_attention: { label: "нужен человек", cls: "stripes-soft border border-black text-black" },
  disabled: { label: "не подключён", cls: "border border-black/30 text-black/40" },
};

/** Состояние площадок и вход в аккаунт работодателя там, где он делается из интерфейса. */
function SourcesTable() {
  const { data: sources = [] } = useSources();
  if (!sources.length) return null;
  return (
    <section className="card overflow-hidden">
      <h2 className="section-title border-b border-black px-4 py-3">Источники</h2>
      <table className="w-full border-collapse text-[13px]">
        <thead className="bg-black/5">
          <tr className="text-left text-[11px] font-semibold tracking-wide text-black/50 uppercase">
            <th className="px-4 py-2">Площадка</th>
            <th className="px-3 py-2">Состояние</th>
            <th className="px-3 py-2 text-right">Последний успех</th>
            <th className="px-4 py-2" aria-label="Действия" />
          </tr>
        </thead>
        <tbody>
          {sources.map((s) => (
            <tr key={s.source} className="border-t border-black/10">
              <td className="px-4 py-2.5 font-medium">{SOURCE_LABELS[s.source]}</td>
              <td className="px-3 py-2.5">
                <span className={`inline-block rounded-md px-2 py-0.5 text-[11px] font-medium ${HEALTH[s.health].cls}`}>
                  {HEALTH[s.health].label}
                </span>
                {s.message && s.health !== "ok" && <span className="ml-2 text-[12px] text-black/50">{s.message}</span>}
              </td>
              <td className="nums px-3 py-2.5 text-right text-black/60">{formatDate(s.last_success_at)}</td>
              <td className="px-4 py-2 text-right">{s.ui_login && <SourceLoginButton source={s.source} />}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
