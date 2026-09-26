import { useCallback, useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type KeyboardEvent, type ReactNode } from "react";
import { motion, useReducedMotion } from "motion/react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import { CountBadge } from "./Badge";
import { useStableId } from "./internal";
import { SEGMENT_GAP, SEGMENT_ITEM, SEGMENT_THUMB, SEGMENT_TRACK } from "./segment";

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
  /**
   * Shared id base: tab `i` is `${id}-tab-${value}`, its panel `${id}-panel-${value}`
   * (`<TabPanel>`, or your own `role="tabpanel"` element with that id).
   */
  id?: string;
  /**
   * Whether the tabs have panels (default: when `id` is given). Only the selected tab's panel is
   * rendered, so only the selected tab gets `aria-controls` — never an id that isn't on the page.
   */
  panels?: boolean;
  /** `underline` (page sections) or `pill` (compact filters). */
  variant?: "underline" | "pill";
  /** On phones (below `sm`) the tabs share the whole row; from `sm` up they hug their labels. */
  fill?: boolean;
  /** Leave out counts of 0 ("Cancelled" rather than "Cancelled 0") — shorter tabs on phones. */
  hideZero?: boolean;
  className?: string;
}

/** Width of the fade at an edge that has more tabs behind it. */
const FADE = 24;

/**
 * Accessible tabs (roving focus with ←/→/Home/End). Pair with `<TabPanel>` using the same `id`.
 *
 * When the tabs don't fit (phones) the row scrolls sideways: the edge with more tabs behind it
 * fades out, and the selected tab is always scrolled into view. The focus ring sits inside each
 * tab, so the scrolling row never cuts it off.
 *
 * @example
 * <Tabs id="inbox" label="Filter letters" value={tab} onChange={setTab}
 *   items={[{value: "all", label: "All"}, {value: "check", label: "Please check", count: 2}]} />
 * <TabPanel id="inbox" value="all" current={tab}>…</TabPanel>
 */
export function Tabs<V extends string>({
  items,
  value,
  onChange,
  label,
  id,
  panels = id !== undefined,
  variant = "underline",
  fill,
  hideZero,
  className,
}: TabsProps<V>) {
  const base = useStableId(id, "tabs");
  const listRef = useRef<HTMLDivElement>(null);
  const reduceMotion = useReducedMotion();
  const [edges, setEdges] = useState({ start: false, end: false });
  const indicatorId = `${base}-indicator`;
  const tabId = useCallback((v: string) => `${base}-tab-${v}`, [base]);
  const pill = variant === "pill";

  /** Which edges have tabs scrolled out of view. */
  const measure = useCallback(() => {
    const el = listRef.current;
    if (!el) return;
    const max = el.scrollWidth - el.clientWidth;
    const start = max > 1 && el.scrollLeft > 1;
    const end = max > 1 && el.scrollLeft < max - 1;
    setEdges((prev) => (prev.start === start && prev.end === end ? prev : { start, end }));
  }, []);

  // every render (labels and counts change the row's width) and whenever the row resizes
  useLayoutEffect(measure);
  useEffect(() => {
    const el = listRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [measure]);

  // keep the selected tab in view (clear of the fades) when it changes or the row starts to
  // overflow — not on every scroll, so a swipe along the row isn't undone
  const overflowing = edges.start || edges.end;
  useEffect(() => {
    const list = listRef.current;
    const tab = list?.querySelector<HTMLElement>(`#${CSS.escape(tabId(value))}`);
    if (!list || !tab || list.scrollWidth <= list.clientWidth) return;
    const from = tab.offsetLeft - FADE;
    const to = tab.offsetLeft + tab.offsetWidth + FADE - list.clientWidth;
    const left = from < list.scrollLeft ? from : to > list.scrollLeft ? to : null;
    if (left === null) return;
    if (typeof list.scrollTo === "function") list.scrollTo({ left, behavior: reduceMotion ? "auto" : "smooth" });
    else list.scrollLeft = left;
  }, [value, tabId, reduceMotion, overflowing]);

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
      listRef.current?.querySelector<HTMLButtonElement>(`#${CSS.escape(tabId(next.value))}`)?.focus();
    }
  };

  const mask = overflowing
    ? `linear-gradient(to right, ${edges.start ? `transparent, #000 ${FADE}px` : "#000"}, ${edges.end ? `#000 calc(100% - ${FADE}px), transparent` : "#000"})`
    : undefined;
  const maskStyle: CSSProperties | undefined = mask ? { maskImage: mask, WebkitMaskImage: mask } : undefined;

  return (
    // the outer box is the pill track (it stays whole while the tabs scroll and fade inside it)
    <div
      data-overflow={overflowing ? [edges.start && "start", edges.end && "end"].filter(Boolean).join(" ") : undefined}
      className={cn(
        "min-w-0 max-w-full",
        // pill tabs hug their labels; underline tabs draw their baseline across the whole row
        pill ? cn("w-fit", SEGMENT_TRACK) : "w-full",
        fill && "max-sm:w-full",
        className,
      )}
    >
      <div
        ref={listRef}
        role="tablist"
        aria-label={label}
        onKeyDown={onKeyDown}
        onScroll={measure}
        style={maskStyle}
        className={cn(
          "relative flex items-center overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden",
          pill ? SEGMENT_GAP : "gap-2 shadow-[inset_0_-1px_0_var(--color-line)]",
        )}
      >
        {items.map((t) => {
          const selected = t.value === value;
          const Icon = t.icon;
          const showCount = t.count !== undefined && (t.count > 0 || !hideZero);
          return (
            <button
              key={t.value}
              id={tabId(t.value)}
              type="button"
              role="tab"
              aria-selected={selected}
              aria-controls={panels && selected ? `${base}-panel-${t.value}` : undefined}
              tabIndex={selected ? 0 : -1}
              disabled={t.disabled}
              onClick={() => onChange(t.value)}
              className={cn(
                "relative inline-flex shrink-0 items-center justify-center gap-1.5 whitespace-nowrap text-base font-medium transition-colors disabled:opacity-50",
                // inside the tab: a scrolling row would cut an outside ring off
                "focus-visible:-outline-offset-2",
                selected ? "text-ink" : "text-muted hover:text-ink",
                pill ? cn("h-7 px-3 max-sm:px-2.5", SEGMENT_ITEM) : "h-10 rounded-md px-2",
                fill && "max-sm:flex-auto",
              )}
            >
              {selected ? (
                <motion.span
                  layoutId={indicatorId}
                  transition={{ type: "spring", stiffness: 500, damping: 40 }}
                  className={cn(
                    "absolute",
                    pill ? cn("inset-0", SEGMENT_THUMB) : "inset-x-2 bottom-0 h-0.5 rounded-full bg-ink",
                  )}
                  aria-hidden
                />
              ) : null}
              {Icon ? <Icon className="relative size-4" aria-hidden /> : null}
              <span className="relative">{t.label}</span>
              {showCount ? <CountBadge count={t.count!} showZero className="relative" tone={selected ? "accent" : "neutral"} /> : null}
            </button>
          );
        })}
      </div>
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
    <div role="tabpanel" id={`${id}-panel-${value}`} aria-labelledby={`${id}-tab-${value}`} tabIndex={0} className={cn("rounded-sm", className)}>
      {children}
    </div>
  );
}
