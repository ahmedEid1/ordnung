import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { cn } from "@/lib/utils";

const CLAMP = { 3: "line-clamp-3", 4: "line-clamp-4" } as const;

/**
 * A paragraph cut at a few lines, with "Read more" / "Show less" — measured, so only text that is
 * really cut offers it. The full text is always in the page for screen readers.
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
  return (
    <>
      <p ref={ref} id={id} className={cn(className, !open && CLAMP[lines])}>
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
