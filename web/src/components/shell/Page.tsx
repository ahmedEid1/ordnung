import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { usePageTitle } from "./page-meta";

export interface PageProps {
  /** Sets the top-bar title and the browser tab title. */
  title?: string;
  /** Breadcrumb parent in the top bar. */
  parent?: { to: string; label: string };
  /** Content width: narrow (reading), default, wide (tables/timelines), full. */
  width?: "narrow" | "default" | "wide" | "full";
  className?: string;
  children: ReactNode;
}

const widths = {
  narrow: "max-w-3xl",
  default: "max-w-5xl",
  wide: "max-w-7xl",
  full: "max-w-none",
};

/**
 * Page container: consistent gutters (16 px on phones), max width and vertical rhythm.
 * Every page should render inside one.
 *
 * @example <Page title="Inbox"><PageHeader title="Inbox" description="…" /></Page>
 */
export function Page({ title, parent, width = "default", className, children }: PageProps) {
  usePageTitle(title, parent);
  return <div className={cn("mx-auto w-full px-4 pb-16 pt-6 sm:px-6 md:pt-8 lg:px-10", widths[width], className)}>{children}</div>;
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
