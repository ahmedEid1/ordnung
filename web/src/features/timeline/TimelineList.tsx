/**
 * The month-by-month list under the lanes: sticky month headers, a Today divider, and entries with
 * the date, what the date is ("Payment due"), who it's with, amount and status.
 *
 * From 768 px it scrolls inside its own card, opened at Today, so the page keeps its place. On
 * phones it is part of the page instead (a box inside a scrolling page traps the thumb): month
 * headers stick under the top bar, the months before this one fold into "Show … earlier dates", and
 * "Back to today" floats above the tab bar.
 */
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router";
import { ArrowDown, ArrowUp, ChevronRight, ChevronsUp, Pencil } from "lucide-react";
import type { TimelineEntry } from "@/api/types";
import { Button } from "@/components/ui/Button";
import { DateLeaf } from "@/components/ui/DateLeaf";
import { KindIcon } from "@/components/ui/KindBadge";
import { Money } from "@/components/ui/Money";
import { TIMELINE_TYPE_COPY, TONES, copyFor } from "@/lib/copy";
import { formatDate, formatTime, formatTotals } from "@/lib/format";
import { useIsTabletUp } from "@/lib/hooks";
import { cn, plural, prefersReducedMotion } from "@/lib/utils";
import { entryDetail, entryRole, entryStatus, foldPast, isPastEntry, type MonthGroup } from "./model";

export interface TimelineListProps {
  groups: MonthGroup[];
  today: string;
  /** link for an entry (null: not clickable) */
  hrefFor: (e: TimelineEntry) => string | null;
  /**
   * What pressing an entry without a link does (null: nothing): a date of the person's own with no letter and no
   * contract opens "Edit your date". The row is then a real button.
   */
  openFor?: (e: TimelineEntry) => (() => void) | null;
  /** How an entry's to-do repeats ("Repeats every month on the 3rd working day"), on a line of its own under its detail. */
  repeatsFor?: (e: TimelineEntry) => string | null;
  /** entry to scroll to and highlight (e.g. after clicking a lane marker) */
  highlight?: { id: string; nonce: number } | null;
  /** header content (title + filters) */
  header?: ReactNode;
  /** when this value changes, the list scrolls back to the Today divider (e.g. "Show past" toggled) */
  scrollKey?: string;
  empty?: ReactNode;
  className?: string;
}

/** Height of a sticky month header (`h-11`). */
export const MONTH_HEADER_H = 44;
/** Height of the app's sticky top bar (`TopBar`, `h-14`): phones' month headers stick under it. */
const TOP_BAR_H = 56;
/** Room the phone tab bar (`h-16`) takes at the bottom of the viewport, plus a little air. */
const TAB_BAR_ROOM = 72;

