import { useEffect, useState } from "react";
import { isRouteErrorResponse, Link, useRouteError } from "react-router";
import { Check, ChevronRight, Copy, Inbox, RotateCw } from "lucide-react";
import { ApiError } from "@/api/client";
import { LogoMark } from "@/components/shell/Logo";
import { Button, buttonVariants } from "@/components/ui/Button";
import { Spinner } from "@/components/ui/Spinner";
import { EmptyState, EmptyArt } from "@/components/ui/EmptyState";
import { technicalDetails } from "@/components/ui/LoadError";
import { Page } from "@/components/shell/Page";
import { CopyCommand } from "@/features/onboarding/CopyCommand";
import { useClipboard } from "@/features/today/clipboard";
import { cn } from "@/lib/utils";

/** The splash says "Starting Ordnung…" once loading takes longer than this (a fast start shows the logo only). */
export const BOOT_SLOW_MS = 1500;
/** …and asks whether Ordnung is running, with "Try again", after this long. */
export const BOOT_STUCK_MS = 10_000;

/**
 * Full-screen splash while the app boots (fonts, health, lazy route): the logo, then
 * "Starting Ordnung…" when it takes a moment, then "Still waiting — is Ordnung running?" with a
 * way to try again (a reload) when it takes too long.
 */
export function BootScreen({ onRetry = () => window.location.reload() }: { onRetry?: () => void }) {
  const [phase, setPhase] = useState<"quiet" | "slow" | "stuck">("quiet");
  useEffect(() => {
    const slow = setTimeout(() => setPhase("slow"), BOOT_SLOW_MS);
    const stuck = setTimeout(() => setPhase("stuck"), BOOT_STUCK_MS);
    return () => {
      clearTimeout(slow);
      clearTimeout(stuck);
    };
  }, []);
  const stuck = phase === "stuck";
  const heading = stuck ? "Still waiting — is Ordnung running?" : "Starting Ordnung…";
  return (
    <main className="grid min-h-dvh place-items-center bg-canvas px-4" aria-busy={!stuck}>
      <div className="flex max-w-sm flex-col items-center text-center">
        <LogoMark className={cn("size-11", !stuck && "animate-pulse-soft motion-reduce:animate-none")} />
        <h1 className={cn(phase === "quiet" ? "sr-only" : "display mt-5 text-balance text-xl font-semibold text-ink")}>{heading}</h1>
        {stuck ? (
          <>
            <p className="mt-2 text-pretty text-base leading-relaxed text-muted">
              Ordnung usually starts in a second or two. If you closed the terminal where it ran, start it again with{" "}
              <code className="whitespace-nowrap rounded bg-surface-2 px-1 font-mono text-[13px] text-ink">ordnung serve</code>.
            </p>
            <Button variant="primary" icon={RotateCw} className="mt-5" onClick={onRetry}>
              Try again
            </Button>
          </>
        ) : null}
        {/* the phases are announced as they change (the first one only once it shows) */}
        <p role="status" className="sr-only">
          {phase === "quiet" ? "" : heading}
        </p>
      </div>
    </main>
  );
}

/** The two ways to start Ordnung, named for what each opens. */
const START_COMMANDS = [
  { label: "Your letters", command: "ordnung serve", what: "start Ordnung with your letters" },
  { label: "Sample life", command: "ordnung demo", what: "open the sample life" },
] as const;

/**
 * Shown when the local API cannot be used: not running (network error / 5xx), or this tab has no
 * session (401/403 — open the link printed by `ordnung serve`).
 *
 * "Try again" stays put while it runs (a spinner, focus kept on it — it is `aria-disabled`, not
 * `disabled`, which would drop focus to the page), and a failed retry is said out loud.
 */
