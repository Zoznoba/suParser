import { useEffect } from "react";

/**
 * Какие анкеты открыты в этой вкладке — карточка или тред в ленте. Сервер показывает это коллегам
 * («сейчас смотрит: Анна»), чтобы двое не писали одному кандидату параллельно.
 * Одна анкета может быть открыта в нескольких местах сразу, поэтому считаем ссылки.
 */
const opened = new Map<number, number>();
let sender: ((ids: number[]) => void) | null = null;

const flush = () => sender?.([...opened.keys()].sort((a, b) => a - b));

/** Вызывает useRealtime, когда WebSocket открылся (в том числе после переподключения) и закрылся. */
export function attachViewingSender(send: ((ids: number[]) => void) | null) {
  sender = send;
  if (opened.size) flush();
}

export function useViewing(candidateId: number | null | undefined) {
  useEffect(() => {
    if (candidateId == null) return;
    opened.set(candidateId, (opened.get(candidateId) ?? 0) + 1);
    flush();
    return () => {
      const left = (opened.get(candidateId) ?? 1) - 1;
      if (left) opened.set(candidateId, left);
      else opened.delete(candidateId);
      flush();
    };
  }, [candidateId]);
}
