/**
 * The month-by-month list under the lanes: sticky month headers, a Today divider the list scrolls
 * to on load, entries with kind icon, title, party, amount and status. Scrolls inside its own card
 * so the lanes above stay put.
 */
import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router";
import { format, parseISO } from "date-fns";
import { ArrowDown, ArrowUp, ChevronRight } from "lucide-react";
import type { TimelineEntry } from "@/api/types";
import { KindIcon } from "@/components/ui/KindBadge";
import { Money } from "@/components/ui/Money";
import { TONES } from "@/lib/copy";
import { formatDate, formatTime, formatTotals } from "@/lib/format";
import { cn, plural, prefersReducedMotion } from "@/lib/utils";
import { entryMeta, entryStatus, isPastEntry, type MonthGroup } from "./model";

export interface TimelineListProps {
  groups: MonthGroup[];
  today: string;
  /** link for an entry (null: not clickable) */
  hrefFor: (e: TimelineEntry) => string | null;
  /** entry to scroll to and highlight (e.g. after clicking a lane marker) */
  highlight?: { id: string; nonce: number } | null;
  /** header content (title + filters) */
  header?: ReactNode;
  /** when this value changes, the list scrolls back to the Today divider (e.g. "Show past" toggled) */
  scrollKey?: string;
  empty?: ReactNode;
  className?: string;
}

const HEADER_H = 44;

function DateLeaf({ date, past, isToday }: { date: string; past: boolean; isToday: boolean }) {
  const d = parseISO(date);
  return (
    <span
      aria-hidden
      className={cn(
        "flex w-10 shrink-0 flex-col items-center rounded-lg border py-1 leading-none",
        isToday ? "border-ink/70 bg-surface text-ink shadow-[inset_0_0_0_1px_var(--color-ink)]" : past ? "border-line bg-surface-2/60 text-muted" : "border-line bg-surface text-ink",
      )}
    >
      <span className={cn("text-[9.5px] font-semibold uppercase tracking-[0.08em]", isToday ? "text-ink" : "text-muted")}>{format(d, "EEE")}</span>
      <span className="display mt-0.5 text-[16px] font-semibold tabular-nums">{format(d, "d")}</span>
    </span>
  );
}

function Entry({ e, today, href, highlighted }: { e: TimelineEntry; today: string; href: string | null; highlighted: boolean }) {
  const past = isPastEntry(e, today);
  const status = entryStatus(e, today);
  const meta = [entryMeta(e), e.time ? formatTime(e.time) : null].filter(Boolean).join(" · ");
  const pill = status ? (
    <span className={cn("inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-[3px] text-[11.5px] font-medium leading-4", TONES[status.tone].soft, TONES[status.tone].text)}>
      <status.icon className="size-3" aria-hidden />
      {status.label}
    </span>
  ) : null;
  const inner = (
    <>
      <DateLeaf date={e.date} past={past} isToday={e.date === today} />
      <KindIcon kind={e.type} size="sm" className={cn(past && "opacity-60")} />
      <span className="min-w-0 flex-1">
        <span className={cn("line-clamp-2 text-[14px] font-medium leading-snug sm:line-clamp-1", past ? "text-ink/70" : "text-ink")}>{e.title}</span>
        {meta ? <span className="mt-0.5 block truncate text-[12.5px] text-muted">{meta}</span> : null}
        {pill ? <span className="mt-1 flex sm:hidden">{pill}</span> : null}
      </span>
      {e.amount && e.type !== "contract" ? <Money amount={e.amount} currency={e.currency} tone={past ? "muted" : "default"} className="shrink-0 text-[13.5px]" /> : null}
      {pill ? <span className="hidden shrink-0 sm:flex">{pill}</span> : null}
      {href ? <ChevronRight className="size-4 shrink-0 text-faint transition-colors group-hover:text-muted" aria-hidden /> : <span className="w-4 shrink-0" aria-hidden />}
    </>
  );
  const cls = cn(
    "group flex items-center gap-3 px-4 py-2.5 transition-colors duration-500 sm:px-5",
    highlighted ? "bg-marker/45" : href && "hover:bg-surface-2/70",
  );
  const sr = <span className="sr-only">{formatDate(e.date, { style: "long" })}: </span>;
  return (
    <li data-entry-id={e.id} data-date={e.date}>
      {href ? (
        <Link to={href} className={cn(cls, "outline-none focus-visible:bg-surface-2 focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent")}>
          {sr}
          {inner}
        </Link>
      ) : (
        <div className={cls}>
          {sr}
          {inner}
        </div>
      )}
    </li>
  );
}

function TodayDivider({ today, nothingElse }: { today: string; nothingElse: boolean }) {
  return (
    <li data-today className="flex items-center gap-3 px-4 py-2 sm:px-5" aria-label={`Today, ${formatDate(today, { style: "long" })}`}>
      <span className="rounded-full bg-ink px-2 py-[3px] text-[10.5px] font-semibold uppercase leading-none tracking-[0.07em] text-canvas">Today</span>
      <span className="whitespace-nowrap text-[12.5px] font-semibold text-ink">{formatDate(today, { style: "short" })}</span>
      <span aria-hidden className="h-[2px] flex-1 rounded-full bg-ink" />
      {nothingElse ? <span className="text-[12px] text-muted">nothing else this month</span> : null}
    </li>
  );
}

