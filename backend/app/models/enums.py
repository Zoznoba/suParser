from enum import StrEnum


class CandidateStatus(StrEnum):
    NEW = "new"
    INTERESTING = "interesting"  # «интересно»
    REJECTED = "rejected"  # «мимо»
    CONTACTED = "contacted"  # «на связи»
    IN_PROGRESS = "in_progress"  # «в работе»


class Source(StrEnum):
    SUPERJOB = "superjob"
    HH = "hh"
    LINKEDIN = "linkedin"


class SourceHealth(StrEnum):
    OK = "ok"
    NEEDS_ATTENTION = "needs_attention"  # капча / разлогин — нужен человек
    DISABLED = "disabled"
