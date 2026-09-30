import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { makeCandidate, mockApi, renderWithProviders, reply } from "../test/utils";
import { StatusPicker } from "./StatusPicker";

describe("StatusPicker", () => {
  it("shows the four team statuses with the current one pressed", () => {
    renderWithProviders(<StatusPicker candidate={makeCandidate({ status: "contacted" })} />);

    const buttons = screen.getAllByRole("button");
    expect(buttons.map((b) => b.textContent)).toEqual(["интересно", "мимо", "на связи", "в работе"]);
    expect(screen.getByRole("button", { name: "на связи" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "мимо" })).toHaveAttribute("aria-pressed", "false");
  });

  it("changes status in one click", async () => {
    const fetchMock = mockApi({ "PATCH /api/candidates/7/status": {} });
    renderWithProviders(<StatusPicker candidate={makeCandidate({ id: 7 })} />);

    await userEvent.click(screen.getByRole("button", { name: "в работе" }));

    // вместе с новым статусом — тот, что человек видел: если коллега успел сменить, сервер ответит 409
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]!.body))).toEqual({ status: "in_progress", expected: "new" });
  });

  it("clicking the active status resets it to 'new'", async () => {
    const fetchMock = mockApi({ "PATCH /api/candidates/1/status": {} });
    renderWithProviders(<StatusPicker candidate={makeCandidate({ status: "interesting" })} />);

    await userEvent.click(screen.getByRole("button", { name: "интересно" }));

    expect(JSON.parse(String(fetchMock.mock.calls[0][1]!.body))).toEqual({ status: "new", expected: "interesting" });
  });

  it("explains a conflict when a colleague changed the status first", async () => {
    const detail = "Статус уже сменили (Олег): «на связи». Проверьте и выберите заново";
    mockApi({ "PATCH /api/candidates/1/status": reply(409, { detail }) });
    renderWithProviders(<StatusPicker candidate={makeCandidate()} />);

    await userEvent.click(screen.getByRole("button", { name: "в работе" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(detail);
  });
});
