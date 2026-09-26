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

/** Filled count colours: a solid tone with text that stays ≥ 4.5:1 on it in both themes. */
const SOLID_COUNT: Partial<Record<Tone, string>> = {
  accent: "bg-accent text-on-accent",
  neutral: "bg-muted text-surface",
};

/**
 * Numeric count bubble (nav badges, tab counts). Hidden when count is 0 unless `showZero`.
 *
 * One look for the same meaning everywhere: `tone="warn"` for counts that need the person
 * ("3 to check"), `neutral` (default) for counts that only inform ("22 letters"). `soft` sits in
 * text rows and tabs; `solid` is for a bubble on an icon's corner (with `size="compact"`, 16 px,
 * still 11 px text).
 */
export function CountBadge({
  count,
  tone = "neutral",
  variant = "soft",
  size = "md",
  showZero,
  className,
  label,
}: {
  count: number;
  tone?: Tone;
  variant?: "soft" | "solid";
  /** `md` (20 px, 12 px text) or `compact` (16 px, 11 px text — icon corners). */
  size?: "md" | "compact";
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
        "inline-grid shrink-0 place-items-center rounded-full font-semibold tabular-nums leading-none",
        size === "md" ? "h-5 min-w-5 px-1.5 text-xs" : "h-4 min-w-4 px-1 text-2xs",
        variant === "soft"
          ? // neutral: surface-3, so the bubble shows on surface-2 tracks and rows too
            cn(tone === "neutral" ? "bg-surface-3" : t.soft, t.text)
          : (SOLID_COUNT[tone] ?? cn(t.solid, "text-white dark:text-canvas")),
        className,
      )}
      aria-label={label}
    >
      {count > 99 ? "99+" : count}
    </span>
  );
}
