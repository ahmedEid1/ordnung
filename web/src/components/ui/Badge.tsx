import type { HTMLAttributes, ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import { TONES, type Tone } from "@/lib/copy";

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: Tone;
  /** `soft` (tinted, default), `outline` (border only), `solid` (strong fill, use sparingly). */
  variant?: "soft" | "outline" | "solid";
  size?: "sm" | "md";
  icon?: LucideIcon;
  /** Show a coloured dot instead of an icon. */
  dot?: boolean;
  children?: ReactNode;
}

/**
 * Small label chip. Colour comes from a semantic tone (item kinds, ok/warn/danger, accent,
 * neutral). Text colours meet WCAG AA on the soft background in light and dark mode.
 *
 * @example <Badge tone="warn" icon={TriangleAlert}>Please check</Badge>
 */
export function Badge({ tone = "neutral", variant = "soft", size = "sm", icon: Icon, dot, className, children, ...rest }: BadgeProps) {
  const t = TONES[tone];
  return (
    <span
      className={cn(
        "inline-flex max-w-full items-center gap-1 whitespace-nowrap rounded-full font-medium leading-none",
        size === "sm" ? "h-[22px] px-2 text-[12px]" : "h-7 px-2.5 text-[13px]",
        variant === "soft" && cn(t.soft, t.text),
        variant === "outline" && cn("border bg-transparent", t.border, t.text),
        variant === "solid" && cn(t.solid, tone === "neutral" ? "text-white" : "text-white dark:text-canvas"),
        className,
      )}
      {...rest}
    >
      {dot ? <span className={cn("size-1.5 shrink-0 rounded-full", variant === "solid" ? "bg-current" : t.solid)} aria-hidden /> : null}
      {Icon && !dot ? <Icon className={cn("shrink-0", size === "sm" ? "size-3" : "size-3.5")} aria-hidden /> : null}
      <span className="truncate">{children}</span>
    </span>
  );
}

/** Numeric count bubble (nav badges, tab counts). Hidden when count is 0 unless `showZero`. */
export function CountBadge({
  count,
  tone = "neutral",
  showZero,
  className,
  label,
}: {
  count: number;
  tone?: Tone;
  showZero?: boolean;
  className?: string;
  /** accessible text, e.g. "3 letters to check" */
  label?: string;
}) {
  if (!count && !showZero) return null;
  const t = TONES[tone];
  return (
    <span
      className={cn(
        "inline-grid h-5 min-w-5 place-items-center rounded-full px-1.5 text-[11px] font-semibold tabular-nums leading-none",
        t.soft,
        t.text,
        className,
      )}
      aria-label={label}
    >
      {count > 99 ? "99+" : count}
    </span>
  );
}
