import { cloneElement, isValidElement, useEffect, useRef, useState, type FocusEvent, type ReactElement, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { cn } from "@/lib/utils";
import { getOverlayRoot, useFloating, useStableId, type Placement } from "./internal";

export interface TooltipProps {
  /** Tooltip text (keep it short; it is also exposed as the accessible description). */
  content: ReactNode;
  /** A single focusable element (button, link, or an element with tabIndex=0). */
  children: ReactElement;
  side?: Placement;
  /** Hover delay in ms (keyboard focus shows immediately). */
  delay?: number;
  /** Disable without unmounting. */
  disabled?: boolean;
  className?: string;
}

/**
 * Hover / focus tooltip. Shown on keyboard focus immediately and on hover after `delay`;
 * dismissed with Escape. The trigger gets `aria-describedby` while it is visible.
 * The trigger is wrapped in a `display: contents` span, so layout is unaffected.
 *
 * @example <Tooltip content="Found on page 2"><button>…</button></Tooltip>
 */
export function Tooltip({ content, children, side = "top", delay = 250, disabled, className }: TooltipProps) {
  const [open, setOpen] = useState(false);
  const [wrap, setWrap] = useState<HTMLSpanElement | null>(null);
  const [tip, setTip] = useState<HTMLDivElement | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const id = useStableId(undefined, "tip");
  const pos = useFloating(wrap, tip, open, side);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);
  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );

  const show = (immediate: boolean) => {
    if (disabled || !content) return;
    if (timer.current) clearTimeout(timer.current);
    if (immediate) setOpen(true);
    else timer.current = setTimeout(() => setOpen(true), delay);
  };
  const hide = () => {
    if (timer.current) clearTimeout(timer.current);
    setOpen(false);
  };

  if (!isValidElement(children)) return children;
  const child = children as ReactElement<{ "aria-describedby"?: string }>;
  const described = child.props["aria-describedby"];
  const trigger = open ? cloneElement(child, { "aria-describedby": cn(described, id) }) : child;

  return (
    <>
      <span
        ref={setWrap}
        className="contents"
        onMouseEnter={() => show(false)}
        onMouseLeave={hide}
        onFocus={(e: FocusEvent<HTMLSpanElement>) => {
          if ((e.target as HTMLElement).matches?.(":focus-visible")) show(true);
        }}
        onBlur={hide}
        onPointerDown={hide}
      >
        {trigger}
      </span>
      {open
        ? createPortal(
            <div
              ref={setTip}
              id={id}
              role="tooltip"
              style={{ position: "fixed", top: pos?.top ?? -9999, left: pos?.left ?? -9999 }}
              className={cn(
                "pointer-events-none z-[70] max-w-72 rounded-lg bg-ink px-2.5 py-1.5 text-[12.5px] leading-snug text-canvas shadow-[var(--shadow-pop)]",
                pos ? "animate-fade-in motion-reduce:animate-none" : "opacity-0",
                className,
              )}
            >
              {content}
            </div>,
            getOverlayRoot(),
          )
        : null}
    </>
  );
}
