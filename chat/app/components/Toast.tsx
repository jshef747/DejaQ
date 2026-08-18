"use client";

import { useEffect } from "react";

export type ToastKind = "success" | "error" | "info";

export interface ToastData {
  id: string;
  kind: ToastKind;
  message: string;
}

interface Props {
  toasts: ToastData[];
  onDismiss: (id: string) => void;
}

const AUTO_DISMISS_MS = 4000;

export default function ToastStack({ toasts, onDismiss }: Props) {
  // Set up auto-dismiss timers whenever a new toast arrives.
  useEffect(() => {
    if (toasts.length === 0) return;
    const latest = toasts[toasts.length - 1];
    const timer = setTimeout(() => onDismiss(latest.id), AUTO_DISMISS_MS);
    return () => clearTimeout(timer);
  }, [toasts, onDismiss]);

  if (toasts.length === 0) return null;

  return (
    <div
      style={{
        bottom: "24px",
        display: "flex",
        flexDirection: "column",
        gap: "8px",
        pointerEvents: "none",
        position: "fixed",
        right: "24px",
        zIndex: 100,
      }}
    >
      {toasts.map((t) => (
        <div
          key={t.id}
          style={{
            alignItems: "center",
            background: t.kind === "error" ? "var(--red-bg)" : t.kind === "success" ? "var(--green-bg)" : "var(--bg-3)",
            border: `1px solid ${t.kind === "error" ? "var(--red-border)" : t.kind === "success" ? "var(--green-border)" : "var(--border-2)"}`,
            borderRadius: "6px",
            boxShadow: "var(--shadow-sm)",
            color: t.kind === "error" ? "var(--red)" : t.kind === "success" ? "var(--green)" : "var(--fg)",
            display: "flex",
            fontSize: "13px",
            gap: "10px",
            maxWidth: "360px",
            padding: "10px 14px",
            pointerEvents: "auto",
          }}
        >
          <span style={{ flex: 1, lineHeight: 1.45 }}>{t.message}</span>
          <button
            onClick={() => onDismiss(t.id)}
            style={{
              background: "transparent",
              border: "none",
              color: "inherit",
              cursor: "pointer",
              flexShrink: 0,
              fontSize: "14px",
              opacity: 0.6,
              padding: "0 2px",
            }}
            aria-label="Dismiss"
          >
            ✕
          </button>
        </div>
      ))}
    </div>
  );
}
