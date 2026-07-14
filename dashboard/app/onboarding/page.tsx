export const dynamic = "force-dynamic";

import { listWorkspaces } from "@/app/actions/workspaces";
import OnboardingWizard from "./OnboardingWizard";

export default async function OnboardingPage() {
  // "Already onboarded?" is decided once, client-side, inside the wizard (see below).
  // We must NOT redirect here: creating the workspace in step 1 runs a server action, which
  // re-renders this Server Component — a server-side redirect would then fire mid-wizard and
  // skip the department + API-key steps.
  let hasWorkspaces = false;
  try {
    const workspaces = await listWorkspaces();
    hasWorkspaces = workspaces.length > 0;
  } catch {
    // Backend unavailable — show the wizard anyway; it will surface errors during submission.
  }

  return (
    <div
      style={{
        minHeight: "100dvh",
        background: "var(--bg)",
        color: "var(--fg)",
        display: "grid",
        placeItems: "center",
        padding: "40px 20px",
      }}
    >
      {/* Branding */}
      <div style={{ width: "100%", maxWidth: 480 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 40 }}>
          <div
            className="ds-logo-mark"
            style={{ width: 28, height: 28, fontSize: 15, fontFamily: "var(--font-mono)" }}
          >
            Dq
          </div>
          <span style={{ fontWeight: 600, fontSize: 16, letterSpacing: "-0.02em" }}>DejaQ</span>
        </div>

        <OnboardingWizard alreadyOnboarded={hasWorkspaces} />
      </div>
    </div>
  );
}
