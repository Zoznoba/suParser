import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, qs } from "./client";
import type {
  CandidateDetail,
  CandidateFilters,
  CandidatePage,
  CandidateStatus,
  Comment,
  Duplicate,
  ImportResult,
  ImportStarted,
  LoginInput,
  LoginState,
  Profile,
  ProfileInput,
  Source,
  SourceState,
  User,
  Viewers,
} from "./types";

export const keys = {
  me: ["me"] as const,
  candidates: ["candidates"] as const,
  candidateList: (f: CandidateFilters) => ["candidates", f] as const,
  candidate: (id: number) => ["candidate", id] as const,
  comments: (id: number) => ["comments", id] as const,
  duplicates: (id: number) => ["duplicates", id] as const,
  profiles: ["profiles"] as const,
  sources: ["sources"] as const,
  sourceLogin: (source: Source) => ["sources", source, "login"] as const,
  presence: ["presence"] as const,
  importResult: (requestId: string) => ["import", requestId] as const,
};

// --- auth ---

export const useMe = () => useQuery({ queryKey: keys.me, queryFn: () => api<User>("/auth/me"), retry: false });

export function useLogin() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { login: string; password: string }) => api<User>("/auth/login", { method: "POST", body }),
    onSuccess: (user) => qc.setQueryData(keys.me, user),
  });
}

export function useLogout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api<void>("/auth/logout", { method: "POST" }),
    onSuccess: () => qc.clear(),
  });
}

// --- candidates ---

export const useCandidates = (filters: CandidateFilters) =>
  useQuery({
    queryKey: keys.candidateList(filters),
    queryFn: () => api<CandidatePage>(`/candidates${qs(filters)}`),
    placeholderData: keepPreviousData,
  });

export const useCandidate = (id: number) =>
  useQuery({ queryKey: keys.candidate(id), queryFn: () => api<CandidateDetail>(`/candidates/${id}`) });

export function useSetStatus() {
  // список и карточка обновятся из WS-события candidate.updated — у всех HR, включая текущего.
  // expected — статус, который человек видел: если коллега успел сменить, сервер ответит 409
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, status, expected }: { id: number; status: CandidateStatus; expected?: CandidateStatus }) =>
      api(`/candidates/${id}/status`, { method: "PATCH", body: { status, expected } }),
    onError: (_, { id }) => {
      qc.invalidateQueries({ queryKey: keys.candidate(id) });
      qc.invalidateQueries({ queryKey: keys.candidates });
    },
  });
}

/** Ручной импорт резюме hh по ссылке: сервер ставит задачу, итог приходит WS-событием import.finished. */
export const useImportResume = () =>
  useMutation({
    mutationFn: (url: string) => api<ImportStarted>("/candidates/import", { method: "POST", body: { url } }),
  });

/** Итог импорта по request_id — кладёт handleEvent из события import.finished. */
export const useImportResult = (requestId: string | undefined) =>
  useQuery({
    queryKey: keys.importResult(requestId ?? ""),
    queryFn: () => null as ImportResult | null,
    enabled: false,
    initialData: null,
  });

export const useDuplicates = (id: number) =>
  useQuery({ queryKey: keys.duplicates(id), queryFn: () => api<Duplicate[]>(`/candidates/${id}/duplicates`) });

export function useMerge(id: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (otherId: number) =>
      api<CandidateDetail>(`/candidates/${id}/merge`, { method: "POST", body: { other_id: otherId } }),
    onSuccess: (merged) => {
      qc.setQueryData(keys.candidate(id), merged);
      qc.invalidateQueries({ queryKey: keys.duplicates(id) });
      qc.invalidateQueries({ queryKey: keys.comments(id) });
    },
  });
}

export const useComments = (candidateId: number) =>
  useQuery({ queryKey: keys.comments(candidateId), queryFn: () => api<Comment[]>(`/candidates/${candidateId}/comments`) });

export const useAddComment = (candidateId: number) =>
  useMutation({
    mutationFn: (text: string) => api<Comment>(`/candidates/${candidateId}/comments`, { method: "POST", body: { text } }),
  });

// правка и удаление — только своих; тред у всех обновят WS-события comment.updated / comment.deleted
export const useEditComment = (candidateId: number) =>
  useMutation({
    mutationFn: ({ id, text }: { id: number; text: string }) =>
      api<Comment>(`/candidates/${candidateId}/comments/${id}`, { method: "PATCH", body: { text } }),
  });

export const useDeleteComment = (candidateId: number) =>
  useMutation({
    mutationFn: (id: number) => api<void>(`/candidates/${candidateId}/comments/${id}`, { method: "DELETE" }),
  });

// --- presence: кто сейчас смотрит анкету ---

export const usePresence = () =>
  useQuery({
    queryKey: keys.presence,
    queryFn: async () =>
      Object.fromEntries((await api<Viewers[]>("/presence")).map((v) => [v.candidate_id, v.viewers])) as Record<
        number,
        User[]
      >,
    // основной канал — WS-событие presence.updated; редкий опрос вычищает вкладки упавшего сервера
    refetchInterval: 60_000,
  });

// --- profiles ---

export const useProfiles = () => useQuery({ queryKey: keys.profiles, queryFn: () => api<Profile[]>("/profiles") });

export function useSaveProfile() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: ProfileInput & { id?: number }) =>
      id ? api<Profile>(`/profiles/${id}`, { method: "PUT", body }) : api<Profile>("/profiles", { method: "POST", body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.profiles }),
  });
}

export function useDeleteProfile() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api<void>(`/profiles/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.profiles }),
  });
}

export const useRunProfile = () =>
  useMutation({ mutationFn: (id: number) => api<{ queued: Source[] }>(`/profiles/${id}/run`, { method: "POST" }) });

// --- sources ---

export const useSources = () => useQuery({ queryKey: keys.sources, queryFn: () => api<SourceState[]>("/sources") });

export function useResumeSource() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (source: Source) => api<SourceState>(`/sources/${source}/resume`, { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.sources }),
  });
}

// --- вход в площадку из интерфейса ---

const ACTIVE_LOGIN = new Set(["queued", "running", "need_input"]);
export const isLoginActive = (state: LoginState | null | undefined) => !!state && ACTIVE_LOGIN.has(state.status);

export const useSourceLogin = (source: Source, enabled = true) =>
  useQuery({
    queryKey: keys.sourceLogin(source),
    queryFn: () => api<LoginState | null>(`/sources/${source}/login`),
    enabled,
    // основной канал — WS-событие source.login; опрос — подстраховка, пока вход идёт
    refetchInterval: (q) => (isLoginActive(q.state.data) ? 3000 : false),
  });

function useLoginMutation(source: Source, fn: () => Promise<LoginState | null>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: (state) => {
      if (state) qc.setQueryData(keys.sourceLogin(source), state);
      else qc.invalidateQueries({ queryKey: keys.sourceLogin(source) });
    },
  });
}

export const useStartLogin = (source: Source) =>
  useLoginMutation(source, () => api<LoginState>(`/sources/${source}/login`, { method: "POST" }));

export const useCancelLogin = (source: Source) =>
  useLoginMutation(source, () => api<LoginState | null>(`/sources/${source}/login/cancel`, { method: "POST" }));

// состояние после ответа приходит из воркера (WS/опрос), здесь ничего не кладём в кэш
export const useLoginInput = (source: Source) =>
  useMutation({
    mutationFn: (body: LoginInput) => api<LoginState>(`/sources/${source}/login/input`, { method: "POST", body }),
  });
