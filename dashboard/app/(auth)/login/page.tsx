"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { signIn } from "@/app/actions/auth";
import Button from "@/components/ui/Button";
import Input from "@/components/ui/Input";
import Field from "@/components/ui/Field";

export default function LoginPage() {
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    const result = await signIn(new FormData(e.currentTarget));
    if (result?.error) {
      setError(result.error);
      setLoading(false);
    }
  }

  return (
    <div style={{ width: "100%", maxWidth: 360 }}>
      <h2 style={{ fontSize: 22, fontWeight: 600, letterSpacing: "-0.02em", margin: "0 0 6px" }}>
        Welcome back
      </h2>
      <p style={{ fontSize: 13, color: "var(--fg-dim)", margin: "0 0 24px" }}>
        Sign in to continue to DejaQ.
      </p>

      <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 0 }}>
        <Field label="Email" required>
          <Input
            name="email"
            type="email"
            required
            autoComplete="username email"
            placeholder="you@company.com"
            autoFocus
          />
        </Field>

        <Field
          label="Password"
          required
          labelRight={
            <span style={{ fontSize: 11, color: "var(--accent)", cursor: "default" }}>Forgot?</span>
          }
        >
          <Input
            name="password"
            type="password"
            required
            autoComplete="current-password"
            placeholder="••••••••"
            reveal
          />
        </Field>

        {error && (
          <div style={{
            background: "var(--red-bg)", border: "1px solid var(--red-border)",
            borderRadius: 5, padding: "8px 10px", color: "var(--red)",
            fontSize: 12, marginBottom: 10,
          }}>
            {error}
          </div>
        )}

        <Button
          type="submit"
          variant="primary"
          loading={loading}
          style={{ width: "100%", padding: "9px 12px", marginTop: 4, fontSize: 13 }}
        >
          Sign in
          {!loading && <ArrowRight size={13} />}
        </Button>
      </form>

      <p style={{ marginTop: 18, textAlign: "center", fontSize: 12.5, color: "var(--fg-dim)" }}>
        Don&apos;t have an account?{" "}
        <Link href="/signup" style={{ color: "var(--accent)", textDecoration: "none", fontWeight: 500 }}>
          Sign up
        </Link>
      </p>

      <p style={{ marginTop: 20, fontSize: 11, color: "var(--fg-dimmer)", textAlign: "center", lineHeight: 1.6 }}>
        By continuing you agree to our{" "}
        <a href="#" style={{ color: "var(--fg-dim)", textDecoration: "none" }}>Terms</a>{" "}
        and{" "}
        <a href="#" style={{ color: "var(--fg-dim)", textDecoration: "none" }}>Privacy Policy</a>.
      </p>
    </div>
  );
}
