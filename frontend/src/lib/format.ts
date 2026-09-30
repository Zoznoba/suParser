import type { CandidateStatus, Source } from "../api/types";

export const STATUS_LABELS: Record<CandidateStatus, string> = {
  new: "новая",
  interesting: "интересно",
  rejected: "мимо",
  contacted: "на связи",
  in_progress: "в работе",
};

export const STATUSES = Object.keys(STATUS_LABELS) as CandidateStatus[];

export const SOURCE_LABELS: Record<Source, string> = {
  superjob: "SuperJob",
  hh: "hh.ru",
  linkedin: "LinkedIn",
};

export const SOURCES = Object.keys(SOURCE_LABELS) as Source[];

const CURRENCY: Record<string, string> = { rub: "₽", usd: "$", eur: "€" };

export function formatSalary(salary: number | null, currency: string | null): string | null {
  if (!salary) return null;
  return `${salary.toLocaleString("ru-RU")} ${CURRENCY[currency ?? "rub"] ?? currency}`;
}

export function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}
