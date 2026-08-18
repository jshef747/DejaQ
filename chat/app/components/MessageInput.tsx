"use client";

import { useEffect, useRef } from "react";

import type { Attachment } from "./chat-store";

// Reject files larger than this before base64-encoding — keeps the request body
// and localStorage sane. Mirrors DEJAQ_MAX_ATTACHMENT_BYTES on the server, which
// is the limit that actually holds; this one just fails faster and more kindly.
const MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024;

const DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document";

// KEEP THIS IN STEP WITH services/file_text.py::kind_for. A mismatch here means
// the browser offers a file the server will 400 on, or the reverse.
//
// PDF and DOCX are recognised by MIME or extension. Everything else the
// browser reports (Markdown, plain text, source/config files, whatever MIME a
// given browser happens to send) is treated client-side as a "markdown"-kind
// attachment and handed to the server as-is — the server is the one place
// that actually decides "is this text?" by attempting a UTF-8 decode of the
// bytes, since a browser can't cheaply replicate that check before upload. A
// file that fails the server's decode comes back as a normal send error.
function attachmentKind(file: File): Attachment["kind"] {
  const name = file.name.toLowerCase();
  if (file.type.startsWith("image/")) return "image";
  if (file.type === "application/pdf" || name.endsWith(".pdf")) return "pdf";
  if (file.type === DOCX_MIME || name.endsWith(".docx")) return "docx";
  return "markdown";
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

interface Props {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  disabled: boolean;
  attachment: Attachment | null;
  onAttachmentChange: (attachment: Attachment | null) => void;
  onAttachmentError?: (message: string) => void;
}

export default function MessageInput({
  value,
  onChange,
  onSend,
  disabled,
  attachment,
  onAttachmentChange,
  onAttachmentError,
}: Props) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Auto-resize the textarea up to a reasonable max height.
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [value]);

  // A drop that lands outside the dropzone below hits the browser default:
  // navigate the tab to the file, wiping unsent input and any unsaved
  // conversation. Block that everywhere; the dropzone's own onDrop still
  // runs first (native bubble order) and does the real attach handling.
  useEffect(() => {
    const preventDefault = (e: DragEvent) => e.preventDefault();
    window.addEventListener("dragover", preventDefault);
    window.addEventListener("drop", preventDefault);
    return () => {
      window.removeEventListener("dragover", preventDefault);
      window.removeEventListener("drop", preventDefault);
    };
  }, []);

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    // Enter alone sends; Shift+Enter inserts a newline.
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (canSend) onSend();
    }
  }

  function attachFile(file: File) {
    const kind = attachmentKind(file);
    if (file.size > MAX_ATTACHMENT_BYTES) {
      onAttachmentError?.(`That file is too large (max ${formatBytes(MAX_ATTACHMENT_BYTES)}).`);
      return;
    }
    const reader = new FileReader();
    // Everything goes as a data URL, PDFs included — the backend takes data URLs
    // only (no remote fetches, no file ids), so one transport covers every kind.
    reader.onload = () =>
      onAttachmentChange(
        typeof reader.result === "string"
          ? { dataUrl: reader.result, kind, name: file.name, size: file.size, sticky: false }
          : null,
      );
    reader.onerror = () => onAttachmentError?.("Could not read that file.");
    reader.readAsDataURL(file);
  }

  function handleFilePick(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = ""; // allow re-picking the same file
    if (file) attachFile(file);
  }

  function handlePaste(e: React.ClipboardEvent<HTMLTextAreaElement>) {
    // Grab the first attachable file in the clipboard (screenshots, copied
    // files). Let text paste through untouched by only acting on a real file.
    const file = Array.from(e.clipboardData.items)
      .map((i) => (i.kind === "file" ? i.getAsFile() : null))
      .find((f): f is File => f != null);
    if (file) {
      e.preventDefault();
      attachFile(file);
    }
  }

  function handleDrop(e: React.DragEvent) {
    const file = e.dataTransfer.files?.[0];
    if (file) {
      e.preventDefault();
      attachFile(file);
    }
  }

  const canSend = !disabled && (value.trim().length > 0 || attachment != null);

  return (
    <div
      style={{
        background: "var(--bg-2)",
        borderTop: "1px solid var(--border)",
        padding: "12px 16px",
      }}
    >
      {attachment && (
        <div
          style={{
            background: "var(--bg)",
            // A pinned attachment rides along with every message from here on,
            // which costs money and shapes the cache lookup. Make that state
            // impossible to miss rather than letting it look like a fresh pick.
            border: `1px solid ${attachment.sticky ? "var(--fg-dimmer)" : "var(--border-2)"}`,
            borderRadius: "8px",
            marginBottom: "8px",
            padding: "8px 10px",
          }}
        >
        <div style={{ alignItems: "center", display: "flex", gap: "10px" }}>
          {attachment.kind === "image" ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={attachment.dataUrl}
              alt="Attached"
              style={{ borderRadius: "6px", height: "44px", objectFit: "cover", width: "44px" }}
            />
          ) : (
            // A document has nothing to preview, so the icon carries the type.
            <div
              style={{
                alignItems: "center",
                background: "var(--bg-3)",
                borderRadius: "6px",
                color: "var(--fg-dim)",
                display: "flex",
                flexShrink: 0,
                height: "44px",
                justifyContent: "center",
                width: "44px",
              }}
            >
              <DocumentIcon />
            </div>
          )}
          <span
            style={{
              alignItems: "center",
              color: attachment.sticky ? "var(--fg)" : "var(--fg-dim)",
              display: "flex",
              flex: 1,
              fontSize: "12px",
              gap: "6px",
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
          >
            {attachment.sticky && (
              <span style={{ color: "var(--fg-dim)", display: "flex", flexShrink: 0 }}>
                <PinIcon />
              </span>
            )}
            {attachment.kind === "image"
              ? attachment.sticky
                ? "Image pinned"
                : "Image attached"
              : `${attachment.name || "Document"} · ${formatBytes(attachment.size)}${
                  attachment.sticky ? " · pinned" : ""
                }`}
          </span>
          <button
            onClick={() => onAttachmentChange(null)}
            title={attachment.sticky ? "Stop sending this attachment" : "Remove attachment"}
            aria-label={attachment.sticky ? "Unpin attachment" : "Remove attachment"}
            style={{
              background: "var(--bg-3)",
              border: "1px solid var(--border)",
              borderRadius: "5px",
              color: "var(--fg-dim)",
              cursor: "pointer",
              flexShrink: 0,
              fontSize: "12px",
              padding: "3px 8px",
            }}
          >
            {attachment.sticky ? "Unpin" : "Remove"}
          </button>
        </div>
        {attachment.sticky && (
          <p style={{ color: "var(--fg-dim)", fontSize: "11px", margin: "6px 0 0" }}>
            Sent with every message so follow-ups can see it. Unpin to stop.
          </p>
        )}
        </div>
      )}
      <div
        style={{
          alignItems: "flex-end",
          background: "var(--bg)",
          border: "1px solid var(--border-2)",
          borderRadius: "8px",
          display: "flex",
          gap: "8px",
          padding: "8px 8px 8px 8px",
          transition: "border-color 0.15s",
        }}
        onDragOver={(e) => e.preventDefault()}
        onDrop={handleDrop}
        onFocusCapture={(e) =>
          (e.currentTarget.style.borderColor = "var(--fg-dimmer)")
        }
        onBlurCapture={(e) =>
          (e.currentTarget.style.borderColor = "var(--border-2)")
        }
      >
        <input
          ref={fileInputRef}
          type="file"
          // No accept filter: text/code files are recognised by content on the
          // server (any UTF-8 file), not by a maintained extension list, so
          // there is no fixed set to filter the picker to. Images, PDF, and
          // DOCX are still recognised as such by attachmentKind() above; a
          // genuinely unsupported pick (a binary file) is rejected server-side
          // with a clear error surfaced as a toast.
          onChange={handleFilePick}
          style={{ display: "none" }}
        />
        <button
          onClick={() => fileInputRef.current?.click()}
          disabled={disabled}
          title="Attach an image, PDF, Word doc, or text/code file"
          aria-label="Attach a file"
          style={{
            alignItems: "center",
            background: "transparent",
            border: "none",
            borderRadius: "6px",
            color: attachment ? "var(--fg)" : "var(--fg-dim)",
            cursor: disabled ? "not-allowed" : "pointer",
            display: "flex",
            flexShrink: 0,
            height: "30px",
            justifyContent: "center",
            width: "30px",
          }}
        >
          <AttachIcon />
        </button>
        <textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          onPaste={handlePaste}
          disabled={disabled}
          placeholder={disabled ? "Waiting for response…" : "Ask anything… (Enter to send, paste or drop a file to attach)"}
          rows={1}
          style={{
            background: "transparent",
            border: "none",
            color: "var(--fg)",
            flex: 1,
            fontFamily: "var(--font-sans)",
            fontSize: "13px",
            lineHeight: 1.5,
            maxHeight: "200px",
            outline: "none",
            padding: 0,
            resize: "none",
          }}
        />
        <button
          onClick={onSend}
          disabled={!canSend}
          title="Send (Enter)"
          style={{
            alignItems: "center",
            background: canSend ? "var(--fg)" : "var(--bg-3)",
            border: "none",
            borderRadius: "6px",
            color: canSend ? "var(--bg)" : "var(--fg-dimmer)",
            cursor: canSend ? "pointer" : "not-allowed",
            display: "flex",
            flexShrink: 0,
            height: "30px",
            justifyContent: "center",
            transition: "background 0.15s",
            width: "30px",
          }}
          aria-label="Send message"
        >
          <SendIcon />
        </button>
      </div>
      <p
        style={{
          color: "var(--fg-dim)",
          fontSize: "11px",
          margin: "6px 2px 0",
          textAlign: "center",
        }}
      >
        DejaQ may make mistakes. Verify important information.
      </p>
    </div>
  );
}

function AttachIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path d="M13 6.5l-5.5 5.5a2.5 2.5 0 0 1-3.5-3.5l5.5-5.5a1.5 1.5 0 0 1 2 2L6 10.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function PinIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4">
      <path d="M6 1.5h4l-.5 4 2.5 2.5H4L6.5 5.5 6 1.5z" strokeLinejoin="round" />
      <path d="M8 8v6.5" strokeLinecap="round" />
    </svg>
  );
}

function DocumentIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3">
      <path d="M9.5 1.5H4a1 1 0 0 0-1 1v11a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1V5l-3.5-3.5z" strokeLinejoin="round" />
      <path d="M9.5 1.5V5H13" strokeLinejoin="round" />
      <path d="M5.5 8h5M5.5 10.5h5" strokeLinecap="round" />
    </svg>
  );
}

function SendIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 16 16" fill="currentColor">
      <path d="M14.5 1.5L7 9M14.5 1.5L10 14.5l-3-5.5L1.5 6l13-4.5z" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" fill="none" />
    </svg>
  );
}
