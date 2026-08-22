"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { BookOpen, FileText, Globe, Image as ImageIcon, Trash2, Upload } from "lucide-react";
import Modal from "@/components/Modal";
import ConfirmDialog from "@/components/ConfirmDialog";
import Button from "@/components/ui/Button";
import Pill from "@/components/ui/Pill";
import Field from "@/components/ui/Field";
import Input from "@/components/ui/Input";
import EmptyState from "@/components/ui/EmptyState";
import SectionHeader from "@/components/ui/SectionHeader";
import { addRagText, addRagUrl, deleteRagDocument, uploadRagFile } from "@/app/actions/rag";
import type { RagDocumentItem } from "@/lib/types";

const fmt = new Intl.DateTimeFormat("en-US", { year: "numeric", month: "short", day: "numeric" });
const MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024; // mirrors server DEJAQ_MAX_ATTACHMENT_BYTES
// Ingestion (chunk embedding) now runs as a background job — this polls the
// catalog for real progress while anything is still "processing". Boring on
// purpose: it's just the existing list endpoint, on a timer.
const POLL_INTERVAL_MS = 1200;

const KIND_ICON: Record<string, typeof FileText> = {
  url: Globe,
  image: ImageIcon,
};

interface Props {
  workspaceSlug: string;
  docs: RagDocumentItem[];
  error: string | null;
}

