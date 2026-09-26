import { useRef, type KeyboardEvent } from "react";
import { motion } from "motion/react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import { useStableId } from "./internal";
import { SEGMENT_GAP, SEGMENT_ITEM, SEGMENT_THUMB, SEGMENT_TRACK } from "./segment";

export interface SegmentOption<V extends string = string> {
  value: V;
  label: string;
  /**
   * Shorter text for phones (below `sm`): "Fit" for "Fit width", "German" for "Letter (German)".
   * Make it part of the label — the full label stays the accessible name and the tooltip.
   */
  shortLabel?: string;
  icon?: LucideIcon;
  /** Show only the icon (label stays as the accessible name). */
  iconOnly?: boolean;
}

export interface SegmentedControlProps<V extends string = string> {
  options: SegmentOption<V>[];
  value: V;
  onChange: (value: V) => void;
  /** Accessible name of the group. */
  label: string;
  size?: "sm" | "md";
  /**
   * Stretch to the full width (the segments share the extra room): `true` always, `"phone"`
   * below `sm` only.
   * Otherwise the control is as wide as its segments (it never stretches as a flex child).
   */
  fill?: boolean | "phone";
  className?: string;
}

/**
 * Single-choice toggle group (radio semantics, ←/→ to move) with a sliding thumb.
 *
 * Segment labels stay on one line. When the control is squeezed (a narrow card), labels end in
 * "…" rather than wrapping or pushing out of their container; give long labels a `shortLabel`.
 *
 * @example <SegmentedControl label="Theme" value={theme} onChange={setTheme}
 *   options={[{value: "light", label: "Light", icon: Sun}, …]} />
 */
export function SegmentedControl<V extends string>({ options, value, onChange, label, size = "md", fill, className }: SegmentedControlProps<V>) {
  const id = useStableId(undefined, "seg");
  const ref = useRef<HTMLDivElement>(null);

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const i = options.findIndex((o) => o.value === value);
    let next: SegmentOption<V> | undefined;
    if (e.key === "ArrowRight" || e.key === "ArrowDown") next = options[(i + 1) % options.length];
    else if (e.key === "ArrowLeft" || e.key === "ArrowUp") next = options[(i - 1 + options.length) % options.length];
    if (next) {
      e.preventDefault();
      onChange(next.value);
      ref.current?.querySelector<HTMLButtonElement>(`[data-value="${CSS.escape(next.value)}"]`)?.focus();
    }
  };

  return (
    <div
      ref={ref}
      role="radiogroup"
      aria-label={label}
      onKeyDown={onKeyDown}
      className={cn(
        // w-fit: as a flex child it hugs its segments instead of stretching the track behind them
        "inline-flex w-fit min-w-0 max-w-full items-center",
        SEGMENT_TRACK,
        SEGMENT_GAP,
        fill === true && "flex w-full",
        fill === "phone" && "max-sm:flex max-sm:w-full",
        className,
      )}
    >
      {options.map((o) => {
        const checked = o.value === value;
        const Icon = o.icon;
        return (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={checked}
            aria-label={o.iconOnly || o.shortLabel ? o.label : undefined}
            title={o.iconOnly || o.shortLabel ? o.label : undefined}
            data-value={o.value}
            tabIndex={checked ? 0 : -1}
            onClick={() => onChange(o.value)}
            className={cn(
              "relative inline-flex min-w-0 items-center justify-center gap-1.5 whitespace-nowrap font-medium transition-colors",
              SEGMENT_ITEM,
              size === "sm" ? "h-6 px-2.5 text-xs" : "h-7 px-3 text-sm",
              o.iconOnly && (size === "sm" ? "w-7 shrink-0 px-0" : "w-8 shrink-0 px-0"),
              // segments grow from their natural widths, so a longer label keeps its room
              fill === true && "flex-auto",
              fill === "phone" && "max-sm:flex-auto",
              checked ? "text-ink" : "text-muted hover:text-ink",
            )}
          >
            {checked ? (
              <motion.span
                layoutId={`${id}-thumb`}
                transition={{ type: "spring", stiffness: 520, damping: 40 }}
                className={cn("absolute inset-0", SEGMENT_THUMB)}
                aria-hidden
              />
            ) : null}
            {Icon ? <Icon className="relative size-3.5 shrink-0" aria-hidden /> : null}
            {o.iconOnly ? null : o.shortLabel ? (
              <>
                <span className="relative truncate sm:hidden">{o.shortLabel}</span>
                <span className="relative truncate max-sm:hidden">{o.label}</span>
              </>
            ) : (
              <span className="relative truncate">{o.label}</span>
            )}
          </button>
        );
      })}
    </div>
  );
}
