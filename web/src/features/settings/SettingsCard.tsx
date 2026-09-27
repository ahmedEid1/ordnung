import { createContext, useContext, useEffect, useRef, useState, type ReactNode, type RefObject } from "react";
import { CircleAlert, CircleCheck, Save } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/utils";
import { useReportDirty } from "./dirty";

/**
 * The width of a settings select or short field: the whole row on phones, from `sm` as wide as a
 * column of the two-column Profile form — so every form in Settings lines up the same way.
 */
export const FIELD_WIDTH = "w-full sm:max-w-sm";

/** How long a save bar stays pinned in view after saving, so its "Saved" can be read. */
export const SAVED_PIN_MS = 3000;

/** Lets a `SaveBar` pin its card's footer to the bottom of the screen (while there is something to save). */
const PinFooter = createContext<((pinned: boolean) => void) | null>(null);

/*
 * A pinned footer sits above whatever covers the bottom of the screen: the phone tab bar (h-16 +
 * home indicator), then — like the toast column — the demo tour card (--ordnung-toast-lift, its
 * height) and the toasts themselves (--ordnung-toast-space tall). Both are 0px when absent, and
 * `min(x * 999, x + gap)` is then 0 too: the gap only counts when there is something to clear. It
 * is opaque and casts a shadow up over the form it floats above.
 */
const PINNED =
  // a little tighter on phones, where the bar can take two lines
  "sticky z-20 bg-surface shadow-[0_-8px_16px_-12px_rgb(0_0_0/0.3)] max-sm:gap-y-1.5 max-sm:py-2.5 " +
  "[--pin-base:calc(4rem+env(safe-area-inset-bottom,0px))] [--pin-lift-gap:0.75rem] [--pin-gap:1.25rem] " +
  "md:[--pin-base:0px] md:[--pin-lift-gap:1.25rem] md:[--pin-gap:1.75rem]";
const clear = (v: string, gap: string) => `min(var(${v}, 0px) * 999, var(${v}, 0px) + var(${gap}))`;
const PINNED_BOTTOM = `calc(var(--pin-base) + ${clear("--ordnung-toast-lift", "--pin-lift-gap")} + ${clear("--ordnung-toast-space", "--pin-gap")})`;

/**
 * While the footer is pinned, a field that gets focus behind it (Tab to the next field) scrolls up
 * clear of it — focus is never hidden under the bar (WCAG 2.4.11).
 */
function useFocusClearOf(bar: RefObject<HTMLElement | null>, pinned: boolean) {
  useEffect(() => {
    if (!pinned) return;
    let frame = 0;
    const onFocusIn = (e: FocusEvent) => {
      const el = e.target;
      if (!(el instanceof HTMLElement) || !bar.current || bar.current.contains(el)) return;
      cancelAnimationFrame(frame);
      // after the browser's own scroll-into-view
      frame = requestAnimationFrame(() => {
        const b = bar.current?.getBoundingClientRect();
        const r = el.getBoundingClientRect();
        if (b && r.bottom > b.top && r.top < b.bottom) window.scrollBy({ top: r.bottom - b.top + 12 });
      });
    };
    document.addEventListener("focusin", onFocusIn);
    return () => {
      cancelAnimationFrame(frame);
      document.removeEventListener("focusin", onFocusIn);
    };
  }, [bar, pinned]);
}

/** A titled block inside a settings section. A `SaveBar` footer stays in view while there are unsaved edits. */
export function SettingsCard({
  title,
  description,
  children,
  footer,
  className,
  id,
}: {
  title?: ReactNode;
  description?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  className?: string;
  id?: string;
}) {
  const [pinned, setPinned] = useState(false);
  const footerRef = useRef<HTMLDivElement>(null);
  useFocusClearOf(footerRef, pinned);
  return (
    // overflow-clip (not -hidden) rounds the footer's corners without making the card a scroll
    // container, so the footer can stick to the screen's bottom edge
    <section aria-labelledby={title && id ? id : undefined} className={cn("card overflow-clip", className)}>
      <div className="p-5 sm:p-6">
        {title ? (
          <div className="mb-5">
            <h3 id={id} className="text-[15px] font-semibold text-ink">
              {title}
            </h3>
            {description ? <p className="mt-1 text-[13.5px] leading-relaxed text-muted">{description}</p> : null}
          </div>
        ) : null}
        {children}
      </div>
      {footer ? (
        <PinFooter.Provider value={setPinned}>
          <div
            ref={footerRef}
            data-pinned={pinned || undefined}
            style={pinned ? { bottom: PINNED_BOTTOM } : undefined}
            className={cn("flex flex-wrap items-center justify-end gap-x-3 gap-y-2 border-t border-line bg-surface-2/40 px-5 py-3 sm:px-6", pinned && PINNED)}
          >
            {footer}
          </div>
        </PinFooter.Provider>
      ) : null}
    </section>
  );
}

