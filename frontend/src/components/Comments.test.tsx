import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { anna, makeComment, mockApi, renderWithProviders } from "../test/utils";
import { Comments } from "./Comments";

describe("Comments", () => {
  it("shows the thread with author and text", async () => {
    mockApi({
      "GET /api/candidates/1/comments": [
        makeComment({ id: 1, text: "Пишу в тг" }),
        makeComment({ id: 2, author: null, text: "Старый коммент" }),
      ],
    });
    renderWithProviders(<Comments candidateId={1} />);

    expect(await screen.findByText("Пишу в тг")).toBeInTheDocument();
    expect(screen.getByText("Анна")).toBeInTheDocument();
    expect(screen.getByText("удалён")).toBeInTheDocument();
  });

  it("shows placeholder for empty thread", async () => {
    mockApi({ "GET /api/candidates/1/comments": [] });
    renderWithProviders(<Comments candidateId={1} />);
    expect(await screen.findByText("Пока нет комментариев")).toBeInTheDocument();
  });

  it("posts a comment and clears the input", async () => {
    const fetchMock = mockApi({
      "GET /api/candidates/1/comments": [],
      "POST /api/candidates/1/comments": makeComment(),
    });
    renderWithProviders(<Comments candidateId={1} />);
    const input = screen.getByPlaceholderText(/Комментарий/);
    const send = screen.getByRole("button", { name: "Отправить" });

    expect(send).toBeDisabled();
    await userEvent.type(input, "Беру кандидата");
    await userEvent.click(send);

    await waitFor(() => expect(input).toHaveValue(""));
    const post = fetchMock.mock.calls.find(([, init]) => init?.method === "POST")!;
    expect(JSON.parse(String(post[1]!.body))).toEqual({ text: "Беру кандидата" });
  });

  it("submits with Ctrl+Enter", async () => {
    const fetchMock = mockApi({
      "GET /api/candidates/1/comments": [],
      "POST /api/candidates/1/comments": makeComment(),
    });
    renderWithProviders(<Comments candidateId={1} />);

    await userEvent.type(screen.getByPlaceholderText(/Комментарий/), "Ок{Control>}{Enter}{/Control}");

    await waitFor(() => expect(fetchMock.mock.calls.some(([, init]) => init?.method === "POST")).toBe(true));
  });

  it("author edits own comment; colleague's comments have no actions", async () => {
    const oleg = { id: 2, login: "oleg", name: "Олег" };
    const fetchMock = mockApi({
      "GET /api/auth/me": anna,
      "GET /api/candidates/1/comments": [
        makeComment({ id: 1, text: "Звоню завтра" }),
        makeComment({ id: 2, author: oleg, text: "Ок" }),
      ],
      "PATCH /api/candidates/1/comments/1": makeComment({ id: 1, text: "Звоню в пн", edited_at: "2026-09-30T11:00:00Z" }),
    });
    renderWithProviders(<Comments candidateId={1} />);
    await screen.findByText("Звоню завтра");

    expect(await screen.findAllByRole("button", { name: "Изменить комментарий" })).toHaveLength(1);
    await userEvent.click(screen.getByRole("button", { name: "Изменить комментарий" }));
    const field = screen.getByRole("textbox", { name: "Текст комментария" });
    await userEvent.clear(field);
    await userEvent.type(field, "Звоню в пн");
    await userEvent.click(screen.getByRole("button", { name: "Сохранить" }));

    await waitFor(() => expect(screen.queryByRole("textbox", { name: "Текст комментария" })).not.toBeInTheDocument());
    const patch = fetchMock.mock.calls.find(([, init]) => init?.method === "PATCH")!;
    expect(JSON.parse(String(patch[1]!.body))).toEqual({ text: "Звоню в пн" });
  });

  it("delete asks for confirmation", async () => {
    const fetchMock = mockApi({
      "GET /api/auth/me": anna,
      "GET /api/candidates/1/comments": [makeComment({ id: 1 })],
      "DELETE /api/candidates/1/comments/1": undefined,
    });
    renderWithProviders(<Comments candidateId={1} />);

    await userEvent.click(await screen.findByRole("button", { name: "Удалить комментарий" }));
    expect(screen.getByText("Удалить для всех?")).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === "DELETE")).toBe(false);
    await userEvent.click(screen.getByRole("button", { name: "Удалить" }));

    await waitFor(() => expect(fetchMock.mock.calls.some(([, init]) => init?.method === "DELETE")).toBe(true));
  });

  it("marks edited comments", async () => {
    mockApi({
      "GET /api/auth/me": anna,
      "GET /api/candidates/1/comments": [makeComment({ edited_at: "2026-09-30T11:00:00Z" })],
    });
    renderWithProviders(<Comments candidateId={1} />);
    expect(await screen.findByText("изменён")).toBeInTheDocument();
  });
});
