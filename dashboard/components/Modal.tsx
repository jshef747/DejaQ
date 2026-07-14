"use client";

import { useEffect, useId, useRef } from "react";
import { X } from "lucide-react";

interface ModalProps {
  open: boolean;
  onClose: () => void;
  title: string;
  subtitle?: string;
  children: React.ReactNode;
  widthPx?: number;
  footer?: React.ReactNode;
}

export default function Modal({ open, onClose, title, subtitle, children, widthPx = 440, footer }: ModalProps) {
  const panelId = useId();
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, onClose]);

  useEffect(() => {
    if (!open) return;
    const focusable = panelRef.current?.querySelector<HTMLElement>(
      "input, button, select, textarea, [tabindex]:not([tabindex='-1'])"
    );
    focusable?.focus();
  }, [open]);

  if (!open) return null;

  return (
    <div
      role="presentation"
      onClick={onClose}
      className="ds-modal-backdrop"
    >
      <div
        ref={panelRef}
        id={panelId}
        role="dialog"
        aria-modal="true"
        aria-labelledby={`${panelId}-title`}
        onClick={(e) => e.stopPropagation()}
        className="ds-modal"
        style={{ width: widthPx }}
      >
        <div className="ds-modal-header" style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: "12px" }}>
          <div>
            <p id={`${panelId}-title`} className="ds-modal-title">{title}</p>
            {subtitle && <p className="ds-modal-sub">{subtitle}</p>}
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            className="ds-btn ds-btn-ghost ds-btn-icon"
            style={{ flexShrink: 0, marginTop: "-2px" }}
          >
            <X size={14} />
          </button>
        </div>
        <div className="ds-modal-body">{children}</div>
        {footer && <div className="ds-modal-footer">{footer}</div>}
      </div>
    </div>
  );
}
