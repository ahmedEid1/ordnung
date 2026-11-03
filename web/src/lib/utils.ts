import { clsx, type ClassValue } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";

/**
 * tailwind-merge that knows the app's type scale (index.css): `text-title`, `text-h1`, `text-detail`
 * and `text-detail-long` are font sizes, not colours — without this, `cn("text-h1", "text-ink")`
 * would drop the size. (`text-2xs` and `text-md` are recognised as t-shirt sizes already.)
 */
const twMerge = extendTailwindMerge({ extend: { theme: { text: ["title", "h1", "detail", "detail-long"], font: ["ident"] } } });

/** Merge class names; later Tailwind utilities win over earlier conflicting ones. */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

/** Initials for avatars ("Wohnbau Musterstadt eG" → "WM"). */
export function initials(name: string, max = 2): string {
  const words = name
    .replace(/[^\p{L}\p{N}\s-]/gu, " ")
    .split(/[\s-]+/)
    .filter((w) => w && !/^(eg|gmbh|ag|e\.?v\.?|kg|dr|und|the|of|für|der|die|das)$/i.test(w));
  const letters = words.slice(0, max).map((w) => w[0]!.toUpperCase());
  return letters.join("") || name.slice(0, 1).toUpperCase();
}

/** Pluralise simply: plural(3, "letter") → "3 letters". */
export function plural(n: number, singular: string, pluralForm = `${singular}s`): string {
  return `${n} ${n === 1 ? singular : pluralForm}`;
}

/** True when the user asked the OS to reduce motion. */
export function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && typeof window.matchMedia === "function"
    ? window.matchMedia("(prefers-reduced-motion: reduce)").matches
    : false;
}
