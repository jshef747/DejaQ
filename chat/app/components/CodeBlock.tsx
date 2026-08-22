"use client";

import { isValidElement, useState, type ReactNode } from "react";
import { copyText } from "./copy-text";

// react-markdown hands <pre> a single <code className="language-x"> child.
// Both the label and the copy text come from that child, so the block
// stays a plain <pre> in the DOM and only gains a head.
export function codeChild(children: ReactNode): { lang: string | null; text: string } {
  if (!isValidElement(children)) return { lang: null, text: "" };
  const props = children.props as { className?: string; children?: ReactNode };
  const match = /language-([\w+-]+)/.exec(props.className ?? "");
  return { lang: match ? match[1] : null, text: plainText(props.children) };
}

export function plainText(node: ReactNode): string {
  if (node === null || node === undefined || typeof node === "boolean") return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(plainText).join("");
  if (isValidElement(node)) return plainText((node.props as { children?: ReactNode }).children);
  return "";
}

type CopyState = "idle" | "copied" | "failed";

export default function CodeBlock({ children }: { children?: ReactNode }) {
  const [state, setState] = useState<CopyState>("idle");
  const { lang, text } = codeChild(children);

  function copy() {
    copyText(text).then((ok) => {
      setState(ok ? "copied" : "failed");
      setTimeout(() => setState("idle"), 1500);
    });
  }

  return (
    <div className="dq-code">
      <div className="dq-code-head">
        <span className="dq-code-lang">{lang ?? "Code"}</span>
        <div style={{ flex: 1 }} />
        <button
          type="button"
          className="dq-code-copy"
          data-state={state}
          onClick={copy}
          title="Copy code"
          aria-label="Copy code"
        >
          <CopyIcon />
          {state === "copied" ? "Copied" : state === "failed" ? "Copy failed" : "Copy"}
        </button>
      </div>
      <pre>{children}</pre>
    </div>
  );
}

function CopyIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round">
      <rect x="5.6" y="5.6" width="8.1" height="8.1" rx="1.5" />
      <path d="M10.6 5.6V3.4a1 1 0 0 0-1-1H3.3a1 1 0 0 0-1 1v6.3a1 1 0 0 0 1 1h2.3" />
    </svg>
  );
}
