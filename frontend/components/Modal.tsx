"use client";

import { useEffect, useRef } from "react";

interface ModalProps {
  open: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
  widthPx?: number;
}

export default function Modal({ open, onClose, title, children, widthPx = 360 }: ModalProps) {
  const firstFocusRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, onClose]);

  useEffect(() => {
    if (open) {
      // Focus first focusable element inside the panel
      setTimeout(() => {
        const panel = document.getElementById("modal-panel");
        const focusable = panel?.querySelector<HTMLElement>(
          "input, button, select, textarea, [tabindex]:not([tabindex='-1'])"
        );
        focusable?.focus();
      }, 0);
    }
  }, [open]);

  if (!open) return null;

  return (
    <div
      role="presentation"
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.55)",
        display: "grid",
        placeItems: "center",
        zIndex: 50,
      }}
    >
      <div
        id="modal-panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby="modal-title"
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "var(--bg-2)",
          border: "1px solid var(--border-2)",
          borderRadius: "8px",
          padding: "18px 20px",
          width: `${widthPx}px`,
          maxWidth: "calc(100vw - 32px)",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            marginBottom: "16px",
          }}
        >
          <span
            id="modal-title"
            style={{ fontWeight: 600, fontSize: "14px", letterSpacing: "-0.01em" }}
          >
            {title}
          </span>
          <button
            onClick={onClose}
            style={{
              background: "none",
              border: "none",
              color: "var(--fg-dimmer)",
              cursor: "pointer",
              fontSize: "16px",
              lineHeight: 1,
              padding: "2px 4px",
            }}
            aria-label="Close"
          >
            ×
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}
