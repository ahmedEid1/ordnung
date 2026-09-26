import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export type EmptyIllustration = "clear" | "inbox" | "search" | "calendar" | "letter" | "error" | "soon";

export interface EmptyStateProps {
  title: ReactNode;
  description?: ReactNode;
  /** Actions (buttons). */
  action?: ReactNode;
  illustration?: EmptyIllustration;
  /** `card` wraps it in a dashed card; `plain` is borderless. */
  variant?: "card" | "plain";
  size?: "sm" | "md";
  /** Heading level of the title (default 3; use 2 when the empty state stands directly under the page's h1). */
  headingLevel?: 2 | 3;
  className?: string;
}

/** Calm paper-stack illustration with a variant badge (inline SVG, theme-aware via CSS vars). */
export function EmptyArt({ kind = "clear", className }: { kind?: EmptyIllustration; className?: string }) {
  return (
    <svg viewBox="0 0 160 120" className={cn("h-24 w-32", className)} aria-hidden fill="none">
      <ellipse cx="80" cy="108" rx="52" ry="6" fill="var(--color-ink)" opacity="0.06" />
      {/* back sheet */}
      <g transform="rotate(-8 70 60)">
        <rect x="38" y="18" width="62" height="80" rx="6" fill="var(--color-surface-2)" stroke="var(--color-line-strong)" />
      </g>
      {/* front sheet */}
      <g transform="rotate(4 88 58)">
        <rect x="52" y="14" width="64" height="84" rx="6" fill="var(--color-surface)" stroke="var(--color-line-strong)" />
        <rect x="61" y="26" width="30" height="4" rx="2" fill="var(--color-accent)" opacity="0.8" />
        <rect x="61" y="36" width="44" height="3" rx="1.5" fill="var(--color-line-strong)" />
        <rect x="61" y="44" width="38" height="3" rx="1.5" fill="var(--color-line-strong)" />
        <rect x="59" y="51" width="34" height="7" rx="2" fill="var(--color-marker)" opacity="0.75" />
        <rect x="61" y="53" width="30" height="3" rx="1.5" fill="var(--color-line-strong)" />
        <rect x="61" y="63" width="42" height="3" rx="1.5" fill="var(--color-line-strong)" />
        <rect x="61" y="71" width="26" height="3" rx="1.5" fill="var(--color-line-strong)" />
      </g>
      {/* badge */}
      <g transform="translate(112 78)">
        <circle r="17" fill={kind === "error" ? "var(--color-danger-soft)" : "var(--color-accent-soft)"} stroke="var(--color-surface)" strokeWidth="3" />
        {kind === "clear" || kind === "letter" ? (
          <path d="M-7 0l4.5 4.5L7-5" stroke="var(--color-accent)" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
        ) : null}
        {kind === "inbox" ? (
          <path d="M-8-4h16v10h-16z M-8-4l8 6 8-6" stroke="var(--color-accent)" strokeWidth="2.4" strokeLinejoin="round" strokeLinecap="round" />
        ) : null}
        {kind === "search" ? (
          <>
            <circle cx="-2" cy="-2" r="6" stroke="var(--color-accent)" strokeWidth="2.6" />
            <path d="M3 3l5 5" stroke="var(--color-accent)" strokeWidth="2.8" strokeLinecap="round" />
          </>
        ) : null}
        {kind === "calendar" ? (
          <>
            <rect x="-8" y="-6" width="16" height="14" rx="2.5" stroke="var(--color-accent)" strokeWidth="2.4" />
            <path d="M-8-1h16M-4-9v5M4-9v5" stroke="var(--color-accent)" strokeWidth="2.4" strokeLinecap="round" />
          </>
        ) : null}
        {kind === "error" ? (
          <path d="M0-8v9M0 6.5v.5" stroke="var(--color-danger)" strokeWidth="3" strokeLinecap="round" />
        ) : null}
        {kind === "soon" ? (
          <>
            <circle r="8" stroke="var(--color-accent)" strokeWidth="2.4" />
            <path d="M0-4v4l3 2" stroke="var(--color-accent)" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
          </>
        ) : null}
      </g>
    </svg>
  );
}

/**
 * Friendly empty / all-clear state with an illustration, e.g. "All clear until Friday".
 *
 * @example <EmptyState illustration="clear" title="All clear until Friday" description="Nothing needs you this week." />
 */
export function EmptyState({ title, description, action, illustration = "clear", variant = "card", size = "md", headingLevel = 3, className }: EmptyStateProps) {
  const Heading = headingLevel === 2 ? "h2" : "h3";
  return (
    <div
      className={cn(
        "flex flex-col items-center text-center",
        size === "md" ? "px-6 py-10" : "px-4 py-6",
        variant === "card" && "rounded-[var(--radius-card)] border border-dashed border-line-strong/80 bg-surface/60",
        className,
      )}
    >
      <EmptyArt kind={illustration} className={size === "sm" ? "h-16 w-24" : undefined} />
      <Heading className={cn("display mt-4 font-semibold text-ink", size === "md" ? "text-xl" : "text-lg")}>{title}</Heading>
      {description ? <p className="mt-1.5 max-w-sm text-base leading-relaxed text-muted">{description}</p> : null}
      {action ? <div className="mt-5 flex flex-wrap items-center justify-center gap-2">{action}</div> : null}
    </div>
  );
}
