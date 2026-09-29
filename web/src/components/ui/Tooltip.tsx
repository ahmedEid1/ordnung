import { cloneElement, isValidElement, useEffect, useRef, useState, type FocusEvent as ReactFocusEvent, type PointerEvent, type ReactElement, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { cn } from "@/lib/utils";
import { floatingStyle, getOverlayRoot, useEscape, useFloating, useStableId, type Placement } from "./internal";

export interface TooltipProps {
  /** Tooltip text (keep it short; it is also exposed as the accessible description). */
  content: ReactNode;
  /** A single focusable element (button, link, or an element with tabIndex=0). */
  children: ReactElement;
  side?: Placement;
  /** Hover delay in ms (keyboard focus and touch show it immediately). */
  delay?: number;
  /** Disable without unmounting. */
  disabled?: boolean;
  className?: string;
}

/** Grace period for moving the mouse from the trigger onto the tooltip (WCAG 1.4.13: hoverable). */
const CLOSE_DELAY = 150;

/**
 * Hover / focus / tap tooltip. Shown on keyboard focus and on a tap immediately, on hover after
 * `delay`; the mouse can move onto it (it stays while hovered). Escape hides it without closing
 * the dialog or drawer around it; so do a click or tap elsewhere, focus moving to another
 * control, and scrolling (unless it was opened from the keyboard). The trigger gets `aria-describedby` while it is visible.
 * The trigger is wrapped in a `display: contents` span, so layout is unaffected.
 *
 * @example <Tooltip content="Found on page 2"><button>…</button></Tooltip>
 */
export function Tooltip({ content, children, side = "top", delay = 250, disabled, className }: TooltipProps) {
  const [open, setOpen] = useState(false);
  const [wrap, setWrap] = useState<HTMLSpanElement | null>(null);
  const [tip, setTip] = useState<HTMLDivElement | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  /** Opened by keyboard focus: it follows its trigger when the page scrolls instead of hiding. */
  const byKeyboard = useRef(false);
  const id = useStableId(undefined, "tip");
  const pos = useFloating(wrap, tip, open, side);

  const cancel = () => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
  };
  const show = (after = 0, keyboard = false) => {
    if (disabled || !content) return;
    cancel();
    byKeyboard.current = keyboard;
    if (after > 0) timer.current = setTimeout(() => setOpen(true), after);
    else setOpen(true);
  };
  const hide = (after = 0) => {
    cancel();
    if (after > 0) timer.current = setTimeout(() => setOpen(false), after);
    else setOpen(false);
  };

  useEscape(open, () => hide());
  useEffect(() => {
    if (!open) return;
    const close = () => {
      if (timer.current) clearTimeout(timer.current);
      setOpen(false);
    };
    const onDown = (e: globalThis.PointerEvent) => {
      const t = e.target as Node;
      if (!wrap?.contains(t) && !tip?.contains(t)) close();
    };
    const onScroll = () => !byKeyboard.current && close();
    // keyboard focus moving on to another control: this tooltip no longer describes what has focus
    const onFocusIn = (e: FocusEvent) => !wrap?.contains(e.target as Node) && close();
    document.addEventListener("pointerdown", onDown, true);
    document.addEventListener("focusin", onFocusIn);
    window.addEventListener("scroll", onScroll, true);
    return () => {
      document.removeEventListener("pointerdown", onDown, true);
      document.removeEventListener("focusin", onFocusIn);
      window.removeEventListener("scroll", onScroll, true);
    };
  }, [open, wrap, tip]);
  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );

  if (!isValidElement(children)) return children;
  const child = children as ReactElement<{ "aria-describedby"?: string }>;
  const described = child.props["aria-describedby"];
  const trigger = open ? cloneElement(child, { "aria-describedby": cn(described, id) }) : child;
  // touch and pen have no hover: a tap toggles the tooltip instead
  const mouse = (e: PointerEvent) => e.pointerType !== "touch" && e.pointerType !== "pen";

  return (
    <>
      <span
        ref={setWrap}
        className="contents"
        onPointerEnter={(e) => mouse(e) && show(delay)}
        onPointerLeave={(e) => mouse(e) && hide(CLOSE_DELAY)}
        // a click hides it (the action matters now); a tap shows it — touch has no hover
        onPointerDown={(e) => (mouse(e) ? hide() : open ? hide() : show())}
        onFocus={(e: ReactFocusEvent<HTMLSpanElement>) => {
          if ((e.target as HTMLElement).matches?.(":focus-visible")) show(0, true);
        }}
        onBlur={() => hide()}
      >
        {trigger}
      </span>
      {open
        ? createPortal(
            <div
              ref={setTip}
              id={id}
              role="tooltip"
              onPointerEnter={(e) => mouse(e) && cancel()}
              onPointerLeave={(e) => mouse(e) && hide(CLOSE_DELAY)}
              style={floatingStyle(pos)}
              className={cn(
                "z-[70] max-w-72 rounded-lg bg-ink px-2.5 py-1.5 text-[12.5px] leading-snug text-canvas shadow-[var(--shadow-pop)]",
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