function Entry({
  e,
  today,
  href,
  open,
  repeats,
  highlighted,
}: {
  e: TimelineEntry;
  today: string;
  href: string | null;
  open: (() => void) | null;
  repeats: string | null;
  highlighted: boolean;
}) {
  const past = isPastEntry(e, today);
  const status = entryStatus(e, today);
  const role = entryRole(e);
  const kind = copyFor(TIMELINE_TYPE_COPY, e.type);
  const detail = [entryDetail(e), e.time ? formatTime(e.time) : null].filter(Boolean).join(" · ") || null;
  const meta = [role, e.party_name, detail].filter(Boolean).join(" · ");
  const amount = e.amount && e.type !== "contract" ? <Money amount={e.amount} currency={e.currency} tone={past ? "muted" : "default"} className="text-base" /> : null;
  const pill = status ? (
    <span className={cn("inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium leading-4", TONES[status.tone].soft, TONES[status.tone].text)}>
      <status.icon className="size-3" aria-hidden />
      {status.label}
    </span>
  ) : null;
  const inner = (
    <>
      <DateLeaf date={e.date} size="sm" tone={e.date === today ? "today" : past ? "muted" : "default"} decorative />
      <KindIcon kind={e.type} size="sm" className={cn("max-sm:hidden", past && "opacity-60")} />
      <span className="min-w-0 flex-1">
        {/* phones: the whole title and who it's with, wrapped; from sm one line each (full text on hover) */}
        <span title={e.title} className={cn("block break-words text-base font-medium leading-snug sm:line-clamp-1", past ? "text-ink/70" : "text-ink")}>
          {e.title}
        </span>
        <span title={meta} className="mt-0.5 block break-words text-sm leading-5 text-muted sm:truncate">
          <kind.icon className={cn("mr-1 inline size-3.5 -translate-y-px align-middle sm:hidden", TONES[kind.tone].icon, past && "opacity-60")} aria-hidden />
          <span className="font-medium">{role}</span>
          {e.party_name ? ` · ${e.party_name}` : null}
          {detail ? <span className="max-sm:hidden"> · {detail}</span> : null}
        </span>
        {/* phones: up to two lines — a day ("Transfer by Thu 14 Jan 2027") is never cut short */}
        {detail ? (
          <span title={detail} className="mt-0.5 line-clamp-2 break-words text-sm leading-5 text-muted sm:hidden">
            {detail}
          </span>
        ) : null}
        {/* how it repeats: a line of its own, wrapped and never cut short (a touch screen shows no title) */}
        {repeats ? <span className="mt-0.5 block break-words text-sm leading-5 text-muted">{repeats}</span> : null}
        {amount || pill ? (
          <span className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 sm:hidden">
            {amount}
            {pill}
          </span>
        ) : null}
      </span>
      {amount ? <span className="hidden shrink-0 sm:block">{amount}</span> : null}
      {pill ? <span className="hidden shrink-0 sm:flex">{pill}</span> : null}
      {href ? (
        <ChevronRight className="size-4 shrink-0 self-center text-faint transition-colors group-hover:text-muted" aria-hidden />
      ) : open ? (
        // a date of your own opens "Edit your date": a pencil where a link has its chevron
        <Pencil className="size-4 shrink-0 self-center text-faint transition-colors group-hover:text-muted" aria-hidden />
      ) : (
        <span className="w-4 shrink-0" aria-hidden />
      )}
    </>
  );
  const cls = cn(
    "group flex items-start gap-3 px-4 py-3 transition-colors duration-500 sm:items-center sm:px-5 sm:py-2.5",
    highlighted ? "bg-marker/45" : (href || open) && "hover:bg-surface-2/70",
  );
  const focusRing = "outline-none focus-visible:bg-surface-2 focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent";
  const sr = <span className="sr-only">{formatDate(e.date, { style: "long" })}: </span>;
  return (
    <li data-entry-id={e.id} data-date={e.date}>
      {href ? (
        <Link to={href} className={cn(cls, focusRing)}>
          {sr}
          {inner}
        </Link>
      ) : open ? (
        <button type="button" aria-haspopup="dialog" onClick={open} className={cn(cls, focusRing, "w-full cursor-pointer text-left")}>
          {sr}
          {inner}
        </button>
      ) : (
        <div className={cls}>
          {sr}
          {inner}
        </div>
      )}
    </li>
  );
}

function TodayDivider({ today, note }: { today: string; note: string | null }) {
  return (
    <li
      data-today
      className="flex flex-wrap items-center gap-x-3 gap-y-0.5 px-4 py-2 sm:px-5"
      aria-label={`Today, ${formatDate(today, { style: "long" })}${note ? ` — ${note.toLowerCase()}` : ""}`}
    >
      <span className="rounded-full bg-ink px-2 py-0.5 text-2xs font-semibold uppercase leading-4 tracking-[0.07em] text-canvas">Today</span>
      <span className="whitespace-nowrap text-sm font-semibold text-ink">{formatDate(today, { style: "short" })}</span>
      <span aria-hidden className="h-[2px] min-w-6 flex-1 rounded-full bg-ink" />
      {note ? <span className="text-xs text-muted max-sm:basis-full">{note}</span> : null}
    </li>
  );
}

