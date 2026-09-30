import { useResumeSource, useSources } from "../api/hooks";
import { SOURCE_LABELS } from "../lib/format";
import { SourceLoginButton } from "./SourceLogin";

/** Плашка, если источник требует человека: капча, разлогин, ошибка API. */
export function SourceAlerts() {
  const { data } = useSources();
  const resume = useResumeSource();
  const broken = data?.filter((s) => s.enabled && s.health === "needs_attention") ?? [];
  if (!broken.length) return null;
  return (
    <div className="stripes-soft border-b border-black bg-white" role="alert">
      <div className="mx-auto max-w-[1400px] space-y-2 px-4 py-2.5 sm:px-6">
        {broken.map((s) => (
          <div key={s.source} className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-[13px]">
            <span className="rounded-md bg-black px-2 py-0.5 text-[11px] font-bold tracking-wide text-white uppercase">
              {SOURCE_LABELS[s.source]}
            </span>
            <span className="min-w-0 flex-1">{s.message}</span>
            {s.ui_login && <SourceLoginButton source={s.source} className="btn btn-primary py-1.5" />}
            <button type="button" className="btn py-1.5" disabled={resume.isPending} onClick={() => resume.mutate(s.source)}>
              Исправлено, продолжить
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
