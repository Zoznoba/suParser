import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { vi } from "vitest";

import type { Candidate, Comment, User } from "../api/types";

export function makeQueryClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
}

/** Рендер с QueryClient и роутером. `path` — шаблон маршрута, `url` — текущий адрес. */
export function renderWithProviders(
  ui: ReactElement,
  { url = "/", path = "*", qc = makeQueryClient() }: { url?: string; path?: string; qc?: QueryClient } = {},
) {
  const result = render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[url]}>
        <Routes>
          <Route path={path} element={ui} />
          <Route path="/login" element={<LocationProbe />} />
        </Routes>
        <LocationProbe hidden />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { ...result, qc };
}

function LocationProbe({ hidden }: { hidden?: boolean }) {
  const location = useLocation();
  return hidden ? (
    <output data-testid="location" hidden>
      {location.pathname + location.search}
    </output>
  ) : (
    <div>login page</div>
  );
}

type Handler = (body: unknown, url: URL) => unknown;

/**
 * Подменяет fetch: ключ — "METHOD /path", значение — JSON-ответ или функция.
 * Ответ `{ status, body }` через `reply()` — для ошибок. Возвращает mock для проверки вызовов.
 */
export function mockApi(routes: Record<string, unknown>) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    const key = `${init?.method ?? "GET"} ${url.pathname}`;
    if (!(key in routes)) throw new Error(`unexpected request: ${key}`);
    const route = routes[key];
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    const value = typeof route === "function" ? (route as Handler)(body, url) : route;
    if (value instanceof Reply) return new Response(JSON.stringify(value.body), { status: value.status });
    return value === undefined ? new Response(null, { status: 204 }) : Response.json(value);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

class Reply {
  constructor(
    public status: number,
    public body: unknown,
  ) {}
}

export const reply = (status: number, body: unknown) => new Reply(status, body);

export const anna: User = { id: 1, login: "anna", name: "Анна" };

export function makeCandidate(patch: Partial<Candidate> = {}): Candidate {
  return {
    id: 1,
    full_name: "Мария Иванова",
    title: "Python-разработчик",
    city: "Москва",
    age: 29,
    birth_date: null,
    salary: 250000,
    currency: "rub",
    photo_url: null,
    status: "new",
    status_changed_by: null,
    status_changed_at: null,
    stale_since: null,
    created_at: "2026-09-30T10:00:00Z",
    updated_at: "2026-09-30T10:00:00Z",
    sources: [
      {
        source: "superjob",
        external_id: "123",
        url: "https://superjob.ru/resume/123",
        published_at: null,
        fetched_at: "2026-09-30T10:00:00Z",
        last_seen_at: "2026-09-30T10:00:00Z",
        gone_at: null,
        imported_by: null,
      },
    ],
    comments_count: 0,
    ...patch,
  };
}

export function makeComment(patch: Partial<Comment> = {}): Comment {
  return {
    id: 1,
    candidate_id: 1,
    author: anna,
    text: "Пишу в тг",
    created_at: "2026-09-30T10:05:00Z",
    edited_at: null,
    ...patch,
  };
}