export function TimelineList({ groups, today, hrefFor, highlight, header, empty, scrollKey = "", className }: TimelineListProps) {
  const scroller = useRef<HTMLDivElement | null>(null);
  const card = useRef<HTMLElement | null>(null);
  const [todayPos, setTodayPos] = useState<"above" | "below" | "visible">("visible");
  const hasEntries = groups.some((g) => g.entries.length);
  const hasToday = groups.some((g) => g.todayIndex !== null);

  // On first render with data (and when `scrollKey` changes): bring the Today divider to the top.
  const scrolledFor = useRef<string | null>(null);
  useLayoutEffect(() => {
    const el = scroller.current;
    if (!el || scrolledFor.current === scrollKey || !hasEntries) return;
    const mark = el.querySelector<HTMLElement>("[data-today]");
    if (!mark) return;
    scrolledFor.current = scrollKey;
    el.scrollTop += mark.getBoundingClientRect().top - el.getBoundingClientRect().top - HEADER_H - 4;
  }, [hasEntries, groups, scrollKey]);

  // "Back to today" pill when the divider scrolled out of view.
  useEffect(() => {
    const el = scroller.current;
    const mark = el?.querySelector<HTMLElement>("[data-today]");
    if (!el || !mark || typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver(
      ([entry]) => {
        if (!entry) return;
        if (entry.isIntersecting) setTodayPos("visible");
        else setTodayPos(entry.boundingClientRect.top < (entry.rootBounds?.top ?? 0) ? "above" : "below");
      },
      { root: el, rootMargin: `-${HEADER_H}px 0px 0px 0px` },
    );
    io.observe(mark);
    return () => io.disconnect();
  }, [groups]);

  // Scroll to a highlighted entry.
  useEffect(() => {
    if (!highlight) return;
    const el = scroller.current;
    const row = el?.querySelector<HTMLElement>(`[data-entry-id="${CSS.escape(highlight.id)}"]`);
    if (!el || !row) return;
    const top = el.scrollTop + row.getBoundingClientRect().top - el.getBoundingClientRect().top - HEADER_H - 24;
    const behavior = prefersReducedMotion() ? "auto" : "smooth";
    el.scrollTo?.({ top, behavior });
    card.current?.scrollIntoView?.({ block: "start", behavior });
  }, [highlight]);

  const jumpToToday = () => {
    const el = scroller.current;
    const mark = el?.querySelector<HTMLElement>("[data-today]");
    if (!el || !mark) return;
    const top = el.scrollTop + mark.getBoundingClientRect().top - el.getBoundingClientRect().top - HEADER_H - 4;
    el.scrollTo?.({ top, behavior: prefersReducedMotion() ? "auto" : "smooth" });
  };

  return (
    <section ref={card} aria-labelledby="timeline-list-title" className={cn("card relative isolate scroll-mt-20 overflow-hidden", className)}>
      {header}
      <div ref={scroller} className="relative max-h-[min(46rem,74vh)] overflow-y-auto overscroll-contain scrollbar-thin">
        {!hasEntries ? (
          <div className="p-5">{empty}</div>
        ) : (
          groups.map((g) => {
            const count = g.entries.length;
            return (
              <section key={g.key} aria-labelledby={`tl-month-${g.key}`} className="border-t border-line first:border-t-0">
                <h3
                  id={`tl-month-${g.key}`}
                  className="sticky top-0 z-10 flex items-baseline gap-3 border-b border-line bg-surface px-4 sm:px-5"
                  style={{ height: HEADER_H, paddingTop: 11 }}
                >
                  <span className={cn("display text-[17px] font-semibold leading-none", g.past ? "text-ink/70" : "text-ink")}>
                    {g.month} <span className="font-normal text-muted">{g.year}</span>
                  </span>
                  <span className="ml-auto flex items-baseline gap-2 text-[12px] text-muted">
                    <span>{plural(count, "date")}</span>
                    {Object.values(g.toPay).some((total) => total > 0) ? (
                      <span>
                        · To pay <span className="font-medium tabular-nums text-ink">{formatTotals(g.toPay)}</span>
                      </span>
                    ) : null}
                  </span>
                </h3>
                <ol className="divide-y divide-line/70">
                  {g.entries.map((e, i) => (
                    <FragmentWithToday key={e.id} show={g.todayIndex === i} today={today}>
                      <Entry e={e} today={today} href={hrefFor(e)} highlighted={highlight?.id === e.id} />
                    </FragmentWithToday>
                  ))}
                  {g.todayIndex !== null && g.todayIndex >= g.entries.length ? <TodayDivider today={today} nothingElse /> : null}
                </ol>
              </section>
            );
          })
        )}
      </div>
      {hasToday && todayPos !== "visible" ? (
        <button
          type="button"
          onClick={jumpToToday}
          className="absolute bottom-4 left-1/2 z-20 inline-flex -translate-x-1/2 items-center gap-1.5 rounded-full bg-ink px-3.5 py-2 text-[13px] font-semibold text-canvas shadow-[var(--shadow-pop)] transition-transform hover:scale-[1.03] motion-reduce:hover:scale-100"
        >
          {todayPos === "above" ? <ArrowUp className="size-3.5" aria-hidden /> : <ArrowDown className="size-3.5" aria-hidden />}
          Back to today
        </button>
      ) : null}
    </section>
  );
}

function FragmentWithToday({ show, today, children }: { show: boolean; today: string; children: ReactNode }) {
  return (
    <>
      {show ? <TodayDivider today={today} nothingElse={false} /> : null}
      {children}
    </>
  );
}
