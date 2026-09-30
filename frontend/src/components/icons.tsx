import type { SVGProps } from "react";

// Линейные иконки 16×16 в духе hh-stats: цвет — currentColor, размер — через className.
const base = {
  viewBox: "0 0 16 16",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.6,
  strokeLinecap: "round",
  strokeLinejoin: "round",
  "aria-hidden": true,
} as const;

type P = SVGProps<SVGSVGElement>;

export const LogoIcon = (p: P) => (
  <svg {...base} {...p}>
    <circle cx="6.5" cy="6.5" r="3.5" />
    <path d="M9 9l4.5 4.5M2 14c.6-1.6 2-2.5 4.5-2.5" />
  </svg>
);
export const SearchIcon = (p: P) => (
  <svg {...base} {...p}>
    <circle cx="7" cy="7" r="4.5" />
    <path d="M11 11l3 3" />
  </svg>
);
export const FilterIcon = (p: P) => (
  <svg {...base} {...p}>
    <path d="M2 4h12M4 8h8M6 12h4" />
  </svg>
);
export const CloseIcon = (p: P) => (
  <svg {...base} {...p}>
    <path d="M3 3l10 10M13 3L3 13" />
  </svg>
);
export const CheckIcon = (p: P) => (
  <svg {...base} strokeWidth={1.8} viewBox="0 0 12 12" {...p}>
    <path d="M2.5 6.5L5 9l4.5-5" />
  </svg>
);
export const BackIcon = (p: P) => (
  <svg {...base} {...p}>
    <path d="M10 3L5 8l5 5" />
  </svg>
);
export const PlayIcon = (p: P) => (
  <svg {...base} {...p}>
    <path d="M5 3.5v9l7-4.5z" />
  </svg>
);
export const PlusIcon = (p: P) => (
  <svg {...base} {...p}>
    <path d="M8 3v10M3 8h10" />
  </svg>
);
export const ChatIcon = (p: P) => (
  <svg {...base} {...p}>
    <path d="M2.5 3.5h11v7.5H7l-3 2.5V11H2.5z" />
  </svg>
);
export const ChevronIcon = (p: P) => (
  <svg {...base} {...p}>
    <path d="M4 6l4 4 4-4" />
  </svg>
);
export const ExternalIcon = (p: P) => (
  <svg {...base} {...p}>
    <path d="M6 3H3v10h10v-3M9 3h4v4M13 3L7 9" />
  </svg>
);
export const EyeIcon = (p: P) => (
  <svg {...base} {...p}>
    <path d="M1.5 8S4 3.5 8 3.5 14.5 8 14.5 8 12 12.5 8 12.5 1.5 8 1.5 8z" />
    <circle cx="8" cy="8" r="2" />
  </svg>
);
export const PencilIcon = (p: P) => (
  <svg {...base} {...p}>
    <path d="M10.5 2.5l3 3L6 13H3v-3z" />
  </svg>
);
export const TrashIcon = (p: P) => (
  <svg {...base} {...p}>
    <path d="M2.5 4h11M6 4V2.5h4V4M4 4l.7 9.5h6.6L12 4" />
  </svg>
);
export const LinkIcon = (p: P) => (
  <svg {...base} {...p}>
    <path d="M6.5 9.5l3-3M7 4.5l1-1a2.5 2.5 0 013.5 3.5l-1 1M9 11.5l-1 1A2.5 2.5 0 014.5 9l1-1" />
  </svg>
);
