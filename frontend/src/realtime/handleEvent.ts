import type { QueryClient } from "@tanstack/react-query";

import { keys } from "../api/hooks";
import type { CandidateDetail, Comment, RealtimeEvent, SourceState, User } from "../api/types";

/** Раскладывает серверное событие по кэшу TanStack Query. */
export function handleEvent(qc: QueryClient, event: RealtimeEvent) {
  switch (event.type) {
    case "candidate.updated": {
      const c = event.data;
      qc.setQueryData<CandidateDetail>(keys.candidate(c.id), (old) => (old ? { ...old, ...c } : old));
      // списки перезапрашиваем: карточка могла выпасть из фильтра по статусу
      qc.invalidateQueries({ queryKey: keys.candidates });
      break;
    }
    case "candidate.merged": {
      // карточка id удалена, её резюме и комментарии теперь в into
      qc.removeQueries({ queryKey: keys.candidate(event.data.id) });
      qc.invalidateQueries({ queryKey: keys.candidate(event.data.into) });
      qc.invalidateQueries({ queryKey: keys.comments(event.data.into) });
      qc.invalidateQueries({ queryKey: ["duplicates"] });
      qc.invalidateQueries({ queryKey: keys.candidates });
      break;
    }
    case "candidates.created":
      qc.invalidateQueries({ queryKey: keys.candidates });
      break;
    case "candidates.stale":
      // анкеты стали неактуальны (или снова актуальны): уходят из ленты / возвращаются, в карточке — плашка
      for (const id of [...event.data.stale, ...event.data.fresh]) qc.invalidateQueries({ queryKey: keys.candidate(id) });
      qc.invalidateQueries({ queryKey: keys.candidates });
      break;
    case "comment.updated": {
      const comment = event.data;
      qc.setQueryData<Comment[]>(keys.comments(comment.candidate_id), (old) =>
        old?.map((c) => (c.id === comment.id ? comment : c)),
      );
      break;
    }
    case "comment.deleted": {
      const { id, candidate_id } = event.data;
      qc.setQueryData<Comment[]>(keys.comments(candidate_id), (old) => old?.filter((c) => c.id !== id));
      qc.invalidateQueries({ queryKey: keys.candidate(candidate_id) });
      qc.invalidateQueries({ queryKey: keys.candidates });
      break;
    }
    case "presence.updated": {
      const { candidate_id, viewers } = event.data;
      qc.setQueryData<Record<number, User[]>>(keys.presence, (old) => {
        const next = { ...old };
        if (viewers.length) next[candidate_id] = viewers;
        else delete next[candidate_id];
        return next;
      });
      break;
    }
    case "import.finished":
      // ждёт только тот, кто импортировал (useImportResult по request_id); остальным хватит candidates.created
      qc.setQueryData(keys.importResult(event.data.request_id), event.data);
      break;
    case "comment.created": {
      const comment = event.data;
      qc.setQueryData<Comment[]>(keys.comments(comment.candidate_id), (old) =>
        old && !old.some((c) => c.id === comment.id) ? [...old, comment] : old,
      );
      qc.invalidateQueries({ queryKey: keys.candidate(comment.candidate_id) });
      qc.invalidateQueries({ queryKey: keys.candidates });
      break;
    }
    case "source.updated":
      qc.setQueryData<SourceState[]>(keys.sources, (old) =>
        old?.map((s) => (s.source === event.data.source ? event.data : s)),
      );
      break;
    case "source.login":
      qc.setQueryData(keys.sourceLogin(event.data.source), event.data);
      break;
  }
}
