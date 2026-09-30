import { QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { keys } from "../api/hooks";
import type { CandidateDetail } from "../api/types";
import { makeCandidate, makeQueryClient } from "../test/utils";
import { useRealtime } from "./useRealtime";
import { useViewing } from "./viewing";

class FakeWebSocket {
  static OPEN = 1;
  static instances: FakeWebSocket[] = [];
  readyState = 0;
  sent: string[] = [];
  onopen?: () => void;
  onmessage?: (e: { data: string }) => void;
  onclose?: () => void;

  constructor(public url: string) {
    FakeWebSocket.instances.push(this);
  }
  send(data: string) {
    this.sent.push(data);
  }
  close() {
    this.readyState = 3;
    this.onclose?.();
  }
  // --- управление из теста ---
  open() {
    this.readyState = FakeWebSocket.OPEN;
    this.onopen?.();
  }
  receive(data: unknown) {
    this.onmessage?.({ data: typeof data === "string" ? data : JSON.stringify(data) });
  }
  drop() {
    this.readyState = 3;
    this.onclose?.();
  }
}

const last = () => FakeWebSocket.instances.at(-1)!;

function setup() {
  const qc = makeQueryClient();
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
  const hook = renderHook(() => useRealtime(), { wrapper });
  return { qc, hook };
}

describe("useRealtime", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    FakeWebSocket.instances = [];
    vi.stubGlobal("WebSocket", FakeWebSocket);
  });
  afterEach(() => vi.useRealTimers());

  it("connects to /api/ws on the same host and reports status", () => {
    const { hook } = setup();
    expect(last().url).toBe(`ws://${location.host}/api/ws`);
    expect(hook.result.current).toBe(false);

    act(() => last().open());

    expect(hook.result.current).toBe(true);
  });

  it("applies server events to the query cache", () => {
    const { qc } = setup();
    qc.setQueryData<CandidateDetail>(keys.candidate(1), { ...makeCandidate(), resume: {} });
    act(() => last().open());

    act(() => last().receive({ type: "candidate.updated", data: makeCandidate({ status: "rejected" }) }));

    expect(qc.getQueryData<CandidateDetail>(keys.candidate(1))!.status).toBe("rejected");
  });

  it("sends keepalive pings and ignores pongs", () => {
    setup();
    act(() => last().open());

    act(() => vi.advanceTimersByTime(25_000));
    expect(last().sent).toEqual(["ping"]);
    expect(() => last().receive("pong")).not.toThrow();
  });

  it("reconnects with backoff and refetches everything missed while offline", () => {
    const { qc, hook } = setup();
    qc.setQueryData(keys.candidateList({}), { items: [], total: 0 });
    act(() => last().open());

    act(() => last().drop());
    expect(hook.result.current).toBe(false);
    act(() => vi.advanceTimersByTime(999));
    expect(FakeWebSocket.instances).toHaveLength(1);
    act(() => vi.advanceTimersByTime(1));
    expect(FakeWebSocket.instances).toHaveLength(2);

    act(() => last().drop()); // вторая попытка не удалась → ждём дольше
    act(() => vi.advanceTimersByTime(1999));
    expect(FakeWebSocket.instances).toHaveLength(2);
    act(() => vi.advanceTimersByTime(1));
    expect(FakeWebSocket.instances).toHaveLength(3);

    act(() => last().open());
    expect(hook.result.current).toBe(true);
    expect(qc.getQueryState(keys.candidateList({}))?.isInvalidated).toBe(true);
  });

  it("closes the socket and stops reconnecting on unmount", () => {
    const { hook } = setup();
    act(() => last().open());

    hook.unmount();
    act(() => vi.advanceTimersByTime(60_000));

    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(last().readyState).toBe(3);
  });

  it("tells the server which cards are open, and repeats it after reconnect", () => {
    setup();
    act(() => last().open());
    const view = (ids: number[]) => JSON.stringify({ type: "view", candidate_ids: ids });

    const card = renderHook(({ id }) => useViewing(id), { initialProps: { id: 5 as number | null } });
    const thread = renderHook(() => useViewing(5)); // та же анкета раскрыта ещё и тредом
    const other = renderHook(() => useViewing(2));
    expect(last().sent).toEqual([view([5]), view([5]), view([2, 5])]);

    card.unmount(); // карточку закрыли, тред ещё открыт — 5 остаётся
    expect(last().sent.at(-1)).toBe(view([2, 5]));

    act(() => last().drop());
    act(() => vi.advanceTimersByTime(1000));
    act(() => last().open());
    expect(last().sent).toEqual([view([2, 5])]); // новое соединение сразу знает, что открыто

    thread.unmount();
    other.unmount();
    expect(last().sent.at(-1)).toBe(view([]));
  });
});