export default function RagClient({ workspaceSlug, docs, error }: Props) {
  const router = useRouter();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [textOpen, setTextOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [textBusy, setTextBusy] = useState(false);
  const [textErr, setTextErr] = useState<string | null>(null);

  const [urlOpen, setUrlOpen] = useState(false);
  const [url, setUrl] = useState("");
  const [urlTitle, setUrlTitle] = useState("");
  const [urlBusy, setUrlBusy] = useState(false);
  const [urlErr, setUrlErr] = useState<string | null>(null);

  const [uploadBusy, setUploadBusy] = useState(false);
  const [uploadErr, setUploadErr] = useState<string | null>(null);
  const [dragActive, setDragActive] = useState(false);

  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteErr, setDeleteErr] = useState<string | null>(null);

  const [toasts, setToasts] = useState<{ id: string; text: string }[]>([]);
  const prevStatusRef = useRef<Map<number, string>>(new Map());

  const banner = error || uploadErr || deleteErr;

  // A document still ingesting must not look done, and a document that just
  // finished must say so — this is the whole point of this page's redesign.
  // Detected by diffing each poll's statuses against the last one seen.
  useEffect(() => {
    const prev = prevStatusRef.current;
    const next = new Map<number, string>();
    for (const doc of docs) {
      const was = prev.get(doc.id);
      if (was === "processing" && doc.status === "ready") {
        const id = `${doc.id}-${doc.updated_at}`;
        const count = doc.chunk_count.toLocaleString();
        setToasts((t) => [
          ...t,
          { id, text: `"${doc.title}" is now searchable — ${count} chunk${doc.chunk_count === 1 ? "" : "s"} indexed.` },
        ]);
        setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 6000);
      }
      next.set(doc.id, doc.status);
    }
    prevStatusRef.current = next;
  }, [docs]);

  const anyProcessing = docs.some((d) => d.status === "processing");
  useEffect(() => {
    if (!anyProcessing) return;
    const id = setInterval(() => router.refresh(), POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [anyProcessing, router]);

  async function handleAddText() {
    setTextBusy(true);
    setTextErr(null);
    const res = await addRagText(workspaceSlug, title, content);
    setTextBusy(false);
    if (!res.ok) { setTextErr(res.error); return; }
    setTextOpen(false);
    setTitle("");
    setContent("");
    router.refresh();
  }

  async function handleAddUrl() {
    setUrlBusy(true);
    setUrlErr(null);
    const res = await addRagUrl(workspaceSlug, url, urlTitle || undefined);
    setUrlBusy(false);
    if (!res.ok) { setUrlErr(res.error); return; }
    setUrlOpen(false);
    setUrl("");
    setUrlTitle("");
    router.refresh();
  }

  async function ingestFile(file: File) {
    setUploadErr(null);
    if (file.size > MAX_ATTACHMENT_BYTES) {
      setUploadErr(`"${file.name}" is larger than 10 MB.`);
      return;
    }
    setUploadBusy(true);
    try {
      const form = new FormData();
      form.append("file", file);
      const res = await uploadRagFile(workspaceSlug, form);
      if (!res.ok) { setUploadErr(res.error); return; }
      router.refresh();
    } catch (e) {
      // A Server Action can throw outright (e.g. a body-size-limit rejection)
      // instead of returning {ok:false}; without this the button was left
      // spinning forever with no error ever shown.
      setUploadErr((e as Error).message || "Upload failed unexpectedly.");
    } finally {
      setUploadBusy(false);
    }
  }

  function handleFilePick(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) ingestFile(file);
    e.target.value = ""; // allow re-picking the same file
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragActive(false);
    const file = e.dataTransfer.files?.[0];
    if (file) ingestFile(file);
  }

  async function handleDelete(docId: number) {
    setDeleteBusy(true);
    setDeleteErr(null);
    const res = await deleteRagDocument(workspaceSlug, docId);
    setDeleteBusy(false);
    if (!res.ok) { setDeleteErr(res.error); return; }
    setConfirmDeleteId(null);
    router.refresh();
  }

  const confirmDeleteDoc = docs.find((d) => d.id === confirmDeleteId);

  return (
    <div
      className="ds-page"
      onDragOver={(e) => { e.preventDefault(); setDragActive(true); }}
      onDragLeave={() => setDragActive(false)}
      onDrop={handleDrop}
      style={dragActive ? { outline: "2px dashed var(--accent)", outlineOffset: -8, borderRadius: 8 } : undefined}
    >
      <SectionHeader
        title="Knowledge Base"
        subtitle={`Curated knowledge for workspace ${workspaceSlug} — grounds answers on a cache miss`}
        action={
          <div style={{ display: "flex", gap: 8 }}>
            <Button onClick={() => { setUrlErr(null); setUrlOpen(true); }}>+ URL</Button>
            <Button onClick={() => { setTextErr(null); setTextOpen(true); }}>+ Text</Button>
            <Button variant="primary" loading={uploadBusy} onClick={() => fileInputRef.current?.click()}>
              <Upload size={12} style={{ marginRight: 5 }} />Upload file
            </Button>
          </div>
        }
      />

      <input
        ref={fileInputRef}
        type="file"
        style={{ display: "none" }}
        onChange={handleFilePick}
      />

      {banner && (
        <div className="ds-pill ds-pill-err" style={{ marginBottom: 16, padding: "8px 12px", borderRadius: 5, fontSize: 12 }}>
          {banner}
        </div>
      )}

      {toasts.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 16 }}>
          {toasts.map((t) => (
            <div key={t.id} className="ds-pill ds-pill-green" style={{ padding: "8px 12px", borderRadius: 5, fontSize: 12 }}>
              {t.text}
            </div>
          ))}
        </div>
      )}

      {docs.length === 0 && !error ? (
        <div className="ds-table-wrap">
          <EmptyState
            icon={BookOpen}
            title="No knowledge yet"
            description="Add text, a URL, or upload a document (PDF, DOCX, text, or an image to OCR). Drag a file anywhere on this page to upload it."
            action={
              <Button variant="primary" loading={uploadBusy} onClick={() => fileInputRef.current?.click()}>
                <Upload size={12} style={{ marginRight: 5 }} />Upload file
              </Button>
            }
          />
        </div>
      ) : (
        <div className="ds-table-wrap">
          <table className="ds-table">
            <thead>
              <tr>
                <th>Title</th>
                <th>Type</th>
                <th>Chars</th>
                <th>Chunks</th>
                <th>Added</th>
                <th style={{ width: 60 }} />
              </tr>
            </thead>
            <tbody>
              {docs.map((doc) => {
                const Icon = KIND_ICON[doc.kind] ?? FileText;
                return (
                  <tr key={doc.id}>
                    <td>
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <Icon size={13} style={{ color: "var(--fg-dimmer)", flexShrink: 0 }} />
                        <span style={{ color: "var(--fg)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: 320 }} title={doc.source_ref ?? doc.title}>
                          {doc.title}
                        </span>
                      </div>
                    </td>
                    <td>
                      <Pill variant="neutral">{doc.kind}{doc.source === "ocr" ? " · ocr" : ""}</Pill>
                    </td>
                    <td className="ds-dim" style={{ fontSize: 12 }}>{doc.char_count.toLocaleString()}</td>
                    <td style={{ fontSize: 12, minWidth: 150 }}>
                      {doc.status === "processing" ? (
                        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                          <span className="ds-dim">
                            {doc.progress_total
                              ? `embedding ${doc.progress_current.toLocaleString()} / ${doc.progress_total.toLocaleString()} chunks`
                              : "starting…"}
                          </span>
                          <div style={{ height: 4, borderRadius: 2, background: "var(--border)", overflow: "hidden" }}>
                            <div
                              style={{
                                height: "100%",
                                width: doc.progress_total
                                  ? `${Math.min(100, (doc.progress_current / doc.progress_total) * 100)}%`
                                  : "3%",
                                background: "var(--accent)",
                                transition: "width 0.3s ease",
                              }}
                            />
                          </div>
                        </div>
                      ) : doc.status === "failed" ? (
                        <div>
                          <Pill variant="err">failed</Pill>
                          {doc.error_message && (
                            <div
                              className="ds-dim"
                              style={{ fontSize: 11, marginTop: 3, maxWidth: 260, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                              title={doc.error_message}
                            >
                              {doc.error_message}
                            </div>
                          )}
                        </div>
                      ) : (
                        <span className="ds-dim">{doc.chunk_count}</span>
                      )}
                    </td>
                    <td className="ds-dim" style={{ fontSize: 12 }}>{fmt.format(new Date(doc.created_at))}</td>
                    <td style={{ textAlign: "right" }}>
                      <Button
                        variant="ghost-danger"
                        size="sm"
                        onClick={() => { setDeleteErr(null); setConfirmDeleteId(doc.id); }}
                        aria-label={`Delete ${doc.title}`}
                        title={`Delete ${doc.title}`}
                      >
                        <Trash2 size={12} />
                      </Button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Add text modal */}
      <Modal
        open={textOpen}
        onClose={() => setTextOpen(false)}
        title="Add text knowledge"
        subtitle="Paste information the assistant should know about this workspace."
        widthPx={520}
        footer={
          <>
            <Button onClick={() => setTextOpen(false)} disabled={textBusy}>Cancel</Button>
            <Button variant="primary" onClick={handleAddText} loading={textBusy} disabled={!title.trim() || !content.trim()}>Add</Button>
          </>
        }
      >
        <Field label="Title" required>
          <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Refund policy" />
        </Field>
        <Field label="Content" required error={textErr ?? undefined}>
          <textarea
            className="ds-input ds-input-sans"
            value={content}
            onChange={(e) => setContent(e.target.value)}
            placeholder="Paste the knowledge text here…"
            rows={8}
            style={{ resize: "vertical", minHeight: 120, fontFamily: "inherit" }}
          />
        </Field>
      </Modal>

      {/* Add URL modal */}
      <Modal
        open={urlOpen}
        onClose={() => setUrlOpen(false)}
        title="Add a web page"
        subtitle="DejaQ fetches the page and stores its readable text."
        widthPx={520}
        footer={
          <>
            <Button onClick={() => setUrlOpen(false)} disabled={urlBusy}>Cancel</Button>
            <Button variant="primary" onClick={handleAddUrl} loading={urlBusy} disabled={!url.trim()}>Fetch &amp; add</Button>
          </>
        }
      >
        <Field label="URL" required error={urlErr ?? undefined}>
          <Input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://example.com/docs" mono />
        </Field>
        <Field label="Title" hint="Optional — defaults to the page title.">
          <Input value={urlTitle} onChange={(e) => setUrlTitle(e.target.value)} placeholder="e.g. Product docs" />
        </Field>
      </Modal>

      {/* Delete confirm */}
      <ConfirmDialog
        open={!!confirmDeleteId}
        title="Delete knowledge document"
        message={`Delete "${confirmDeleteDoc?.title ?? ""}"? Its chunks are removed from the knowledge base and it will no longer ground answers. This cannot be undone.`}
        confirmLabel="Delete"
        destructive
        busy={deleteBusy}
        onCancel={() => setConfirmDeleteId(null)}
        onConfirm={() => confirmDeleteId !== null && handleDelete(confirmDeleteId)}
      />
    </div>
  );
}
