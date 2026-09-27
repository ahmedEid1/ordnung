import { useRef, type FocusEvent, type ReactNode, type RefObject } from "react";
import { createPortal } from "react-dom";
import { AnimatePresence, motion } from "motion/react";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";
import { IconButton } from "./Button";
import { getOverlayRoot, useModal, useStableId } from "./internal";

export interface DialogProps {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  description?: ReactNode;
  children?: ReactNode;
  /** Footer actions, right-aligned (primary action last). */
  footer?: ReactNode;
  size?: "sm" | "md" | "lg" | "xl";
  /** Element to focus first (default: the dialog itself, announced by its title; an `autoFocus` child keeps focus). */
  initialFocus?: RefObject<HTMLElement | null>;
  /** Where focus goes on close when the element that opened the dialog is gone (default: the page's main). */
  returnFocus?: RefObject<HTMLElement | null>;
  /** Hide the × button (e.g. for forced choices). */
  hideClose?: boolean;
  /** Close when clicking the backdrop (default true). */
  dismissible?: boolean;
  /** `center` (bottom sheet on phones, default) or `top` (e.g. search: stays above the keyboard). */
  align?: "center" | "top";
  className?: string;
}

const widths = { sm: "max-w-sm", md: "max-w-lg", lg: "max-w-2xl", xl: "max-w-4xl" };

/**
 * Modal dialog: focus trap, Escape to close, backdrop click, scroll lock, focus restore.
 * On phones it becomes a bottom sheet (44 px Close button, footer above the home indicator).
 * A focused field in the body scrolls fully into view, clear of the footer.
 *
 * @example
 * <Dialog open={open} onClose={close} title="Are these pages of one letter?"
 *   footer={<><Button onClick={separate}>Separate</Button><Button variant="primary">Combine</Button></>} />
 */
export function Dialog({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  size = "md",
  initialFocus,
  returnFocus,
  hideClose,
  dismissible = true,
  align = "center",
  className,
}: DialogProps) {
  const panelRef = useRef<HTMLDivElement | null>(null);
  const titleId = useStableId(undefined, "dlg-title");
  const descId = useStableId(undefined, "dlg-desc");
  useModal(open, panelRef, onClose, { initialFocus, returnFocus });
  const sheet = align === "center"; // a bottom sheet below `sm`
  // the body scrolls on its own: a focused field (e.g. a tall textarea) comes fully into view
  const revealFocused = (e: FocusEvent<HTMLDivElement>) => {
    if (e.target !== e.currentTarget) e.target.scrollIntoView?.({ block: "nearest" });
  };

  return createPortal(
    <AnimatePresence>
      {open ? (
        <div
          className={cn(
            "fixed inset-0 z-50 flex justify-center",
            align === "top" ? "items-start p-3 sm:p-6 sm:pt-[12vh]" : "items-end sm:items-center sm:p-6",
          )}
        >
          <motion.div
            className="absolute inset-0 bg-scrim backdrop-blur-[2px]"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.18 }}
            onClick={dismissible ? onClose : undefined}
            aria-hidden
          />
          <motion.div
            ref={panelRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby={titleId}
            aria-describedby={description ? descId : undefined}
            tabIndex={-1}
            initial={{ opacity: 0, y: 16, scale: 0.985 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 12, scale: 0.99, transition: { duration: 0.14 } }}
            transition={{ type: "spring", stiffness: 420, damping: 34 }}
            className={cn(
              "relative flex max-h-[92dvh] w-full flex-col overflow-hidden border border-line bg-surface shadow-[var(--shadow-pop)] outline-none",
              align === "top" ? "rounded-2xl" : "rounded-t-2xl sm:rounded-2xl",
              widths[size],
              className,
            )}
          >
            <div className={cn("flex items-start gap-3 px-5 pt-5 sm:px-6 sm:pt-6", children ? "pb-2" : "pb-5 sm:pb-6")}>
              <div className="min-w-0 flex-1">
                <h2 id={titleId} className="display text-title font-semibold text-ink">
                  {title}
                </h2>
                {description ? (
                  <p id={descId} className="mt-1.5 text-base leading-relaxed text-muted">
                    {description}
                  </p>
                ) : null}
              </div>
              {!hideClose ? (
                <IconButton icon={X} label="Close" size="sm" onClick={onClose} className="-mr-3 -mt-2 size-11 sm:-mr-2 sm:-mt-1 sm:size-8" />
              ) : null}
            </div>
            {children ? (
              // `relative`: the body is the containing block of what it positions (a link's screen-reader-only
              // "opens in a new tab"), so nothing overflows the panel itself — a panel with overflow of its own
              // is scrolled by scrollIntoView, which moved the title and Close off the top
              <div
                onFocus={revealFocused}
                className={cn(
                  "relative min-h-0 flex-1 scroll-py-6 overflow-y-auto overscroll-contain px-5 py-3 scrollbar-thin sm:px-6",
                  sheet && !footer && "pb-[calc(0.75rem+env(safe-area-inset-bottom))] sm:pb-3",
                )}
              >
                {children}
              </div>
            ) : null}
            {footer ? (
              <div
                className={cn(
                  "flex flex-col-reverse gap-2 border-t border-line bg-surface-2/50 px-5 py-4 sm:flex-row sm:justify-end sm:px-6",
                  sheet && "pb-[calc(1rem+env(safe-area-inset-bottom))] sm:pb-4",
                )}
              >
                {footer}
              </div>
            ) : null}
          </motion.div>
        </div>
      ) : null}
    </AnimatePresence>,
    getOverlayRoot(),
  );
}
