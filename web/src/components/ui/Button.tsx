import type { ComponentProps, ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import { Spinner } from "./Spinner";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger" | "link" | "soft";
export type ButtonSize = "sm" | "md" | "lg";

/*
 * Buttons don't shrink or wrap by default (toolbars, card footers). To let one share a tight row,
 * pass `min-w-0` with `flex-1` (or `shrink`): its text label then ends in "…" instead of
 * overflowing.
 *
 * Disabled (not busy) buttons turn neutral — a disabled teal "Write the letter" must not read as
 * ready; a busy one (`loading`) keeps its colour next to the spinner. `inactive:` is defined in
 * styles/index.css.
 */
const base =
  "relative inline-flex shrink-0 select-none items-center justify-center gap-2 whitespace-nowrap rounded-lg font-medium " +
  "transition-[background-color,border-color,color,box-shadow,transform] duration-150 ease-out " +
  "active:translate-y-px disabled:pointer-events-none aria-disabled:pointer-events-none " +
  "inactive:text-faint inactive:shadow-none " +
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent";

/** Filled variants lose their fill when disabled. */
const inactiveFill = "inactive:border-transparent inactive:bg-surface-3";

const variants: Record<ButtonVariant, string> = {
  primary: cn(
    "bg-accent text-on-accent shadow-[inset_0_1px_0_rgb(255_255_255/0.14),0_1px_2px_rgb(0_0_0/0.14)] hover:bg-accent-strong dark:hover:bg-accent-strong",
    inactiveFill,
  ),
  secondary: cn("border border-line-strong/80 bg-surface text-ink shadow-[var(--shadow-card)] hover:border-line-strong hover:bg-surface-2", inactiveFill),
  soft: cn("bg-accent-soft text-accent hover:bg-accent/15", inactiveFill),
  ghost: "text-muted hover:bg-surface-3/70 hover:text-ink",
  danger: cn(
    "bg-danger text-white shadow-[0_1px_2px_rgb(0_0_0/0.14)] hover:bg-danger/90 dark:border dark:border-danger/40 dark:bg-danger-soft dark:text-danger-ink dark:hover:bg-danger/20",
    inactiveFill,
  ),
  // text-sized, but still a 24 px tall target (WCAG 2.5.8)
  link: "h-auto! min-h-6 px-0! text-accent underline-offset-4 hover:underline active:translate-y-0",
};

const sizes: Record<ButtonSize, string> = {
  sm: "h-8 px-3 text-[13px] [&_svg]:size-3.5",
  md: "h-9 px-3.5 text-base [&_svg]:size-4",
  lg: "h-11 px-5 text-[15px] [&_svg]:size-[18px]",
};

/** Class names for a button look — use on `<Link>`/`<a>` to style links as buttons. */
export function buttonVariants({
  variant = "secondary",
  size = "md",
  className,
}: { variant?: ButtonVariant; size?: ButtonSize; className?: string } = {}): string {
  return cn(base, variants[variant], sizes[size], className);
}

export interface ButtonProps extends ComponentProps<"button"> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** Shows a spinner, disables the button and sets aria-busy. */
  loading?: boolean;
  /** Leading icon (lucide component). */
  icon?: LucideIcon;
  /** Trailing icon (lucide component). */
  iconRight?: LucideIcon;
  children?: ReactNode;
}

/**
 * The one button. Variants: `primary` (one per view), `secondary` (default), `soft`, `ghost`,
 * `danger`, `link`. Sizes `sm` / `md` / `lg`. Use a verb label ("Pay", "Draft letter").
 *
 * @example <Button variant="primary" icon={Plus}>Add letters</Button>
 */
export function Button({
  variant = "secondary",
  size = "md",
  loading = false,
  icon: Icon,
  iconRight: IconRight,
  className,
  children,
  disabled,
  type,
  ref,
  ...rest
}: ButtonProps) {
  return (
    <button
      ref={ref}
      type={type ?? "button"}
      className={buttonVariants({ variant, size, className })}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...rest}
    >
      {loading ? <Spinner className="size-4" /> : Icon ? <Icon aria-hidden /> : null}
      {/* a text label can end in "…" when the caller lets the button shrink (`min-w-0 flex-1`) */}
      {typeof children === "string" || typeof children === "number" ? <span className="min-w-0 truncate">{children}</span> : children}
      {IconRight && !loading ? <IconRight aria-hidden /> : null}
    </button>
  );
}

export interface IconButtonProps extends Omit<ComponentProps<"button">, "children"> {
  /** Accessible name (required — icon-only buttons need a label). */
  label: string;
  icon: LucideIcon;
  variant?: Exclude<ButtonVariant, "link">;
  size?: ButtonSize;
  loading?: boolean;
}

const iconSizes: Record<ButtonSize, string> = {
  sm: "size-8 [&_svg]:size-4",
  md: "size-9 [&_svg]:size-[18px]",
  lg: "size-11 [&_svg]:size-5",
};

/**
 * Square icon-only button. `label` becomes the aria-label and the native tooltip.
 *
 * @example <IconButton icon={X} label="Close" variant="ghost" onClick={onClose} />
 */
export function IconButton({
  label,
  icon: Icon,
  variant = "ghost",
  size = "md",
  loading,
  className,
  type,
  disabled,
  title,
  ref,
  ...rest
}: IconButtonProps) {
  return (
    <button
      ref={ref}
      type={type ?? "button"}
      aria-label={label}
      title={title ?? label}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={cn(base, variants[variant], iconSizes[size], "px-0", className)}
      {...rest}
    >
      {loading ? <Spinner className="size-4" /> : <Icon aria-hidden />}
    </button>
  );
}
