import {
  cloneElement,
  isValidElement,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactElement,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";
import { useIsTabletUp } from "@/lib/hooks";
import { IconButton } from "./Button";
import {
  floatingStyle,
  focusableIn,
  getOverlayRoot,
  mergeRefs,
  pageInsets,
  resolveBox,
  setPanelTrigger,
  tabbableAfter,
  tabbableIn,
  useDismiss,
  useFloating,
  useModal,
  useStableId,
  type Placement,
} from "./internal";

type TriggerProps = {
  "aria-expanded"?: boolean;
  "aria-controls"?: string;
  "aria-haspopup"?: "dialog" | "menu" | "listbox" | boolean;
};

export interface PopoverProps {
  /** The trigger: a single clickable element (Button, button…). */
  children: ReactElement;
  /** Panel content, or a render function receiving `close` (which gives focus back to the trigger). */
  content: ReactNode | ((close: () => void) => ReactNode);
  placement?: Placement;
  /** Controlled open state. */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  /** Accessible name of the panel. */
  label?: string;
  /**
   * Visible title of the phone bottom sheet (default: `label`). Content can hide a heading of its
   * own that would repeat it with `in-sheet:hidden`.
   */
  title?: ReactNode;
  /** Floating-panel classes (width, padding). Default: w-80 p-4. On phones the sheet is full width with its own padding. */
  className?: string;
  /**
   * Move focus into the panel on open (default true): to the panel itself (announced by its label;
   * Tab then reaches the first control), or with `"first"` to its first control (menus).
   */
  autoFocus?: boolean | "first";
  role?: "dialog" | "menu" | "listbox";
}

/** Smallest height a floating panel shrinks to when its anchor is scrolled towards an edge. */
const MIN_PANEL_HEIGHT = 120;

/**
 * Click-triggered floating panel (e.g. "Why this date?"), a modal bottom sheet on phones.
 *
 * - Placement: the preferred side when the panel fits there, otherwise the side with more room;
 *   it never covers its trigger or the top bar, keeps its side while open, and when it grows the
 *   page scrolls to make room.
 * - Keyboard: focus moves to the panel on open; Tab past the last control (or Shift+Tab before
 *   the first) closes it and continues from the trigger, like the panel sat right after it.
 *   Escape closes and returns focus to the trigger; so does leaving it with focus or an outside click.
 * - Phones: a sheet with a title and a Close button that traps focus, locks the page scroll and
 *   makes the page inert.
 *
 * Works controlled or uncontrolled. The trigger is wrapped in a `display: contents` span, so
 * layout is unaffected.
 *
 * @example
 * <Popover label="Why this date?" content={<ReceiptSteps />}><Button variant="link">Why this date?</Button></Popover>
 */
export function Popover({
  children,
  content,
  placement = "bottom-start",
  open: openProp,
  onOpenChange,
  label,
  title,
  className,
  autoFocus = true,
  role = "dialog",
}: PopoverProps) {
  const [openState, setOpenState] = useState(false);
  const open = openProp ?? openState;
  const [wrap, setWrap] = useState<HTMLSpanElement | null>(null);
  const [panel, setPanel] = useState<HTMLDivElement | null>(null);
  const panelRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLElement | null>(null);
  const id = useStableId(undefined, "pop");
  const titleId = useStableId(undefined, "pop-title");
  // phones: a bottom sheet — a small floating panel with its own scroll gets clipped there. The
  // form is fixed while it is open (rotating a phone or resizing doesn't swap the panel under you).
  const reduceMotion = useReducedMotion();
  const phone = !useIsTabletUp();
  const [openedAsSheet, setOpenedAsSheet] = useState<boolean | null>(null);
  if (open && openedAsSheet === null) setOpenedAsSheet(phone);
  else if (!open && openedAsSheet !== null) setOpenedAsSheet(null);
  const sheet = open ? (openedAsSheet ?? phone) : phone;
  const pos = useFloating(wrap, panel, open && !sheet, placement, { insets: pageInsets, scrollToFit: true });
  const ref = useMemo(() => mergeRefs<HTMLDivElement>(setPanel, panelRef), []);

  useEffect(() => {
    triggerRef.current = resolveBox(wrap);
    setPanelTrigger(panel, triggerRef.current);
  }, [wrap, panel]);

  const setOpen = useCallback(
    (v: boolean) => {
      if (openProp === undefined) setOpenState(v);
      onOpenChange?.(v);
    },
    [openProp, onOpenChange],
  );
  /** Close; focus inside the panel goes back to the trigger instead of dropping to <body>. */
  const close = useCallback(() => {
    if (panel?.contains(document.activeElement)) resolveBox(wrap)?.focus({ preventScroll: true });
    setOpen(false);
  }, [setOpen, panel, wrap]);
  const dismiss = useCallback(() => setOpen(false), [setOpen]);
  const closeAndFocus = useCallback(() => {
    setOpen(false);
    resolveBox(wrap)?.focus({ preventScroll: true });
  }, [setOpen, wrap]);

  const initialFocus = useCallback(() => {
    const p = panelRef.current;
    if (!p) return null;
    // "first": the first control of the content (not the sheet's Close button)
    const body = p.querySelector<HTMLElement>("[data-popover-body]") ?? p;
    return autoFocus === "first" ? (tabbableIn(body)[0] ?? focusableIn(body)[0] ?? p) : p;
  }, [autoFocus]);

  // Floating panel: Escape returns focus to the trigger; an outside click just closes.
  useDismiss(open && !sheet, closeAndFocus, [wrap, panel], { outside: false });
  useDismiss(open, dismiss, [wrap, panel], { escape: false });
  // Sheet: a real modal (focus trap, Escape, inert page, scroll lock, focus back to the trigger).
  useModal(open && sheet, panelRef, close, { initialFocus, returnFocus: triggerRef });

  useEffect(() => {
    if (!open || sheet || !autoFocus || !panel) return;
    const raf = requestAnimationFrame(() => initialFocus()?.focus({ preventScroll: true }));
    return () => cancelAnimationFrame(raf);
  }, [open, sheet, autoFocus, panel, initialFocus]);

  // The panel is portaled to the end of <body>: Tab out of it continues from the trigger.
  const onPanelKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (sheet || e.key !== "Tab" || e.defaultPrevented || !panel) return;
    const items = tabbableIn(panel);
    const active = document.activeElement;
    const leaving = e.shiftKey ? active === panel || active === items[0] || items.length === 0 : items.length === 0 || active === items[items.length - 1];
    if (!leaving) return;
    e.preventDefault();
    const trigger = triggerRef.current;
    setOpen(false);
    (e.shiftKey || !trigger ? trigger : (tabbableAfter(trigger) ?? trigger))?.focus();
  };
  // Focus that moves on into the page (not the trigger, not another overlay opened from here)
  // closes it — also when focus got there from <body>, e.g. after a focused button disappeared.
  useEffect(() => {
    if (!open || sheet) return;
    const onFocusIn = (e: globalThis.FocusEvent) => {
      const t = e.target as Node;
      if (panel?.contains(t) || wrap?.contains(t) || getOverlayRoot().contains(t)) return;
      dismiss();
    };
    document.addEventListener("focusin", onFocusIn);
    return () => document.removeEventListener("focusin", onFocusIn);
  }, [open, sheet, panel, wrap, dismiss]);

  if (!isValidElement(children)) return null;
  const trigger = cloneElement(children as ReactElement<TriggerProps>, {
    "aria-expanded": open,
    "aria-controls": open ? id : undefined,
    "aria-haspopup": sheet ? "dialog" : role,
  });
  const body = typeof content === "function" ? content(close) : content;
  const heading = title ?? label;

  return (
    <>
      <span ref={setWrap} className="contents" onClick={(e) => !e.defaultPrevented && setOpen(!open)}>
        {trigger}
      </span>
      {createPortal(
        <AnimatePresence>
          {open && sheet ? (
            <motion.div
              key="backdrop"
              aria-hidden
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="fixed inset-0 z-[59] bg-scrim backdrop-blur-[2px]"
            />
          ) : null}
          {open && sheet ? (
            <motion.div
              key="sheet"
              ref={ref}
              id={id}
              role="dialog"
              aria-modal="true"
              aria-label={label}
              aria-labelledby={label ? undefined : titleId}
              data-popover=""
              data-sheet=""
              tabIndex={-1}
              initial={{ y: "100%" }}
              animate={{ y: 0 }}
              exit={{ y: "100%", transition: { duration: 0.15 } }}
              transition={{ type: "spring", stiffness: 420, damping: 40 }}
              className="fixed inset-x-0 bottom-0 z-[60] flex max-h-[85dvh] flex-col rounded-t-2xl border border-b-0 border-line bg-surface text-base text-ink shadow-[var(--shadow-pop)] outline-none"
            >
              <div className="flex shrink-0 items-start gap-3 px-5 pb-2 pt-5">
                {heading ? (
                  <h2 id={titleId} className="display min-w-0 flex-1 text-title font-semibold text-ink">
                    {heading}
                  </h2>
                ) : (
                  <span className="flex-1" />
                )}
                <IconButton icon={X} label="Close" size="lg" onClick={close} className="-mr-3 -mt-2.5" />
              </div>
              <div
                data-popover-body=""
                role={role === "dialog" ? undefined : role}
                aria-label={role === "dialog" ? undefined : label}
                // content with a sticky footer (a pay panel's actions): focus scrolls clear of it (WCAG 2.4.11)
                className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-5 pb-[calc(1.25rem+env(safe-area-inset-bottom))] pt-1 scrollbar-thin has-[[data-sticky-footer]]:scroll-pb-24"
              >
                {body}
              </div>
            </motion.div>
          ) : null}
          {open && !sheet ? (
            <motion.div
              ref={ref}
              id={id}
              role={role}
              aria-label={label}
              data-popover=""
              tabIndex={-1}
              onKeyDown={onPanelKeyDown}
              initial={{ opacity: 0, scale: 0.97, y: pos?.side === "top" ? 4 : -4 }}
              animate={{ opacity: pos ? 1 : 0, scale: 1, y: 0 }}
              // with reduced motion it goes at once (no fading panel over whatever Tab focused next)
              exit={{ opacity: 0, scale: 0.98, transition: { duration: reduceMotion ? 0 : 0.1 } }}
              transition={{ duration: 0.16, ease: [0.2, 0.8, 0.2, 1] }}
              style={{
                ...floatingStyle(pos),
                maxHeight: pos ? Math.max(MIN_PANEL_HEIGHT, pos.maxHeight) : undefined,
                transformOrigin: `${pos?.side === "top" ? "bottom" : "top"} ${pos?.placement.endsWith("end") ? "right" : "left"}`,
              }}
              className={cn(
                "z-[60] w-80 max-w-[calc(100vw-16px)] overflow-y-auto overscroll-contain rounded-xl border border-line bg-surface p-4 text-base text-ink shadow-[var(--shadow-pop)] outline-none scrollbar-thin scroll-shadow has-[[data-sticky-footer]]:scroll-pb-20",
                className,
              )}
            >
              <div data-popover-body="">{body}</div>
            </motion.div>
          ) : null}
        </AnimatePresence>,
        getOverlayRoot(),
      )}
    </>
  );
}
