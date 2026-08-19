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
  // An answer is in flight — the composer stays disabled and a Stop control
  // appears underneath it.
  isGenerating: boolean;
  onStop: () => void;
}

export default function MessageInput({
  value,
  onChange,
  onSend,
  disabled,
  attachment,
  onAttachmentChange,
  onAttachmentError,
  isGenerating,
  onStop,
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
  const pinned = Boolean(attachment?.sticky);

  return (
    // Sits on the reading column, not full-bleed: same rail+gutter offset
    // every turn and the provenance marker use, so the box lines up with the
    // text above it rather than spanning the whole window.
    <div style={{ padding: "0 0 18px" }}>
      <div style={{ display: "flex", margin: "0 auto", maxWidth: "calc(var(--shell) + 32px)", padding: "0 16px" }}>
        <div style={{ flex: "none", width: "calc(var(--rail) + var(--gutter))" }} />
        <div style={{ flex: 1, maxWidth: "var(--col)", minWidth: 0 }}>
          {attachment && (
            <div
              style={{
                background: "var(--bg-2)",
                border: `1.5px solid ${pinned ? "var(--accent-solid)" : "var(--border-2)"}`,
                borderRadius: "14px",
                marginBottom: "10px",
                overflow: "hidden",
              }}
            >
              <div
                style={{
                  alignItems: "center",
                  background: pinned ? "var(--accent-bg)" : "transparent",
                  borderBottom: pinned ? "1px solid var(--accent-border)" : "none",
                  display: "flex",
                  gap: "11px",
                  padding: "10px 12px",
                }}
              >
                {attachment.kind === "image" ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={attachment.dataUrl}
                    alt="Attached"
                    style={{ borderRadius: "8px", flexShrink: 0, height: "38px", objectFit: "cover", width: "38px" }}
                  />
                ) : (
                  <div
                    style={{
                      alignItems: "center",
                      background: pinned ? "var(--bg-2)" : "var(--bg-3)",
                      border: pinned ? "1px solid var(--accent-border)" : "none",
                      borderRadius: "8px",
                      color: pinned ? "var(--accent)" : "var(--fg-dim)",
                      display: "flex",
                      flexShrink: 0,
                      height: "38px",
                      justifyContent: "center",
                      width: "38px",
                    }}
                  >
                    <DocumentIcon />
                  </div>
                )}
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ alignItems: "center", display: "flex", gap: "6px" }}>
                    {pinned && (
                      <span style={{ color: "var(--accent)", display: "flex", flexShrink: 0 }}>
                        <PinIcon />
                      </span>
                    )}
                    <span
                      style={{
                        color: pinned ? "var(--accent)" : "var(--fg)",
                        fontSize: "12.5px",
                        fontWeight: pinned ? 600 : 500,
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {attachment.kind === "image"
                        ? pinned
                          ? "Image pinned"
                          : "Image attached"
                        : attachment.name || "Document"}
                    </span>
                  </div>
                  <div style={{ color: pinned ? "var(--fg-dim)" : "var(--fg-dimmer)", fontSize: "11px", marginTop: "2px" }}>
                    {attachment.kind === "image"
                      ? pinned
                        ? "sent with every message so follow-ups can see it"
                        : formatBytes(attachment.size)
                      : `${formatBytes(attachment.size)} · ${pinned ? "sent with every message so follow-ups can see it" : "sent with this message only"}`}
                  </div>
                </div>
                <button
                  onClick={() => onAttachmentChange(null)}
                  title={pinned ? "Stop sending this attachment" : "Remove attachment"}
                  aria-label={pinned ? "Unpin attachment" : "Remove attachment"}
                  style={{
                    background: pinned ? "transparent" : "var(--bg-3)",
                    border: `1px solid ${pinned ? "var(--accent-border)" : "var(--border)"}`,
                    borderRadius: "7px",
                    color: pinned ? "var(--accent)" : "var(--fg-dim)",
                    cursor: "pointer",
                    flexShrink: 0,
                    fontSize: "12px",
                    padding: "4px 10px",
                  }}
                >
                  {pinned ? "Unpin" : "Remove"}
                </button>
              </div>
            </div>
          )}

          <div
            style={{
              alignItems: "flex-end",
              background: "var(--bg-2)",
              border: "1px solid var(--border-2)",
              borderRadius: "14px",
              boxShadow: "var(--shadow-sm)",
              display: "flex",
              gap: "8px",
              padding: "8px 8px 8px 10px",
              transition: "border-color var(--t-base)",
            }}
            onDragOver={(e) => e.preventDefault()}
            onDrop={handleDrop}
            onFocusCapture={(e) => (e.currentTarget.style.borderColor = "var(--fg-dimmer)")}
            onBlurCapture={(e) => (e.currentTarget.style.borderColor = "var(--border-2)")}
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
                borderRadius: "9px",
                color: attachment ? "var(--fg)" : "var(--fg-dim)",
                cursor: disabled ? "not-allowed" : "pointer",
                display: "flex",
                flexShrink: 0,
                height: "32px",
                justifyContent: "center",
                width: "32px",
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
              placeholder={disabled ? "Waiting for response…" : "Ask anything"}
              rows={1}
              style={{
                background: "transparent",
                border: "none",
                color: "var(--fg)",
                flex: 1,
                fontFamily: "var(--font-sans)",
                fontSize: "13.5px",
                lineHeight: "20px",
                maxHeight: "200px",
                outline: "none",
                padding: "6px 0",
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
                borderRadius: "9px",
                color: canSend ? "var(--bg)" : "var(--fg-dimmer)",
                cursor: canSend ? "pointer" : "not-allowed",
                display: "flex",
                flexShrink: 0,
                height: "32px",
                justifyContent: "center",
                transition: "background var(--t-base)",
                width: "32px",
              }}
              aria-label="Send message"
            >
              <SendIcon />
            </button>
          </div>

          {isGenerating && (
            <div style={{ display: "flex", justifyContent: "flex-end", marginTop: "9px" }}>
              <button
                onClick={onStop}
                style={{
                  alignItems: "center",
                  background: "transparent",
                  border: "1px solid var(--border-2)",
                  borderRadius: "999px",
                  color: "var(--fg-dim)",
                  cursor: "pointer",
                  display: "inline-flex",
                  fontSize: "11.5px",
                  fontWeight: 500,
                  gap: "6px",
                  height: "26px",
                  padding: "0 11px",
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.color = "var(--fg)";
                  e.currentTarget.style.borderColor = "var(--fg-dimmer)";
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.color = "var(--fg-dim)";
                  e.currentTarget.style.borderColor = "var(--border-2)";
                }}
              >
                <svg width="11" height="11" viewBox="0 0 16 16" fill="currentColor">
                  <rect x="4" y="4" width="8" height="8" rx="1.5" />
                </svg>
                Stop
              </button>
            </div>
          )}

          <div style={{ alignItems: "center", display: "flex", margin: "9px 4px 0" }}>
            <div style={{ color: "var(--fg-dimmer)", fontSize: "11px" }}>
              Enter to send · Shift + Enter for a new line · drop a file to attach
            </div>
            <div style={{ flex: 1 }} />
            <div style={{ color: "var(--fg-dimmer)", fontSize: "11px" }}>
              Answers can be wrong — check anything that matters.
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function AttachIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path d="M13 6.5l-5.5 5.5a2.5 2.5 0 0 1-3.5-3.5l5.5-5.5a1.5 1.5 0 0 1 2 2L6 10.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function PinIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" strokeLinecap="round">
      <path d="M6 1.9h4l-.5 4.2 2.6 2.6H3.9l2.6-2.6L6 1.9z" />
      <path d="M8 8.7v5.4" />
    </svg>
  );
}

function DocumentIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round">
      <path d="M9.5 1.6H4a1 1 0 0 0-1 1v10.8a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1V5.1L9.5 1.6z" />
      <path d="M9.5 1.6v3.5H13" />
    </svg>
  );
}

function SendIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M8 13.2V3.4" />
      <path d="M3.7 7.7 8 3.4l4.3 4.3" />
    </svg>
  );
}
