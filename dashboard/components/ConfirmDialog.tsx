"use client";

import Modal from "./Modal";
import Button from "./ui/Button";

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
    <Modal
      open={open}
      onClose={onCancel}
      title={title}
      widthPx={360}
      footer={
        <>
          <Button onClick={onCancel} disabled={busy}>Cancel</Button>
          <Button
            variant={destructive ? "danger" : "primary"}
            onClick={onConfirm}
            loading={busy}
          >
            {confirmLabel}
          </Button>
        </>
      }
    >
      <p style={{ margin: 0, color: "var(--fg-dim)", fontSize: "13px", lineHeight: 1.6 }}>
        {message}
      </p>
    </Modal>
  );
}
