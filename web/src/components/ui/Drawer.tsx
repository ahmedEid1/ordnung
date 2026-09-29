import { useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { AnimatePresence, motion } from "motion/react";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";
import { useMediaQuery } from "@/lib/hooks";
import { IconButton } from "./Button";
import { getOverlayRoot, useModal, useStableId } from "./internal";

export interface DrawerProps {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  /** Small line above the title (e.g. "Landlord"). */
  eyebrow?: ReactNode;
  description?: ReactNode;
  /** Extra header content (chips, actions) under the title. On phones it scrolls with the body. */
  headerExtra?: ReactNode;
  children?: ReactNode;
  footer?: ReactNode;
  /** Width from `sm` up: `md` 448 px; `lg` grows with the screen (448 → 512 px from `lg`, 576 px from `2xl`). */
  size?: "md" | "lg";
  className?: string;
}

const widths = { md: "sm:max-w-md", lg: "sm:max-w-md lg:max-w-lg 2xl:max-w-xl" };

/**
 * Right-side sheet (People & organisations, details). Full-width on phones. Same modal behaviour
 * as Dialog: focus trap, Escape, backdrop click, focus restore.
 */
export function Drawer({ open, onClose, title, eyebrow, description, headerExtra, children, footer, size = "md", className }: DrawerProps) {
  const panelRef = useRef<HTMLDivElement | null>(null);
  const titleId = useStableId(undefined, "drw-title");
  useModal(open, panelRef, onClose);
  // phones: only the title stays pinned — chips and actions scroll away with the content
  const wide = useMediaQuery("(min-width: 640px)");
  const extra = headerExtra ? <div className={wide ? "mt-3" : "mb-5"}>{headerExtra}</div> : null;

  return createPortal(
    <AnimatePresence>
      {open ? (
        <div className="fixed inset-0 z-50">
          <motion.div
            className="absolute inset-0 bg-scrim backdrop-blur-[2px]"
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
              "absolute inset-y-0 right-0 flex w-full flex-col border-line bg-canvas shadow-[var(--shadow-pop)] outline-none sm:border-l",
              widths[size],
              className,
            )}
          >
            <header className="flex items-start gap-3 border-b border-line bg-surface px-5 pb-4 pt-[calc(1.25rem+env(safe-area-inset-top))]">
              <div className="min-w-0 flex-1">
                {eyebrow ? <div className="eyebrow mb-1">{eyebrow}</div> : null}
                <h2 id={titleId} className="display text-title font-semibold text-ink">
                  {title}
                </h2>
                {description ? <p className="mt-1 text-base text-muted">{description}</p> : null}
                {wide ? extra : null}
              </div>
              <IconButton icon={X} label="Close" size="sm" onClick={onClose} className="-mr-3 -mt-2.5 size-11 sm:-mr-1.5 sm:mt-0 sm:size-8" />
            </header>
            <div
              className={cn(
                "min-h-0 flex-1 overflow-y-auto overscroll-contain px-5 py-5 scrollbar-thin",
                !footer && "pb-[calc(1.25rem+env(safe-area-inset-bottom))]",
              )}
            >
              {wide ? null : extra}
              {children}
            </div>
            {footer ? <footer className="border-t border-line bg-surface px-5 pb-[calc(0.75rem+env(safe-area-inset-bottom))] pt-3">{footer}</footer> : null}
          </motion.div>
        </div>
      ) : null}
    </AnimatePresence>,
    getOverlayRoot(),
  );
}
