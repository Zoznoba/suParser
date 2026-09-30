import { type FormEvent, useEffect, useId, useState } from "react";

import { isLoginActive, useCancelLogin, useLoginInput, useSourceLogin, useStartLogin } from "../api/hooks";
import type { LoginState, Source } from "../api/types";
import { SOURCE_LABELS } from "../lib/format";
import { CloseIcon } from "./icons";
import { ErrorText } from "./ui";

/** Кнопка «Войти» у площадки: запускает (или подхватывает уже идущий) вход и открывает окно с шагами. */
export function SourceLoginButton({ source, className = "btn py-1.5" }: { source: Source; className?: string }) {
  const [open, setOpen] = useState(false);
  const start = useStartLogin(source);
  const { data: state } = useSourceLogin(source);
  const active = isLoginActive(state);
  return (
    <>
      <button
        type="button"
        className={className}
        disabled={start.isPending}
        onClick={() => (active ? setOpen(true) : start.mutate(undefined, { onSuccess: () => setOpen(true) }))}
      >
        {active ? "Вход идёт…" : "Войти"}
      </button>
      {open && <SourceLoginDialog source={source} onClose={() => setOpen(false)} />}
    </>
  );
}

export function SourceLoginDialog({ source, onClose }: { source: Source; onClose: () => void }) {
  const titleId = useId();
  const { data: state } = useSourceLogin(source);
  const start = useStartLogin(source);
  const cancel = useCancelLogin(source);
  const active = isLoginActive(state);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 grid place-items-center overflow-y-auto p-4">
      {/* закрытие окна не отменяет вход: его можно открыть снова кнопкой «Вход идёт…» */}
      <button
        type="button"
        aria-label="Закрыть"
        className="enter fixed inset-0 cursor-default bg-black/50 backdrop-blur-sm"
        style={{ animationDuration: "0.2s" }}
        onClick={onClose}
      />
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="enter card relative w-full max-w-lg p-5"
        style={{ animationDuration: "0.2s" }}
      >
        <div className="mb-4 flex items-center gap-2">
          <h2 id={titleId} className="section-title flex-1">
            Вход в {SOURCE_LABELS[source]}
          </h2>
          <button type="button" aria-label="Закрыть" className="btn btn-ghost p-2" onClick={onClose}>
            <CloseIcon className="size-4" />
          </button>
        </div>

        {!state ? (
          <Waiting text="Загрузка…" />
        ) : (
          <LoginBody key={state.updated_at} source={source} state={state} />
        )}

        <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-black/10 pt-3">
          {state?.started_by && <span className="text-[12px] text-black/50">Вход начат: {state.started_by}</span>}
          <span className="ml-auto" />
          {active ? (
            <button type="button" className="btn" disabled={cancel.isPending} onClick={() => cancel.mutate()}>
              Отменить вход
            </button>
          ) : state?.status === "done" ? (
            <button type="button" className="btn btn-primary" onClick={onClose}>
              Готово
            </button>
          ) : (
            <button type="button" className="btn btn-primary" disabled={start.isPending} onClick={() => start.mutate()}>
              Начать заново
            </button>
          )}
        </div>
      </section>
    </div>
  );
}

function LoginBody({ source, state }: { source: Source; state: LoginState }) {
  switch (state.status) {
    case "queued":
      return <Waiting text="Ждём браузер — он может быть занят сбором анкет, это займёт до нескольких минут." />;
    case "running":
      return <Waiting text={state.prompt ?? "Браузер работает…"} />;
    case "need_input":
      return <LoginStepForm source={source} state={state} />;
    case "done":
      return (
        <p className="text-[13px]">
          {state.prompt ?? "Вход выполнен."} Сбор с {SOURCE_LABELS[source]} продолжится по расписанию.
        </p>
      );
    case "cancelled":
      return <p className="text-[13px] text-black/60">Вход отменён.</p>;
    case "failed":
      return (
        <div className="space-y-3">
          <ErrorText>Не удалось войти: {state.error}</ErrorText>
          <Screenshot src={state.screenshot} />
        </div>
      );
  }
}

function LoginStepForm({ source, state }: { source: Source; state: LoginState }) {
  const send = useLoginInput(source);
  const [login, setLogin] = useState("");
  const [password, setPassword] = useState("");
  const [value, setValue] = useState("");
  // после отправки ждём, пока воркер заберёт ответ и пришлёт новое состояние (форма перемонтируется по key)
  const sent = send.isPending || send.isSuccess;
  const isLogin = state.step === "login";
  const ready = isLogin ? login.trim() !== "" : value.trim() !== "";

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (ready) send.mutate(isLogin ? { login: login.trim(), password: password || undefined } : { value: value.trim() });
  };

  return (
    <form className="space-y-3" onSubmit={submit}>
      <Screenshot src={state.screenshot} />
      {state.error && <ErrorText>{state.error}</ErrorText>}
      {send.error && <ErrorText>{send.error.message}</ErrorText>}
      {isLogin ? (
        <>
          <label className="block">
            <span className="label">{state.prompt}</span>
            <input
              className="field"
              autoFocus
              autoComplete="username"
              value={login}
              onChange={(e) => setLogin(e.target.value)}
            />
          </label>
          <label className="block">
            <span className="label">Пароль (необязательно)</span>
            <input
              className="field"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            <span className="mt-1 block text-[12px] text-black/50">
              Без пароля {SOURCE_LABELS[source]} пришлёт код в SMS или на почту — его спросим следующим шагом.
            </span>
          </label>
        </>
      ) : (
        <label className="block">
          <span className="label">{state.prompt}</span>
          <input
            className="field"
            autoFocus
            autoComplete={state.step === "code" ? "one-time-code" : "off"}
            inputMode={state.step === "code" ? "numeric" : undefined}
            value={value}
            onChange={(e) => setValue(e.target.value)}
          />
        </label>
      )}
      <button type="submit" className="btn btn-primary w-full" disabled={!ready || sent}>
        {sent ? "Отправлено, ждём ответ площадки…" : "Отправить"}
      </button>
    </form>
  );
}

function Screenshot({ src }: { src: string | null }) {
  if (!src) return null;
  return (
    <img
      src={src}
      alt="Что сейчас видит браузер"
      className="max-h-72 w-full rounded-xl border border-black/50 bg-white object-contain"
    />
  );
}

function Waiting({ text }: { text: string }) {
  return (
    <div className="flex items-center gap-3 py-2" role="status">
      <span className="size-5 shrink-0 animate-spin rounded-full border-[3px] border-black/30 border-t-black" />
      <p className="text-[13px] text-black/70">{text}</p>
    </div>
  );
}
