/**
 * The page images of a letter with evidence overlays: every fact and to-do found in the letter is
 * highlighted where it was found (marker colour, multiply blend, so the print stays crisp).
 * Hovering a fact in the panel lights up its highlight; selecting one brings it into view and pulses
 * it. Photos read by AI (no text layer, so no boxes) show the quote in a "Read by AI from the photo"
 * callout instead. Zoom: fit width / 150%; thumbnails for multi-page letters; highlights are
 * keyboard-focusable buttons.
 *
 * Two layouts (UI audit round 1):
 * - `paged` (phones and tablets, where the viewer sits in the page's own column): one page at a time
 *   with a pager, and no scroll box of its own — a swipe scrolls the page, never a box inside it. The
 *   quote callout sits under the page instead of over the photo, and after jumping to a fact a
 *   "Back to …" pill returns to where the person was.
 * - the sticky column (xl): every page in a scroll box as tall as the screen, or shorter when the
 *   pages are.
 */
import {
  Fragment,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import { createPortal } from "react-dom";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import {
  Camera,
  ChevronLeft,
  ChevronRight,
  ExternalLink,
  FileText,
  ScanText,
  TriangleAlert,
  Undo2,
  X,
} from "lucide-react";
import type { PageInfo } from "@/api/types";
import { api } from "@/api/endpoints";
import { cn } from "@/lib/utils";
import { useIsTabletUp } from "@/lib/hooks";
import { GROUNDING_COPY, TONES, copyFor } from "@/lib/copy";
import { Button } from "@/components/ui/Button";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { Skeleton } from "@/components/ui/Skeleton";
import { ComputerOnly } from "@/features/phone/ComputerOnly";
import { useEvidence } from "./EvidenceContext";
import {
  boxToStyle,
  centerScrollOffset,
  hasBoxes,
  highlightGroups,
  hitBoxStyle,
  hitBoxes,
  labelPlacement,
  pagesWithHighlights,
  type EvidenceAnchor,
  type HighlightGroup,
} from "./evidence";

type Zoom = "fit" | "zoom";

const A4 = { width: 1240, height: 1754 };
/** Highlighter on paper (page images are always light, so this is theme-independent). */
const MARKER = "#fde047";
const MARKER_EDGE = "#d97706";

export interface PageViewerProps {
  docId: string;
  pages: PageInfo[];
  /** Page count from the document (used while pages are not rendered yet). */
  pageCount: number;
  /** The letter is a phone photo (read by AI). */
  photo?: boolean;
  /** One page at a time with a pager and no scroll box (phones and tablets); else every page in a scroll box. */
  paged?: boolean;
  className?: string;
}

/** Where to return to after jumping to a fact on a phone ("Back to Key facts"). */
interface BackTo {
  /** The page's scroll position then (used when the control is gone). */
  y: number;
  /** The control that chose the fact, and where it was on the screen. */
  el: HTMLElement | null;
  top: number;
  label: string;
}

export function PageViewer({
  docId,
  pages,
  pageCount,
  photo,
  paged = false,
  className,
}: PageViewerProps) {
  const { anchors, hovered, selected, nonce, hover, select, anchor } =
    useEvidence();
  const reduced = useReducedMotion();
  const [zoom, setZoom] = useState<Zoom>("fit");
  const wide = useIsTabletUp();
  const [active, setActive] = useState(1);
  const [loaded, setLoaded] = useState<Record<number, boolean>>({});
  const [back, setBack] = useState<BackTo | null>(null);
  const rootRef = useRef<HTMLElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const pageEls = useRef(new Map<number, HTMLElement>());
  /** The selection (nonce and zoom) already brought into view — so turning the page later doesn't jump back. */
  const shown = useRef<string | null>(null);

  const list: PageInfo[] = useMemo(
    () =>
      pages.length
        ? pages
        : Array.from({ length: Math.max(1, pageCount) }, (_, i) => ({
            page: i + 1,
            ...A4,
            text_source: "none" as const,
          })),
    [pages, pageCount],
  );
  const groups = useMemo(() => highlightGroups(anchors), [anchors]);
  const hlPages = useMemo(() => pagesWithHighlights(groups), [groups]);
  const total = list.length;
  const current = Math.min(active, total);
  const visible = paged ? list.filter((p) => p.page === current) : list;
  const focusId = hovered ?? selected;
  const selectedAnchor = anchor(selected);
  const calloutAnchor =
    selectedAnchor &&
    (!hasBoxes(selectedAnchor) ||
      selectedAnchor.evidence.grounding === "model_read")
      ? selectedAnchor
      : null;
  const behavior: ScrollBehavior = reduced ? "auto" : "smooth";

  // Track the most visible page in the scroll box (for "Page 2 of 3" and the thumbnail strip).
  useEffect(() => {
    const root = scrollRef.current;
    if (paged || !root || typeof IntersectionObserver === "undefined") return;
    const ratios = new Map<number, number>();
    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries)
          ratios.set(
            Number((e.target as HTMLElement).dataset.page),
            e.intersectionRatio,
          );
        let best = 1;
        let max = -1;
        for (const [p, r] of ratios) if (r > max) [best, max] = [p, r];
        setActive(best);
      },
      { root, threshold: [0, 0.2, 0.4, 0.6, 0.8, 1] },
    );
    pageEls.current.forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, [list.length, zoom, paged]);

  // Selecting a fact: show its page, then bring the highlight (or the page) into view.
  useEffect(() => {
    if (!selected) return;
    const a = anchor(selected);
    if (!a) return;
    const key = `${nonce}:${zoom}`;
    if (shown.current === key) return;
    const group = groups.find((g) => g.anchors.some((x) => x.id === selected));
    const pageNo = group?.page ?? a.evidence.page ?? null;
    if (paged) {
      const frame = window.requestAnimationFrame(() => {
        if (pageNo && pageNo !== current && pageNo <= total) {
          setActive(pageNo); // this runs again once the page is there
          return;
        }
        shown.current = key;
        // the panel is below or above the viewer here: remember where the person was
        const from =
          document.activeElement instanceof HTMLElement &&
          !rootRef.current?.contains(document.activeElement)
            ? document.activeElement
            : null;
        // measured now, before the jump (an updater would run after it)
        const here: BackTo = {
          y: window.scrollY,
          el: from,
          top: from?.getBoundingClientRect().top ?? 0,
          label: backLabel(a),
        };
        setBack((b) => b ?? here);
        const target = group
          ? rootRef.current?.querySelector<HTMLElement>(
              `[data-highlight="${CSS.escape(group.key)}"]`,
            )
          : null;
        if (target)
          target.scrollIntoView?.({
            block: "center",
            inline: "center",
            behavior,
          });
        else {
          // a photo's quote sits under it: show both when they fit, else the quote (the page scrolls up to it)
          const root = rootRef.current;
          const quote = root?.querySelector<HTMLElement>(
            '[data-testid="evidence-quote"]',
          );
          const fits = root
            ? root.getBoundingClientRect().height <= window.innerHeight - 160
            : true;
          if (quote && !fits)
            quote.scrollIntoView?.({ block: "end", behavior });
          else root?.scrollIntoView?.({ block: "start", behavior });
        }
      });
      return () => window.cancelAnimationFrame(frame);
    }
    shown.current = key;
    const container = scrollRef.current;
    if (!container) return;
    rootRef.current?.scrollIntoView?.({ block: "nearest", behavior });
    const pageEl = pageNo ? pageEls.current.get(pageNo) : undefined;
    if (!pageEl) return;
    const c = container.getBoundingClientRect();
    const p = pageEl.getBoundingClientRect();
    const pageTop = p.top - c.top + container.scrollTop;
    const pageLeft = p.left - c.left + container.scrollLeft;
    if (group) {
      const { top, left } = centerScrollOffset(group.bounds, {
        pageTop,
        pageLeft,
        pageWidth: p.width,
        pageHeight: p.height,
        viewportWidth: container.clientWidth,
        viewportHeight: container.clientHeight,
        contentWidth: container.scrollWidth,
        contentHeight: container.scrollHeight,
      });
      container.scrollTo?.({ top, left, behavior });
    } else {
      container.scrollTo?.({ top: Math.max(0, pageTop - 12), behavior });
    }
    // re-run on every selection (nonce), after zoom changes the layout and once a turned page is there
  }, [selected, nonce, zoom, groups, anchor, behavior, paged, current, total]);

  // The quote callout closes with Escape (not while a dialog or menu has the key).
  useEffect(() => {
    if (!calloutAnchor) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || e.defaultPrevented) return;
      if (
        e.target instanceof Element &&
        e.target.closest(
          "[role=dialog],[role=menu],[role=listbox],[role=alertdialog]",
        )
      )
        return;
      select(null);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [calloutAnchor, select]);

  // "Back to …" goes away once the person scrolls back there themselves.
  useEffect(() => {
    if (!back) return;
    const onScroll = () => {
      if (Math.abs(window.scrollY - back.y) < 120) setBack(null);
    };
    // not before the jump has moved away from there
    const t = window.setTimeout(
      () => window.addEventListener("scroll", onScroll, { passive: true }),
      900,
    );
    return () => {
      window.clearTimeout(t);
      window.removeEventListener("scroll", onScroll);
    };
  }, [back]);

  const goBack = () => {
    if (!back) return;
    // back to the control itself, where it was on the screen: the layout above it may have changed meanwhile
    // (the quote under the page opened or closed)
    const el = back.el?.isConnected ? back.el : null;
    window.scrollTo({
      top: el
        ? window.scrollY + el.getBoundingClientRect().top - back.top
        : back.y,
      behavior,
    });
    el?.focus({ preventScroll: true });
    setBack(null);
  };

  const goToPage = (n: number) => {
    if (paged) {
      setActive(Math.min(Math.max(1, n), total));
      return;
    }
    const container = scrollRef.current;
    const el = pageEls.current.get(n);
    if (!container || !el) return;
    const top =
      el.getBoundingClientRect().top -
      container.getBoundingClientRect().top +
      container.scrollTop -
      12;
    container.scrollTo?.({ top: Math.max(0, top), behavior });
  };

  const callout = calloutAnchor ? (
    <QuoteCallout
      label={calloutAnchor.label}
      quote={calloutAnchor.evidence.quote}
      page={calloutAnchor.evidence.page}
      grounding={calloutAnchor.evidence.grounding}
      onClose={() => select(null)}
    />
  ) : null;

  return (
    <section
      ref={rootRef}
      aria-label="Letter pages"
      // clear of the sticky top bar when a fact brings it into view
      className={cn(
        "card @container relative flex scroll-mt-20 flex-col overflow-hidden",
        className,
      )}
    >
      {/* toolbar: the page count and zoom never wrap; the thumbnails take the room left (none under 360 px) */}
      <div className="flex items-center gap-x-3 border-b border-line bg-surface px-3 py-2 @sm:px-4">
        <div className="flex shrink-0 items-center gap-2 text-[13px] font-medium text-ink">
          {photo ? (
            <Camera
              className="size-4 text-muted"
              aria-label="Phone photo"
              role="img"
            />
          ) : (
            <FileText className="size-4 text-muted" aria-hidden />
          )}
          <span className="whitespace-nowrap tabular-nums">
            Page {current}{" "}
            <span className="font-normal text-muted">of {total}</span>
          </span>
          {photo ? (
            <span
              className="hidden whitespace-nowrap rounded-full bg-accent-soft px-2 py-0.5 text-[12px] font-medium text-accent @xl:inline"
              aria-hidden
            >
              Phone photo
            </span>
          ) : null}
        </div>
        {total > 1 ? (
          <ol
            aria-label="Pages"
            className="hidden min-w-0 flex-1 items-center gap-1.5 overflow-x-auto p-1 scrollbar-thin @min-[340px]:flex"
          >
            {list.map((p) => {
              const isActive = p.page === current;
              return (
                <li key={p.page} className="shrink-0">
                  <button
                    type="button"
                    onClick={() => goToPage(p.page)}
                    aria-current={isActive ? "page" : undefined}
                    aria-label={`Go to page ${p.page}${hlPages.has(p.page) ? " (has highlights)" : ""}`}
                    className={cn(
                      "group relative block rounded-[4px] ring-1 transition-[box-shadow] duration-150",
                      isActive
                        ? "ring-2 ring-accent"
                        : "ring-line-strong hover:ring-faint",
                    )}
                    style={{
                      width: 24,
                      aspectRatio: `${p.width} / ${p.height}`,
                    }}
                  >
                    <span className="block size-full overflow-hidden rounded-[4px] bg-white">
                      <img
                        src={api.pageUrl(docId, p.page)}
                        alt=""
                        className="size-full object-cover dark:brightness-[0.93]"
                        loading="lazy"
                        decoding="async"
                      />
                    </span>
                    {/* outside the clipped thumbnail, so the round corner never cuts it */}
                    {hlPages.has(p.page) ? (
                      <span
                        className="absolute -right-1 -top-1 size-2 rounded-full ring-2 ring-surface"
                        style={{ background: MARKER_EDGE }}
                        aria-hidden
                      />
                    ) : null}
                  </button>
                </li>
              );
            })}
          </ol>
        ) : null}
        <div className="ml-auto flex shrink-0 items-center gap-1.5">
          <SegmentedControl<Zoom>
            label="Zoom"
            size="sm"
            value={zoom}
            onChange={setZoom}
            options={[
              { value: "fit", label: wide ? "Fit width" : "Fit" },
              { value: "zoom", label: "150%" },
            ]}
          />
          {/* the original file never leaves the computer for a paired phone (its page images do) */}
          <ComputerOnly what="Open the original file">
            <a
              href={api.fileUrl(docId)}
              target="_blank"
              rel="noreferrer"
              className="grid size-8 place-items-center rounded-lg text-muted transition-colors hover:bg-surface-3/70 hover:text-ink"
              title="Open the original file"
            >
              <ExternalLink className="size-4" aria-hidden />
              <span className="sr-only">Open the original file (new tab)</span>
            </a>
          </ComputerOnly>
        </div>
      </div>

      {/* pages */}
      {/* focusable, so the pages can be scrolled with the keyboard (e.g. at 150%) */}
      <div
        ref={scrollRef}
        role="group"
        aria-label="Page images"
        className={cn(
          "relative bg-surface-2 p-3 outline-none scrollbar-thin focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent @sm:p-4 dark:bg-surface-3/40",
          // paged: the page scrolls, not this box (only sideways at 150%); the column: a scroll box of its own
          paged
            ? "overflow-x-auto overflow-y-hidden"
            : "min-h-0 flex-1 overflow-auto overscroll-contain",
        )}
        tabIndex={0}
      >
        <div
          className={cn(
            "mx-auto flex flex-col gap-4",
            zoom === "zoom" ? "w-[150%] max-w-none" : "w-full",
          )}
        >
          {visible.map((p) => (
            <figure
              key={p.page}
              data-page={p.page}
              ref={(el) => {
                if (el) pageEls.current.set(p.page, el);
                else pageEls.current.delete(p.page);
              }}
              className="relative m-0 overflow-hidden rounded-[3px] bg-white shadow-[0_1px_2px_rgb(0_0_0/0.10),0_10px_28px_-14px_rgb(0_0_0/0.35)]"
              style={{ aspectRatio: `${p.width} / ${p.height}` }}
            >
              {!loaded[p.page] ? (
                <Skeleton className="absolute inset-0 rounded-none bg-surface-3/60" />
              ) : null}
              <img
                src={api.pageUrl(docId, p.page)}
                alt={`Page ${p.page} of ${total}`}
                width={p.width}
                height={p.height}
                loading={p.page > 2 ? "lazy" : "eager"}
                decoding="async"
                onLoad={() => setLoaded((l) => ({ ...l, [p.page]: true }))}
                className="relative block h-auto w-full select-none dark:brightness-[0.93]"
                draggable={false}
              />
              <figcaption className="sr-only">Page {p.page}</figcaption>
              <div className="absolute inset-0">
                {groups
                  .filter((g) => g.page === p.page)
                  .map((g, _i, onPage) => (
                    <Highlight
                      key={g.key}
                      group={g}
                      groups={onPage}
                      focusId={focusId}
                      selectedId={selected}
                      nonce={nonce}
                      reduced={Boolean(reduced)}
                      onHover={hover}
                      onSelect={select}
                    />
                  ))}
              </div>
            </figure>
          ))}
        </div>
      </div>

      {paged && total > 1 ? (
        <nav
          aria-label="Turn pages"
          className="flex items-center justify-between gap-2 border-t border-line bg-surface px-2 py-1.5"
        >
          <Button
            variant="ghost"
            size="sm"
            icon={ChevronLeft}
            disabled={current <= 1}
            onClick={() => goToPage(current - 1)}
          >
            Previous
          </Button>
          <span className="text-[13px] tabular-nums text-muted" aria-hidden>
            {current} / {total}
          </span>
          <Button
            variant="ghost"
            size="sm"
            disabled={current >= total}
            onClick={() => goToPage(current + 1)}
          >
            Next
            <ChevronRight aria-hidden />
          </Button>
        </nav>
      ) : null}

      {/* quote callout for photo / not-found evidence: under the page here, over it in the tall column */}
      <AnimatePresence>
        {callout ? (
          <motion.div
            key={calloutAnchor!.id + nonce}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 6, transition: { duration: 0.12 } }}
            transition={{ duration: 0.2, ease: [0.2, 0.8, 0.2, 1] }}
            className={
              paged
                ? "border-t border-line p-3 @sm:p-4"
                : "pointer-events-auto absolute inset-x-3 bottom-3 z-10 @sm:inset-x-4 @sm:bottom-4"
            }
            role="status"
          >
            {callout}
          </motion.div>
        ) : null}
      </AnimatePresence>

      {back && typeof document !== "undefined"
        ? createPortal(
            <button
              type="button"
              onClick={goBack}
              className="fixed bottom-[calc(4.75rem+env(safe-area-inset-bottom,0px)+var(--ordnung-tour-bar,0px))] left-1/2 z-30 inline-flex min-h-9 -translate-x-1/2 items-center gap-1.5 whitespace-nowrap rounded-full border border-line bg-surface/95 px-4 text-[13px] font-medium text-ink shadow-[var(--shadow-pop)] backdrop-blur-md transition-colors hover:bg-surface-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent md:bottom-[calc(1.5rem+var(--ordnung-tour-clearance,0px))]"
            >
              <Undo2 className="size-4 text-muted" aria-hidden />
              {back.label}
            </button>,
            document.body,
          )
        : null}
    </section>
  );
}