export interface SaveBarProps {
  dirty: boolean;
  saving?: boolean;
  /**
   * Saves the form (rejects when the save failed — the app's error toast says why). May resolve to a
   * short note the bar shows after "Saved." ("New letters use this name and address.").
   */
  onSave: () => Promise<ReactNode | void>;
  onDiscard?: () => void;
  /** The form has a mistake: Save doesn't save but calls `onInvalid` (show the errors, focus the first). */
  invalid?: boolean;
  onInvalid?: () => void;
  label?: string;
}

/**
 * Save row for a form card: what's unsaved (or "Saved." with a note, right after saving) +
 * Discard + Save. While there are unsaved edits it stays pinned to the bottom of the screen. It
 * reports unsaved edits — and how to save them — to the Settings page ("Save and go").
 */
export function SaveBar({ dirty, saving = false, onSave, onDiscard, invalid = false, onInvalid, label = "Save changes" }: SaveBarProps) {
  const pin = useContext(PinFooter);
  const [saved, setSaved] = useState<{ note: ReactNode } | null>(null);
  const [justSaved, setJustSaved] = useState(false);
  const [attempted, setAttempted] = useState(false);
  // a new round of edits starts without "Fix the highlighted field" (its form hides its errors again too)
  const [wasDirty, setWasDirty] = useState(dirty);
  if (dirty !== wasDirty) {
    setWasDirty(dirty);
    if (!dirty) setAttempted(false);
  }

  const save = async (): Promise<boolean> => {
    if (invalid) {
      setAttempted(true);
      onInvalid?.();
      return false;
    }
    try {
      const note = await onSave();
      setSaved({ note: note ?? null });
      setJustSaved(true);
      return true;
    } catch {
      return false; // the error toast explains; the edits stay
    }
  };
  useReportDirty(dirty, save);

  // "Saved." stays readable in place a moment before the bar goes back to the end of its card
  useEffect(() => {
    if (!justSaved) return;
    const t = setTimeout(() => setJustSaved(false), SAVED_PIN_MS);
    return () => clearTimeout(t);
  }, [justSaved]);
  const pinned = dirty || saving || justSaved;
  useEffect(() => {
    pin?.(pinned);
  }, [pin, pinned]);
  useEffect(() => () => pin?.(false), [pin]);

  const fix = dirty && invalid && attempted;
  return (
    <>
      <p
        role="status"
        className={cn(
          "mr-auto flex min-w-0 items-start gap-1.5 text-sm leading-5",
          fix ? "font-medium text-danger-ink" : dirty ? "text-warn-ink" : saved ? "text-ok-ink" : "text-muted",
        )}
      >
        {fix ? <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden /> : !dirty && saved ? <CircleCheck className="mt-0.5 size-4 shrink-0" aria-hidden /> : null}
        <span className="min-w-0">
          {fix ? (
            "Fix the highlighted field to save"
          ) : dirty ? (
            "Unsaved changes"
          ) : saved ? (
            <>
              <span className="font-medium">Saved.</span>
              {saved.note ? <span className="text-ink/80"> {saved.note}</span> : null}
            </>
          ) : (
            "All changes saved"
          )}
        </span>
      </p>
      {dirty ? (
        // Discard and Save wrap together (never Save alone on a line)
        <div className="ml-auto flex shrink-0 items-center gap-2">
          {onDiscard ? (
            <Button variant="ghost" size="sm" onClick={onDiscard} disabled={saving}>
              Discard
            </Button>
          ) : null}
          <Button variant="primary" size="sm" icon={Save} onClick={() => void save()} loading={saving}>
            {label}
          </Button>
        </div>
      ) : null}
    </>
  );
}

/**
 * Heading of a settings section (the right-hand pane). The page moves focus here when you switch
 * sections — a place for screen readers and the keyboard to start, not a control, so no focus box.
 */
export function SectionHeading({ title, description, id }: { title: string; description?: ReactNode; id: string }) {
  return (
    <header className="mb-5">
      <h2 id={id} tabIndex={-1} className="display text-[24px] font-semibold leading-tight text-ink outline-none">
        {title}
      </h2>
      {description ? <p className="mt-1.5 max-w-2xl text-[14px] leading-relaxed text-muted">{description}</p> : null}
    </header>
  );
}
