/**
 * Text measurement for label fitting. Uses a shared canvas with the app font; falls back to a
 * character estimate where canvas is unavailable (jsdom, SSR).
 */
import { approxTextWidth, type TextMeasure } from "./layout";

let ctx: CanvasRenderingContext2D | null | undefined;
const cache = new Map<string, number>();

function context(): CanvasRenderingContext2D | null {
  if (ctx !== undefined) return ctx;
  try {
    const canvas = typeof document !== "undefined" ? document.createElement("canvas") : null;
    // jsdom logs "not implemented" for getContext — only call it in real browsers
    const isJsdom = typeof navigator !== "undefined" && /jsdom/i.test(navigator.userAgent);
    ctx = canvas && !isJsdom ? canvas.getContext("2d") : null;
  } catch {
    ctx = null;
  }
  return ctx;
}

/** Measurer for a CSS font shorthand, e.g. `500 12px "Inter Variable"`. */
export function textMeasurer(font: string): TextMeasure {
  return (text: string) => {
    const key = `${font}|${text}`;
    const hit = cache.get(key);
    if (hit !== undefined) return hit;
    const c = context();
    let w: number;
    if (c) {
      c.font = font;
      w = Math.ceil(c.measureText(text).width);
    } else {
      w = approxTextWidth(text);
    }
    cache.set(key, w);
    return w;
  };
}

/** Bar labels: 12px medium Inter. */
export const measureBarLabel = textMeasurer(`500 12px "Inter Variable", ui-sans-serif, system-ui, sans-serif`);
/** The lane label's second line ("Send by 8 Oct"): 12px regular Inter. */
export const measureLine = textMeasurer(`400 12px "Inter Variable", ui-sans-serif, system-ui, sans-serif`);
/** Marker captions and the axis's year labels: 12px semibold Inter. */
export const measureCaption = textMeasurer(`600 12px "Inter Variable", ui-sans-serif, system-ui, sans-serif`);
