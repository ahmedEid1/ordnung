import { useRef, type KeyboardEvent } from "react";
import { motion } from "motion/react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import { useStableId } from "./internal";

export interface SegmentOption<V extends string = string> {
  value: V;
  label: string;
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
  /** Stretch segments to the full width. */
  fill?: boolean;
  className?: string;
}

/**
 * Single-choice toggle group (radio semantics, ←/→ to move) with a sliding thumb.
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
      className={cn("inline-flex items-center gap-0.5 rounded-lg bg-surface-3/70 p-0.5", fill && "flex w-full", className)}
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
            aria-label={o.iconOnly ? o.label : undefined}
            title={o.iconOnly ? o.label : undefined}
            data-value={o.value}
            tabIndex={checked ? 0 : -1}
            onClick={() => onChange(o.value)}
            className={cn(
              "relative inline-flex items-center justify-center gap-1.5 rounded-md font-medium transition-colors",
              size === "sm" ? "h-7 px-2.5 text-[12.5px]" : "h-8 px-3 text-[13px]",
              o.iconOnly && (size === "sm" ? "w-8 px-0" : "w-9 px-0"),
              fill && "flex-1",
              checked ? "text-ink" : "text-muted hover:text-ink",
            )}
          >
            {checked ? (
              <motion.span
                layoutId={`${id}-thumb`}
                transition={{ type: "spring", stiffness: 520, damping: 40 }}
                className="absolute inset-0 rounded-md bg-surface shadow-[0_1px_2px_rgb(0_0_0/0.08)] ring-1 ring-line"
                aria-hidden
              />
            ) : null}
            {Icon ? <Icon className="relative size-3.5" aria-hidden /> : null}
            {!o.iconOnly ? <span className="relative">{o.label}</span> : null}
          </button>
        );
      })}
    </div>
  );
}
