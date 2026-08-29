"use client";

import { useEffect } from "react";

/** Lightweight overlay for content that doesn't warrant a permanent sidebar
 *  tab -- static/reference panels a viewer opens occasionally, not ones they
 *  scrub or re-solve. Backdrop click and Escape both close it.
 *
 *  No title bar of its own: every current caller passes a <Panel>, which
 *  already renders its own header, so a second one here would just repeat
 *  the title back. The close button floats over the content instead. */
export default function Modal({
  onClose,
  children,
}: {
  onClose: () => void;
  children: React.ReactNode;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
    >
      <div
        className="relative w-full max-w-3xl max-h-[85vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          onClick={onClose}
          className="absolute top-3 right-3 z-10 text-[var(--muted)] hover:text-[var(--foreground)] text-[15px] leading-none px-1.5 py-1 rounded bg-[var(--panel-2)] border border-[var(--border)]"
          aria-label="Close"
        >
          ✕
        </button>
        {children}
      </div>
    </div>
  );
}
