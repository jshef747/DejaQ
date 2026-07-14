"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Key, Copy, Check, Trash2 } from "lucide-react";
import Modal from "@/components/Modal";
import ConfirmDialog from "@/components/ConfirmDialog";
import Button from "@/components/ui/Button";
import Pill from "@/components/ui/Pill";
import EmptyState from "@/components/ui/EmptyState";
import SectionHeader from "@/components/ui/SectionHeader";
import { deleteRevokedKey, generateKey, revokeKey } from "@/app/actions/keys";
import type { ApiKeyCreated, ApiKeyItem } from "@/lib/types";

const fmt = new Intl.DateTimeFormat("en-US", { year: "numeric", month: "short", day: "numeric" });

interface Props {
  orgSlug: string;
  keys: ApiKeyItem[];
  error: string | null;
}

export default function KeysClient({ orgSlug, keys, error }: Props) {
  const router = useRouter();

  const [generateOpen, setGenerateOpen] = useState(false);
  const [generateBusy, setGenerateBusy] = useState(false);
  const [generateErr, setGenerateErr] = useState<string | null>(null);
  const [generateConflict, setGenerateConflict] = useState(false);

  const [newKey, setNewKey] = useState<ApiKeyCreated | null>(null);
  const [copied, setCopied] = useState(false);

  const [confirmRevokeId, setConfirmRevokeId] = useState<number | null>(null);
  const [revokeBusy, setRevokeBusy] = useState(false);
  const [revokeErr, setRevokeErr] = useState<string | null>(null);

  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteErr, setDeleteErr] = useState<string | null>(null);

  async function handleGenerate(force = false) {
    setGenerateBusy(true);
    setGenerateErr(null);
    setGenerateConflict(false);
    const res = await generateKey(orgSlug, force);
    setGenerateBusy(false);
    if (!res.ok) {
      setGenerateErr(res.error);
      if (res.conflict) setGenerateConflict(true);
      return;
    }
    setGenerateOpen(false);
    setNewKey(res.key);
  }

  async function handleRevoke(keyId: number) {
    setRevokeBusy(true);
    setRevokeErr(null);
    const res = await revokeKey(keyId);
    setRevokeBusy(false);
    if (!res.ok) { setRevokeErr(res.error); return; }
    setConfirmRevokeId(null);
    router.refresh();
  }

  async function handleDelete(keyId: number) {
    setDeleteBusy(true);
    setDeleteErr(null);
    const res = await deleteRevokedKey(keyId);
    setDeleteBusy(false);
    if (!res.ok) { setDeleteErr(res.error); return; }
    setConfirmDeleteId(null);
    router.refresh();
  }

  function openGenerate() {
    setGenerateErr(null);
    setGenerateConflict(false);
    setGenerateOpen(true);
  }

  async function handleCopy() {
    if (!newKey) return;
    await navigator.clipboard.writeText(newKey.token);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  function closeReveal() {
    setNewKey(null);
    setCopied(false);
    router.refresh();
  }

  const confirmRevokeKey = keys.find((k) => k.id === confirmRevokeId);
  const confirmDeleteKey = keys.find((k) => k.id === confirmDeleteId);

  return (
    <div className="ds-page">
      <SectionHeader
        title="API Keys"
        subtitle={`Keys for org ${orgSlug}`}
        action={<Button variant="primary" onClick={openGenerate}>+ Generate key</Button>}
      />

      {(error || revokeErr || deleteErr) && (
        <div className="ds-pill ds-pill-err" style={{ marginBottom: 16, padding: "8px 12px", borderRadius: 5, fontSize: 12 }}>
          {error ?? revokeErr ?? deleteErr}
        </div>
      )}

      {keys.length === 0 && !error ? (
        <div className="ds-table-wrap">
          <EmptyState
            icon={Key}
            title="No API keys yet"
            description="Generate a key to start using the gateway."
            action={<Button variant="primary" onClick={openGenerate}>+ Generate key</Button>}
          />
        </div>
      ) : (
        <div className="ds-table-wrap">
          <table className="ds-table">
            <thead>
              <tr>
                <th>Key</th>
                <th>Created</th>
                <th>Status</th>
                <th style={{ width: 60 }} />
              </tr>
            </thead>
            <tbody>
              {keys.map((key) => {
                const isRevoked = key.revoked_at !== null;
                return (
                  <tr key={key.id}>
                    <td>
                      <code className="ds-mono" style={{ color: "var(--fg)" }}>
                        {key.token_prefix}<span style={{ color: "var(--fg-dimmer)" }}>••••••••</span>
                      </code>
                    </td>
                    <td className="ds-dim" style={{ fontSize: 12 }}>{fmt.format(new Date(key.created_at))}</td>
                    <td>
                      <Pill variant={isRevoked ? "neutral" : "hit"}>
                        {isRevoked ? "revoked" : "active"}
                      </Pill>
                    </td>
                    <td style={{ textAlign: "right" }}>
                      {isRevoked ? (
                        <Button
                          variant="ghost-danger"
                          size="sm"
                          onClick={() => { setDeleteErr(null); setConfirmDeleteId(key.id); }}
                          aria-label={`Delete revoked key ${key.token_prefix}`}
                          title={`Delete revoked key ${key.token_prefix}`}
                        >
                          <Trash2 size={12} />
                        </Button>
                      ) : (
                        <Button
                          variant="ghost-danger"
                          size="sm"
                          onClick={() => { setRevokeErr(null); setConfirmRevokeId(key.id); }}
                          aria-label={`Revoke key ${key.token_prefix}`}
                          title={`Revoke key ${key.token_prefix}`}
                        >
                          <Trash2 size={12} />
                        </Button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Generate modal */}
      <Modal
        open={generateOpen}
        onClose={() => setGenerateOpen(false)}
        title="Generate API key"
        subtitle={`New key for org ${orgSlug}`}
        footer={
          <>
            <Button onClick={() => setGenerateOpen(false)} disabled={generateBusy}>Cancel</Button>
            <Button variant="primary" onClick={() => handleGenerate(false)} loading={generateBusy}>Generate</Button>
          </>
        }
      >
        <p style={{ color: "var(--fg-dim)", fontSize: 12, margin: "0 0 12px" }}>
          The full key will be shown once — copy it before closing.
        </p>

        {generateConflict && (
          <div style={{ background: "var(--amber-bg)", border: "1px solid var(--amber-border)", borderRadius: 5, padding: "10px 12px", marginBottom: 10 }}>
            <p style={{ margin: "0 0 8px", fontSize: 12, color: "var(--fg)" }}>
              An active key already exists for this org.
            </p>
            <Button variant="ghost-danger" size="sm" onClick={() => handleGenerate(true)} loading={generateBusy}>
              Rotate (revoke &amp; replace)
            </Button>
          </div>
        )}

        {generateErr && !generateConflict && (
          <p style={{ color: "var(--red)", fontSize: 11, margin: 0 }}>{generateErr}</p>
        )}
      </Modal>

      {/* One-time reveal modal */}
      <Modal
        open={newKey !== null}
        onClose={closeReveal}
        title="Your new API key"
        subtitle="This is the only time this key will be shown."
        widthPx={480}
        footer={<Button onClick={closeReveal}>Done</Button>}
      >
        <div style={{ background: "var(--amber-bg)", border: "1px solid var(--amber-border)", borderRadius: 5, padding: "8px 12px", marginBottom: 12, fontSize: 12, color: "var(--fg)" }}>
          Copy it now — you cannot retrieve it later.
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 10, background: "var(--bg-3)", border: "1px solid var(--border-2)", borderRadius: 5, padding: "10px 12px" }}>
          <code style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--accent)", flex: 1, overflowWrap: "break-word", wordBreak: "break-all", userSelect: "all" }}>
            {newKey?.token}
          </code>
          <Button size="sm" onClick={handleCopy} style={{ flexShrink: 0, gap: 5 }}>
            {copied ? <><Check size={11} style={{ color: "var(--green)" }} />Copied</> : <><Copy size={11} />Copy</>}
          </Button>
        </div>
      </Modal>

      {/* Revoke confirm */}
      <ConfirmDialog
        open={!!confirmRevokeId}
        title="Revoke API key"
        message={`Revoke key ${confirmRevokeKey?.token_prefix ?? ""}? It will stop working immediately and cannot be re-activated.`}
        confirmLabel="Revoke"
        destructive
        busy={revokeBusy}
        onCancel={() => setConfirmRevokeId(null)}
        onConfirm={() => confirmRevokeId !== null && handleRevoke(confirmRevokeId)}
      />

      {/* Delete revoked confirm */}
      <ConfirmDialog
        open={!!confirmDeleteId}
        title="Delete revoked API key"
        message={`Permanently delete revoked key ${confirmDeleteKey?.token_prefix ?? ""}? This only removes the old dashboard record and cannot be undone.`}
        confirmLabel="Delete"
        destructive
        busy={deleteBusy}
        onCancel={() => setConfirmDeleteId(null)}
        onConfirm={() => confirmDeleteId !== null && handleDelete(confirmDeleteId)}
      />
    </div>
  );
}
