import type { ReactNode } from "react";
import { ChevronRight, RotateCw } from "lucide-react";
import { ApiError, UNREADABLE_CODE } from "@/api/client";
import { cn } from "@/lib/utils";
import { Button } from "./Button";
import { EmptyState } from "./EmptyState";

export interface LoadErrorProps {
  /**
   * What didn't load, in the words of the heading: "your letters" → "Couldn't load your letters".
   * Ignored when `title` is given.
   */
  what?: string;
  /** The heading, when "Couldn't load …" doesn't fit ("Couldn't open this letter"). */
  title?: ReactNode;
  /** One calm sentence under the heading (default: the letters are safe, and what went wrong — {@link loadErrorDescription}). */
  description?: ReactNode;
  /** The error, shown under "Technical details" (never as the sentence itself). */
  error?: unknown;
  /** Show "Try again". */
  onRetry?: () => void;
  /** A retry is running: the button spins, the message stays put. */
  retrying?: boolean;
  /** Heading level: 2 under the page's h1 (default), 1 when it replaces the page, 3 inside a section, 4 inside a card. */
  headingLevel?: 1 | 2 | 3 | 4;
  /** `error` (default) is a solid card; `plain` goes inside a card that already has an edge. */
  variant?: "error" | "plain";
  size?: "sm" | "md";
  className?: string;
}

/**
 * The technical side of an error, for people who want to report it: "HTTP 500 · Internal Server Error" — the
 * server's own words when the message is a plain sentence instead ({@link ApiError.technical}).
 */
export function technicalDetails(error: unknown): string | null {
  if (error instanceof ApiError) return [error.status ? `HTTP ${error.status}` : null, error.technical ?? error.message].filter(Boolean).join(" · ");
  if (error instanceof Error) return error.message || error.name;
  if (typeof error === "string") return error || null;
  return null;
}

/**
 * The sentence under "Couldn't load …", worded by what happened (UX audit U9, as Today's own): Ordnung didn't
 * answer at all (or nothing says why), it answered with a failure of its own, or it refused. `what` is the
 * heading's ("your letters").
 */
export function loadErrorDescription(error: unknown, what = "this page"): string {
  if (error == null || (error instanceof ApiError && error.status === 0)) return "Your letters are safe — Ordnung didn't answer. Is it still running?";
  if (!(error instanceof ApiError) || error.status >= 500 || error.code === UNREADABLE_CODE) {
    return `Your letters are safe — Ordnung ran into a problem while loading ${what}. Try again, and restart Ordnung if it keeps happening.`;
  }
  return `Your letters are safe — Ordnung couldn't load ${what}. Try again in a moment.`;
}

/**
 * A page or section that failed to load: the error illustration, "Couldn't load your …", one
 * sentence that says what is (and isn't) wrong, a primary "Try again" and the technical message
 * behind a disclosure. It is an alert, and stays mounted while retrying so it isn't announced twice.
 *
 * @example <LoadError what="your letters" error={q.error} onRetry={() => q.refetch()} retrying={q.isFetching} />
 */
export function LoadError({
  what = "this page",
  title,
  description,
  error,
  onRetry,
  retrying = false,
  headingLevel = 2,
  variant = "error",
  size = "md",
  className,
}: LoadErrorProps) {
  const details = technicalDetails(error);
  return (
    <EmptyState
      role="alert"
      variant={variant}
      size={size}
      illustration="error"
      headingLevel={headingLevel}
      title={title ?? `Couldn't load ${what}`}
      description={description ?? loadErrorDescription(error, what)}
      className={className}
      action={
        onRetry ? (
          <Button variant="primary" size={size === "sm" ? "sm" : "md"} icon={RotateCw} loading={retrying} onClick={onRetry}>
            Try again
          </Button>
        ) : undefined
      }
    >
      {details ? <TechnicalDetails text={details} className="mt-4 max-w-sm" centered /> : null}
    </EmptyState>
  );
}

/** "Technical details": an error's technical side behind a disclosure, closed until asked for (a load error, a toast). */
export function TechnicalDetails({ text, centered = false, className }: { text: string; centered?: boolean; className?: string }) {
  return (
    <details className={cn("group w-full text-left", className)}>
      <summary
        className={cn(
          "flex min-h-6 w-fit cursor-pointer list-none items-center gap-1 rounded-md px-1 text-sm font-medium text-muted hover:text-ink",
          "[&::-webkit-details-marker]:hidden",
          centered ? "mx-auto" : "-ml-1",
        )}
      >
        <ChevronRight className="size-3.5 transition-transform group-open:rotate-90 motion-reduce:transition-none" aria-hidden />
        Technical details
      </summary>
      <p className="mt-2 rounded-lg bg-surface-2 px-3 py-2 font-mono text-xs leading-5 text-muted [overflow-wrap:anywhere]">{text}</p>
    </details>
  );
}
