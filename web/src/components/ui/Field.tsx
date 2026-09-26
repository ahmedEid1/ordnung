import { cloneElement, isValidElement, type ComponentProps, type ReactElement, type ReactNode } from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";
import { useStableId } from "./internal";

const control =
  "w-full rounded-lg border border-line-strong/80 bg-surface px-3 text-base text-ink shadow-[inset_0_1px_1px_rgb(0_0_0/0.03)] " +
  "placeholder:text-muted/70 transition-[border-color,box-shadow] hover:border-line-strong " +
  "focus-visible:border-accent focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-accent/20 " +
  "disabled:cursor-not-allowed disabled:opacity-60 aria-invalid:border-danger aria-invalid:ring-danger/15";

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
      <label htmlFor={cid} className="text-[13px] font-medium text-ink">
        {label}
        {optional ? <span className="font-normal text-muted"> (optional)</span> : null}
      </label>
      {child}
      {hint && !error ? (
        <p id={hintId} className="text-[12.5px] leading-5 text-muted">
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={errId} className="text-[12.5px] font-medium leading-5 text-danger-ink">
          {error}
        </p>
      ) : null}
    </div>
  );
}

/** Text input. */
export function Input({ className, ...rest }: ComponentProps<"input">) {
  return <input className={cn(control, "h-9", className)} {...rest} />;
}

/** Multi-line text input. */
export function Textarea({ className, ...rest }: ComponentProps<"textarea">) {
  return <textarea className={cn(control, "min-h-24 py-2 leading-relaxed", className)} {...rest} />;
}

/** Native select with a custom chevron. */
export function Select({ className, children, ...rest }: ComponentProps<"select">) {
  return (
    <div className={cn("relative", className)}>
      <select className={cn(control, "h-9 appearance-none pr-9")} {...rest}>
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
        {description ? <span className="mt-0.5 block text-[13px] leading-5 text-pretty text-muted">{description}</span> : null}
      </label>
      {btn}
    </div>
  );
}

/** Checkbox with label. */
export function Checkbox({
  label,
  description,
  className,
  id,
  ...rest
}: Omit<ComponentProps<"input">, "type"> & { label: ReactNode; description?: ReactNode }) {
  const cid = useStableId(id, "cb");
  return (
    <div className={cn("flex items-start gap-2.5", className)}>
      <input id={cid} type="checkbox" className="mt-0.5 size-4 shrink-0 rounded accent-[var(--color-accent)]" {...rest} />
      <label htmlFor={cid} className="cursor-pointer text-base">
        <span className="font-medium text-ink">{label}</span>
        {description ? <span className="mt-0.5 block text-[13px] leading-5 text-pretty text-muted">{description}</span> : null}
      </label>
    </div>
  );
}
