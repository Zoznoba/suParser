import type { ReactNode } from "react";

import { CheckIcon } from "./icons";

export function Spinner({ label = "Загрузка…" }: { label?: string }) {
  return (
    <div className="grid min-h-[40vh] place-items-center" role="status">
      <div className="flex flex-col items-center gap-2">
        <div className="size-8 animate-spin rounded-full border-[3px] border-black/30 border-t-black" />
        <p className="text-sm text-black/50">{label}</p>
      </div>
    </div>
  );
}

/** Карточки-заглушки, пока грузится список. */
export function Skeleton({ rows = 4, height = 112 }: { rows?: number; height?: number }) {
  return (
    <div className="space-y-2" aria-hidden>
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="card animate-pulse p-4" style={{ height }}>
          <div className="mb-3 h-4 w-48 rounded bg-black/10" />
          <div className="mb-2 h-3 w-72 max-w-full rounded bg-black/5" />
          <div className="h-3 w-32 rounded bg-black/5" />
        </div>
      ))}
    </div>
  );
}

/** Квадратный чекбокс-«галочка», сам input спрятан (sr-only) и остаётся доступным. */
export function Checkbox({
  checked,
  onChange,
  disabled,
  children,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
  children: ReactNode;
}) {
  return (
    <label
      className={`flex items-center gap-2 text-[13px] text-black ${disabled ? "cursor-not-allowed opacity-40" : "cursor-pointer"}`}
    >
      <span
        className={`grid size-4 shrink-0 place-items-center rounded-[5px] text-white transition-colors ${
          checked ? "bg-black" : "border border-black/50 bg-white"
        }`}
      >
        {checked && <CheckIcon className="size-3" />}
      </span>
      <input
        type="checkbox"
        className="sr-only"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
      />
      {children}
    </label>
  );
}

export function ErrorText({ children }: { children: ReactNode }) {
  return <p className="stripes-soft rounded-xl border border-black/50 px-3 py-2 text-[13px] font-medium">{children}</p>;
}

/** Первые буквы имени — вместо фото. */
export function Avatar({ name, src, size = 44 }: { name: string | null; src?: string | null; size?: number }) {
  const initials =
    (name ?? "")
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((w) => w[0]?.toUpperCase())
      .join("") || "?";
  return src ? (
    <img src={src} alt="" className="shrink-0 rounded-2xl border border-black/50 object-cover" style={{ width: size, height: size }} />
  ) : (
    <span
      aria-hidden
      className="grid shrink-0 place-items-center rounded-2xl bg-black font-bold text-white"
      style={{ width: size, height: size, fontSize: size * 0.34 }}
    >
      {initials}
    </span>
  );
}
