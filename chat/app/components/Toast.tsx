"use client";

import { useEffect } from "react";

export type ToastKind = "success" | "error" | "info";

export interface ToastAction {
  label: string;
  href: string;
}

export interface ToastData {
  id: string;
  kind: ToastKind;
  title: string;
  body: string;
  action?: ToastAction;
}

interface Props {
  toasts: ToastData[];
  onDismiss: (id: string) => void;
}

const AUTO_DISMISS_MS = 4000;
// Toasts that carry an action need time to be read and clicked, not just read.
const AUTO_DISMISS_WITH_ACTION_MS = 7000;

export default function ToastStack({ toasts, onDismiss }: Props) {
  // Set up an auto-dismiss timer for the latest toast only — the oldest
  // toasts in the stack are still visible and dismissible by hand.
  useEffect(() => {
    if (toasts.length === 0) return;
    const latest = toasts[toasts.length - 1];
    const ms = latest.action ? AUTO_DISMISS_WITH_ACTION_MS : AUTO_DISMISS_MS;
    const timer = setTimeout(() => onDismiss(latest.id), ms);
    return () => clearTimeout(timer);
  }, [toasts, onDismiss]);

  if (toasts.length === 0) return null;

  return (
    // Top-centre, never over the composer's send button — the whole reason
    // this moved off bottom-right, where it used to sit directly on top of
    // the control someone would reach for to retry a failed send.
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: "8px",
        left: 0,
        pointerEvents: "none",
        position: "fixed",
        right: 0,
        top: "20px",
        zIndex: 100,
      }}
    >
      {toasts.map((t) => (
        <ToastCard key={t.id} toast={t} onDismiss={() => onDismiss(t.id)} />
      ))}
    </div>
  );
}

const KEYLINE: Record<ToastKind, string> = {
  success: "var(--green)",
  error: "var(--red)",
  info: "var(--border-2)",
};

function ToastCard({ toast, onDismiss }: { toast: ToastData; onDismiss: () => void }) {
  return (
    <div
      style={{
        background: "var(--bg-2)",
        border: "1px solid var(--border-2)",
        borderRadius: "11px",
        boxShadow: "var(--shadow)",
        display: "flex",
        gap: "12px",
        maxWidth: "396px",
        overflow: "hidden",
        padding: "13px 14px 13px 0",
        pointerEvents: "auto",
        position: "relative",
        width: "396px",
      }}
    >
      <div
        aria-hidden
        style={{ background: KEYLINE[toast.kind], bottom: 0, left: 0, position: "absolute", top: 0, width: "3px" }}
      />
      <div style={{ alignItems: "flex-start", color: KEYLINE[toast.kind], display: "flex", flexShrink: 0, justifyContent: "center", paddingTop: "1px", width: "44px" }}>
        <ToastIcon kind={toast.kind} />
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: "13px", fontWeight: 600, letterSpacing: "-0.006em" }}>{toast.title}</div>
        <div style={{ color: "var(--fg-dim)", fontSize: "12.5px", lineHeight: "19px", marginTop: "3px" }}>
          {toast.body}
        </div>
        {toast.action && (
          <a
            href={toast.action.href}
            target="_blank"
            rel="noreferrer"
            style={{
              alignItems: "center",
              color: "var(--accent)",
              display: "flex",
              fontSize: "12.5px",
              fontWeight: 600,
              gap: "5px",
              marginTop: "9px",
              textDecoration: "none",
            }}
          >
            {toast.action.label}
            <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <path d="M3 8h9M8.4 4.4 12 8l-3.6 3.6" />
            </svg>
          </a>
        )}
      </div>
      <button
        onClick={onDismiss}
        aria-label="Dismiss"
        style={{
          alignItems: "flex-start",
          background: "transparent",
          border: "none",
          color: "var(--fg-dimmer)",
          cursor: "pointer",
          display: "flex",
          flexShrink: 0,
          paddingTop: "1px",
        }}
      >
        <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
          <path d="M4.2 4.2 11.8 11.8M11.8 4.2 4.2 11.8" />
        </svg>
      </button>
    </div>
  );
}

function ToastIcon({ kind }: { kind: ToastKind }) {
  if (kind === "success") {
    return (
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
        <path d="M3.2 8.4 6.4 11.6 12.8 5" />
      </svg>
    );
  }
  if (kind === "error") {
    return (
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
        <circle cx="8" cy="8" r="6.2" />
        <path d="M8 4.8v3.7M8 11h.01" />
      </svg>
    );
  }
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
      <circle cx="8" cy="8" r="6.2" />
      <path d="M8 7.4v3.6M8 5h.01" />
    </svg>
  );
}
