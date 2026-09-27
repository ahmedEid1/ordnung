import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";

/** A titled section of the document panel (landmark with a heading). */
export function PanelSection({
  id,
  title,
  icon: Icon,
  count,
  countLabel,
  action,
  children,
  className,
}: {
  id: string;
  title: string;
  icon?: LucideIcon;
  /** Shown after the title: "To-dos & dates · 3". */
  count?: number;
  /** What the count counts, for screen readers ("3 open"); default: the number alone. */
  countLabel?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  const hid = `${id}-title`;
  return (
    <section id={id} aria-labelledby={hid} className={className}>
      <div className="mb-2.5 flex items-center gap-2 px-1">
        {/* the app's eyebrow, like the verdict's sections (UI audit round 1) */}
        <h2 id={hid} className="eyebrow flex items-center gap-2">
          {Icon ? <Icon className="size-4 shrink-0" aria-hidden /> : null}
          {title}
          {count !== undefined ? (
            <>
              {/* "· 3" on screen; "To-dos & dates, 3 open" to a screen reader, not "dot 3" */}
              <span aria-hidden className="font-medium tabular-nums">
                · {count}
              </span>
              <span className="sr-only">, {countLabel ?? count}</span>
            </>
          ) : null}
        </h2>
        {action ? <div className="ml-auto flex items-center gap-2">{action}</div> : null}
      </div>
      {children}
    </section>
  );
}
