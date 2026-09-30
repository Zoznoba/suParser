import { NavLink, Outlet, useLocation, useNavigate } from "react-router";

import { useLogout, useMe } from "../api/hooks";
import { useRealtime } from "../realtime/useRealtime";
import { LogoIcon } from "./icons";
import { SourceAlerts } from "./SourceAlerts";

const navClass = ({ isActive }: { isActive: boolean }) =>
  `rounded-[9px] px-3 py-1.5 text-[13px] font-medium transition-colors ${
    isActive ? "bg-black text-white" : "text-black/60 hover:text-black"
  }`;

export function Layout() {
  const { data: me } = useMe();
  const logout = useLogout();
  const navigate = useNavigate();
  const connected = useRealtime();
  // карточка кандидата — часть ленты
  const inFeed = useLocation().pathname.startsWith("/candidates/");

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-30 border-b border-black bg-canvas/90 backdrop-blur">
        <div className="mx-auto flex max-w-[1400px] items-center gap-3 px-4 py-3 sm:px-6">
          <div className="grid size-9 shrink-0 place-items-center rounded-xl bg-black text-white">
            <LogoIcon className="size-5" />
          </div>
          <span className="hidden text-[15px] font-bold tracking-tight uppercase sm:block">HR-парсер</span>

          <nav className="ml-1 flex rounded-xl border border-black/50 bg-white p-0.5 sm:ml-3">
            <NavLink to="/" end className={({ isActive }) => navClass({ isActive: isActive || inFeed })}>
              Лента
            </NavLink>
            <NavLink to="/profiles" className={navClass}>
              Поиск
            </NavLink>
          </nav>

          <div className="ml-auto flex items-center gap-3">
            <span
              className="flex items-center gap-1.5 text-[12px] font-medium text-black/60"
              title="Синхронизация в реальном времени"
            >
              <span className="relative flex size-2">
                {connected && <span className="absolute inset-0 animate-ping rounded-full bg-black/40" />}
                <span className={`relative size-2 rounded-full ${connected ? "bg-black" : "border border-black"}`} />
              </span>
              <span className="hidden md:inline">{connected ? "онлайн" : "переподключение…"}</span>
            </span>
            <span className="hidden text-[13px] font-medium sm:inline">{me?.name}</span>
            <button
              type="button"
              className="btn"
              onClick={() => logout.mutate(undefined, { onSuccess: () => navigate("/login") })}
            >
              Выйти
            </button>
          </div>
        </div>
      </header>
      <SourceAlerts />
      <main className="mx-auto max-w-[1400px] px-4 py-5 sm:px-6">
        <Outlet />
      </main>
    </div>
  );
}
