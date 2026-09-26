import { cloneElement, isValidElement, useCallback, useEffect, useState, type ReactElement, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { AnimatePresence, motion } from "motion/react";
import { cn } from "@/lib/utils";
import { useIsTabletUp } from "@/lib/hooks";
import { focusableIn, getOverlayRoot, resolveBox, useDismiss, useFloating, useStableId, type Placement } from "./internal";

type TriggerProps = {
  "aria-expanded"?: boolean;
  "aria-controls"?: string;
  "aria-haspopup"?: "dialog" | "menu" | "listbox" | boolean;
};

export interface PopoverProps {
  /** The trigger: a single clickable element (Button, button…). */
  children: ReactElement;
  /** Panel content, or a render function receiving `close`. */
  content: ReactNode | ((close: () => void) => ReactNode);
  placement?: Placement;
  /** Controlled open state. */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  /** Accessible name of the panel. */
  label?: string;
  /** Panel classes (width, padding). Default: w-80 p-4. */
  className?: string;
  /** Move focus into the panel on open (default true). */
  autoFocus?: boolean;
  role?: "dialog" | "menu" | "listbox";
}

/**
 * Click-triggered floating panel (e.g. "Why this date?"). Closes on outside click and Escape
 * (focus returns to the trigger). Works controlled or uncontrolled. The trigger is wrapped in a
 * `display: contents` span, so layout is unaffected.
 *
 * @example
 * <Popover content={<ReceiptSteps />}><Button variant="link">Why this date?</Button></Popover>
 */
export function Popover({
  children,
  content,
  placement = "bottom-start",
  open: openProp,
  onOpenChange,
  label,
  className,
  autoFocus = true,
  role = "dialog",
}: PopoverProps) {
  const [openState, setOpenState] = useState(false);
  const open = openProp ?? openState;
  const [wrap, setWrap] = useState<HTMLSpanElement | null>(null);
  const [panel, setPanel] = useState<HTMLDivElement | null>(null);
  const id = useStableId(undefined, "pop");
  // phones: a bottom sheet — a small floating panel with its own scroll gets clipped there
  const sheet = !useIsTabletUp();
  const pos = useFloating(wrap, panel, open && !sheet, placement);

  const setOpen = useCallback(
    (v: boolean) => {
      if (openProp === undefined) setOpenState(v);
      onOpenChange?.(v);
    },
    [openProp, onOpenChange],
  );
  const close = useCallback(() => setOpen(false), [setOpen]);
  const closeAndFocus = useCallback(() => {
    setOpen(false);
    resolveBox(wrap)?.focus({ preventScroll: true });
  }, [setOpen, wrap]);

  // Escape returns focus to the trigger; an outside click just closes.
  useDismiss(open, closeAndFocus, [wrap, panel], { outside: false });
  useDismiss(open, close, [wrap, panel], { escape: false });

  useEffect(() => {
    if (!open || !autoFocus || !panel) return;
    const raf = requestAnimationFrame(() => (focusableIn(panel)[0] ?? panel).focus({ preventScroll: true }));
    return () => cancelAnimationFrame(raf);
  }, [open, autoFocus, panel]);

  if (!isValidElement(children)) return null;
  const trigger = cloneElement(children as ReactElement<TriggerProps>, {
    "aria-expanded": open,
    "aria-controls": open ? id : undefined,
    "aria-haspopup": role,
  });

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
              className="fixed inset-0 z-[59] bg-ink/25"
            />
          ) : null}
          {open && sheet ? (
            <motion.div
              key="sheet"
              ref={setPanel}
              id={id}
              role={role}
              aria-label={label}
              aria-modal={role === "dialog" ? true : undefined}
              data-popover=""
              tabIndex={-1}
              initial={{ y: "100%" }}
              animate={{ y: 0 }}
              exit={{ y: "100%", transition: { duration: 0.15 } }}
              transition={{ type: "spring", stiffness: 420, damping: 40 }}
              className={cn(
                className,
                "fixed inset-x-0 bottom-0 z-[60] max-h-[85dvh] w-auto max-w-none overflow-auto rounded-b-none rounded-t-2xl border border-b-0 border-line bg-surface p-5 pb-[calc(1.25rem+env(safe-area-inset-bottom))] text-sm text-ink shadow-[var(--shadow-pop)] outline-none scrollbar-thin",
              )}
            >
              <div aria-hidden className="mx-auto -mt-2 mb-3 h-1 w-10 rounded-full bg-line-strong" />
              {typeof content === "function" ? content(close) : content}
            </motion.div>
          ) : null}
          {open && !sheet ? (
            <motion.div
              ref={setPanel}
              id={id}
              role={role}
              aria-label={label}
              data-popover=""
              tabIndex={-1}
              initial={{ opacity: 0, scale: 0.97, y: -4 }}
              animate={{ opacity: pos ? 1 : 0, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.98, transition: { duration: 0.1 } }}
              transition={{ duration: 0.16, ease: [0.2, 0.8, 0.2, 1] }}
              style={{
                position: "fixed",
                top: pos?.top ?? -9999,
                left: pos?.left ?? -9999,
                maxHeight: pos ? Math.max(160, pos.maxHeight) : undefined,
                transformOrigin: pos?.placement.startsWith("top") ? "bottom left" : "top left",
              }}
              className={cn(
                "z-[60] w-80 max-w-[calc(100vw-16px)] overflow-auto rounded-xl border border-line bg-surface p-4 text-sm text-ink shadow-[var(--shadow-pop)] outline-none scrollbar-thin",
                className,
              )}
            >
              {typeof content === "function" ? content(close) : content}
            </motion.div>
          ) : null}
        </AnimatePresence>,
        getOverlayRoot(),
      )}
    </>
  );
}
