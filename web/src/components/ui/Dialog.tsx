import { useRef, type ReactNode, type RefObject } from "react";
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
  /** Element to focus first (defaults to the first focusable element). */
  initialFocus?: RefObject<HTMLElement | null>;
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
 * On phones it becomes a bottom sheet.
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
  hideClose,
  dismissible = true,
  align = "center",
  className,
}: DialogProps) {
  const panelRef = useRef<HTMLDivElement | null>(null);
  const titleId = useStableId(undefined, "dlg-title");
  const descId = useStableId(undefined, "dlg-desc");
  useModal(open, panelRef, onClose, initialFocus);

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
            className="absolute inset-0 bg-[rgb(20_18_14/0.42)] backdrop-blur-[2px] dark:bg-black/60"
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
            <div className="flex items-start gap-3 px-5 pb-2 pt-5 sm:px-6 sm:pt-6">
              <div className="min-w-0 flex-1">
                <h2 id={titleId} className="display text-[22px] font-semibold leading-7 text-ink">
                  {title}
                </h2>
                {description ? (
                  <p id={descId} className="mt-1.5 text-base leading-relaxed text-muted">
                    {description}
                  </p>
                ) : null}
              </div>
              {!hideClose ? <IconButton icon={X} label="Close" size="sm" onClick={onClose} className="-mr-2 -mt-1" /> : null}
            </div>
            {children ? <div className="min-h-0 flex-1 overflow-y-auto px-5 py-3 scrollbar-thin sm:px-6">{children}</div> : null}
            {footer ? (
              <div className="flex flex-col-reverse gap-2 border-t border-line bg-surface-2/50 px-5 py-4 sm:flex-row sm:justify-end sm:px-6">
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
