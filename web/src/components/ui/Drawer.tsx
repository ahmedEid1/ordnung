import { useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { AnimatePresence, motion } from "motion/react";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";
import { IconButton } from "./Button";
import { getOverlayRoot, useModal, useStableId } from "./internal";

export interface DrawerProps {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  /** Small line above the title (e.g. "Landlord"). */
  eyebrow?: ReactNode;
  description?: ReactNode;
  /** Extra header content (chips, actions) under the title. */
  headerExtra?: ReactNode;
  children?: ReactNode;
  footer?: ReactNode;
  /** Width on larger screens. */
  size?: "md" | "lg";
  className?: string;
}

/**
 * Right-side sheet (People & organisations, details). Full-width on phones. Same modal behaviour
 * as Dialog: focus trap, Escape, backdrop click, focus restore.
 */
export function Drawer({ open, onClose, title, eyebrow, description, headerExtra, children, footer, size = "md", className }: DrawerProps) {
  const panelRef = useRef<HTMLDivElement | null>(null);
  const titleId = useStableId(undefined, "drw-title");
  useModal(open, panelRef, onClose);

  return createPortal(
    <AnimatePresence>
      {open ? (
        <div className="fixed inset-0 z-50">
          <motion.div
            className="absolute inset-0 bg-[rgb(20_18_14/0.32)] dark:bg-black/55"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            onClick={onClose}
            aria-hidden
          />
          <motion.div
            ref={panelRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby={titleId}
            tabIndex={-1}
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%", transition: { duration: 0.18, ease: "easeIn" } }}
            transition={{ type: "spring", stiffness: 380, damping: 38 }}
            className={cn(
              "absolute inset-y-0 right-0 flex w-full flex-col border-l border-line bg-canvas shadow-[var(--shadow-pop)] outline-none",
              size === "md" ? "sm:max-w-md" : "sm:max-w-xl",
              className,
            )}
          >
            <header className="flex items-start gap-3 border-b border-line bg-surface px-5 pb-4 pt-5">
              <div className="min-w-0 flex-1">
                {eyebrow ? <div className="mb-1 text-xs font-medium uppercase tracking-wide text-muted">{eyebrow}</div> : null}
                <h2 id={titleId} className="display text-2xl font-semibold leading-tight text-ink">
                  {title}
                </h2>
                {description ? <p className="mt-1 text-sm text-muted">{description}</p> : null}
                {headerExtra ? <div className="mt-3">{headerExtra}</div> : null}
              </div>
              <IconButton icon={X} label="Close" size="sm" onClick={onClose} className="-mr-1.5" />
            </header>
            <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5 scrollbar-thin">{children}</div>
            {footer ? <footer className="border-t border-line bg-surface px-5 py-3">{footer}</footer> : null}
          </motion.div>
        </div>
      ) : null}
    </AnimatePresence>,
    getOverlayRoot(),
  );
}
