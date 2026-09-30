import { useMe, usePresence } from "../api/hooks";
import { EyeIcon } from "./icons";

/**
 * Кто из коллег сейчас открыл анкету (карточку или тред) — ТЗ: «чтобы двое не писали одному кандидату».
 * Себя не показываем. `compact` — строка ленты, иначе — плашка в карточке.
 */
export function Viewers({ candidateId, compact = false }: { candidateId: number; compact?: boolean }) {
  const { data: me } = useMe();
  const { data: presence } = usePresence();
  const others = (presence?.[candidateId] ?? []).filter((u) => u.id !== me?.id);
  if (!others.length) return null;
  const names = others.map((u) => u.name).join(", ");

  if (compact) {
    return (
      <span className="flex items-center gap-1 text-[12px] font-medium" title={`Сейчас открыли: ${names}`}>
        <EyeIcon className="size-3.5 animate-pulse" />
        <span className="max-w-[160px] truncate">{names}</span>
      </span>
    );
  }
  return (
    <p role="status" className="stripes-soft flex items-center gap-2 rounded-xl border border-black px-3 py-2 text-[13px]">
      <EyeIcon className="size-4 shrink-0 animate-pulse" />
      <span>
        Сейчас {others.length > 1 ? "смотрят" : "смотрит"}: <strong className="font-semibold">{names}</strong> — договоритесь,
        кто пишет кандидату
      </span>
    </p>
  );
}