/** Where "Back to …" returns: the list the fact or to-do was chosen from. */
function backLabel(a: EvidenceAnchor): string {
  return a.source === "fact" ? "Back to Key facts" : "Back to To-dos";
}

function Highlight({
  group,
  groups,
  focusId,
  selectedId,
  nonce,
  reduced,
  onHover,
  onSelect,
}: {
  group: HighlightGroup;
  /** Every highlight on this page (the targets keep clear of each other). */
  groups: readonly HighlightGroup[];
  focusId: string | null;
  selectedId: string | null;
  nonce: number;
  reduced: boolean;
  onHover: (id: string | null) => void;
  onSelect: (id: string) => void;
}) {
  const ids = group.anchors.map((a) => a.id);
  const lead =
    group.anchors.find((a) => a.source === "fact") ?? group.anchors[0]!;
  const isFocus = focusId !== null && ids.includes(focusId);
  const isSelected = selectedId !== null && ids.includes(selectedId);
  const dimmed = focusId !== null && !isFocus;
  const bounds = boxToStyle(group.bounds, 0.006, 0.004);
  const place = labelPlacement(group, groups);
  const labelTop =
    place.side === "below"
      ? `calc(${bounds.top} + ${bounds.height})`
      : bounds.top;
  const readByAi = group.grounding === "model_read";
  // smaller highlights on top: where two quotes share a line, the shorter one stays reachable
  const area =
    (group.bounds.x1 - group.bounds.x0) * (group.bounds.y1 - group.bounds.y0);
  const z = 2 + Math.round((1 - Math.min(1, area * 20)) * 20);
  const hits = hitBoxes(group, groups);
  const pointer = {
    onMouseEnter: () => onHover(lead.id),
    onMouseLeave: () => onHover(null),
    onClick: () => onSelect(lead.id),
  };

  return (
    <Fragment>
      {group.boxes.map((b, i) => (
        <span
          key={i}
          aria-hidden
          className="pointer-events-none absolute rounded-[2px] mix-blend-multiply transition-opacity duration-200"
          style={
            {
              ...boxToStyle(b, 0.003, 0.0015),
              background: MARKER,
              opacity: dimmed ? 0.28 : isFocus ? 0.95 : 0.62,
            } as CSSProperties
          }
        />
      ))}
      {/* the pointer targets: one per line, a finger tall, never over a neighbouring highlight's line */}
      {hits.map((h, i) => (
        <span
          key={`hit${i}`}
          aria-hidden
          data-hit={group.key}
          className="absolute cursor-pointer"
          style={{ ...hitBoxStyle(h), zIndex: z }}
          {...pointer}
        />
      ))}
      {/* the keyboard target (and its focus outline) spans the whole quote, at least a finger's 24 px each
          way (a one-line quote at a small zoom is shorter; axe measures it as a target, though the pointer
          uses the lines above) */}
      <button
        type="button"
        data-highlight={group.key}
        aria-label={`${lead.label}${lead.value ? `: ${lead.value}` : ""} — “${lead.evidence.quote}”`}
        aria-pressed={isSelected}
        onFocus={() => onHover(lead.id)}
        onBlur={() => onHover(null)}
        onClick={() => onSelect(lead.id)}
        className="pointer-events-none absolute rounded-[3px] transition-[box-shadow] duration-200 focus-visible:outline-2 focus-visible:outline-solid focus-visible:outline-offset-2 focus-visible:outline-accent"
        style={{
          ...bounds,
          minWidth: 24,
          minHeight: 24,
          zIndex: z,
          boxShadow: isFocus ? `0 0 0 1.5px ${MARKER_EDGE}` : undefined,
        }}
      >
        {isSelected ? (
          // a thin ring that blinks in place (it grew over the neighbouring lines)
          <motion.span
            key={nonce}
            aria-hidden
            className="pointer-events-none absolute -inset-[3px] rounded-[5px]"
            style={{ outline: `2px solid ${MARKER_EDGE}` }}
            initial={reduced ? false : { opacity: 1 }}
            animate={
              reduced ? { opacity: 1 } : { opacity: [1, 0.15, 1, 0.15, 1] }
            }
            transition={{ duration: 1.8, ease: "easeInOut" }}
          />
        ) : null}
      </button>
      {isFocus ? (
        <span
          aria-hidden
          className="pointer-events-none absolute z-[30] flex"
          style={
            // never past the page's edge: right-aligned to a box in the right half, and no wider than the room
            place.align === "right"
              ? {
                  right: `calc(100% - ${bounds.left} - ${bounds.width})`,
                  top: labelTop,
                  justifyContent: "flex-end",
                  maxWidth: `min(70%, calc(${bounds.left} + ${bounds.width}))`,
                }
              : {
                  left: bounds.left,
                  top: labelTop,
                  maxWidth: `min(70%, calc(100% - ${bounds.left}))`,
                }
          }
        >
          <span
            className={cn(
              "inline-flex max-w-full items-center gap-1 truncate rounded-md bg-[#1d1b16] px-1.5 py-[3px] text-[11px] font-medium leading-none text-white shadow-md",
              place.side === "below" ? "mt-1" : "-translate-y-[calc(100%+4px)]",
            )}
          >
            {readByAi ? (
              <ScanText className="size-3 shrink-0 opacity-80" />
            ) : null}
            <span className="truncate">
              {lead.label}
              {lead.value ? (
                <span className="font-normal opacity-75"> · {lead.value}</span>
              ) : null}
            </span>
          </span>
        </span>
      ) : null}
    </Fragment>
  );
}

