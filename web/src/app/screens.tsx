import { isRouteErrorResponse, Link, useRouteError } from "react-router";
import { RotateCw, Terminal } from "lucide-react";
import { LogoMark } from "@/components/shell/Logo";
import { Button, buttonVariants } from "@/components/ui/Button";
import { EmptyState, EmptyArt } from "@/components/ui/EmptyState";
import { Page } from "@/components/shell/Page";

/** Full-screen splash while the app boots (fonts, health, lazy route). */
export function BootScreen() {
  return (
    <div className="grid min-h-dvh place-items-center bg-canvas" role="status" aria-label="Loading Ordnung">
      <div className="flex flex-col items-center gap-4">
        <LogoMark className="size-11 animate-pulse-soft motion-reduce:animate-none" />
        <span className="sr-only">Loading…</span>
      </div>
    </div>
  );
}

/**
 * Shown when the local API cannot be used: not running (network error / 5xx), or this tab has no
 * session (401/403 — open the link printed by `ordnung serve`).
 */
export function UnreachableScreen({ onRetry, retrying, status }: { onRetry: () => void; retrying?: boolean; status?: number }) {
  const noSession = status === 401 || status === 403;
  return (
    <div className="grid min-h-dvh place-items-center bg-canvas px-4">
      <div className="card flex w-full max-w-md flex-col items-center px-6 py-10 text-center sm:px-10">
        <EmptyArt kind="error" />
        <h1 className="display mt-5 text-2xl font-semibold text-ink">{noSession ? "Please open Ordnung from its link" : "Ordnung isn't running"}</h1>
        <p className="mt-2 text-base leading-relaxed text-muted">
          {noSession
            ? "For your privacy, Ordnung only talks to the browser tab it opened itself. Run the command below and use the link it prints (or opens)."
            : "This page talks to the Ordnung app on your computer, and it didn't answer. Start it again in your terminal, then try again."}
        </p>
        <div className="mt-5 flex flex-wrap justify-center gap-2">
          {["ordnung serve", "ordnung demo"].map((cmd) => (
            <code key={cmd} className="inline-flex items-center gap-2 rounded-lg bg-surface-2 px-3 py-2 font-mono text-[13px] text-ink">
              <Terminal className="size-4 text-muted" aria-hidden />
              {cmd}
            </code>
          ))}
        </div>
        <Button variant="primary" icon={RotateCw} className="mt-6" onClick={onRetry} loading={retrying}>
          Try again
        </Button>
      </div>
    </div>
  );
}

/** 404 inside the shell. */
export function NotFound() {
  return (
    <Page title="Not found" width="narrow">
      <EmptyState
        className="mt-10"
        headingLevel={1}
        illustration="search"
        title="This page doesn't exist"
        description="The link may be old, or the letter was deleted. Everything else is where you left it."
        action={
          <Link to="/" className={buttonVariants({ variant: "primary" })}>
            Back to Today
          </Link>
        }
      />
    </Page>
  );
}

/** Route error boundary: friendly message, technical details folded away. */
export function RouteError({ fullScreen }: { fullScreen?: boolean }) {
  const error = useRouteError();
  if (isRouteErrorResponse(error) && error.status === 404) return <NotFound />;
  const message = error instanceof Error ? error.message : isRouteErrorResponse(error) ? `${error.status} ${error.statusText}` : String(error);
  const body = (
    <div className="card mx-auto flex w-full max-w-lg flex-col items-center px-6 py-10 text-center sm:px-10">
      <EmptyArt kind="error" />
      <h1 className="display mt-5 text-2xl font-semibold text-ink">Something went wrong on this page</h1>
      <p className="mt-2 text-base leading-relaxed text-muted">
        Your letters and dates are safe — this is only a display problem. Reloading usually helps.
      </p>
      <div className="mt-6 flex flex-wrap justify-center gap-2">
        <Button variant="primary" icon={RotateCw} onClick={() => window.location.reload()}>
          Reload
        </Button>
        <Link to="/" className={buttonVariants({ variant: "secondary" })}>
          Go to Today
        </Link>
      </div>
      <details className="mt-6 w-full text-left text-xs text-muted">
        <summary className="cursor-pointer select-none text-center">Technical details</summary>
        <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap rounded-lg bg-surface-2 p-3 font-mono text-[11.5px] text-ink/80">{message}</pre>
      </details>
    </div>
  );
  return fullScreen ? <div className="grid min-h-dvh place-items-center bg-canvas px-4">{body}</div> : <div className="px-4 py-12">{body}</div>;
}
