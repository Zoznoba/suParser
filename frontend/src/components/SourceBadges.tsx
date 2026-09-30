import type { CandidateSource } from "../api/types";
import { SOURCE_LABELS } from "../lib/format";
import { ExternalIcon } from "./icons";

export function SourceBadges({ sources, links = false }: { sources: CandidateSource[]; links?: boolean }) {
  return (
    <span className="flex flex-wrap gap-1">
      {sources.map((s) =>
        links && s.url ? (
          <a
            key={`${s.source}:${s.external_id}`}
            className="tag transition-colors hover:bg-black hover:text-white"
            href={s.url}
            target="_blank"
            rel="noreferrer"
          >
            {SOURCE_LABELS[s.source]}
            <ExternalIcon className="size-3" />
          </a>
        ) : (
          <span key={`${s.source}:${s.external_id}`} className="tag">
            {SOURCE_LABELS[s.source]}
          </span>
        ),
      )}
    </span>
  );
}
