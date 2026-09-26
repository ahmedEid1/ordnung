import { useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { AnimatePresence, motion } from "motion/react";
import { CircleCheck, Info, TriangleAlert, CircleX, X, Undo2 } from "lucide-react";
import { useHotkey, useMediaQuery } from "@/lib/hooks";
import { cn } from "@/lib/utils";
import { getOverlayRoot, useModalOpen } from "./internal";

export type ToastTone = "info" | "success" | "warn" | "danger";

export interface ToastOptions {
  title: ReactNode;
  description?: ReactNode;
  tone?: ToastTone;
  /** A secondary action ("Open", "View letter"). */
  action?: { label: string; onClick: () => void };
  /** Adds an "Undo" button; the toast closes after it runs. */
  undo?: () => void | Promise<void>;
  /**
   * Auto-dismiss after ms (see {@link toastDuration}: 5 s, 10 s with an action, 15 s with Undo;
   * errors stay until dismissed). `Infinity` keeps it open.
   */
  duration?: number;
  /** Re-using an id replaces the existing toast (e.g. progress updates). */
  id?: string;
}

export interface ToastRecord extends ToastOptions {
  id: string;
  createdAt: number;
  /** Bumped whenever the toast is shown (again): a replaced toast starts a fresh lifetime. */
  seq: number;
}

/** How long a toast stays: long enough to reach its buttons from the keyboard; errors wait for the person. */
export const TOAST_DURATION = { plain: 5000, action: 10_000, undo: 15_000 } as const;

/** The lifetime of a toast in ms (`Infinity`: until dismissed). */
export function toastDuration(t: Pick<ToastOptions, "duration" | "tone" | "undo" | "action">): number {
  if (t.duration !== undefined) return t.duration;
  if (t.tone === "danger") return Infinity;
  if (t.undo) return TOAST_DURATION.undo;
  if (t.action) return TOAST_DURATION.action;
  return TOAST_DURATION.plain;
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
  const seq = ++counter;
  const id = opts.id ?? `t${seq}`;
  const record: ToastRecord = { ...opts, id, createdAt: Date.now(), seq };
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

const IS_MAC = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
/** The keyboard shortcut that moves focus to the newest toast (the notifications region names it). */
export const TOAST_HOTKEY_LABEL = IS_MAC ? "Option+N" : "Alt+N";
const isToastHotkey = (e: KeyboardEvent) => e.altKey && !e.ctrlKey && !e.metaKey && e.code === "KeyN";

/** A text-sized toast button that is still a 28 px target, its label aligned with the title. */
const actionCls =
  "inline-flex h-7 items-center gap-1.5 rounded-md px-2 text-sm font-semibold text-accent transition-[background-color] hover:bg-accent-soft disabled:opacity-60";

/** Where focus was before Alt+N moved it into a toast: it goes back there when that toast closes. */
let focusBeforeToasts: HTMLElement | null = null;

function restoreFocus() {
  const back = focusBeforeToasts?.isConnected && !focusBeforeToasts.closest("[inert]") ? focusBeforeToasts : document.querySelector<HTMLElement>("main");
  focusBeforeToasts = null;
  back?.focus({ preventScroll: true });
}

function ToastItem({ t, paused }: { t: ToastRecord; paused: boolean }) {
  const [busy, setBusy] = useState(false);
  const ref = useRef<HTMLLIElement>(null);
  const lifetime = toastDuration(t);
  /** Time left of the current showing (`seq`): a toast shown again (a progress update) starts over. */
  const remaining = useRef<{ seq: number; ms: number } | null>(null);

  useEffect(() => {
    if (remaining.current?.seq !== t.seq) remaining.current = { seq: t.seq, ms: lifetime };
    const left = remaining.current;
    if (paused || !Number.isFinite(left.ms)) return;
    const started = Date.now();
    const timer = setTimeout(() => dismissToast(t.id), Math.max(0, left.ms));
    return () => {
      clearTimeout(timer);
      left.ms -= Date.now() - started;
    };
  }, [paused, t.id, t.seq, lifetime]);

  const hasFocus = () => Boolean(ref.current?.contains(document.activeElement));
  /** Close it; when focus was inside, hand it back instead of dropping it on the page. */
  const close = (hadFocus = hasFocus()) => {
    dismissToast(t.id);
    if (hadFocus) restoreFocus();
  };

  const { icon: Icon, cls } = toneIcon[t.tone ?? "info"];

  return (
    <motion.li
      ref={ref}
      layout
      initial={{ opacity: 0, y: 16, scale: 0.97 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, x: 24, transition: { duration: 0.15 } }}
      transition={{ type: "spring", stiffness: 460, damping: 36 }}
      tabIndex={-1}
      data-toast={t.id}
      onKeyDown={(e) => {
        if (e.key !== "Escape" || e.defaultPrevented) return;
        e.preventDefault();
        close();
      }}
      className="pointer-events-auto flex w-full items-start gap-3 rounded-xl border border-line bg-surface p-3.5 pr-2.5 text-base shadow-[var(--shadow-pop)] outline-none focus-visible:ring-2 focus-visible:ring-accent"
    >
      <Icon className={cn("mt-0.5 size-[18px] shrink-0", cls)} aria-hidden />
      <div className="min-w-0 flex-1">
        <div className="font-medium leading-5 text-ink">{t.title}</div>
        {t.description ? <div className="mt-0.5 leading-5 text-muted">{t.description}</div> : null}
        {t.action || t.undo ? (
          <div className="-ml-2 mt-1.5 flex flex-wrap items-center gap-1">
            {t.undo ? (
              <button
                type="button"
                disabled={busy}
                className={actionCls}
                onClick={async () => {
                  // (read before the busy button is disabled and loses focus)
                  const hadFocus = hasFocus();
                  setBusy(true);
                  try {
                    await t.undo?.();
                  } finally {
                    close(hadFocus);
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
                className={actionCls}
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
        onClick={() => close()}
        className="grid size-7 shrink-0 place-items-center rounded-md text-muted hover:bg-surface-2 hover:text-ink"
        aria-label="Dismiss notification"
      >
        <X className="size-4" aria-hidden />
      </button>
    </motion.li>
  );
}

/** Is the page in a background tab? Toasts wait until it is seen. */
function useDocumentHidden(): boolean {
  return useSyncExternalStore(
    (fn) => {
      document.addEventListener("visibilitychange", fn);
      return () => document.removeEventListener("visibilitychange", fn);
    },
    () => document.visibilityState === "hidden",
    () => false,
  );
}

/** CSS variable other bottom overlays (the demo tour card) set to lift the toast corner above them. */
export const TOAST_LIFT_VAR = "--ordnung-toast-lift";

/**
 * CSS variable (on `<html>`) with the height the toast column covers above its bottom edge (0px
 * when it is empty): page bottoms can pad by it, so their last buttons can scroll clear of it.
 */
export const TOAST_SPACE_VAR = "--ordnung-toast-space";

/** Keep {@link TOAST_SPACE_VAR} at the height of the cards in the column (toasts and uploads). */
function useToastSpace(section: HTMLElement | null) {
  useLayoutEffect(() => {
    if (!section) return;
    const root = document.documentElement;
    const measure = () => {
      const cards = section.querySelectorAll(":scope li");
      const bottom = section.getBoundingClientRect().bottom - parseFloat(getComputedStyle(section).paddingBottom || "0");
      let top = bottom;
      for (const c of cards) top = Math.min(top, c.getBoundingClientRect().top);
      root.style.setProperty(TOAST_SPACE_VAR, `${Math.max(0, Math.ceil(bottom - top))}px`);
    };
    measure();
    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(measure) : null;
    ro?.observe(section);
    const mo = new MutationObserver(measure);
    mo.observe(section, { childList: true, subtree: true });
    return () => {
      ro?.disconnect();
      mo.disconnect();
      root.style.removeProperty(TOAST_SPACE_VAR);
    };
  }, [section]);
}

/**
 * Renders the toast stack (mounted once by the app shell).
 *
 * One bottom-anchored column, 400 px wide from tablets up (toasts and upload cards alike), so
 * nothing in it can overlap: toasts on top, `children` below them (the shell puts the upload
 * progress there), on phones above the tab bar. A bottom overlay that shares the corner (the demo
 * tour) lifts the whole column with {@link TOAST_LIFT_VAR}. On phones only the newest toast shows,
 * with a "+N more" button for the rest (they wait their turn: a toast's time only runs while it is
 * shown); on small screens the column never grows past the top bar: older toasts give way first. While a modal is open the column steps behind it and every toast
 * waits, as it does while any toast is hovered or focused (and while the tab is in the background).
 *
 * Screen readers hear each toast once — errors assertively, the rest politely — and `Alt+N`
 * (Option+N) moves focus to the newest toast; Escape closes it and focus goes back.
 */
export function Toaster({ className, children }: { className?: string; children?: ReactNode }) {
  const list = useSyncExternalStore(subscribe, () => toasts, () => toasts);
  const phone = !useMediaQuery("(min-width: 768px)");
  const modal = useModalOpen();
  const hidden = useDocumentHidden();
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  /** Phones: the rest of the stack was opened while this toast was the newest (closes again when it goes). */
  const [expandedFor, setExpandedFor] = useState<string | null>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const expanded = list.length > 1 && list.some((t) => t.id === expandedFor);
  const shown = phone && !expanded ? list.slice(-1) : list;
  const more = list.length - shown.length;

  // Alt+N: to the newest toast (its buttons are a Tab away), and from a toast back to the page
  useHotkey(isToastHotkey, (e) => {
    const id = list[list.length - 1]?.id;
    const newest = Array.from(listRef.current?.querySelectorAll<HTMLElement>("li[data-toast]") ?? []).find((el) => el.dataset.toast === id);
    if (!newest || modal) return;
    e.preventDefault();
    if (listRef.current?.contains(document.activeElement)) return restoreFocus();
    focusBeforeToasts = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    newest.focus();
  });

  const paused = hovered || focused || modal || hidden;
  const [section, setSection] = useState<HTMLElement | null>(null);
  useToastSpace(section);

  return createPortal(
    <section
      ref={setSection}
      aria-label={`Notifications (${TOAST_HOTKEY_LABEL})`}
      data-testid="toaster"
      data-behind-modal={modal || undefined}
      className={cn(
        // The column plus room for the toasts' shadow, so the clip (older toasts give way at the top)
        // doesn't cut the shadow into a hard rectangle: 24 px above, below and inside, and up to the
        // screen edge where the column sits closer to it than that. Nothing sticks out of the screen.
        "pointer-events-none fixed inset-x-0 -my-6 flex flex-col justify-end gap-2 overflow-hidden px-3 py-6 transition-[bottom] duration-200 motion-reduce:transition-none",
        "md:inset-x-auto md:right-0 md:-mb-5 md:w-[calc(25rem+2.75rem)] md:pb-5 md:pl-6 md:pr-5",
        // (the top shadow room counts against the height: older toasts still give way below the top bar)
        "max-h-[calc(100dvh-7.5rem-env(safe-area-inset-bottom)-var(--ordnung-toast-lift,0px))] md:max-h-[calc(100dvh-4.75rem-var(--ordnung-toast-lift,0px))]",
        "bottom-[calc(4.75rem+env(safe-area-inset-bottom)+var(--ordnung-toast-lift,0px))] md:bottom-[calc(1.25rem+var(--ordnung-toast-lift,0px))]",
        // above the page and its bars; behind a dialog, drawer or sheet (z-50), never over its buttons
        modal ? "z-[49]" : "z-[80]",
        className,
      )}
    >
      {phone && list.length > 1 ? (
        <button
          type="button"
          aria-expanded={expanded}
          aria-label={expanded ? "Show less" : `+${more} more notification${more === 1 ? "" : "s"}`}
          onClick={() => setExpandedFor(expanded ? null : (list[list.length - 1]?.id ?? null))}
          className="pointer-events-auto inline-flex h-7 shrink-0 items-center self-end rounded-full border border-line bg-surface px-3 text-xs font-medium text-ink shadow-[var(--shadow-card)] hover:bg-surface-2"
        >
          {expanded ? "Show less" : `+${more} more`}
        </button>
      ) : null}
      {/* Two live lists, so each toast is announced once: errors assertively, the rest politely.
          An empty list takes back the gap it would add. */}
      <div
        ref={listRef}
        data-testid="toast-list"
        className="flex min-h-0 shrink flex-col justify-end gap-2 [&>ol:empty]:-mb-2"
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
        onFocus={() => setFocused(true)}
        onBlur={(e) => {
          if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setFocused(false);
        }}
      >
        {(["assertive", "polite"] as const).map((politeness) => (
          <ol key={politeness} aria-live={politeness} className="flex flex-col gap-2">
            <AnimatePresence initial={false}>
              {shown
                .filter((t) => (t.tone === "danger") === (politeness === "assertive"))
                .map((t) => (
                  <ToastItem key={t.id} t={t} paused={paused} />
                ))}
            </AnimatePresence>
          </ol>
        ))}
      </div>
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
