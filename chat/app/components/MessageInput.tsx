"use client";

import { useEffect, useRef } from "react";

// Reject files larger than this before base64-encoding — keeps the request body
// and localStorage sane. CLIP downsizes to 224px anyway, so this loses nothing.
const MAX_IMAGE_BYTES = 10 * 1024 * 1024;

interface Props {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  disabled: boolean;
  image: string | null;
  onImageChange: (dataUrl: string | null) => void;
  onImageError?: (message: string) => void;
}

export default function MessageInput({
  value,
  onChange,
  onSend,
  disabled,
  image,
  onImageChange,
  onImageError,
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

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    // Enter alone sends; Shift+Enter inserts a newline.
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (canSend) onSend();
    }
  }

  function attachImageFile(file: File) {
    if (!file.type.startsWith("image/")) {
      onImageError?.("Only image files can be attached.");
      return;
    }
    if (file.size > MAX_IMAGE_BYTES) {
      onImageError?.("Image is too large (max 10 MB).");
      return;
    }
    const reader = new FileReader();
    reader.onload = () => onImageChange(typeof reader.result === "string" ? reader.result : null);
    reader.onerror = () => onImageError?.("Could not read that image.");
    reader.readAsDataURL(file);
  }

  function handleFilePick(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = ""; // allow re-picking the same file
    if (file) attachImageFile(file);
  }

  function handlePaste(e: React.ClipboardEvent<HTMLTextAreaElement>) {
    // Grab the first image in the clipboard (screenshots, copied image files).
    // Let text paste through untouched by only acting when an image is present.
    const imageItem = Array.from(e.clipboardData.items).find((i) => i.type.startsWith("image/"));
    const file = imageItem?.getAsFile();
    if (file) {
      e.preventDefault();
      attachImageFile(file);
    }
  }

  const canSend = !disabled && (value.trim().length > 0 || image != null);

  return (
    <div
      style={{
        background: "var(--bg-2)",
        borderTop: "1px solid var(--border)",
        padding: "12px 16px",
      }}
    >
      {image && (
        <div
          style={{
            alignItems: "center",
            background: "var(--bg)",
            border: "1px solid var(--border-2)",
            borderRadius: "8px",
            display: "flex",
            gap: "10px",
            marginBottom: "8px",
            padding: "8px 10px",
          }}
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={image}
            alt="Attached"
            style={{ borderRadius: "6px", height: "44px", objectFit: "cover", width: "44px" }}
          />
          <span style={{ color: "var(--fg-dim)", flex: 1, fontSize: "12px" }}>
            Image attached
          </span>
          <button
            onClick={() => onImageChange(null)}
            title="Remove image"
            aria-label="Remove attached image"
            style={{
              background: "var(--bg-3)",
              border: "1px solid var(--border)",
              borderRadius: "5px",
              color: "var(--fg-dim)",
              cursor: "pointer",
              fontSize: "12px",
              padding: "3px 8px",
            }}
          >
            Remove
          </button>
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
        onFocusCapture={(e) =>
          (e.currentTarget.style.borderColor = "var(--accent-border)")
        }
        onBlurCapture={(e) =>
          (e.currentTarget.style.borderColor = "var(--border-2)")
        }
      >
        <input
          ref={fileInputRef}
          type="file"
          accept="image/*"
          onChange={handleFilePick}
          style={{ display: "none" }}
        />
        <button
          onClick={() => fileInputRef.current?.click()}
          disabled={disabled}
          title="Attach image"
          aria-label="Attach image"
          style={{
            alignItems: "center",
            background: "transparent",
            border: "none",
            borderRadius: "6px",
            color: image ? "var(--accent)" : "var(--fg-dim)",
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
          placeholder={disabled ? "Waiting for response…" : "Ask anything… (Enter to send, paste an image to attach)"}
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
            background: canSend ? "var(--accent)" : "var(--bg-3)",
            border: "none",
            borderRadius: "6px",
            color: canSend ? "#1a0d00" : "var(--fg-dimmer)",
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

function SendIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 16 16" fill="currentColor">
      <path d="M14.5 1.5L7 9M14.5 1.5L10 14.5l-3-5.5L1.5 6l13-4.5z" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" fill="none" />
    </svg>
  );
}
