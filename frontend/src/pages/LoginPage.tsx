import { type FormEvent, useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router";

import { useLogin, useMe } from "../api/hooks";
import { LogoIcon } from "../components/icons";
import { ErrorText } from "../components/ui";

export function LoginPage() {
  const { data: me } = useMe();
  const login = useLogin();
  const navigate = useNavigate();
  const from = (useLocation().state as { from?: string } | null)?.from ?? "/";
  const [form, setForm] = useState({ login: "", password: "" });

  if (me) return <Navigate to={from} replace />;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    login.mutate(form, { onSuccess: () => navigate(from, { replace: true }) });
  };

  return (
    <div className="grid min-h-screen place-items-center px-4">
      <form className="enter card w-full max-w-sm space-y-4 p-6" onSubmit={submit}>
        <div className="flex items-center gap-3">
          <div className="grid size-10 place-items-center rounded-xl bg-black text-white">
            <LogoIcon className="size-5" />
          </div>
          <div>
            <h1 className="text-[15px] font-bold tracking-tight uppercase">HR-парсер</h1>
            <p className="text-[12px] text-black/50">Вход для команды</p>
          </div>
        </div>
        <label className="block">
          <span className="label">Логин</span>
          <input
            autoFocus
            className="field"
            autoComplete="username"
            value={form.login}
            onChange={(e) => setForm({ ...form, login: e.target.value })}
          />
        </label>
        <label className="block">
          <span className="label">Пароль</span>
          <input
            type="password"
            className="field"
            autoComplete="current-password"
            value={form.password}
            onChange={(e) => setForm({ ...form, password: e.target.value })}
          />
        </label>
        {login.error && <ErrorText>{login.error.message}</ErrorText>}
        <button type="submit" className="btn btn-primary w-full py-2.5" disabled={login.isPending}>
          Войти
        </button>
      </form>
    </div>
  );
}
