"use client";

import { Component, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
}

// A bug in one stored conversation (bad shape, future schema drift) should
// degrade the sidebar, not white-screen the whole app - the chat pane and
// composer stay usable even if history can't render.
export class SidebarErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(): State {
    return { hasError: true };
  }

  render() {
    if (this.state.hasError) {
      return (
        <div
          style={{
            alignItems: "center",
            color: "var(--fg-dim)",
            display: "flex",
            fontSize: "13px",
            height: "100vh",
            justifyContent: "center",
            padding: "16px",
            width: "260px",
          }}
        >
          Conversation history couldn&apos;t load.
        </div>
      );
    }
    return this.props.children;
  }
}
