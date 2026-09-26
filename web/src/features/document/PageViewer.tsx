/**
 * The page images of a letter with evidence overlays: every fact and to-do found in the letter is
 * highlighted where it was found (marker colour, multiply blend, so the print stays crisp).
 * Hovering a fact in the panel lights up its highlight; selecting one scrolls it into the middle
 * of the viewer and pulses it. Photos read by AI (no text layer, so no boxes) show the quote in a
 * "Read by AI from the photo" callout instead. Zoom: fit width / 150 %; thumbnails for multi-page
 * letters; highlights are keyboard-focusable buttons.
 */
import { Fragment, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { Camera, ExternalLink, FileText, ScanText, TriangleAlert, X } from "lucide-react";
import type { PageInfo } from "@/api/types";
import { api } from "@/api/endpoints";
import { cn } from "@/lib/utils";
import { useIsTabletUp } from "@/lib/hooks";
import { GROUNDING_COPY, TONES, copyFor } from "@/lib/copy";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { Skeleton } from "@/components/ui/Skeleton";
import { useEvidence } from "./EvidenceContext";
import { boxToStyle, centerScrollOffset, hasBoxes, highlightGroups, pagesWithHighlights, type HighlightGroup } from "./evidence";

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
  className?: string;
}

export function PageViewer({ docId, pages, pageCount, photo, className }: PageViewerProps) {
  const { anchors, hovered, selected, nonce, hover, select, anchor } = useEvidence();
  const reduced = useReducedMotion();
  const [zoom, setZoom] = useState<Zoom>("fit");
  const wide = useIsTabletUp();
  const [active, setActive] = useState(1);
  const [loaded, setLoaded] = useState<Record<number, boolean>>({});
  const rootRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const pageEls = useRef(new Map<number, HTMLElement>());

  const list: PageInfo[] = useMemo(
    () =>
      pages.length
        ? pages
        : Array.from({ length: Math.max(1, pageCount) }, (_, i) => ({ page: i + 1, ...A4, text_source: "none" as const })),
    [pages, pageCount],
  );
  const groups = useMemo(() => highlightGroups(anchors), [anchors]);
  const hlPages = useMemo(() => pagesWithHighlights(groups), [groups]);
  const focusId = hovered ?? selected;
  const selectedAnchor = anchor(selected);
  const calloutAnchor =
    selectedAnchor && (!hasBoxes(selectedAnchor) || selectedAnchor.evidence.grounding === "model_read") ? selectedAnchor : null;

  // Track the most visible page (for "Page 2 of 3" and the thumbnail strip).
  useEffect(() => {
    const root = scrollRef.current;
    if (!root || typeof IntersectionObserver === "undefined") return;
    const ratios = new Map<number, number>();
    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) ratios.set(Number((e.target as HTMLElement).dataset.page), e.intersectionRatio);
        let best = 1;
        let max = -1;
        for (const [p, r] of ratios) if (r > max) [best, max] = [p, r];
        setActive(best);
      },
      { root, threshold: [0, 0.2, 0.4, 0.6, 0.8, 1] },
    );
    pageEls.current.forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, [list.length, zoom]);

  // Selecting a fact: bring the viewer into view and centre the highlight (or the page) in it.
  useEffect(() => {
    if (!selected) return;
    const a = anchor(selected);
    const container = scrollRef.current;
    if (!a || !container) return;
    const behavior: ScrollBehavior = reduced ? "auto" : "smooth";
    rootRef.current?.scrollIntoView?.({ block: "nearest", behavior });
    const group = groups.find((g) => g.anchors.some((x) => x.id === selected));
    const pageNo = group?.page ?? a.evidence.page ?? null;
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
    // re-run on every selection (nonce) and after zoom changes the layout
  }, [selected, nonce, zoom, groups, anchor, reduced]);

  const goToPage = (n: number) => {
    const container = scrollRef.current;
    const el = pageEls.current.get(n);
    if (!container || !el) return;
    const top = el.getBoundingClientRect().top - container.getBoundingClientRect().top + container.scrollTop - 12;
    container.scrollTo?.({ top: Math.max(0, top), behavior: reduced ? "auto" : "smooth" });
  };

  const total = list.length;

  return (
    <section
      ref={rootRef}
      aria-label="Letter pages"
      className={cn("card relative flex flex-col overflow-hidden", className)}
    >
      {/* toolbar */}
      <div className="flex items-center gap-x-3 border-b border-line bg-surface px-3 py-2 sm:px-4">
        <div className="flex shrink-0 items-center gap-2 text-[13px] font-medium text-ink">
          {photo ? <Camera className="size-4 text-muted" aria-hidden /> : <FileText className="size-4 text-muted" aria-hidden />}
          <span className="tabular-nums">
            Page {Math.min(active, total)} <span className="font-normal text-muted">of {total}</span>
          </span>
          {photo ? (
            <span className="hidden rounded-full bg-accent-soft px-2 py-0.5 text-[11.5px] font-medium text-accent sm:inline">Phone photo</span>
          ) : null}
        </div>
        {total > 1 ? (
          <ol aria-label="Pages" className="flex min-w-0 items-center gap-1.5 overflow-x-auto p-0.5 scrollbar-thin">
            {list.map((p) => {
              const isActive = p.page === active;
              return (
                <li key={p.page} className="shrink-0">
                  <button
                    type="button"
                    onClick={() => goToPage(p.page)}
                    aria-current={isActive ? "page" : undefined}
                    aria-label={`Go to page ${p.page}${hlPages.has(p.page) ? " (has highlights)" : ""}`}
                    className={cn(
                      "group relative block overflow-hidden rounded-[4px] bg-white ring-1 transition-[box-shadow,transform] duration-150",
                      isActive ? "ring-2 ring-accent" : "ring-line-strong hover:ring-faint",
                    )}
                    style={{ width: 24, aspectRatio: `${p.width} / ${p.height}` }}
                  >
                    <img src={api.pageUrl(docId, p.page)} alt="" className="size-full object-cover" loading="lazy" decoding="async" />
                    {hlPages.has(p.page) ? (
                      <span className="absolute right-0 top-0 size-[7px] rounded-full ring-1 ring-white" style={{ background: MARKER_EDGE }} aria-hidden />
                    ) : null}
                  </button>
                </li>
              );
            })}
          </ol>
        ) : null}
        <div className="ml-auto flex items-center gap-1.5">
          <SegmentedControl<Zoom>
            label="Zoom"
            size="sm"
            value={zoom}
            onChange={setZoom}
            options={[
              { value: "fit", label: wide ? "Fit width" : "Fit" },
              { value: "zoom", label: "150 %" },
            ]}
          />
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
        </div>
      </div>

      {/* pages */}
      {/* focusable, so the pages can be scrolled with the keyboard (e.g. at 150 %) */}
      <div
        ref={scrollRef}
        role="group"
        aria-label="Page images"
        className="relative min-h-0 flex-1 overflow-auto overscroll-contain bg-surface-2 p-3 outline-none scrollbar-thin focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent sm:p-4 dark:bg-surface-3/40"
        tabIndex={0}
      >
        <div className={cn("mx-auto flex flex-col gap-4", zoom === "zoom" ? "w-[150%] max-w-none" : "w-full")}>
          {list.map((p) => (
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
              {!loaded[p.page] ? <Skeleton className="absolute inset-0 rounded-none bg-surface-3/60" /> : null}
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
                  .map((g) => (
                    <Highlight
                      key={g.key}
                      group={g}
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

      {/* quote callout for photo / not-found evidence */}
      <AnimatePresence>
        {calloutAnchor ? (
          <motion.div
            key={calloutAnchor.id + nonce}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 6, transition: { duration: 0.12 } }}
            transition={{ duration: 0.2, ease: [0.2, 0.8, 0.2, 1] }}
            className="pointer-events-auto absolute inset-x-3 bottom-3 z-10 sm:inset-x-4 sm:bottom-4"
            role="status"
          >
            <QuoteCallout
              label={calloutAnchor.label}
              quote={calloutAnchor.evidence.quote}
              page={calloutAnchor.evidence.page}
              grounding={calloutAnchor.evidence.grounding}
              onClose={() => select(null)}
            />
          </motion.div>
        ) : null}
      </AnimatePresence>
    </section>
  );
}

function Highlight({
  group,
  focusId,
  selectedId,
  nonce,
  reduced,
  onHover,
  onSelect,
}: {
  group: HighlightGroup;
  focusId: string | null;
  selectedId: string | null;
  nonce: number;
  reduced: boolean;
  onHover: (id: string | null) => void;
  onSelect: (id: string) => void;
}) {
  const ids = group.anchors.map((a) => a.id);
  const lead = group.anchors.find((a) => a.source === "fact") ?? group.anchors[0]!;
  const isFocus = focusId !== null && ids.includes(focusId);
  const isSelected = selectedId !== null && ids.includes(selectedId);
  const dimmed = focusId !== null && !isFocus;
  const bounds = boxToStyle(group.bounds, 0.006, 0.004);
  const labelBelow = group.bounds.y0 < 0.05;
  const readByAi = group.grounding === "model_read";

  return (
    <Fragment>
      {group.boxes.map((b, i) => (
        <span
          key={i}
          aria-hidden
          className="pointer-events-none absolute rounded-[2px] mix-blend-multiply transition-opacity duration-200"
          style={{ ...boxToStyle(b, 0.003, 0.0015), background: MARKER, opacity: dimmed ? 0.28 : isFocus ? 0.95 : 0.62 } as CSSProperties}
        />
      ))}
      <button
        type="button"
        data-highlight={group.key}
        aria-label={`${lead.label}${lead.value ? `: ${lead.value}` : ""} — “${lead.evidence.quote}”`}
        aria-pressed={isSelected}
        onMouseEnter={() => onHover(lead.id)}
        onMouseLeave={() => onHover(null)}
        onFocus={() => onHover(lead.id)}
        onBlur={() => onHover(null)}
        onClick={() => onSelect(lead.id)}
        className={cn(
          "absolute cursor-pointer rounded-[3px] outline-none transition-[box-shadow] duration-200",
          "focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-1",
        )}
        style={{ ...bounds, boxShadow: isFocus ? `0 0 0 1.5px ${MARKER_EDGE}` : undefined }}
      >
        {isSelected ? (
          <motion.span
            key={nonce}
            aria-hidden
            className="pointer-events-none absolute -inset-1 rounded-[5px]"
            style={{ boxShadow: `0 0 0 2px ${MARKER_EDGE}` }}
            initial={reduced ? false : { opacity: 0.9, scale: 1 }}
            animate={reduced ? { opacity: 1 } : { opacity: [0.9, 0, 0.9, 0, 0.9], scale: [1, 1.06, 1, 1.06, 1] }}
            transition={{ duration: 1.8, ease: "easeInOut" }}
          />
        ) : null}
      </button>
      {isFocus ? (
        <span
          aria-hidden
          className="pointer-events-none absolute z-[1] max-w-[70%]"
          style={{ left: bounds.left, top: labelBelow ? `calc(${bounds.top} + ${bounds.height})` : bounds.top }}
        >
          <span
            className={cn(
              "inline-flex max-w-full items-center gap-1 truncate rounded-md bg-[#1d1b16] px-1.5 py-[3px] text-[11px] font-medium leading-none text-white shadow-md",
              labelBelow ? "mt-1" : "-translate-y-[calc(100%+4px)]",
            )}
          >
            {readByAi ? <ScanText className="size-3 shrink-0 opacity-80" /> : null}
            <span className="truncate">
              {lead.label}
              {lead.value ? <span className="font-normal opacity-75"> · {lead.value}</span> : null}
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
    <div data-testid="evidence-quote" className="rounded-xl border border-line bg-surface/95 p-3.5 shadow-[var(--shadow-pop)] backdrop-blur-md">
      <div className="flex items-start gap-2.5">
        <span className={cn("grid size-7 shrink-0 place-items-center rounded-lg", t.soft, t.icon)}>
          <Icon className="size-4" aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <p className={cn("text-[12.5px] font-semibold", t.text)}>
            {c.label}
            {page ? <span className="font-normal text-muted"> · page {page}</span> : null}
          </p>
          <p className="mt-0.5 text-[12.5px] text-muted">{label}</p>
          <blockquote lang="de" className="mt-2 text-[13.5px] leading-relaxed text-ink">
            <span className="marker box-decoration-clone px-0.5">“{quote}”</span>
          </blockquote>
          {grounding === "model_read" ? (
            <p className="mt-2 text-[12px] leading-5 text-muted">This is what Claude read from the photo. Worth comparing with the paper letter.</p>
          ) : grounding === "unverified" ? (
            <p className="mt-2 text-[12px] leading-5 text-muted">We couldn't find this sentence on the page. Please check the letter yourself.</p>
          ) : null}
        </div>
        {onClose ? (
          <button
            type="button"
            onClick={onClose}
            className="grid size-7 shrink-0 place-items-center rounded-md text-muted hover:bg-surface-2 hover:text-ink"
            aria-label="Close quote"
          >
            <X className="size-4" aria-hidden />
          </button>
        ) : null}
      </div>
    </div>
  );
}
