// Зеркало схем бэкенда (backend/app/schemas). При росте API можно генерировать из /openapi.json.

export type CandidateStatus = "new" | "interesting" | "rejected" | "contacted" | "in_progress";
export type Source = "superjob" | "hh" | "linkedin";
export type SourceHealth = "ok" | "needs_attention" | "disabled";

export interface User {
  id: number;
  login: string;
  name: string;
}

export interface CandidateSource {
  source: Source;
  external_id: string;
  url: string | null;
  published_at: string | null;
  fetched_at: string;
  /** последний раз попадалось в поиске */
  last_seen_at: string;
  /** площадка ответила 404 — удалено или скрыто */
  gone_at: string | null;
  /** добавлено вручную по ссылке */
  imported_by: User | null;
}

export interface Candidate {
  id: number;
  full_name: string | null;
  title: string | null;
  city: string | null;
  age: number | null;
  birth_date: string | null;
  salary: number | null;
  currency: string | null;
  photo_url: string | null;
  status: CandidateStatus;
  status_changed_by: User | null;
  status_changed_at: string | null;
  /** с какого момента анкета неактуальна (все резюме сняты или давно не попадались в поиске) */
  stale_since: string | null;
  created_at: string;
  updated_at: string;
  sources: CandidateSource[];
  comments_count: number;
}

export interface WorkItem {
  company: string | null;
  position: string | null;
  period: string | null;
  description: string | null;
}

export interface Resume {
  about: string | null;
  experience: WorkItem[];
  education: string[];
  skills: string[];
}

export interface CandidateDetail extends Candidate {
  resume: Partial<Resume>;
}

export interface Duplicate {
  candidate: Candidate;
  reasons: string[];
  sure: boolean;
}

export interface CandidatePage {
  items: Candidate[];
  total: number;
}

export interface Comment {
  id: number;
  candidate_id: number;
  author: User | null;
  text: string;
  created_at: string;
  edited_at: string | null;
}

export interface ProfileInput {
  title: string;
  keywords: string;
  sources: Source[];
  interval_minutes: number;
  is_active: boolean;
}

export interface Profile extends ProfileInput {
  id: number;
  last_run_at: string | null;
  created_at: string;
}

export interface SourceState {
  source: Source;
  enabled: boolean;
  /** можно войти в аккаунт площадки из интерфейса */
  ui_login: boolean;
  health: SourceHealth;
  message: string | null;
  last_success_at: string | null;
}

export type LoginStatus = "queued" | "running" | "need_input" | "done" | "failed" | "cancelled";
export type LoginStep = "login" | "code" | "captcha";

/** Вход в площадку из интерфейса: браузер в воркере, человек отвечает на шаги по скриншотам. */
export interface LoginState {
  source: Source;
  status: LoginStatus;
  step: LoginStep | null;
  prompt: string | null;
  error: string | null;
  screenshot: string | null;
  started_by: string | null;
  updated_at: string;
}

export interface LoginInput {
  login?: string;
  password?: string;
  value?: string;
}

export type Freshness = "actual" | "stale" | "all";

export interface CandidateFilters {
  status?: CandidateStatus;
  profile_id?: number;
  source?: Source;
  q?: string;
  /** по умолчанию (не задано) — только актуальные */
  freshness?: Freshness;
  offset?: number;
  limit?: number;
}

/** Кто сейчас смотрит анкету (карточку или тред в ленте). */
export interface Viewers {
  candidate_id: number;
  viewers: User[];
}

export interface ImportStarted {
  request_id: string;
  /** резюме уже есть в базе — карточка сразу, без ожидания */
  candidate_id: number | null;
}

export interface ImportResult {
  request_id: string;
  user_id: number;
  url: string;
  candidate_id: number | null;
  error: string | null;
}

export type RealtimeEvent =
  | { type: "candidate.updated"; data: Candidate }
  | { type: "candidates.created"; data: { ids: number[]; profile_id: number | null } }
  | { type: "candidate.merged"; data: { id: number; into: number } }
  | { type: "candidates.stale"; data: { stale: number[]; fresh: number[] } }
  | { type: "comment.created"; data: Comment }
  | { type: "comment.updated"; data: Comment }
  | { type: "comment.deleted"; data: { id: number; candidate_id: number } }
  | { type: "presence.updated"; data: Viewers }
  | { type: "import.finished"; data: ImportResult }
  | { type: "source.updated"; data: SourceState }
  | { type: "source.login"; data: LoginState };
