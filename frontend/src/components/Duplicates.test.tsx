import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { makeCandidate, mockApi, renderWithProviders } from "../test/utils";
import { Duplicates } from "./Duplicates";

const twin = makeCandidate({ id: 2, full_name: "Мария Иванова Петровна", status: "interesting" });

describe("Duplicates", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("renders nothing when there are no duplicates", async () => {
    const fetchMock = mockApi({ "GET /api/candidates/1/duplicates": [] });
    renderWithProviders(<Duplicates candidateId={1} />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(screen.queryByRole("region", { name: "Возможные дубли" })).not.toBeInTheDocument();
  });

  it("shows reasons and merges after confirmation", async () => {
    const fetchMock = mockApi({
      "GET /api/candidates/1/duplicates": [{ candidate: twin, reasons: ["ФИО", "город"], sure: false }],
      "POST /api/candidates/1/merge": { ...makeCandidate(), resume: {} },
    });
    vi.stubGlobal("confirm", vi.fn(() => true));
    renderWithProviders(<Duplicates candidateId={1} />);

    expect(await screen.findByText("Мария Иванова Петровна")).toBeInTheDocument();
    expect(screen.getByText("совпало: ФИО, город")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Объединить" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/candidates/1/merge"),
        expect.objectContaining({ method: "POST", body: JSON.stringify({ other_id: 2 }) }),
      ),
    );
  });
});
