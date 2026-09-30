import { type FormEvent, useEffect, useState } from "react";
import { useNavigate } from "react-router";

import { useImportResult, useImportResume } from "../api/hooks";
import { CloseIcon, LinkIcon } from "./icons";

/**
 * Ручной импорт резюме hh по ссылке — ТЗ: резервный вариант, если аккаунт работодателя на hh заблокируют.
 * Резюме открывает браузерный воркер без входа (без ФИО и контактов), итог приходит WS-событием import.finished.
 */
export function ImportByLink() {
  const [open, setOpen] = useState(false);
  const [url, setUrl] = useState("");
  const [requestId, setRequestId] = useState<string>();
  const start = useImportResume();
  const { data: result } = useImportResult(requestId);
  const navigate = useNavigate();

  const waiting = start.isPending || (requestId !== undefined && !result);
  const error = start.error?.message ?? result?.error;

  useEffect(() => {
    if (result?.candidate_id) navigate(`/candidates/${result.candidate_id}`);
  }, [result, navigate]);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!url.trim()) return;
    setRequestId(undefined);
    start.mutate(url.trim(), {
      onSuccess: (r) => (r.candidate_id ? navigate(`/candidates/${r.candidate_id}`) : setRequestId(r.request_id)),
    });
  };

  if (!open) {
    return (
      <button type="button" className="btn" onClick={() => setOpen(true)} title="Добавить резюме hh.ru по ссылке">
        <LinkIcon className="size-4" />
        <span className="hidden sm:inline">По ссылке</span>
      </button>
    );
  }
  return (
    <form onSubmit={submit} className="enter card w-full space-y-2 p-3" style={{ animationDuration: "0.2s" }}>
      <div className="flex items-center gap-2">
        <input
          type="url"
          className="field flex-1"
          placeholder="https://hh.ru/resume/…"
          aria-label="Ссылка на резюме hh.ru"
          value={url}
          autoFocus
          disabled={waiting}
          onChange={(e) => setUrl(e.target.value)}
          onKeyDown={(e) => e.key === "Escape" && setOpen(false)}
        />
        <button type="submit" className="btn btn-primary" disabled={waiting || !url.trim()}>
          {waiting ? "Открываем…" : "Добавить"}
        </button>
        <button type="button" aria-label="Закрыть" className="btn-ghost btn p-2" onClick={() => setOpen(false)}>
          <CloseIcon className="size-4" />
        </button>
      </div>
      {error ? (
        <p role="alert" className="text-[12px] font-medium">
          {error}
        </p>
      ) : (
        <p className="text-[12px] text-black/50">
          {waiting
            ? "Браузер открывает резюме на hh в бережном темпе — обычно до минуты."
            : "Если аккаунт работодателя на hh заблокирован: резюме откроется без входа — без ФИО и контактов."}
        </p>
      )}
    </form>
  );
}
