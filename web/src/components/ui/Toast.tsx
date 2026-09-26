import { useEffect, useRef, useState, useSyncExternalStore, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { AnimatePresence, motion } from "motion/react";
import { CircleCheck, Info, TriangleAlert, CircleX, X, Undo2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { getOverlayRoot } from "./internal";

export type ToastTone = "info" | "success" | "warn" | "danger";

export interface ToastOptions {
  title: ReactNode;
  description?: ReactNode;
  tone?: ToastTone;
  /** A secondary action ("Open", "View letter"). */
  action?: { label: string; onClick: () => void };
  /** Adds an "Undo" button; the toast closes after it runs. */
  undo?: () => void | Promise<void>;
  /** Auto-dismiss after ms (default 5000; 8000 with undo). `Infinity` keeps it open. */
  duration?: number;
  /** Re-using an id replaces the existing toast (e.g. progress updates). */
  id?: string;
}

export interface ToastRecord extends ToastOptions {
  id: string;
  createdAt: number;
}

// ------------------------------------------------------------------------------------------------
// Store (module-level so non-React code — e.g. the query client's error handler — can toast)
// ------------------------------------------------------------------------------------------------

let toasts: ToastRecord[] = [];
const listeners = new Set<() => void>();
let counter = 0;

function emit() {
  listeners.forEach((l) => l());
}

/** Show a toast; returns its id. */
export function toast(opts: ToastOptions): string {
  const id = opts.id ?? `t${++counter}`;
  const record: ToastRecord = { ...opts, id, createdAt: Date.now() };
  const exists = toasts.some((t) => t.id === id);
  toasts = exists ? toasts.map((t) => (t.id === id ? record : t)) : [...toasts, record].slice(-4);
  emit();
  return id;
}

toast.success = (title: ReactNode, opts: Omit<ToastOptions, "title" | "tone"> = {}) => toast({ ...opts, title, tone: "success" });
toast.error = (title: ReactNode, opts: Omit<ToastOptions, "title" | "tone"> = {}) => toast({ ...opts, title, tone: "danger" });
toast.warn = (title: ReactNode, opts: Omit<ToastOptions, "title" | "tone"> = {}) => toast({ ...opts, title, tone: "warn" });

/** Dismiss a toast by id. */
export function dismissToast(id: string): void {
  toasts = toasts.filter((t) => t.id !== id);
  emit();
}

function subscribe(fn: () => void) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

/**
 * Toast API for components.
 *
 * @example
 * const { toast } = useToast();
 * toast({ title: "Marked as done", undo: () => update({ status: "open" }) });
 */
export function useToast() {
  return { toast, dismiss: dismissToast };
}

// ------------------------------------------------------------------------------------------------
// UI
// ------------------------------------------------------------------------------------------------

const toneIcon: Record<ToastTone, { icon: typeof Info; cls: string }> = {
  info: { icon: Info, cls: "text-accent" },
  success: { icon: CircleCheck, cls: "text-ok" },
  warn: { icon: TriangleAlert, cls: "text-warn" },
  danger: { icon: CircleX, cls: "text-danger" },
};

function ToastItem({ t }: { t: ToastRecord }) {
  const [paused, setPaused] = useState(false);
  const [busy, setBusy] = useState(false);
  const remaining = useRef<number>(t.duration ?? (t.undo ? 8000 : 5000));
  const started = useRef<number>(0);

  useEffect(() => {
    if (paused || !Number.isFinite(remaining.current)) return;
    started.current = Date.now();
    const timer = setTimeout(() => dismissToast(t.id), remaining.current);
    return () => {
      clearTimeout(timer);
      remaining.current -= Date.now() - started.current;
    };
  }, [paused, t.id]);

  const { icon: Icon, cls } = toneIcon[t.tone ?? "info"];

  return (
    <motion.li
      layout
      initial={{ opacity: 0, y: 16, scale: 0.97 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, x: 24, transition: { duration: 0.15 } }}
      transition={{ type: "spring", stiffness: 460, damping: 36 }}
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
      onFocus={() => setPaused(true)}
      onBlur={() => setPaused(false)}
      className="pointer-events-auto flex w-full items-start gap-3 rounded-xl border border-line bg-surface p-3.5 pr-2.5 text-base shadow-[var(--shadow-pop)] sm:w-[380px]"
      role={t.tone === "danger" ? "alert" : undefined}
    >
      <Icon className={cn("mt-0.5 size-[18px] shrink-0", cls)} aria-hidden />
      <div className="min-w-0 flex-1">
        <div className="font-medium leading-5 text-ink">{t.title}</div>
        {t.description ? <div className="mt-0.5 leading-5 text-muted">{t.description}</div> : null}
        {t.action || t.undo ? (
          <div className="mt-2 flex items-center gap-3">
            {t.undo ? (
              <button
                type="button"
                disabled={busy}
                className="inline-flex items-center gap-1.5 rounded-md text-[13px] font-semibold text-accent hover:underline disabled:opacity-60"
                onClick={async () => {
                  setBusy(true);
                  try {
                    await t.undo?.();
                  } finally {
                    dismissToast(t.id);
                  }
                }}
              >
                <Undo2 className="size-3.5" aria-hidden />
                Undo
              </button>
            ) : null}
            {t.action ? (
              <button
                type="button"
                className="rounded-md text-[13px] font-semibold text-accent hover:underline"
                onClick={() => {
                  t.action?.onClick();
                  dismissToast(t.id);
                }}
              >
                {t.action.label}
              </button>
            ) : null}
          </div>
        ) : null}
      </div>
      <button
        type="button"
        onClick={() => dismissToast(t.id)}
        className="grid size-7 shrink-0 place-items-center rounded-md text-muted hover:bg-surface-2 hover:text-ink"
        aria-label="Dismiss notification"
      >
        <X className="size-4" aria-hidden />
      </button>
    </motion.li>
  );
}

/** CSS variable other bottom overlays (the demo tour card) set to lift the toast corner above them. */
export const TOAST_LIFT_VAR = "--ordnung-toast-lift";

/**
 * Renders the toast stack (mounted once by the app shell). Polite live region.
 *
 * One bottom-anchored column, so nothing in it can overlap: toasts on top, `children` below them
 * (the shell puts the upload progress there), on phones above the tab bar. A bottom overlay that
 * shares the corner (the demo tour) lifts the whole column with {@link TOAST_LIFT_VAR}. On small
 * screens the column never grows past the top bar: older toasts give way first.
 */
export function Toaster({ className, children }: { className?: string; children?: ReactNode }) {
  const list = useSyncExternalStore(subscribe, () => toasts, () => toasts);
  return createPortal(
    <section
      aria-label="Notifications"
      data-testid="toaster"
      className={cn(
        "pointer-events-none fixed inset-x-3 z-[80] flex max-h-[calc(100dvh-9rem-env(safe-area-inset-bottom)-var(--ordnung-toast-lift,0px))] flex-col justify-end gap-2 overflow-hidden transition-[bottom] duration-200 motion-reduce:transition-none",
        "bottom-[calc(4.75rem+env(safe-area-inset-bottom)+var(--ordnung-toast-lift,0px))] md:inset-x-auto md:right-5 md:bottom-[calc(1.25rem+var(--ordnung-toast-lift,0px))] md:max-h-[calc(100dvh-6rem-var(--ordnung-toast-lift,0px))]",
        className,
      )}
    >
      <ol aria-live="polite" data-testid="toast-list" className="flex min-h-0 shrink flex-col items-stretch justify-end gap-2 md:items-end">
        <AnimatePresence initial={false}>
          {list.map((t) => (
            <ToastItem key={t.id} t={t} />
          ))}
        </AnimatePresence>
      </ol>
      {children ? <div className="shrink-0">{children}</div> : null}
    </section>,
    getOverlayRoot(),
  );
}

/** Test helper. */
export function __clearToasts(): void {
  toasts = [];
  emit();
}
