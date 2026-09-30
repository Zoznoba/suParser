import { useEffect } from "react";

import { useSetStatus } from "../api/hooks";
import type { Candidate } from "../api/types";
import { STATUSES, STATUS_LABELS } from "../lib/format";

/**
 * Смена статуса в один клик. Кто и когда менял — видно всем, чтобы двое не писали одному кандидату.
 * С запросом уходит статус, который человек видел: если коллега успел сменить его раньше, сервер отвечает 409 —
 * показываем, кто и на что сменил, а карточка обновляется до свежего статуса.
 */
export function StatusPicker({ candidate }: { candidate: Candidate }) {
  const setStatus = useSetStatus();
  const { error, reset } = setStatus;
  useEffect(() => {
    if (!error) return;
    const id = setTimeout(reset, 6000);
    return () => clearTimeout(id);
  }, [error, reset]);
  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
      <div className="flex flex-wrap gap-1" role="group" aria-label="Статус">
        {STATUSES.filter((s) => s !== "new").map((status) => (
          <button
            key={status}
            type="button"
            className="chip px-2.5 py-1"
            aria-pressed={candidate.status === status}
            disabled={setStatus.isPending}
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              setStatus.mutate({
                id: candidate.id,
                status: candidate.status === status ? "new" : status,
                expected: candidate.status,
              });
            }}
          >
            {STATUS_LABELS[status]}
          </button>
        ))}
      </div>
      {error && (
        <span role="alert" className="text-[12px] font-medium">
          {error.message}
        </span>
      )}
    </div>
  );
}