export function UnreachableScreen({
  onRetry,
  retrying,
  status,
  stillFailing,
}: {
  onRetry: () => void;
  retrying?: boolean;
  status?: number;
  /** A retry failed too: "Still can't reach Ordnung." */
  stillFailing?: boolean;
}) {
  const noSession = status === 401 || status === 403;
  return (
    <main className="grid min-h-dvh place-items-center bg-canvas px-4 py-8">
      <div className="card flex w-full max-w-md flex-col items-center px-5 py-10 text-center sm:px-10">
        <EmptyArt kind="error" />
        <h1 className="display mt-5 text-balance text-2xl font-semibold text-ink">{noSession ? "Please open Ordnung from its link" : "Ordnung isn't running"}</h1>
        <p className="mt-2 text-pretty text-base leading-relaxed text-muted">
          {noSession
            ? "For your privacy, Ordnung only talks to the browser tab it opened itself. Run one of these commands in a terminal and use the link it prints (or opens)."
            : "This page talks to the Ordnung app on your computer, and it didn't answer. Start it again with one of these commands, then try again."}
        </p>
        <ul className="mt-5 w-full space-y-3 text-left">
          {START_COMMANDS.map((c) => (
            <li key={c.command}>
              <p className="mb-1 text-sm font-medium text-ink">{c.label}</p>
              <CopyCommand command={c.command} label={c.what} />
            </li>
          ))}
        </ul>
        <Button
          variant="primary"
          icon={retrying ? undefined : RotateCw}
          // a long label may take two lines on a narrow phone instead of pushing the card wider
          className="mt-6 h-auto min-h-9 max-w-full whitespace-normal py-1.5 text-balance"
          aria-disabled={retrying || undefined}
          aria-busy={retrying || undefined}
          onClick={() => {
            if (!retrying) onRetry();
          }}
        >
          {retrying ? <Spinner className="size-4" /> : null}
          <span>{noSession ? "I opened the link — check again" : "Try again"}</span>
        </Button>
        <p role="status" className="mt-3 min-h-5 text-sm text-muted">
          {retrying ? "Trying again…" : stillFailing ? (noSession ? "Still no access from this tab." : "Still can't reach Ordnung.") : ""}
        </p>
      </div>
    </main>
  );
}

/**
 * The shell's "can't reach the API" state. TanStack clears the error while "Try again" refetches,
 * so the last error's status is kept here: the card doesn't flip between its two messages.
 */
export function HealthUnreachable({ error, retrying, failures, onRetry }: { error: unknown; retrying: boolean; failures: number; onRetry: () => void }) {
  const status = error instanceof ApiError ? error.status : undefined;
  const [lastStatus, setLastStatus] = useState(status);
  if (error && status !== lastStatus) setLastStatus(status);
  return <UnreachableScreen onRetry={onRetry} retrying={retrying} status={error ? status : lastStatus} stillFailing={failures > 1} />;
}

/** The way back from a page that isn't there or broke (one label everywhere). */
const BACK_TO_TODAY = "Back to Today";

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
          <>
            <Link to="/" className={buttonVariants({ variant: "primary" })}>
              {BACK_TO_TODAY}
            </Link>
            <Link to="/inbox" className={buttonVariants({ variant: "secondary" })}>
              <Inbox aria-hidden />
              Open Inbox
            </Link>
          </>
        }
      />
    </Page>
  );
}

/** "Technical details": the error behind a disclosure (a real 32 px target), with a Copy button for a report. */
export function TechnicalDetails({ text, className }: { text: string; className?: string }) {
  const { copy, copied } = useClipboard();
  const done = copied === text;
  return (
    <details className={cn("group mt-5 w-full max-w-sm text-left", className)}>
      <summary className="mx-auto flex min-h-8 w-fit cursor-pointer list-none items-center gap-1 rounded-md px-2 text-sm font-medium text-muted hover:text-ink [&::-webkit-details-marker]:hidden">
        <ChevronRight className="size-3.5 transition-transform group-open:rotate-90 motion-reduce:transition-none" aria-hidden />
        Technical details
      </summary>
      <div className="mt-2 rounded-lg bg-surface-2 p-3">
        <pre className="max-h-48 overflow-auto whitespace-pre-wrap font-mono text-xs leading-5 text-muted [overflow-wrap:anywhere] scrollbar-thin">{text}</pre>
        <div className="mt-2 flex justify-end">
          <Button size="sm" variant="ghost" icon={done ? Check : Copy} onClick={() => void copy(text)}>
            {done ? "Copied" : "Copy"}
          </Button>
        </div>
        <span className="sr-only" aria-live="polite">
          {done ? "Copied to the clipboard" : ""}
        </span>
      </div>
    </details>
  );
}

/** Route error boundary: friendly message, technical details folded away — the same card as a failed load. */
export function RouteError({ fullScreen }: { fullScreen?: boolean }) {
  const error = useRouteError();
  if (isRouteErrorResponse(error) && error.status === 404) return <NotFound />;
  const message = (isRouteErrorResponse(error) ? `${error.status} ${error.statusText}` : technicalDetails(error)) ?? String(error);
  const body = (
    <EmptyState
      role="alert"
      illustration="error"
      headingLevel={1}
      className="mx-auto w-full max-w-lg"
      title="Something went wrong on this page"
      description="Your letters and dates are safe — this is only a display problem. Reloading usually helps."
      action={
        <>
          <Button variant="primary" icon={RotateCw} onClick={() => window.location.reload()}>
            Reload
          </Button>
          <Link to="/" className={buttonVariants({ variant: "secondary" })}>
            {BACK_TO_TODAY}
          </Link>
        </>
      }
    >
      <TechnicalDetails text={message} />
    </EmptyState>
  );
  return fullScreen ? <main className="grid min-h-dvh place-items-center bg-canvas px-4 py-8">{body}</main> : <div className="px-4 py-12">{body}</div>;
}