/** "Read by AI from the photo" / "Couldn't find this — please check" with the verbatim quote. */
export function QuoteCallout({
  label,
  quote,
  page,
  grounding,
  onClose,
}: {
  label: string;
  quote: string;
  page: number | null;
  grounding: keyof typeof GROUNDING_COPY;
  onClose?: () => void;
}) {
  const c = copyFor(GROUNDING_COPY, grounding);
  const t = TONES[c.tone];
  const Icon = grounding === "unverified" ? TriangleAlert : c.icon;
  return (
    <div
      data-testid="evidence-quote"
      className="rounded-xl border border-line bg-surface/95 p-3.5 shadow-[var(--shadow-pop)] backdrop-blur-md"
    >
      <div className="flex items-start gap-2.5">
        <span
          className={cn(
            "grid size-7 shrink-0 place-items-center rounded-lg",
            t.soft,
            t.icon,
          )}
        >
          <Icon className="size-4" aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <p className={cn("text-[12.5px] font-semibold", t.text)}>
            {c.label}
            {page ? (
              <span className="font-normal text-muted"> · page {page}</span>
            ) : null}
          </p>
          <p className="mt-0.5 text-[12.5px] text-muted">{label}</p>
          <blockquote
            lang="de"
            className="mt-2 text-[13.5px] leading-relaxed text-ink wrap-break-word hyphens-auto"
          >
            <span className="marker box-decoration-clone px-0.5">
              “{quote}”
            </span>
          </blockquote>
          {grounding === "model_read" ? (
            <p className="mt-2 text-[12px] leading-5 text-muted">
              This is what Claude read from the photo. Worth comparing with the
              paper letter.
            </p>
          ) : grounding === "unverified" ? (
            <p className="mt-2 text-[12px] leading-5 text-muted">
              We couldn't find this sentence on the page. Please check the
              letter yourself.
            </p>
          ) : null}
        </div>
        {onClose ? (
          <button
            type="button"
            onClick={onClose}
            className="grid size-7 shrink-0 place-items-center rounded-md text-muted hover:bg-surface-2 hover:text-ink"
            aria-label="Close quote"
            title="Close (Esc)"
          >
            <X className="size-4" aria-hidden />
          </button>
        ) : null}
      </div>
    </div>
  );
}
