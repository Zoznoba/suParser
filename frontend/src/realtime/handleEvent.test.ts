import { describe, expect, it } from "vitest";

import { keys } from "../api/hooks";
import type { CandidateDetail, Comment, SourceState } from "../api/types";
import { anna, makeCandidate, makeComment, makeQueryClient } from "../test/utils";
import { handleEvent } from "./handleEvent";

const isInvalidated = (qc: ReturnType<typeof makeQueryClient>, key: readonly unknown[]) =>
  qc.getQueryState(key)?.isInvalidated;

describe("handleEvent", () => {
  it("candidate.updated patches open card but keeps its resume, and refreshes lists", () => {
    const qc = makeQueryClient();
    const detail: CandidateDetail = { ...makeCandidate(), resume: { skills: ["Python"] } };
    qc.setQueryData(keys.candidate(1), detail);
    qc.setQueryData(keys.candidateList({ status: "new" }), { items: [detail], total: 1 });

    handleEvent(qc, {
      type: "candidate.updated",
      data: makeCandidate({ status: "contacted", status_changed_by: anna }),
    });

    const updated = qc.getQueryData<CandidateDetail>(keys.candidate(1))!;
    expect(updated.status).toBe("contacted");
    expect(updated.status_changed_by?.name).toBe("Анна");
    expect(updated.resume.skills).toEqual(["Python"]);
    expect(isInvalidated(qc, keys.candidateList({ status: "new" }))).toBe(true);
  });

  it("candidate.updated does not create a card that nobody opened", () => {
    const qc = makeQueryClient();
    handleEvent(qc, { type: "candidate.updated", data: makeCandidate({ id: 5 }) });
    expect(qc.getQueryData(keys.candidate(5))).toBeUndefined();
  });

  it("candidate.merged drops the merged card and refreshes the target", () => {
    const qc = makeQueryClient();
    qc.setQueryData(keys.candidate(2), { ...makeCandidate({ id: 2 }), resume: {} });
    qc.setQueryData(keys.candidate(1), { ...makeCandidate(), resume: {} });
    qc.setQueryData(keys.candidateList({}), { items: [], total: 0 });

    handleEvent(qc, { type: "candidate.merged", data: { id: 2, into: 1 } });

    expect(qc.getQueryData(keys.candidate(2))).toBeUndefined();
    expect(isInvalidated(qc, keys.candidate(1))).toBe(true);
    expect(isInvalidated(qc, keys.candidateList({}))).toBe(true);
  });

  it("candidates.created refreshes the feed", () => {
    const qc = makeQueryClient();
    qc.setQueryData(keys.candidateList({}), { items: [], total: 0 });

    handleEvent(qc, { type: "candidates.created", data: { ids: [1, 2], profile_id: 1 } });

    expect(isInvalidated(qc, keys.candidateList({}))).toBe(true);
  });

  it("comment.created appends to the thread once", () => {
    const qc = makeQueryClient();
    qc.setQueryData<Comment[]>(keys.comments(1), [makeComment({ id: 1 })]);
    const event = { type: "comment.created" as const, data: makeComment({ id: 2, text: "Беру" }) };

    handleEvent(qc, event);
    handleEvent(qc, event); // повтор (например, после реконнекта) не дублирует

    expect(qc.getQueryData<Comment[]>(keys.comments(1))!.map((c) => c.id)).toEqual([1, 2]);
  });

  it("source.updated replaces the source state", () => {
    const qc = makeQueryClient();
    const ok: SourceState = {
      source: "hh",
      enabled: true,
      ui_login: true,
      health: "ok",
      message: null,
      last_success_at: null,
    };
    qc.setQueryData<SourceState[]>(keys.sources, [ok]);

    handleEvent(qc, { type: "source.updated", data: { ...ok, health: "needs_attention", message: "капча" } });

    expect(qc.getQueryData<SourceState[]>(keys.sources)![0]).toMatchObject({ health: "needs_attention" });
  });

  it("comment.updated replaces the text in the open thread", () => {
    const qc = makeQueryClient();
    qc.setQueryData<Comment[]>(keys.comments(1), [makeComment({ id: 1 }), makeComment({ id: 2, text: "Звоню завтра" })]);

    handleEvent(qc, {
      type: "comment.updated",
      data: makeComment({ id: 2, text: "Звоню в пн", edited_at: "2026-09-30T11:00:00Z" }),
    });

    const thread = qc.getQueryData<Comment[]>(keys.comments(1))!;
    expect(thread.map((c) => c.text)).toEqual(["Пишу в тг", "Звоню в пн"]);
    expect(thread[1].edited_at).not.toBeNull();
  });

  it("comment.deleted removes it from the thread and refreshes counters", () => {
    const qc = makeQueryClient();
    qc.setQueryData<Comment[]>(keys.comments(1), [makeComment({ id: 1 }), makeComment({ id: 2 })]);
    qc.setQueryData(keys.candidateList({}), { items: [], total: 0 });

    handleEvent(qc, { type: "comment.deleted", data: { id: 1, candidate_id: 1 } });

    expect(qc.getQueryData<Comment[]>(keys.comments(1))!.map((c) => c.id)).toEqual([2]);
    expect(isInvalidated(qc, keys.candidateList({}))).toBe(true);
  });

  it("candidates.stale refreshes the feed and affected cards", () => {
    const qc = makeQueryClient();
    qc.setQueryData(keys.candidateList({}), { items: [], total: 0 });
    qc.setQueryData(keys.candidate(3), { ...makeCandidate({ id: 3 }), resume: {} });

    handleEvent(qc, { type: "candidates.stale", data: { stale: [3], fresh: [] } });

    expect(isInvalidated(qc, keys.candidateList({}))).toBe(true);
    expect(isInvalidated(qc, keys.candidate(3))).toBe(true);
  });

  it("presence.updated sets and clears viewers of a card", () => {
    const qc = makeQueryClient();
    qc.setQueryData(keys.presence, { 7: [anna] });

    handleEvent(qc, { type: "presence.updated", data: { candidate_id: 1, viewers: [anna] } });
    expect(qc.getQueryData(keys.presence)).toEqual({ 1: [anna], 7: [anna] });

    handleEvent(qc, { type: "presence.updated", data: { candidate_id: 7, viewers: [] } });
    expect(qc.getQueryData(keys.presence)).toEqual({ 1: [anna] });
  });

  it("import.finished is stored by request id", () => {
    const qc = makeQueryClient();
    const result = { request_id: "abc", user_id: 1, url: "https://hh.ru/resume/x", candidate_id: 5, error: null };

    handleEvent(qc, { type: "import.finished", data: result });

    expect(qc.getQueryData(keys.importResult("abc"))).toEqual(result);
  });
});
