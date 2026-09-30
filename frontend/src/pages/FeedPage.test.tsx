import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { keys } from "../api/hooks";
import { anna, makeCandidate, makeComment, mockApi, renderWithProviders, reply } from "../test/utils";
import { FeedPage } from "./FeedPage";

const profiles = [{ id: 3, title: "Python", keywords: "", sources: ["superjob"], interval_minutes: 60, is_active: true }];

function setup(url = "/", extra: Record<string, unknown> = {}) {
  const fetchMock = mockApi({
    "GET /api/profiles": profiles,
    "GET /api/candidates": (_: unknown, u: URL) => ({
      items: [
        makeCandidate({
          id: 1,
          comments_count: 2,
          status: "contacted",
          status_changed_by: anna,
          status_changed_at: "2026-09-30T10:00:00Z",
        }),
        makeCandidate({ id: 2, full_name: null, salary: null }),
      ],
      total: u.searchParams.get("status") ? 1 : 2,
    }),
    ...extra,
  });
  const view = renderWithProviders(<FeedPage />, { url });
  const lastQuery = () => {
    const calls = fetchMock.mock.calls.filter(([u]) => String(u).startsWith("/api/candidates"));
    return new URL(String(calls.at(-1)![0]), "http://x").searchParams;
  };
  return { ...view, lastQuery, fetchMock };
}

