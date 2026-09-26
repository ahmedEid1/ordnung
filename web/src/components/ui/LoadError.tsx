import type { ReactNode } from "react";
import { ChevronRight, RotateCw } from "lucide-react";
import { ApiError } from "@/api/client";
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
  /** One calm sentence under the heading (default: the letters are safe, is Ordnung still running?). */
  description?: ReactNode;
  /** The error, shown under "Technical details" (never as the sentence itself). */
  error?: unknown;
  /** Show "Try again". */
  onRetry?: () => void;
  /** A retry is running: the button spins, the message stays put. */
  retrying?: boolean;
  /** Heading level: 2 under the page's h1 (default), 1 when it replaces the page, 3 inside a section. */
  headingLevel?: 1 | 2 | 3;
  /** `error` (default) is a solid card; `plain` goes inside a card that already has an edge. */
  variant?: "error" | "plain";
  size?: "sm" | "md";
  className?: string;
}

/** The technical side of an error, for people who want to report it: "HTTP 500 · Internal error". */
export function technicalDetails(error: unknown): string | null {
  if (error instanceof ApiError) return [error.status ? `HTTP ${error.status}` : null, error.message].filter(Boolean).join(" · ");
  if (error instanceof Error) return error.message || error.name;
  if (typeof error === "string") return error || null;
  return null;
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
  description = "Your letters are safe — Ordnung didn't answer. Is it still running?",
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
      description={description}
      className={className}
      action={
        onRetry ? (
          <Button variant="primary" size={size === "sm" ? "sm" : "md"} icon={RotateCw} loading={retrying} onClick={onRetry}>
            Try again
          </Button>
        ) : undefined
      }
    >
      {details ? (
        <details className="group mt-4 w-full max-w-sm text-left">
          <summary
            className={cn(
              "mx-auto flex min-h-6 w-fit cursor-pointer list-none items-center gap-1 rounded-md px-1 text-sm font-medium text-muted hover:text-ink",
              "[&::-webkit-details-marker]:hidden",
            )}
          >
            <ChevronRight className="size-3.5 transition-transform group-open:rotate-90 motion-reduce:transition-none" aria-hidden />
            Technical details
          </summary>
          <p className="mt-2 rounded-lg bg-surface-2 px-3 py-2 font-mono text-xs leading-5 text-muted [overflow-wrap:anywhere]">
            {details}
          </p>
        </details>
      ) : null}
    </EmptyState>
  );
}
