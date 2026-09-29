/**
 * The shell's one column: the top bar, the "Claude paused" banner and every page share these
 * gutters and widths, so page headings, the top-bar title and its actions line up at every size.
 */

/** Side gutters: 16 px on phones, 24 px from 640 px, 40 px from 1024 px. */
export const SHELL_GUTTERS = "px-4 sm:px-6 lg:px-10";

/**
 * Content widths (gutters included). Every section page uses `default` and fills it with its own
 * grid; `narrow` is a centred reading column (Ask, "Not found"); `full` has no limit.
 */
export const PAGE_WIDTHS = {
  narrow: "max-w-3xl",
  default: "max-w-7xl",
  full: "max-w-none",
} as const;

export type PageWidth = keyof typeof PAGE_WIDTHS;

/** Width of the top bar and banner row for a page: the shell column, or wider for a `full` page. */
export function shellWidth(width: PageWidth | undefined): string {
  return PAGE_WIDTHS[width === "full" ? "full" : "default"];
}
