import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

export interface SectionHeaderProps {
  title: ReactNode;
  description?: ReactNode;
  icon?: LucideIcon;
  /** Count shown after the title ("Coming up · 6"). */
  count?: number;
  /** Right-aligned actions or a "See all" link. */
  action?: ReactNode;
  /** Heading level (default h2). */
  level?: 2 | 3;
  id?: string;
  className?: string;
}

/**
 * Section title row used between cards on a page ("This week", "Coming up", "Ideas").
 * Pass `id` and use `aria-labelledby` on the section for landmarks.
 */
export function SectionHeader({ title, description, icon: Icon, count, action, level = 2, id, className }: SectionHeaderProps) {
  const H = `h${level}` as "h2" | "h3";
  return (
    <div className={cn("mb-3 flex items-end gap-3", className)}>
      <div className="min-w-0 flex-1">
        <H id={id} className="flex items-center gap-2 text-[13px] font-semibold uppercase tracking-[0.06em] text-muted">
          {Icon ? <Icon className="size-4" aria-hidden /> : null}
          <span>{title}</span>
          {count !== undefined ? <span className="font-medium tabular-nums text-muted">· {count}</span> : null}
        </H>
        {description ? <p className="mt-1 text-base text-muted">{description}</p> : null}
      </div>
      {action ? <div className="flex min-w-0 max-w-full shrink-0 items-center gap-2">{action}</div> : null}
    </div>
  );
}
