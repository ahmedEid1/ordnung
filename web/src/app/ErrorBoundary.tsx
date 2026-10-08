import { Component, type ErrorInfo, type ReactNode } from "react";
import { clientKind } from "@/api/clientKind";
import { PHONE_SAFE } from "@/features/phone/copy";

interface State {
  error: Error | null;
}

/**
 * Last-resort boundary around the whole app (errors outside the router, e.g. in providers).
 * Route-level errors are handled by `RouteError` so the shell stays visible.
 */
export class AppErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("Ordnung crashed", error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="grid min-h-dvh place-items-center bg-canvas px-4 text-ink">
        <div className="card max-w-md px-8 py-10 text-center">
          <h1 className="display text-2xl font-semibold">Ordnung hit a snag</h1>
          <p className="mt-2 text-base text-muted">{clientKind() === "phone" ? PHONE_SAFE : "Your letters and dates are safe on this computer. Please reload the page."}</p>
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="mt-6 inline-flex h-9 items-center rounded-lg bg-accent px-4 text-base font-medium text-on-accent hover:bg-accent-strong"
          >
            Reload
          </button>
        </div>
      </div>
    );
  }
}
