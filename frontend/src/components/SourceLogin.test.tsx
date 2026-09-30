import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { keys } from "../api/hooks";
import type { LoginState } from "../api/types";
import { handleEvent } from "../realtime/handleEvent";
import { makeQueryClient, mockApi, renderWithProviders } from "../test/utils";
import { SourceLoginButton } from "./SourceLogin";

const SHOT = "data:image/jpeg;base64,AAAA";

function loginState(patch: Partial<LoginState> = {}): LoginState {
  return {
    source: "hh",
    status: "need_input",
    step: "login",
    prompt: "Почта или телефон аккаунта работодателя на hh.ru",
    error: null,
    screenshot: SHOT,
    started_by: "Анна",
    updated_at: "2026-09-30T10:00:00Z",
    ...patch,
  };
}

describe("SourceLoginButton", () => {
  it("starts login and shows the waiting state", async () => {
    let state: LoginState | null = null;
    const fetchMock = mockApi({
      "GET /api/sources/hh/login": () => state,
      "POST /api/sources/hh/login": () =>
        (state = loginState({ status: "queued", step: null, prompt: null, screenshot: null })),
    });
    renderWithProviders(<SourceLoginButton source="hh" />);

    await userEvent.click(await screen.findByRole("button", { name: "Войти" }));

    expect(await screen.findByRole("dialog", { name: "Вход в hh.ru" })).toBeInTheDocument();
    expect(screen.getByText(/Ждём браузер/)).toBeInTheDocument();
    expect(screen.getByText("Вход начат: Анна")).toBeInTheDocument();
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
  });

  it("joins a login already in progress instead of starting a new one", async () => {
    const fetchMock = mockApi({ "GET /api/sources/hh/login": loginState() });
    renderWithProviders(<SourceLoginButton source="hh" />);

    await userEvent.click(await screen.findByRole("button", { name: "Вход идёт…" }));

    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(fetchMock.mock.calls.every(([, init]) => (init?.method ?? "GET") === "GET")).toBe(true);
  });

  it("sends login and optional password, then waits for the site", async () => {
    const sent: unknown[] = [];
    mockApi({
      "GET /api/sources/hh/login": loginState(),
      "POST /api/sources/hh/login/input": (body: unknown) => (sent.push(body), loginState()),
    });
    renderWithProviders(<SourceLoginButton source="hh" />);
    await userEvent.click(await screen.findByRole("button", { name: "Вход идёт…" }));

    expect(screen.getByAltText("Что сейчас видит браузер")).toHaveAttribute("src", SHOT);
    const submit = screen.getByRole("button", { name: "Отправить" });
    expect(submit).toBeDisabled();
    await userEvent.type(screen.getByLabelText(/Почта или телефон/), " hr@example.com ");
    await userEvent.type(screen.getByLabelText(/Пароль/), "secret");
    await userEvent.click(submit);

    await waitFor(() => expect(sent).toEqual([{ login: "hr@example.com", password: "secret" }]));
    expect(await screen.findByRole("button", { name: /Отправлено/ })).toBeDisabled();
  });

  it("shows site error on the code step and sends the code", async () => {
    const sent: unknown[] = [];
    mockApi({
      "GET /api/sources/hh/login": loginState({ step: "code", prompt: "Код из SMS", error: "Неверный код" }),
      "POST /api/sources/hh/login/input": (body: unknown) => (sent.push(body), loginState()),
    });
    renderWithProviders(<SourceLoginButton source="hh" />);
    await userEvent.click(await screen.findByRole("button", { name: "Вход идёт…" }));

    expect(screen.getByText("Неверный код")).toBeInTheDocument();
    expect(screen.queryByLabelText(/Пароль/)).not.toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Код из SMS"), "123456");
    await userEvent.click(screen.getByRole("button", { name: "Отправить" }));

    await waitFor(() => expect(sent).toEqual([{ value: "123456" }]));
  });

  it("cancels a running login", async () => {
    let cancelled = false;
    mockApi({
      "GET /api/sources/hh/login": () => (cancelled ? loginState({ status: "cancelled" }) : loginState()),
      "POST /api/sources/hh/login/cancel": () => ((cancelled = true), loginState({ status: "cancelled" })),
    });
    renderWithProviders(<SourceLoginButton source="hh" />);
    await userEvent.click(await screen.findByRole("button", { name: "Вход идёт…" }));

    await userEvent.click(screen.getByRole("button", { name: "Отменить вход" }));

    expect(await screen.findByText("Вход отменён.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Начать заново" })).toBeInTheDocument();
  });

  it("shows failure with screenshot and restarts", async () => {
    let state = loginState({ status: "failed", error: "не дождались ответа", step: null });
    const qc = makeQueryClient();
    mockApi({
      "GET /api/sources/hh/login": () => state,
      "POST /api/sources/hh/login": () => (state = loginState({ status: "queued", screenshot: null })),
    });
    renderWithProviders(<SourceLoginButton source="hh" />, { qc });
    await userEvent.click(await screen.findByRole("button", { name: "Войти" }));
    expect(await screen.findByText(/Ждём браузер/)).toBeInTheDocument();

    // пока окно открыто, вход падает
    handleEvent(qc, { type: "source.login", data: loginState({ status: "failed", error: "не дождались ответа" }) });

    expect(await screen.findByText("Не удалось войти: не дождались ответа")).toBeInTheDocument();
    expect(screen.getByAltText("Что сейчас видит браузер")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Начать заново" }));
    expect(await screen.findByText(/Ждём браузер/)).toBeInTheDocument();
  });

  it("updates the dialog from the source.login event", async () => {
    const qc = makeQueryClient();
    mockApi({ "GET /api/sources/hh/login": loginState({ status: "running", prompt: "Проверяем…" }) });
    renderWithProviders(<SourceLoginButton source="hh" />, { qc });
    await userEvent.click(await screen.findByRole("button", { name: "Вход идёт…" }));
    expect(await screen.findByText("Проверяем…")).toBeInTheDocument();

    handleEvent(qc, { type: "source.login", data: loginState({ status: "done", prompt: "Вход выполнен, сессия сохранена" }) });

    expect(await screen.findByText(/Вход выполнен, сессия сохранена/)).toBeInTheDocument();
    expect(qc.getQueryData(keys.sourceLogin("hh"))).toMatchObject({ status: "done" });
  });
});
