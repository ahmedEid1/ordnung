/**
 * The facts a template letter needs, rendered from its {@link TemplateConfig}: dates, amounts, a
 * description, addresses. Errors show next to the field; the composer keeps "Write the letter"
 * disabled until every required fact is there.
 */
import type { ReactNode } from "react";
import { useHref } from "react-router";
import { ExternalLink, Landmark, MapPinHouse } from "lucide-react";
import type { Profile } from "@/api/types";
import { Checkbox, Field, Input, Textarea } from "@/components/ui/Field";
import { MoneyInput, moneyReadBack } from "@/components/ui/MoneyInput";
import { formatDate, formatIban, formatMoney } from "@/lib/format";
import { cn } from "@/lib/utils";
import { usePhoneCompanion } from "@/features/phone/client";
import { moveStanding } from "@/features/today/moving";
import { fieldError, nextDay, type DetailField, type DetailValues, type LetterDefaults, type TemplateConfig } from "./templates";

export interface TemplateFieldsProps {
  config: TemplateConfig;
  values: DetailValues;
  onChange: (values: DetailValues) => void;
  today: string;
  profile: Profile | undefined;
  /** the answered letter's own deadline and amount (used when the person leaves theirs empty) */
  defaults?: LetterDefaults;
}

/** The hint under a field: how an amount was read ("= 1.500,00 €"), and what an empty field falls back to. */
function hintFor(field: DetailField, value: string, defaults: LetterDefaults): string | undefined {
  // "1.500" or "1,5": say how it was read (a plain "50" needs no echo)
  if (field.type === "money" && value.trim()) return moneyReadBack(value);
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

/**
 * A link to the profile settings that keeps the letter being written: it opens in a new tab — following
 * it inside the composer would close the dialog and drop everything typed. It says so the way the
 * app's other new-tab links do: the external-link icon, glued to the last word.
 */
function SettingsLink({ children }: { children: ReactNode }) {
  const href = useHref({ pathname: "/settings", hash: "#set-profile" });
  return (
    <a href={href} target="_blank" rel="noopener noreferrer" data-new-tab className="font-medium text-accent underline-offset-2 hover:underline">
      {children}
      <span className="sr-only"> (opens in a new tab, so this letter stays as it is)</span>
      {"⁠"}
      <ExternalLink className="ml-0.5 inline size-3 align-[-0.1em]" aria-hidden />
    </a>
  );
}

/**
 * Under the new-address letter: where the rest of the list is after a move the person told, else how to start the
 * moving checklist — in Settings, which is on the computer (a phone gets no link). The letter never changes the
 * profile: its address is the sender of every letter.
 */
function MovingNote({ profile, today }: { profile: Profile | undefined; today: string }) {
  const phone = usePhoneCompanion();
  return (
    <p className="flex items-start gap-2 rounded-xl bg-surface-2/70 px-3 py-2.5 text-[13px] leading-5 text-ink/85">
      <MapPinHouse className="mt-0.5 size-4 shrink-0 text-muted" aria-hidden />
      {moveStanding(profile, today) ? (
        <span>Your moving checklist on Today lists who else needs your new address.</span>
      ) : (
        <span>
          Telling several places? Change your address in {phone ? "Settings → Profile on your computer" : <SettingsLink>Settings → Profile</SettingsLink>} and
          tick <em>I moved</em>: Today then lists everyone who needs it, starting with the <span lang="de">Bürgeramt</span>.
        </span>
      )}
    </p>
  );
}

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
              {/* grouped in fours like everywhere else: a line breaks only between the groups */}
              The refund goes to your account <span className="font-ident">{formatIban(iban)}</span> from <SettingsLink>Settings</SettingsLink>.
            </span>
          ) : (
            <span>
              Add your IBAN under <SettingsLink>Settings → Profile</SettingsLink> so the letter says where to send the money — or fill it in in
              the letter.
            </span>
          )}
        </p>
      ) : null}
      {config.kind === "address_change" ? <MovingNote profile={profile} today={today} /> : null}
    </div>
  );
}
