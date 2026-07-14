"use client";

import { useEffect } from "react";
import { X, CheckCircle, AlertCircle, Info, AlertTriangle } from "lucide-react";

export type ToastKind = "success" | "error" | "info" | "warning";

export interface ToastItem {
  id: string;
  kind: ToastKind;
  message: string;
}

const KIND_STYLE: Record<ToastKind, { bg: string; border: string; color: string }> = {
  success: { bg: "var(--green-bg)", border: "var(--green-border)", color: "var(--green)" },
  error:   { bg: "var(--red-bg)",   border: "var(--red-border)",   color: "var(--red)" },
  warning: { bg: "var(--amber-bg)", border: "var(--amber-border)", color: "var(--amber)" },
  info:    { bg: "var(--blue-bg)",  border: "var(--blue-border)",  color: "var(--blue)" },
};

const KIND_ICON: Record<ToastKind, React.ElementType> = {
  success: CheckCircle,
  error:   AlertCircle,
  warning: AlertTriangle,
  info:    Info,
};

const AUTO_DISMISS_MS = 4000;

function Toast({ item, onDismiss }: { item: ToastItem; onDismiss: (id: string) => void }) {
  const style = KIND_STYLE[item.kind];
  const Icon = KIND_ICON[item.kind];

  useEffect(() => {
    const t = setTimeout(() => onDismiss(item.id), AUTO_DISMISS_MS);
    return () => clearTimeout(t);
  }, [item.id, onDismiss]);

  return (
    <div
      role="status"
      aria-live="polite"
      style={{
        display: "flex",
        alignItems: "flex-start",
        gap: "10px",
        padding: "10px 12px",
        background: style.bg,
        border: `1px solid ${style.border}`,
        borderRadius: "6px",
        fontSize: "13px",
        color: "var(--fg)",
        boxShadow: "0 4px 16px rgba(0,0,0,0.4)",
        animation: "ds-scale-in 0.15s ease",
        maxWidth: "360px",
      }}
    >
      <Icon size={15} style={{ color: style.color, flexShrink: 0, marginTop: 1 }} />
      <span style={{ flex: 1, lineHeight: 1.5 }}>{item.message}</span>
      <button
        onClick={() => onDismiss(item.id)}
        aria-label="Dismiss"
        style={{
          background: "none",
          border: "none",
          color: "var(--fg-dim)",
          cursor: "pointer",
          padding: "1px",
          lineHeight: 0,
          flexShrink: 0,
        }}
      >
        <X size={13} />
      </button>
    </div>
  );
}

interface ToastStackProps {
  toasts: ToastItem[];
  onDismiss: (id: string) => void;
}

export default function ToastStack({ toasts, onDismiss }: ToastStackProps) {
  if (toasts.length === 0) return null;
  return (
    <div
      style={{
        position: "fixed",
        bottom: "24px",
        right: "24px",
        zIndex: 200,
        display: "flex",
        flexDirection: "column",
        gap: "8px",
        pointerEvents: "none",
      }}
    >
      {toasts.map((t) => (
        <div key={t.id} style={{ pointerEvents: "auto" }}>
          <Toast item={t} onDismiss={onDismiss} />
        </div>
      ))}
    </div>
  );
}
