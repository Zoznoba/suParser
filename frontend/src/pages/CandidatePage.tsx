import type { ReactNode } from "react";
import { Link, useParams } from "react-router";

import { useCandidate } from "../api/hooks";
import type { CandidateDetail } from "../api/types";
import { Comments } from "../components/Comments";
import { Duplicates } from "../components/Duplicates";
import { BackIcon } from "../components/icons";
import { SourceBadges } from "../components/SourceBadges";
import { StatusPicker } from "../components/StatusPicker";
import { Avatar, ErrorText, Skeleton } from "../components/ui";
import { Viewers } from "../components/Viewers";
import { SOURCE_LABELS, STATUS_LABELS, formatDate, formatSalary } from "../lib/format";
import { useViewing } from "../realtime/viewing";

export function CandidatePage() {
  const id = Number(useParams().id);
  const { data: c, isPending, error } = useCandidate(id);
  useViewing(c ? id : null); // коллеги увидят «сейчас смотрит: …»

  if (isPending) return <Skeleton rows={3} height={160} />;
  if (error || !c) return <ErrorText>Анкета не найдена</ErrorText>;

  const { about, experience = [], education = [], skills = [] } = c.resume;
  const salary = formatSalary(c.salary, c.currency);

  return (
    <article className="space-y-2">
      <Link to=".." className="btn-ghost btn -ml-2 px-2 py-1">
        <BackIcon className="size-4" />К ленте
      </Link>

      <header className="enter card flex flex-wrap items-start gap-4 p-5">
        <Avatar name={c.full_name} src={c.photo_url} size={72} />
        <div className="min-w-0 flex-1">
          <h1 className="text-2xl font-bold tracking-tight">{c.full_name ?? "Без имени"}</h1>
          <div className="text-[15px] text-black/70">{c.title}</div>
          <div className="nums mt-1 text-[13px] text-black/50">
            {[c.city, c.age && `${c.age} лет`].filter(Boolean).join(" · ")}
          </div>
          <div className="mt-2">
            <SourceBadges sources={c.sources} links />
          </div>
        </div>
        {salary && (
          <div className="text-right">
            <div className="text-[12px] font-medium text-black/50">Зарплата</div>
            <div className="nums text-2xl font-semibold tracking-tight">{salary}</div>
          </div>
        )}
      </header>

      <StaleNotice candidate={c} />

      <section className="enter card flex flex-wrap items-center gap-x-4 gap-y-2 p-4" style={{ animationDelay: "60ms" }}>
        <div className="text-[13px]">
          <span className="text-black/50">Статус: </span>
          <strong className="font-semibold">{STATUS_LABELS[c.status]}</strong>
          {c.status_changed_by && (
            <span className="nums text-black/50">
              {" "}
              — {c.status_changed_by.name}, {formatDate(c.status_changed_at)}
            </span>
          )}
        </div>
        <div className="ml-auto">
          <StatusPicker candidate={c} />
        </div>
        <div className="w-full empty:hidden">
          <Viewers candidateId={c.id} />
        </div>
      </section>

      <Duplicates candidateId={c.id} />

      <div className="grid items-start gap-2 lg:grid-cols-[minmax(0,2fr)_minmax(320px,1fr)]">
        <div className="space-y-2">
          {about && (
            <Block title="О себе" delay={120}>
              <p className="text-[14px] leading-relaxed whitespace-pre-line">{about}</p>
            </Block>
          )}
          {experience.length > 0 && (
            <Block title="Опыт работы" hint={`${experience.length}`} delay={160}>
              <ol className="relative space-y-4 border-l border-black/20 pl-5">
                {experience.map((w, i) => (
                  <li key={i} className="relative">
                    <span className="absolute top-1.5 -left-[25px] size-2.5 rounded-full border-2 border-black bg-white" />
                    <div className="text-[14px]">
                      <strong className="font-semibold">{w.position}</strong>
                      {w.company && <span className="text-black/70"> — {w.company}</span>}
                    </div>
                    {w.period && <div className="nums text-[12px] text-black/50">{w.period}</div>}
                    {w.description && (
                      <p className="mt-1.5 text-[13px] leading-relaxed text-black/80 whitespace-pre-line">{w.description}</p>
                    )}
                  </li>
                ))}
              </ol>
            </Block>
          )}
          {education.length > 0 && (
            <Block title="Образование" delay={200}>
              <ul className="space-y-1.5 text-[14px]">
                {education.map((e, i) => (
                  <li key={i}>{e}</li>
                ))}
              </ul>
            </Block>
          )}
          {skills.length > 0 && (
            <Block title="Навыки и сферы" delay={240}>
              <ul className="flex flex-wrap gap-1.5">
                {skills.map((s) => (
                  <li key={s} className="rounded-full border border-black/50 px-2.5 py-1 text-[12px] font-medium">
                    {s}
                  </li>
                ))}
              </ul>
            </Block>
          )}
          <p className="nums px-1 text-[12px] text-black/50">
            Найдена {formatDate(c.created_at)}, обновлена {formatDate(c.updated_at)}
            {c.sources
              .filter((s) => s.imported_by)
              .map((s) => (
                <span key={s.external_id}>
                  {" "}
                  · {SOURCE_LABELS[s.source]} добавил(а) вручную {s.imported_by!.name}
                </span>
              ))}
          </p>
        </div>

        <div className="lg:sticky lg:top-[82px]">
          <Comments candidateId={c.id} />
        </div>
      </div>
    </article>
  );
}

function Block({ title, hint, delay = 0, children }: { title: string; hint?: string; delay?: number; children: ReactNode }) {
  return (
    <section className="enter card p-5" style={{ animationDelay: `${delay}ms` }}>
      <h2 className="section-title mb-3">
        {title}
        {hint && <span className="nums ml-2 font-normal text-black/40">{hint}</span>}
      </h2>
      {children}
    </section>
  );
}

/** Анкета неактуальна: все её резюме сняты с площадок или давно не попадались в поиске. */
function StaleNotice({ candidate: c }: { candidate: CandidateDetail }) {
  if (!c.stale_since) return null;
  const gone = c.sources.every((s) => s.gone_at);
  const lastSeen = c.sources.map((s) => s.last_seen_at).sort().at(-1) ?? null;
  return (
    <p role="status" className="enter stripes-soft rounded-2xl border border-black/50 px-4 py-3 text-[13px]">
      <strong className="font-semibold">Неактуальна</strong> —{" "}
      {gone
        ? "резюме удалено или скрыто на площадке."
        : `резюме не попадается в поиске с ${formatDate(lastSeen)}.`}{" "}
      Из ленты скрыта, статус и комментарии сохранены. Появится в поиске снова — вернётся в ленту.
    </p>
  );
}
