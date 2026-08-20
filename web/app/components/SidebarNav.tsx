"use client";

import { ReactNode } from "react";

export type PanelKey =
  | "map"
  | "risk"
  | "procurement"
  | "impact"
  | "reserve"
  | "backtest"
  | "bypass";

const ITEMS: { key: PanelKey; label: string; icon: ReactNode }[] = [
  {
    key: "map",
    label: "Flow map",
    icon: (
      <path d="M9 3 3 6v15l6-3 6 3 6-3V3l-6 3-6-3Zm0 0v15m6-15v15" strokeLinecap="round" strokeLinejoin="round" />
    ),
  },
  {
    key: "risk",
    label: "Risk index",
    icon: <path d="M3 17 9 9l4 4 8-10M15 3h6v6" strokeLinecap="round" strokeLinejoin="round" />,
  },
  {
    key: "procurement",
    label: "Reallocation",
    icon: (
      <path
        d="M4 6h16M4 6l3-3M4 6l3 3M20 18H4M20 18l-3-3M20 18l-3 3M8 12h8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    ),
  },
  {
    key: "impact",
    label: "Impact cascade",
    icon: <path d="M4 20V10m6 10V4m6 16V13m4 7h-1" strokeLinecap="round" strokeLinejoin="round" />,
  },
  {
    key: "reserve",
    label: "Strategic reserve",
    icon: (
      <path
        d="M12 3c4 3 7 6.5 7 10.5A7 7 0 1 1 5 13.5C5 9.5 8 6 12 3Z"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    ),
  },
  {
    key: "backtest",
    label: "Backtest",
    icon: <path d="M3 3v18h18M8 16l4-6 3 3 4-7" strokeLinecap="round" strokeLinejoin="round" />,
  },
  {
    key: "bypass",
    label: "Bypass routes",
    icon: <path d="M4 12h5l2-4 3 8 2-4h4M4 12a8 8 0 1 0 16 0" strokeLinecap="round" strokeLinejoin="round" />,
  },
];

/** Left rail that switches which single panel is focused in the main content
 *  area. Deliberately not a router: this is a one-page dashboard already
 *  holding all its state in page.tsx, so a plain activePanel useState is the
 *  whole mechanism — no new dependency, no URL sync needed for a demo. */
export default function SidebarNav({
  active,
  onChange,
}: {
  active: PanelKey;
  onChange: (key: PanelKey) => void;
}) {
  return (
    <nav className="panel flex xl:flex-col flex-row xl:w-[176px] w-full xl:h-full shrink-0 p-1.5 gap-1 overflow-x-auto xl:overflow-visible">
      {ITEMS.map((item) => {
        const isActive = item.key === active;
        return (
          <button
            key={item.key}
            onClick={() => onChange(item.key)}
            className={`flex items-center gap-2.5 px-2.5 py-2 rounded-md text-[12px] whitespace-nowrap shrink-0 transition-colors ${
              isActive
                ? "bg-[var(--accent)] text-[#06121f] font-medium"
                : "text-[var(--muted)] hover:bg-[var(--panel-2)] hover:text-[var(--foreground)]"
            }`}
          >
            <svg
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              className="shrink-0"
            >
              {item.icon}
            </svg>
            <span className="hidden xl:inline">{item.label}</span>
          </button>
        );
      })}
    </nav>
  );
}
