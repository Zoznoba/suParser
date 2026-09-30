import { describe, expect, it, vi } from "vitest";

import { mockApi, reply } from "../test/utils";
import { ApiError, api, qs } from "./client";

describe("qs", () => {
  it("drops empty values and keeps zero", () => {
    expect(qs({ status: "new", q: "", profile_id: undefined, source: null, offset: 0 })).toBe("?status=new&offset=0");
  });

  it("returns empty string when nothing to send", () => {
    expect(qs({ q: "" })).toBe("");
  });

  it("encodes values", () => {
    expect(qs({ q: "C++ & Go" })).toBe("?q=C%2B%2B+%26+Go");
  });
});

describe("api", () => {
  it("sends JSON body with same-origin credentials", async () => {
    const fetchMock = mockApi({ "POST /api/things": (body: unknown) => ({ echo: body }) });

    expect(await api("/things", { method: "POST", body: { a: 1 } })).toEqual({ echo: { a: 1 } });
    const init = fetchMock.mock.calls[0][1]!;
    expect(init.credentials).toBe("same-origin");
    expect(init.headers).toEqual({ "Content-Type": "application/json" });
  });

  it("returns undefined for 204", async () => {
    mockApi({ "DELETE /api/things/1": undefined });
    expect(await api("/things/1", { method: "DELETE" })).toBeUndefined();
  });

  it("throws ApiError with backend detail", async () => {
    mockApi({ "GET /api/me": reply(401, { detail: "Не авторизован" }) });

    const error = await api("/me").catch((e) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 401, message: "Не авторизован" });
  });

  it("falls back to status text for validation errors and non-JSON bodies", async () => {
    vi.stubGlobal("fetch", async () => new Response("<html>", { status: 502, statusText: "Bad Gateway" }));
    await expect(api("/x")).rejects.toMatchObject({ status: 502, message: "Bad Gateway" });
  });
});
