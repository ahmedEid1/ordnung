import { cloneElement, isValidElement, type ComponentProps, type ReactElement, type ReactNode } from "react";
import { Check, ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";
import { useStableId } from "./internal";

/**
 * The look of every text field and select. The edge is `control-border` (≥ 3:1 against the page,
 * WCAG 1.4.11) and placeholders are `muted` (4.5:1) — other fields (a search box, the letter
 * editor) reuse these classes via {@link controlClasses}.
 */
const control =
  "w-full rounded-lg border border-control-border bg-surface px-3 text-base text-ink shadow-[inset_0_1px_1px_rgb(0_0_0/0.03)] " +
  "placeholder:text-muted transition-[border-color,box-shadow] hover:border-muted " +
  // focus-within, not focus-visible: a date field's calendar button is a Tab stop of its own, and while it
  // has focus the field matches neither :focus nor :focus-visible (Chromium), so the ring would vanish
  "focus-within:border-accent focus-within:outline-none focus-within:ring-3 focus-within:ring-accent/20 " +
  "disabled:cursor-not-allowed disabled:opacity-60 aria-invalid:border-danger " +
  // an invalid field keeps a visible focus indicator: its red border alone looks the same focused or not (WCAG
  // 2.4.7; review round 3 of phase 2 — the old 15 % ring vanished on a warning background)
  "aria-invalid:focus-within:ring-danger/25 aria-invalid:focus-within:outline-2 aria-invalid:focus-within:outline-offset-1 " +
  "aria-invalid:focus-within:outline-solid aria-invalid:focus-within:outline-danger";

/** Classes of a text field (`Input`), for fields built by hand (e.g. a search box with an icon). */
export function controlClasses(className?: string): string {
  return cn(control, "h-9", className);
}

export interface FieldProps {
  label: ReactNode;
  /** Help text under the control. */
  hint?: ReactNode;
  /** Error message (sets aria-invalid on the control). */
  error?: ReactNode;
  /** Mark as optional in the label. */
  optional?: boolean;
  /** The control (Input, Select, Textarea…); gets id/aria wiring automatically. */
  children: ReactElement;
  id?: string;
  className?: string;
}

/**
 * Label + control + hint/error, with ids and aria-describedby wired up.
 *
 * @example <Field label="Your name" hint="Used as the sender on letters"><Input value={…} /></Field>
 */
export function Field({ label, hint, error, optional, children, id, className }: FieldProps) {
  const cid = useStableId(id, "fld");
  const hintId = `${cid}-hint`;
  const errId = `${cid}-err`;
  const describedBy = [hint ? hintId : null, error ? errId : null].filter(Boolean).join(" ") || undefined;
  const child = isValidElement(children)
    ? cloneElement(children as ReactElement<Record<string, unknown>>, {
        id: cid,
        "aria-describedby": describedBy,
        "aria-invalid": error ? true : undefined,
      })
    : children;
  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <label htmlFor={cid} className="text-sm font-medium text-ink">
        {label}
        {optional ? <span className="font-normal text-muted"> (optional)</span> : null}
      </label>
      {child}
      {hint && !error ? (
        <p id={hintId} className="text-sm leading-5 text-muted">
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={errId} className="text-sm font-medium leading-5 text-danger-ink">
          {error}
        </p>
      ) : null}
    </div>
  );
}

/** Text input. */
export function Input({ className, ...rest }: ComponentProps<"input">) {
  return <input className={controlClasses(className)} {...rest} />;
}

/** Multi-line text input. */
export function Textarea({ className, ...rest }: ComponentProps<"textarea">) {
  return <textarea className={cn(control, "min-h-24 py-2 leading-relaxed", className)} {...rest} />;
}

/**
 * Native select with a custom chevron. A long choice ("Nordrhein-Westfalen (North Rhine-Westphalia)")
 * ends in "…" in the closed select; the open list shows it whole.
 */
export function Select({ className, children, ...rest }: ComponentProps<"select">) {
  return (
    <div className={cn("relative min-w-0", className)}>
      <select className={cn(control, "h-9 appearance-none truncate pr-9")} {...rest}>
        {children}
      </select>
      <ChevronDown className="pointer-events-none absolute right-3 top-1/2 size-4 -translate-y-1/2 text-muted" aria-hidden />
    </div>
  );
}

export interface SwitchProps extends Omit<ComponentProps<"button">, "onChange"> {
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  /** Visible label (also the accessible name). */
  label?: ReactNode;
  description?: ReactNode;
}

/**
 * On/off switch (`role="switch"`). With `label` it renders a full clickable row.
 *
 * @example <Switch checked={priv} onCheckedChange={setPriv} label="Keep private — no AI" />
 */
export function Switch({ checked, onCheckedChange, label, description, className, id, ...rest }: SwitchProps) {
  const sid = useStableId(id, "sw");
  const btn = (
    <button
      id={sid}
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onCheckedChange(!checked)}
      className={cn(
        "relative inline-flex h-6 w-10 shrink-0 items-center rounded-full transition-colors duration-200",
        checked ? "bg-accent" : "bg-faint",
        !label && className,
      )}
      {...rest}
    >
      <span
        className={cn(
          "inline-block size-5 rounded-full bg-white shadow-[0_1px_3px_rgb(0_0_0/0.25)] transition-transform duration-200",
          checked ? "translate-x-[18px]" : "translate-x-0.5",
        )}
        aria-hidden
      />
    </button>
  );
  if (!label) return btn;
  return (
    <div className={cn("flex items-start justify-between gap-4", className)}>
      <label htmlFor={sid} className="min-w-0 flex-1 cursor-pointer">
        <span className="block text-base font-medium text-ink">{label}</span>
        {description ? <span className="mt-0.5 block text-sm leading-5 text-pretty text-muted">{description}</span> : null}
      </label>
      {btn}
    </div>
  );
}

/**
 * Checkbox with label. The input itself is a 24 × 24 px cell (WCAG 2.5.8 target size — a native checkbox
 * can't be given a hit area larger than its box, so the 16 px box is drawn under it), and the whole row is
 * its label: the words toggle it too, as before.
 */
export function Checkbox({
  label,
  description,
  className,
  id,
  ...rest
}: Omit<ComponentProps<"input">, "type"> & { label: ReactNode; description?: ReactNode }) {
  const cid = useStableId(id, "cb");
  return (
    <label className={cn("flex cursor-pointer items-start gap-1.5 text-base", className)}>
      {/* the input covers the cell and takes the pointer (the box and the check under it let it through) */}
      <span className="relative grid size-6 shrink-0 place-items-center">
        <input id={cid} type="checkbox" className="peer absolute inset-0 m-0 size-6 cursor-pointer appearance-none rounded-md outline-none disabled:cursor-not-allowed" {...rest} />
        <span
          aria-hidden
          className={cn(
            "pointer-events-none size-4 rounded border border-control-border bg-surface transition-colors",
            "peer-checked:border-accent peer-checked:bg-accent peer-disabled:opacity-60",
            "peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-accent",
          )}
        />
        <Check className="pointer-events-none absolute size-3 text-on-accent opacity-0 peer-checked:opacity-100" strokeWidth={3} aria-hidden />
      </span>
      <span className="min-w-0">
        <span className="font-medium text-ink">{label}</span>
        {description ? <span className="mt-0.5 block text-sm leading-5 text-pretty text-muted">{description}</span> : null}
      </span>
    </label>
  );
}
