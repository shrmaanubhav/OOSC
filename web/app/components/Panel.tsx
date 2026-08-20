"use client";

import { ReactNode } from "react";

/** Every panel carries an as-of line and, where the underlying data has a
 *  known limitation, a caveat. That's a design constraint from the brief,
 *  not decoration -- a number without its vintage is a liability here. */
export default function Panel({
  title,
  subtitle,
  asOf,
  caveat,
  right,
  children,
  className = "",
}: {
  title: string;
  subtitle?: string;
  asOf?: string | null;
  caveat?: string;
  right?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`panel flex flex-col ${className}`}>
      <header className="flex items-start justify-between gap-3 px-4 pt-3 pb-2 border-b border-[var(--border)]">
        <div className="min-w-0">
          <h2 className="text-[13px] font-semibold tracking-wide uppercase text-[var(--foreground)]">
            {title}
          </h2>
          {subtitle && (
            <p className="text-[11px] text-[var(--muted)] mt-0.5">{subtitle}</p>
          )}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {right}
          {asOf && <span className="asof mono">as of {asOf}</span>}
        </div>
      </header>
      <div className="flex-1 min-h-0 p-4">{children}</div>
      {caveat && (
        <footer className="px-4 pb-3 -mt-1">
          <p className="asof leading-snug">⚠ {caveat}</p>
        </footer>
      )}
    </section>
  );
}
