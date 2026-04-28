"use client";

import Modal from "./Modal";

interface ConfirmDialogProps {
  open: boolean;
  title?: string;
  message: string;
  confirmLabel?: string;
  destructive?: boolean;
  busy?: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}

export default function ConfirmDialog({
  open,
  title = "Are you sure?",
  message,
  confirmLabel = "Confirm",
  destructive = false,
  busy = false,
  onCancel,
  onConfirm,
}: ConfirmDialogProps) {
  return (
    <Modal open={open} onClose={onCancel} title={title} widthPx={320}>
      <p style={{ margin: "0 0 20px", color: "var(--fg-dim)", fontSize: "13px", lineHeight: 1.6 }}>
        {message}
      </p>
      <div style={{ display: "flex", gap: "8px", justifyContent: "flex-end" }}>
        <button
          onClick={onCancel}
          disabled={busy}
          style={{
            background: "var(--bg-3)",
            border: "1px solid var(--border-2)",
            borderRadius: "5px",
            color: "var(--fg-dim)",
            cursor: busy ? "not-allowed" : "pointer",
            fontSize: "12px",
            padding: "6px 12px",
            opacity: busy ? 0.5 : 1,
          }}
        >
          Cancel
        </button>
        <button
          onClick={onConfirm}
          disabled={busy}
          style={{
            background: destructive ? "var(--red-bg)" : "var(--accent-bg)",
            border: `1px solid ${destructive ? "var(--red-border)" : "var(--accent-border)"}`,
            borderRadius: "5px",
            color: destructive ? "var(--red)" : "var(--accent)",
            cursor: busy ? "not-allowed" : "pointer",
            fontSize: "12px",
            fontWeight: 500,
            padding: "6px 12px",
            opacity: busy ? 0.7 : 1,
          }}
        >
          {busy ? "Deleting…" : confirmLabel}
        </button>
      </div>
    </Modal>
  );
}
