import type { HTMLAttributes, ReactNode } from "react";
import { cn } from "@/lib/utils";

export type EmptyIllustration = "clear" | "inbox" | "search" | "calendar" | "letter" | "contract" | "error" | "soon";

export interface EmptyStateProps extends Omit<HTMLAttributes<HTMLDivElement>, "title"> {
  title: ReactNode;
  description?: ReactNode;
  /** Actions (buttons). */
  action?: ReactNode;
  /** Badge on the paper stack (default `clear`, or `error` for the error variant). */
  illustration?: EmptyIllustration;
  /**
   * `card`: a dashed "nothing here yet" card; `plain`: borderless (inside a card that has one);
   * `error`: a solid card — something failed, so it must not look like a drop zone. Default:
   * `error` with the error illustration, else `card`.
   */
  variant?: "card" | "plain" | "error";
  size?: "sm" | "md";
  /**
   * Heading level of the title. Default 2: the empty state stands in for the page's content, right
   * under the page's h1. Use 3 (or 4) inside a section or card that has its own heading, and 1 when
   * it replaces the whole page (not found, a letter that didn't load).
   */
  headingLevel?: 1 | 2 | 3 | 4;
}

/** Badge glyphs, drawn on a 34 px disc centred on 0,0 (theme-aware via CSS vars). */
function Badge({ kind }: { kind: EmptyIllustration }) {
  const stroke = { stroke: "var(--color-accent)", strokeWidth: 2.4, strokeLinecap: "round", strokeLinejoin: "round" } as const;
  switch (kind) {
    case "clear":
      return <path d="M-7 0l4.5 4.5L7-5" {...stroke} strokeWidth={3} />;
    case "inbox":
      return <path d="M-8-5h16v11h-16z M-8-5l8 6 8-6" {...stroke} />;
    case "search":
      return (
        <>
          <circle cx="-2" cy="-2" r="6" {...stroke} strokeWidth={2.6} />
          <path d="M3 3l5 5" {...stroke} strokeWidth={2.8} />
        </>
      );
    case "calendar":
      return (
        <>
          <rect x="-8" y="-6" width="16" height="14" rx="2.5" {...stroke} />
          <path d="M-8-1h16M-4-9v5M4-9v5" {...stroke} />
        </>
      );
    case "letter":
      // a pen writing: letters you draft
      return (
        <>
          <path d="M-7 8l1.4-5.2L4.2-7a2 2 0 0 1 2.8 2.8L-2.8 5.6z" {...stroke} strokeWidth={2.2} />
          <path d="M1.8-4.6l2.8 2.8" {...stroke} strokeWidth={2.2} />
        </>
      );
    case "contract":
      // a signature on its line
      return <path d="M-9 7h18M-8 2.5c2-3 3.5-7 5.5-7 2.4 0-.6 8 1.6 8 1.6 0 2.2-3 3.6-3 1.1 0 1.2 2 2.8 2" {...stroke} strokeWidth={2.2} />;
    case "error":
      return <path d="M0-8v9M0 6.5v.5" {...stroke} stroke="var(--color-danger)" strokeWidth={3} />;
    case "soon":
      return (
        <>
          <circle r="8" {...stroke} />
          <path d="M0-4v4l3 2" {...stroke} />
        </>
      );
  }
}

/** Calm paper-stack illustration with a variant badge (inline SVG, theme-aware via CSS vars). */
export function EmptyArt({ kind = "clear", className }: { kind?: EmptyIllustration; className?: string }) {
  const error = kind === "error";
  return (
    <svg viewBox="0 0 160 120" className={cn("h-24 w-32 shrink-0", className)} aria-hidden fill="none">
      <ellipse cx="80" cy="108" rx="52" ry="6" fill="var(--color-ink)" opacity="0.06" />
      {/* back sheet */}
      <g transform="rotate(-8 70 60)">
        <rect x="38" y="18" width="62" height="80" rx="6" fill="var(--color-surface-2)" stroke="var(--color-line-strong)" />
      </g>
      {/* front sheet (an error greys out its title and highlight: nothing to read there) */}
      <g transform="rotate(4 88 58)">
        <rect x="52" y="14" width="64" height="84" rx="6" fill="var(--color-surface)" stroke="var(--color-line-strong)" />
        <rect x="61" y="26" width="30" height="4" rx="2" fill={error ? "var(--color-line-strong)" : "var(--color-accent)"} opacity="0.8" />
        <rect x="61" y="36" width="44" height="3" rx="1.5" fill="var(--color-line-strong)" />
        <rect x="61" y="44" width="38" height="3" rx="1.5" fill="var(--color-line-strong)" />
        {error ? null : <rect x="59" y="51" width="34" height="7" rx="2" fill="var(--color-marker)" opacity="0.75" />}
        <rect x="61" y="53" width="30" height="3" rx="1.5" fill="var(--color-line-strong)" />
        <rect x="61" y="63" width="42" height="3" rx="1.5" fill="var(--color-line-strong)" />
        <rect x="61" y="71" width="26" height="3" rx="1.5" fill="var(--color-line-strong)" />
      </g>
      {/* badge */}
      <g transform="translate(112 78)" data-badge={kind}>
        <circle r="17" fill={error ? "var(--color-danger-soft)" : "var(--color-accent-soft)"} stroke="var(--color-surface)" strokeWidth="3" />
        <Badge kind={kind} />
      </g>
    </svg>
  );
}

const variants = {
  card: "rounded-[var(--radius-card)] border border-dashed border-line-strong/80 bg-surface/60",
  plain: "",
  error: "card",
} as const;

/**
 * Friendly empty / all-clear state with an illustration, e.g. "All clear until Friday". Its content
 * is centred both ways, so it sits in the middle of a taller box. For a page or section that failed
 * to load, use {@link LoadError} (built on the `error` variant).
 *
 * @example <EmptyState illustration="clear" title="All clear until Friday" description="Nothing needs you this week." />
 */
export function EmptyState({
  title,
  description,
  action,
  illustration,
  variant = illustration === "error" ? "error" : "card",
  size = "md",
  headingLevel = 2,
  className,
  children,
  ...rest
}: EmptyStateProps) {
  const Heading = `h${headingLevel}` as "h1" | "h2" | "h3" | "h4";
  return (
    <div
      {...rest}
      data-variant={variant}
      className={cn(
        "flex flex-col items-center justify-center text-center",
        size === "md" ? "px-6 py-10" : "px-4 py-6",
        variants[variant],
        className,
      )}
    >
      <EmptyArt kind={illustration ?? (variant === "error" ? "error" : "clear")} className={size === "sm" ? "h-16 w-24" : undefined} />
      <Heading className={cn("display mt-4 text-balance font-semibold text-ink", size === "md" ? "text-xl" : "text-lg")}>{title}</Heading>
      {description ? <p className="mt-1.5 max-w-sm text-pretty text-base leading-relaxed text-muted">{description}</p> : null}
      {action ? <div className="mt-5 flex flex-wrap items-center justify-center gap-2">{action}</div> : null}
      {children}
    </div>
  );
}
