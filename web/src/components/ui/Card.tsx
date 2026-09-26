import type { HTMLAttributes, ReactNode, Ref } from "react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

export interface CardProps extends HTMLAttributes<HTMLDivElement> {
  /** Render as another element (section, article, li…). */
  as?: "div" | "section" | "article" | "li" | "aside";
  /** Hover lift for clickable cards. */
  interactive?: boolean;
  /** Inner padding preset. */
  padding?: "none" | "sm" | "md" | "lg";
  /** Accent edge on the left (e.g. urgency). */
  accent?: "danger" | "warn" | "ok" | "accent";
  ref?: Ref<HTMLDivElement>;
}

const paddings = { none: "", sm: "p-3", md: "p-4 sm:p-5", lg: "p-5 sm:p-7" };
const accents = {
  danger: "before:bg-danger",
  warn: "before:bg-warn",
  ok: "before:bg-ok",
  accent: "before:bg-accent",
};

/**
 * Paper card surface (`.card`: white/near-black surface, hairline border, soft shadow).
 *
 * @example <Card as="section" padding="md"><CardHeader title="Coming up" /></Card>
 */
export function Card({ as: Tag = "div", interactive, padding = "md", accent, className, ref, ...rest }: CardProps) {
  return (
    <Tag
      {...(rest as HTMLAttributes<HTMLElement>)}
      ref={ref as never}
      className={cn(
        "card relative",
        paddings[padding],
        interactive &&
          "transition-[box-shadow,border-color,transform] duration-200 hover:-translate-y-px hover:border-line-strong hover:shadow-[var(--shadow-pop)] motion-reduce:hover:translate-y-0",
        accent &&
          cn(
            "overflow-hidden before:absolute before:inset-y-0 before:left-0 before:w-[3px] before:content-['']",
            accents[accent],
          ),
        className,
      )}
    />
  );
}

export interface CardHeaderProps extends Omit<HTMLAttributes<HTMLDivElement>, "title"> {
  title: ReactNode;
  description?: ReactNode;
  icon?: LucideIcon;
  /** Right-aligned actions (buttons, links). */
  action?: ReactNode;
  /** Heading level for the title (default h3). */
  level?: 2 | 3 | 4;
}

/**
 * Title row of a card: optional icon, title, description and actions. A lone title is centred on
 * the icon; with a description the icon lines up with the title's first line.
 */
export function CardHeader({ title, description, icon: Icon, action, level = 3, className, ...rest }: CardHeaderProps) {
  const H = `h${level}` as "h2" | "h3" | "h4";
  return (
    <div className={cn("mb-3 flex gap-3", description ? "items-start" : "items-center", className)} {...rest}>
      {Icon ? (
        <span className={cn("grid size-8 shrink-0 place-items-center rounded-lg bg-surface-2 text-muted", description && "mt-0.5")}>
          <Icon className="size-4" aria-hidden />
        </span>
      ) : null}
      <div className="min-w-0 flex-1">
        <H className="text-[15px] font-semibold leading-6 text-ink">{title}</H>
        {description ? <p className="mt-0.5 text-base text-muted">{description}</p> : null}
      </div>
      {action ? <div className="flex shrink-0 items-center gap-2">{action}</div> : null}
    </div>
  );
}
