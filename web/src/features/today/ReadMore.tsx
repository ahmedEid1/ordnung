import { useEffect, useId, useLayoutEffect, useRef, useState, type FocusEvent, type ReactNode } from "react";
import { cn } from "@/lib/utils";

const CLAMP = { 3: "line-clamp-3", 4: "line-clamp-4" } as const;

/**
 * A paragraph cut at a few lines, with "Read more" / "Show less" — measured, so only text that is
 * really cut offers it. The full text is always in the page for screen readers.
 *
 * A link below the cut still takes keyboard focus: focusing it opens the text, so the link shows where
 * it is. (Left clamped, the browser scrolled the cut box to the link and nothing scrolled it back — the
 * card read from its third line on while "Read more" still said it was cut; UI audit round 2.)
 *
 * @example <ReadMore className="mt-2 text-sm text-muted"><LetterText text={reason} /></ReadMore>
 */
export function ReadMore({ children, lines = 4, className }: { children: ReactNode; lines?: keyof typeof CLAMP; className?: string }) {
  const id = useId();
  const ref = useRef<HTMLParagraphElement>(null);
  const [open, setOpen] = useState(false);
  const [cut, setCut] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el || open || typeof ResizeObserver === "undefined") return;
    // (the observer reports once right away, then on every resize)
    const ro = new ResizeObserver(() => setCut(el.scrollHeight > el.clientHeight + 1));
    ro.observe(el);
    return () => ro.disconnect();
  }, [open]);
  // cut again from its first line, whatever a focused link scrolled it to
  useLayoutEffect(() => {
    if (!open && ref.current) ref.current.scrollTop = 0;
  }, [open]);

  /** Focus in the paragraph (it fires for its links): open the text when the focused part is below the cut. */
  const onFocus = (e: FocusEvent<HTMLParagraphElement>) => {
    const el = ref.current;
    if (!el || open || e.target === el) return;
    const box = el.getBoundingClientRect();
    const hidden = el.scrollTop > 0 || e.target.getBoundingClientRect().bottom > box.bottom + 1;
    if (!hidden) return;
    el.scrollTop = 0;
    setOpen(true);
  };

  return (
    <>
      {/* data-opens-on-focus: the UI audit's clipped-content probe knows its cut links are reachable */}
      <p ref={ref} id={id} onFocus={onFocus} data-opens-on-focus="" className={cn(className, !open && CLAMP[lines])}>
        {children}
      </p>
      {cut || open ? (
        <button
          type="button"
          aria-expanded={open}
          aria-controls={id}
          onClick={() => setOpen(!open)}
          className="-mx-1 mt-0.5 inline-flex min-h-6 items-center self-start rounded-md px-1 text-sm font-semibold text-accent underline-offset-2 hover:underline"
        >
          {open ? "Show less" : "Read more"}
        </button>
      ) : null}
    </>
  );
}