function MonthHeader({ g }: { g: MonthGroup }) {
  const count = g.entries.length;
  const toPay = Object.values(g.toPay).some((total) => total > 0) ? formatTotals(g.toPay) : null;
  return (
    <h3
      id={`tl-month-${g.key}`}
      className="sticky top-14 z-10 flex h-11 items-center gap-3 border-b border-line bg-surface px-4 sm:px-5 md:top-0"
    >
      <span className={cn("display shrink-0 whitespace-nowrap text-lg font-semibold leading-none", g.past ? "text-ink/70" : "text-ink")}>
        {g.month} <span className="font-normal text-muted">{g.year}</span>
      </span>
      {count || toPay ? (
        <span className="ml-auto min-w-0 truncate text-xs text-muted">
          {/* below 360 px only the money: "€586.35 to pay" */}
          {count ? <span className={cn(toPay && "max-[360px]:hidden")}>{`${plural(count, "date")}${toPay ? " · " : ""}`}</span> : null}
          {toPay ? (
            <>
              <span className="font-medium tabular-nums text-ink">{toPay}</span> to pay
            </>
          ) : null}
        </span>
      ) : null}
    </h3>
  );
}

export function TimelineList({ groups, today, hrefFor, openFor, repeatsFor, highlight, header, empty, scrollKey = "", className }: TimelineListProps) {
  const wide = useIsTabletUp();
  const scroller = useRef<HTMLDivElement | null>(null);
  const card = useRef<HTMLElement | null>(null);
  const [todayPos, setTodayPos] = useState<"above" | "below" | "visible">("visible");
  const [showEarlier, setShowEarlier] = useState(false);
  const [scrollable, setScrollable] = useState(false);
  const hasEntries = groups.some((g) => g.entries.length);

  // Phones: the dates before today fold away until asked for, so the list starts at Today.
  const fold = useMemo(() => foldPast(groups), [groups]);
  let folded = !wide && !showEarlier && fold.hidden > 0;
  // a highlighted entry (a lane marker was clicked) among the folded ones unfolds them for good
  const has = (gs: MonthGroup[], id: string) => gs.some((g) => g.entries.some((e) => e.id === id));
  if (folded && highlight && has(groups, highlight.id) && !has(fold.groups, highlight.id)) {
    folded = false;
    setShowEarlier(true);
  }
  const shown = folded ? fold.groups : groups;

  /** Where a row should land: right under the sticky month header, in the card (wide) or the page. */
  const scrollRowTo = useCallback(
    (row: HTMLElement, behavior: ScrollBehavior) => {
      const el = scroller.current;
      if (!el) return;
      if (wide) {
        el.scrollTo?.({ top: el.scrollTop + row.getBoundingClientRect().top - el.getBoundingClientRect().top - MONTH_HEADER_H, behavior });
      } else {
        window.scrollTo?.({ top: window.scrollY + row.getBoundingClientRect().top - TOP_BAR_H - MONTH_HEADER_H, behavior });
      }
    },
    [wide],
  );

  // From 768 px, on first render with data (and when `scrollKey` changes): open the card at Today.
  // Phones never move the page on their own.
  const scrolledFor = useRef<string | null>(null);
  useLayoutEffect(() => {
    const el = scroller.current;
    if (!wide || !el || scrolledFor.current === scrollKey || !hasEntries) return;
    const mark = el.querySelector<HTMLElement>("[data-today]");
    if (!mark) return;
    scrolledFor.current = scrollKey;
    // exactly under the sticky month header: no sliver of the row before it
    el.scrollTop += mark.getBoundingClientRect().top - el.getBoundingClientRect().top - MONTH_HEADER_H;
  }, [wide, hasEntries, groups, scrollKey]);

  // "Back to today" when the divider is out of sight — in the card, or (phones) while reading the list.
  useEffect(() => {
    const el = scroller.current;
    if (!el) return;
    const update = () => {
      const mark = el.querySelector<HTMLElement>("[data-today]");
      const box = el.getBoundingClientRect();
      // (the room at the end is only there when the card scrolls — measured without it)
      setScrollable(wide && el.scrollHeight - (parseFloat(getComputedStyle(el).paddingBottom) || 0) > el.clientHeight + 1);
      if (!mark || !box.height) return setTodayPos("visible");
      const r = mark.getBoundingClientRect();
      const top = wide ? box.top + MONTH_HEADER_H : TOP_BAR_H + MONTH_HEADER_H;
      const bottom = wide ? box.bottom : window.innerHeight - TAB_BAR_ROOM;
      // phones: only once the list fills the screen, not while the lanes above are in view
      const reading = wide || (box.top < top && box.bottom > top + 80);
      if (!reading) setTodayPos("visible");
      else if (r.bottom <= top) setTodayPos("above");
      else if (r.top >= bottom) setTodayPos("below");
      else setTodayPos("visible");
    };
    let frame = 0;
    const onScroll = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(update);
    };
    const target: HTMLElement | Window = wide ? el : window;
    target.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    update();
    return () => {
      cancelAnimationFrame(frame);
      target.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
    };
  }, [wide, groups, folded]);

  // Scroll to a highlighted entry (once — after its month unfolded, if it had to).
  const scrolledTo = useRef<number | null>(null);
  useEffect(() => {
    if (!highlight || scrolledTo.current === highlight.nonce) return;
    const row = scroller.current?.querySelector<HTMLElement>(`[data-entry-id="${CSS.escape(highlight.id)}"]`);
    if (!row) return;
    scrolledTo.current = highlight.nonce;
    const behavior = prefersReducedMotion() ? "auto" : "smooth";
    if (wide) card.current?.scrollIntoView?.({ block: "start", behavior });
    scrollRowTo(row, behavior);
  }, [highlight, wide, folded, scrollRowTo]);

  const jumpToToday = () => {
    const mark = scroller.current?.querySelector<HTMLElement>("[data-today]");
    if (mark) scrollRowTo(mark, prefersReducedMotion() ? "auto" : "smooth");
  };

  return (
    // `overflow-clip`, not `hidden`: on phones the month headers stick to the page, through the card
    <section ref={card} aria-labelledby="timeline-list-title" className={cn("card relative isolate overflow-clip", className)}>
      {header}
      <div
        ref={scroller}
        className={cn(
          "relative",
          // the card scrolls from 768 px, with a soft edge where more follows and room at the end so
          // "Back to today" never covers the last row
          wide && "scroll-shadow max-h-[min(46rem,74vh)] overflow-y-auto scrollbar-thin",
          wide && scrollable && "pb-14",
        )}
      >
        {!hasEntries ? (
          <div className="p-5">{empty}</div>
        ) : (
          <>
            {folded ? (
              <div className="px-2 py-1.5 sm:px-3">
                <Button variant="ghost" size="sm" icon={ChevronsUp} aria-expanded={false} onClick={() => setShowEarlier(true)}>
                  Show {plural(fold.hidden, "earlier date")}
                </Button>
              </div>
            ) : null}
            {shown.map((g) => (
              <section key={g.key} aria-labelledby={`tl-month-${g.key}`} className="border-t border-line first:border-t-0">
                <MonthHeader g={g} />
                <ol className="divide-y divide-line/70">
                  {g.entries.map((e, i) => (
                    <FragmentWithToday key={e.id} show={g.todayIndex === i} today={today}>
                      <Entry e={e} today={today} href={hrefFor(e)} open={openFor?.(e) ?? null} repeats={repeatsFor?.(e) ?? null} highlighted={highlight?.id === e.id} />
                    </FragmentWithToday>
                  ))}
                  {g.todayIndex !== null && g.todayIndex >= g.entries.length ? (
                    <TodayDivider today={today} note={g.entries.length || g.folded ? "Nothing else this month" : "Nothing this month"} />
                  ) : null}
                </ol>
              </section>
            ))}
          </>
        )}
      </div>
      {hasEntries && todayPos !== "visible" ? (
        <button
          type="button"
          onClick={jumpToToday}
          className={cn(
            "left-1/2 z-20 inline-flex -translate-x-1/2 items-center gap-1.5 rounded-full bg-ink px-3.5 py-2 text-sm font-semibold text-canvas shadow-[var(--shadow-pop)] transition-transform hover:scale-[1.03] motion-reduce:hover:scale-100",
            wide ? "absolute bottom-4" : "fixed bottom-[calc(5rem+env(safe-area-inset-bottom)+var(--ordnung-tour-bar,0px))]",
          )}
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
      {show ? <TodayDivider today={today} note={null} /> : null}
      {children}
    </>
  );
}
