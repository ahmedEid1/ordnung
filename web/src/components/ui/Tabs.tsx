import { useRef, type KeyboardEvent, type ReactNode } from "react";
import { motion } from "motion/react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import { CountBadge } from "./Badge";
import { useStableId } from "./internal";

export interface TabItem<V extends string = string> {
  value: V;
  label: string;
  icon?: LucideIcon;
  count?: number;
  disabled?: boolean;
}

export interface TabsProps<V extends string = string> {
  items: TabItem<V>[];
  value: V;
  onChange: (value: V) => void;
  /** Accessible name of the tab list. */
  label: string;
  /** Shared id base so `<TabPanel>` can reference the tabs. */
  id?: string;
  /** `underline` (page sections) or `pill` (compact filters). */
  variant?: "underline" | "pill";
  className?: string;
}

/**
 * Accessible tabs (roving focus with ←/→/Home/End). Pair with `<TabPanel>` using the same `id`.
 *
 * @example
 * <Tabs id="inbox" label="Filter letters" value={tab} onChange={setTab}
 *   items={[{value: "all", label: "All"}, {value: "check", label: "Please check", count: 2}]} />
 * <TabPanel id="inbox" value="all" current={tab}>…</TabPanel>
 */
export function Tabs<V extends string>({ items, value, onChange, label, id, variant = "underline", className }: TabsProps<V>) {
  const base = useStableId(id, "tabs");
  const listRef = useRef<HTMLDivElement>(null);
  const indicatorId = `${base}-indicator`;

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const enabled = items.filter((t) => !t.disabled);
    const i = enabled.findIndex((t) => t.value === value);
    let next: TabItem<V> | undefined;
    if (e.key === "ArrowRight") next = enabled[(i + 1) % enabled.length];
    else if (e.key === "ArrowLeft") next = enabled[(i - 1 + enabled.length) % enabled.length];
    else if (e.key === "Home") next = enabled[0];
    else if (e.key === "End") next = enabled[enabled.length - 1];
    if (next) {
      e.preventDefault();
      onChange(next.value);
      listRef.current?.querySelector<HTMLButtonElement>(`#${CSS.escape(`${base}-tab-${next.value}`)}`)?.focus();
    }
  };

  return (
    <div
      ref={listRef}
      role="tablist"
      aria-label={label}
      onKeyDown={onKeyDown}
      className={cn(
        "flex max-w-full items-center overflow-x-auto scrollbar-thin",
        variant === "underline" ? "gap-5 border-b border-line" : "gap-1 rounded-xl bg-surface-2 p-1",
        className,
      )}
    >
      {items.map((t) => {
        const selected = t.value === value;
        const Icon = t.icon;
        return (
          <button
            key={t.value}
            id={`${base}-tab-${t.value}`}
            type="button"
            role="tab"
            aria-selected={selected}
            aria-controls={`${base}-panel-${t.value}`}
            tabIndex={selected ? 0 : -1}
            disabled={t.disabled}
            onClick={() => onChange(t.value)}
            className={cn(
              "relative inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap text-base font-medium transition-colors disabled:opacity-50",
              variant === "underline"
                ? cn("h-10 px-0.5", selected ? "text-ink" : "text-muted hover:text-ink")
                : cn("h-8 rounded-lg px-3", selected ? "text-ink" : "text-muted hover:text-ink"),
            )}
          >
            {selected ? (
              <motion.span
                layoutId={indicatorId}
                transition={{ type: "spring", stiffness: 500, damping: 40 }}
                className={cn(
                  "absolute",
                  variant === "underline"
                    ? "inset-x-0 -bottom-px h-0.5 rounded-full bg-ink"
                    : "inset-0 rounded-lg bg-surface shadow-[var(--shadow-card)] ring-1 ring-line",
                )}
                aria-hidden
              />
            ) : null}
            {Icon ? <Icon className="relative size-4" aria-hidden /> : null}
            <span className="relative">{t.label}</span>
            {t.count !== undefined ? (
              <CountBadge count={t.count} showZero className="relative" tone={selected ? "accent" : "neutral"} />
            ) : null}
          </button>
        );
      })}
    </div>
  );
}

/** Panel for a tab; only renders its children when `value === current`. */
export function TabPanel({
  id,
  value,
  current,
  children,
  className,
}: {
  id: string;
  value: string;
  current: string;
  children: ReactNode;
  className?: string;
}) {
  if (value !== current) return null;
  return (
    <div role="tabpanel" id={`${id}-panel-${value}`} aria-labelledby={`${id}-tab-${value}`} tabIndex={0} className={cn("outline-none", className)}>
      {children}
    </div>
  );
}
