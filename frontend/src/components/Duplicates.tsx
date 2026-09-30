import { Link } from "react-router";

import { useDuplicates, useMerge } from "../api/hooks";
import { STATUS_LABELS } from "../lib/format";
import { SourceBadges } from "./SourceBadges";
import { Avatar, ErrorText } from "./ui";

/**
 * Похожие карточки: совпало ФИО или дата рождения, но автоматически не склеились.
 * «Объединить» вливает дубль в текущую карточку (резюме, комментарии, профили); дубль удаляется.
 */
export function Duplicates({ candidateId }: { candidateId: number }) {
  const { data: duplicates = [] } = useDuplicates(candidateId);
  const merge = useMerge(candidateId);

  if (duplicates.length === 0) return null;

  const onMerge = (otherId: number, name: string) => {
    if (confirm(`Объединить с карточкой «${name}»? Её резюме и комментарии перейдут сюда, а сама она исчезнет.`)) {
      merge.mutate(otherId);
    }
  };

  return (
    <section className="enter card p-5" style={{ animationDelay: "90ms" }} aria-label="Возможные дубли">
      <h2 className="section-title mb-3">
        Возможно, тот же человек
        <span className="nums ml-2 font-normal text-black/40">{duplicates.length}</span>
      </h2>
      <ul className="space-y-2">
        {duplicates.map(({ candidate: d, reasons }) => {
          const name = d.full_name ?? "Без имени";
          return (
            <li key={d.id} className="flex flex-wrap items-center gap-3 rounded-xl border border-black/15 p-3">
              <Avatar name={d.full_name} src={d.photo_url} size={40} />
              <div className="min-w-0 flex-1">
                <Link to={`/candidates/${d.id}`} className="font-semibold hover:underline">
                  {name}
                </Link>
                <div className="text-[13px] text-black/70">
                  {[d.title, d.city, d.age && `${d.age} лет`, STATUS_LABELS[d.status]].filter(Boolean).join(" · ")}
                </div>
                <div className="mt-1 flex flex-wrap items-center gap-2 text-[12px] text-black/50">
                  <SourceBadges sources={d.sources} links />
                  <span>совпало: {reasons.join(", ")}</span>
                </div>
              </div>
              <button className="btn" disabled={merge.isPending} onClick={() => onMerge(d.id, name)}>
                Объединить
              </button>
            </li>
          );
        })}
      </ul>
      {merge.error && (
        <div className="mt-2">
          <ErrorText>Не удалось объединить: {merge.error.message}</ErrorText>
        </div>
      )}
    </section>
  );
}
