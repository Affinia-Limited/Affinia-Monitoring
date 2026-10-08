import { Component, type ErrorInfo, type ReactNode } from "react";
import { Button } from "./ui/button";
import { EmptyState } from "./ui/states";

/**
 * Contains a rendering failure to the area it wraps, so one broken page never blanks the whole app.
 * Pass a ``resetKey`` (e.g. the pathname) to recover automatically when the user navigates away.
 */
export class ErrorBoundary extends Component<{ children: ReactNode; resetKey?: string }, { error: Error | null; resetKey?: string }> {
  state: { error: Error | null; resetKey?: string } = { error: null, resetKey: this.props.resetKey };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  static getDerivedStateFromProps(props: { resetKey?: string }, state: { error: Error | null; resetKey?: string }) {
    return props.resetKey !== state.resetKey ? { error: null, resetKey: props.resetKey } : null;
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("render_failed", error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <EmptyState
        title="Something went wrong on this page"
        description="The rest of the dashboard still works. Reload to try again; if it keeps happening, contact your administrator."
        action={<Button onClick={() => window.location.reload()}>Reload</Button>}
      />
    );
  }
}
