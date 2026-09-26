/**
 * The facts a template letter needs, rendered from its {@link TemplateConfig}: dates, amounts, a
 * description, addresses. Errors show next to the field; the composer keeps "Write the letter"
 * disabled until every required fact is there.
 */
import type { ComponentProps } from "react";
import { Link } from "react-router";
import { Landmark } from "lucide-react";
import type { Profile } from "@/api/types";
import { Checkbox, Field, Input, Textarea } from "@/components/ui/Field";
import { formatDate, formatMoney } from "@/lib/format";
import { cn } from "@/lib/utils";
import { fieldError, nextDay, parseMoney, type DetailField, type DetailValues, type LetterDefaults, type TemplateConfig } from "./templates";

export interface TemplateFieldsProps {
  config: TemplateConfig;
  values: DetailValues;
  onChange: (values: DetailValues) => void;
  today: string;
  profile: Profile | undefined;
  /** the answered letter's own deadline and amount (used when the person leaves theirs empty) */
  defaults?: LetterDefaults;
}

/** An amount in euros: the label's id and descriptions (from {@link Field}) reach the input itself. */
function MoneyInput({ className, ...rest }: ComponentProps<"input">) {
  return (
    <div className="relative">
      <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-sm text-muted" aria-hidden>
        €
      </span>
      <Input inputMode="decimal" placeholder="0,00" autoComplete="off" {...rest} className={cn("pl-7 tabular-nums", className)} />
    </div>
  );
}

/** The hint under a field: how an amount was read ("= 1.500,00 €"), and what an empty field falls back to. */
function hintFor(field: DetailField, value: string, defaults: LetterDefaults): string | undefined {
  if (field.type === "money" && value.trim()) {
    // "1.500" or "1,5": say how it was read (a plain "50" needs no echo)
    const amount = parseMoney(value);
    return amount !== null && /[.,]/.test(value) ? `= ${formatMoney(amount)}` : undefined;
  }
  if (field.name === "deadline" && defaults.deadline && !value) return `Leave empty to use the letter's deadline, ${formatDate(defaults.deadline, { style: "short" })}.`;
  if (field.name === "amount" && defaults.amount !== null) return `Leave empty to use the letter's amount, ${formatMoney(defaults.amount)}.`;
  return field.hint;
}

function FieldControl({
  field,
  values,
  onChange,
  today,
  defaults,
}: {
  field: DetailField;
  values: DetailValues;
  onChange: (v: DetailValues) => void;
  today: string;
  defaults: LetterDefaults;
}) {
  const error = fieldError(field, values, today, defaults);
  const optional = field.type !== "checkbox" && !field.required;
  if (field.type === "checkbox") {
    return (
      <Checkbox
        label={field.label}
        description={field.hint}
        checked={Boolean(values.instructions_missing)}
        onChange={(e) => onChange({ ...values, instructions_missing: e.target.checked })}
        className="sm:col-span-2"
      />
    );
  }
  const value = (values[field.name] as string | undefined) ?? "";
  const set = (v: string) => onChange({ ...values, [field.name]: v });
  const hint = hintFor(field, value, defaults);
  if (field.type === "textarea") {
    return (
      <Field label={field.label} hint={hint} error={error} optional={optional} className="sm:col-span-2">
        <Textarea value={value} onChange={(e) => set(e.target.value)} placeholder={field.placeholder} rows={field.name === "defect" ? 3 : 2} className="min-h-16" />
      </Field>
    );
  }
  if (field.type === "date") {
    return (
      <Field label={field.label} hint={hint} error={error} optional={optional}>
        <Input
          type="date"
          value={value}
          onChange={(e) => set(e.target.value)}
          min={field.when === "future" ? nextDay(today) : undefined}
          max={field.when === "past" ? today : undefined}
        />
      </Field>
    );
  }
  if (field.type === "money") {
    return (
      <Field label={field.label} hint={hint} error={error} optional={optional}>
        <MoneyInput value={value} onChange={(e) => set(e.target.value)} />
      </Field>
    );
  }
  return (
    <Field label={field.label} hint={hint} error={error} optional={optional} className={cn(field.name === "subject_matter" && "sm:col-span-2")}>
      <Input value={value} onChange={(e) => set(e.target.value)} placeholder={field.placeholder} />
    </Field>
  );
}

const NO_DEFAULTS: LetterDefaults = { deadline: null, amount: null };

export function TemplateFields({ config, values, onChange, today, profile, defaults = NO_DEFAULTS }: TemplateFieldsProps) {
  const iban = profile?.iban?.trim() ?? "";
  return (
    <div className="space-y-3">
      {config.fields.length ? (
        <div className="grid gap-3 sm:grid-cols-2">
          {config.fields.map((f) => (
            <FieldControl key={f.name} field={f} values={values} onChange={onChange} today={today} defaults={defaults} />
          ))}
        </div>
      ) : null}
      {config.kind === "deposit_return" ? (
        <p className="flex items-start gap-2 rounded-xl bg-surface-2/70 px-3 py-2.5 text-[13px] leading-5 text-ink/85">
          <Landmark className="mt-0.5 size-4 shrink-0 text-muted" aria-hidden />
          {iban ? (
            <span>
              The refund goes to your account <span className="font-mono text-[12.5px] [overflow-wrap:anywhere]">{iban}</span> from{" "}
              <Link to="/settings#set-profile" className="font-medium text-accent underline-offset-2 hover:underline">
                Settings
              </Link>
              .
            </span>
          ) : (
            <span>
              Add your IBAN under{" "}
              <Link to="/settings#set-profile" className="font-medium text-accent underline-offset-2 hover:underline">
                Settings → Profile
              </Link>{" "}
              so the letter says where to send the money — or fill it in in the letter.
            </span>
          )}
        </p>
      ) : null}
    </div>
  );
}
