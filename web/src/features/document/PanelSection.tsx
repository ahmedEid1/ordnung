import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

/** A titled section of the document panel (landmark with a heading). */
export function PanelSection({
  id,
  title,
  icon: Icon,
  count,
  action,
  children,
  className,
}: {
  id: string;
  title: string;
  icon?: LucideIcon;
  count?: number;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  const hid = `${id}-title`;
  return (
    <section id={id} aria-labelledby={hid} className={cn("scroll-mt-20", className)}>
      <div className="mb-2.5 flex items-center gap-2 px-1">
        <h2 id={hid} className="flex items-center gap-2 text-[12.5px] font-semibold uppercase tracking-[0.07em] text-muted">
          {Icon ? <Icon className="size-4" aria-hidden /> : null}
          {title}
          {count !== undefined ? <span className="font-medium tabular-nums text-muted">· {count}</span> : null}
        </h2>
        {action ? <div className="ml-auto flex items-center gap-2">{action}</div> : null}
      </div>
      {children}
    </section>
  );
}