describe("FeedPage", () => {
  it("renders candidate cards with source, comments and who changed the status", async () => {
    setup();

    const cards = await screen.findAllByRole("listitem");
    expect(cards).toHaveLength(2);
    const first = within(cards[0]);
    expect(first.getByText("Мария Иванова")).toBeInTheDocument();
    expect(first.getByText("SuperJob")).toBeInTheDocument();
    expect(first.getByRole("button", { name: /Тред · 2/ })).toHaveAttribute("aria-expanded", "false");
    expect(within(cards[1]).getByRole("button", { name: /Начать тред/ })).toBeInTheDocument();
    expect(first.getByText(/^Анна,/)).toBeInTheDocument();
    expect(first.getByRole("link")).toHaveAttribute("href", "/candidates/1");
    expect(within(cards[1]).getByText("Без имени")).toBeInTheDocument();
    expect(screen.getByText("найдено: 2")).toBeInTheDocument();
  });

  it("reads filters from the URL", async () => {
    const { lastQuery } = setup("/?status=contacted&profile=3");
    await screen.findAllByRole("listitem");
    expect(Object.fromEntries(lastQuery())).toEqual({ status: "contacted", profile_id: "3", offset: "0", limit: "50" });
  });

  it("changing a filter updates the URL and the request", async () => {
    const { lastQuery } = setup();
    await screen.findAllByRole("listitem");

    const statusFilter = within(screen.getAllByRole("group", { name: "Фильтр: Статус" })[0]);
    await userEvent.click(statusFilter.getByRole("button", { name: "интересно" }));

    await waitFor(() => expect(lastQuery().get("status")).toBe("interesting"));
    expect(screen.getByTestId("location")).toHaveTextContent("/?status=interesting");
    expect(statusFilter.getByRole("button", { name: "интересно" })).toHaveAttribute("aria-pressed", "true");
  });

  it("search waits for the user to stop typing", async () => {
    const { lastQuery } = setup();
    await screen.findAllByRole("listitem");

    await userEvent.type(screen.getByPlaceholderText("Имя или должность"), "python");

    expect(lastQuery().get("q")).toBeNull();
    await waitFor(() => expect(lastQuery().get("q")).toBe("python"));
    expect(screen.getByTestId("location")).toHaveTextContent("/?q=python");
  });

  it("active filter chips remove one filter or reset all", async () => {
    setup("/?status=contacted&source=superjob&offset=50");
    await screen.findAllByRole("listitem");

    await userEvent.click(screen.getByRole("button", { name: "Убрать фильтр Статус: на связи" }));
    expect(screen.getByTestId("location")).toHaveTextContent(/^\/\?source=superjob$/);

    await userEvent.click(screen.getByRole("button", { name: "Сбросить всё" }));
    expect(screen.getByTestId("location")).toHaveTextContent(/^\/$/);
  });

  it("shows empty state", async () => {
    mockApi({ "GET /api/profiles": [], "GET /api/candidates": { items: [], total: 0 } });
    renderWithProviders(<FeedPage />);
    expect(await screen.findByText(/Анкет пока нет/)).toBeInTheDocument();
  });

  it("opens the comment thread right under the card", async () => {
    setup("/", {
      "GET /api/auth/me": anna,
      "GET /api/candidates/1/comments": [makeComment({ text: "Пишу в тг" })],
    });
    const [first] = await screen.findAllByRole("listitem");

    await userEvent.click(within(first).getByRole("button", { name: /Тред · 2/ }));

    const thread = within(first).getByRole("region", { name: "Тред" });
    expect(await within(thread).findByText("Пишу в тг")).toBeInTheDocument();
    expect(within(first).getByRole("button", { name: /Тред · 2/ })).toHaveAttribute("aria-expanded", "true");
  });

  it("starts a thread from the feed", async () => {
    const { fetchMock } = setup("/", {
      "GET /api/auth/me": anna,
      "GET /api/candidates/2/comments": [],
      "POST /api/candidates/2/comments": makeComment({ candidate_id: 2 }),
    });
    const cards = await screen.findAllByRole("listitem");

    await userEvent.click(within(cards[1]).getByRole("button", { name: /Начать тред/ }));
    expect(await within(cards[1]).findByText(/напишите первым/)).toBeInTheDocument();
    const input = within(cards[1]).getByPlaceholderText(/Комментарий/);
    expect(input).toHaveFocus();

    await userEvent.type(input, "Беру себе{Control>}{Enter}{/Control}");

    await waitFor(() => expect(input).toHaveValue(""));
    const post = fetchMock.mock.calls.find(([, init]) => init?.method === "POST")!;
    expect(String(post[0])).toBe("/api/candidates/2/comments");
  });

  it("shows which colleague has the card open, but not yourself", async () => {
    const oleg = { id: 2, login: "oleg", name: "Олег" };
    setup("/", { "GET /api/auth/me": anna, "GET /api/presence": [{ candidate_id: 1, viewers: [anna, oleg] }] });

    const cards = await screen.findAllByRole("listitem");
    expect(await within(cards[0]).findByTitle("Сейчас открыли: Олег")).toBeInTheDocument();
    expect(within(cards[1]).queryByTitle(/Сейчас открыли/)).not.toBeInTheDocument();
  });

  it("marks stale cards and filters by freshness via URL", async () => {
    const { lastQuery } = setup("/?freshness=stale", {
      "GET /api/candidates": { items: [makeCandidate({ stale_since: "2026-09-28T10:00:00Z" })], total: 1 },
    });

    const [card] = await screen.findAllByRole("listitem");
    expect(within(card).getByText("неактуальна")).toBeInTheDocument();
    expect(lastQuery().get("freshness")).toBe("stale");
    const group = screen.getByRole("group", { name: "Фильтр: Актуальность" });
    expect(within(group).getByRole("button", { name: "неактуальные" })).toHaveAttribute("aria-pressed", "true");

    await userEvent.click(within(group).getByRole("button", { name: "актуальные" }));
    await waitFor(() => expect(lastQuery().has("freshness")).toBe(false)); // актуальные — по умолчанию
  });

  it("imports an hh resume by link and opens the card when the worker is done", async () => {
    const { fetchMock, qc } = setup("/", {
      "POST /api/candidates/import": { request_id: "req-1", candidate_id: null },
    });
    await userEvent.click(await screen.findByRole("button", { name: /По ссылке/ }));
    await userEvent.type(screen.getByRole("textbox", { name: "Ссылка на резюме hh.ru" }), "https://hh.ru/resume/abc");
    await userEvent.click(screen.getByRole("button", { name: "Добавить" }));

    expect(await screen.findByRole("button", { name: "Открываем…" })).toBeDisabled();
    const post = fetchMock.mock.calls.find(([, init]) => init?.method === "POST")!;
    expect(JSON.parse(String(post[1]!.body))).toEqual({ url: "https://hh.ru/resume/abc" });

    // воркер открыл резюме — событие import.finished кладёт итог в кэш
    qc.setQueryData(keys.importResult("req-1"), {
      request_id: "req-1",
      user_id: 1,
      url: "https://hh.ru/resume/abc",
      candidate_id: 42,
      error: null,
    });
    await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("/candidates/42"));
  });

  it("shows import errors", async () => {
    setup("/", {
      "POST /api/candidates/import": reply(422, { detail: "Нужна ссылка на резюме hh.ru: https://hh.ru/resume/…" }),
    });
    await userEvent.click(await screen.findByRole("button", { name: /По ссылке/ }));
    await userEvent.type(screen.getByRole("textbox", { name: "Ссылка на резюме hh.ru" }), "https://superjob.ru/r/1");
    await userEvent.click(screen.getByRole("button", { name: "Добавить" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Нужна ссылка на резюме hh.ru");
  });
});
