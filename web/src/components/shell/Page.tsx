import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { usePageTitle } from "./page-meta";
import { PAGE_WIDTHS, SHELL_GUTTERS, type PageWidth } from "./layout";

export interface PageProps {
  /** Sets the top-bar title and the browser tab title. */
  title?: string;
  /** Breadcrumb parent in the top bar (on phones: its back button). */
  parent?: { to: string; label: string };
  /**
   * Content width: `default` (every section page — the shell column the top bar lines up with),
   * `narrow` (a centred reading column) or `full`.
   */
  width?: PageWidth;
  className?: string;
  children: ReactNode;
}

/**
 * Page container: the shell's gutters (16 px on phones), max width and vertical rhythm.
 * Every page should render inside one.
 *
 * @example <Page title="Inbox"><PageHeader title="Inbox" description="…" /></Page>
 */
export function Page({ title, parent, width = "default", className, children }: PageProps) {
  usePageTitle(title, parent, width);
  return <div className={cn("mx-auto w-full pb-16 pt-6 md:pt-8", SHELL_GUTTERS, PAGE_WIDTHS[width], className)}>{children}</div>;
}

export interface PageHeaderProps {
  title: ReactNode;
  /** Small line above the title ("Monday, 28 September"). */
  eyebrow?: ReactNode;
  description?: ReactNode;
  /** Right-aligned actions. */
  actions?: ReactNode;
  className?: string;
}

/** Big Fraunces page heading with optional eyebrow, description and actions. */
export function PageHeader({ title, eyebrow, description, actions, className }: PageHeaderProps) {
  return (
    <header className={cn("mb-6 flex flex-col gap-4 sm:mb-8 sm:flex-row sm:items-end", className)}>
      <div className="min-w-0 flex-1">
        {eyebrow ? <p className="mb-1.5 text-[13px] font-medium text-muted">{eyebrow}</p> : null}
        <h1 className="display text-h1 font-semibold text-ink">{title}</h1>
        {description ? <p className="mt-2 max-w-2xl text-[15px] leading-relaxed text-muted">{description}</p> : null}
      </div>
      {actions ? <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div> : null}
    </header>
  );
}
