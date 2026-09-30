import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { anna, mockApi, renderWithProviders, reply } from "../test/utils";
import { RequireAuth } from "./RequireAuth";

describe("RequireAuth", () => {
  it("renders the page for a logged-in user", async () => {
    mockApi({ "GET /api/auth/me": anna });
    renderWithProviders(
      <RequireAuth>
        <div>лента</div>
      </RequireAuth>,
    );
    expect(await screen.findByText("лента")).toBeInTheDocument();
  });

  it("redirects anonymous user to /login", async () => {
    mockApi({ "GET /api/auth/me": reply(401, { detail: "Не авторизован" }) });
    renderWithProviders(
      <RequireAuth>
        <div>лента</div>
      </RequireAuth>,
      { url: "/candidates/5" },
    );
    expect(await screen.findByText("login page")).toBeInTheDocument();
    expect(screen.queryByText("лента")).not.toBeInTheDocument();
  });
});
