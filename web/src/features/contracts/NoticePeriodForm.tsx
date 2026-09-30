/**
 * The notice terms of a contract, entered or corrected by hand on its card (`PATCH /api/contracts/{id}`):
 * the notice period and how it runs, the contract's own day of the month for notice where the rules read
 * one, whether it names the statutory notice periods (a job's or a lease's, or one read so by mistake) and
 * whether a fixed-term job can be left earlier by notice — the rules engine then works out the dates from them.
 */
import { useId, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { useUpdateContract } from "@/api/hooks";
import type { Contract, ContractPatch, NoticeBasis, NoticeUnit } from "@/api/types";
import { Button } from "@/components/ui/Button";
import { Checkbox, Input, Select } from "@/components/ui/Field";
import { toast } from "@/components/ui/Toast";
import { NOTICE_BASIS_COPY } from "@/lib/copy";
import { formatDate } from "@/lib/format";
import { earlyNoticeCounts, noticeDayCounts, statutoryNoticeCounts, termsUnclear } from "./model";

/** The longest notice period the form takes per unit (longer ones are misreadings). */
export const NOTICE_MAX: Record<NoticeUnit, number> = { days: 730, weeks: 104, months: 24 };
const UNITS: readonly NoticeUnit[] = ["days", "weeks", "months"];

/**
 * A job's notice without a basis of its own: the law's, to the 15th or the end of a month (§ 622 Abs. 1
 * BGB; `_plan_employment` in `src/ordnung/rules/contracts.py`). Saved as no basis.
 */
export const BY_LAW = "by_law";
export type NoticeChoice = NoticeBasis | typeof BY_LAW;

const choiceLabel = (b: NoticeChoice) => (b === BY_LAW ? "to the 15th or the end of a month" : NOTICE_BASIS_COPY[b].label);

/** What is wrong with a typed notice period, in the form's words — null when it is fine. */
export function noticeValueError(raw: string, unit: NoticeUnit): string | null {
  const t = raw.trim();
  if (!t) return "Enter the notice period, e.g. 1 or 3";
  if (!/^\d+$/.test(t)) return "Enter a whole number, e.g. 1 or 3";
  const n = Number(t);
  if (n < 1) return `At least 1 ${unit.replace(/s$/, "")}`;
  if (n > NOTICE_MAX[unit]) return `Up to ${NOTICE_MAX[unit]} ${unit}`;
  return null;
}

/**
 * What the statutory notice periods are for this contract, in the form's words (`_STATUTORY_NOTE` in
 * `src/ordnung/rules/contracts.py`): no statute gives other contracts one, so there the period decides.
 */
export function statutoryHint(c: Pick<Contract, "category">): string {
  if (c.category === "employment")
    return "The law's “gesetzliche Kündigungsfristen”: for you, 4 weeks to the 15th or the end of a month (§ 622 BGB) — longer if the contract extends your employer's longer periods to you.";
  if (c.category === "rent") return "The law's “gesetzliche Kündigungsfristen”: for you as the tenant, by the 3rd working day of a month for the end of the month after next (§ 573c BGB).";
  return "No law gives this kind of contract a notice period of its own — the period you enter decides.";
}

/** What is wrong with a typed day of the month for notice — null when it is fine or left empty (no day). */
export function noticeDayError(raw: string): string | null {
  const t = raw.trim();
  if (!t) return null;
  return /^\d+$/.test(t) && Number(t) >= 1 && Number(t) <= 31 ? null : "Enter a day from 1 to 31";
}

/**
 * The ways a contract can be ended that give dates for this one: "to the end of the term" only
 * with a term to count from (else the engine can't place it), or when the letter already said so.
 * A job's notice runs to the 15th or the end of a month unless its contract says otherwise.
 */
export function noticeBases(c: Pick<Contract, "category" | "initial_term_months" | "start_date" | "concluded_date" | "notice_basis">): NoticeChoice[] {
  if (c.category === "employment") return [BY_LAW, "end_of_month", "any_time"];
  const hasTerm = Boolean(c.initial_term_months && (c.start_date || c.concluded_date));
  return hasTerm || c.notice_basis === "end_of_term" ? ["any_time", "end_of_month", "end_of_term"] : ["any_time", "end_of_month"];
}

const unitLabel = (unit: NoticeUnit, value: string) => (value.trim() === "1" ? unit.replace(/s$/, "") : unit);

export function NoticePeriodForm({
  contract: c,
  onClose,
  onUndone,
}: {
  contract: Contract;
  /** Closed: with the saved contract, or null (Cancel, Escape). */
  onClose: (saved: Contract | null) => void;
  /** The toast's Undo put the old terms back (the contract as it is again). */
  onUndone: (restored: Contract) => void;
}) {
  const update = useUpdateContract();
  const id = useId();
  const valueRef = useRef<HTMLInputElement>(null);
  const basisRef = useRef<HTMLSelectElement>(null);
  const dayRef = useRef<HTMLInputElement>(null);
  const [value, setValue] = useState(c.notice_value ? String(c.notice_value) : "");
  const job = c.category === "employment";
  // a job's notice is counted in weeks unless it says otherwise (the law's is four: § 622 Abs. 1 BGB)
  const [unit, setUnit] = useState<NoticeUnit>(c.notice_unit ?? (job ? "weeks" : "months"));
  const bases = noticeBases(c);
  const [basis, setBasis] = useState<NoticeChoice | "">(
    c.notice_basis && bases.includes(c.notice_basis) ? c.notice_basis : bases.includes(BY_LAW) ? BY_LAW : "",
  );
  const [day, setDay] = useState(c.notice_day ? String(c.notice_day) : "");
  const [early, setEarly] = useState(c.notice_before_end);
  const [statutory, setStatutory] = useState(c.notice_statutory);
  // the contract's own day of the month, where the rules read one: with the end of a month as the basis
  const byDay = basis === "end_of_month" && noticeDayCounts(c);
  const fixedTermJob = earlyNoticeCounts(c);
  // a job's or a lease's statutory periods give the dates; elsewhere shown only to clear a misreading
  const statutoryShown = statutoryNoticeCounts(c) || c.notice_statutory;
  // the law's periods, named by the contract, need no period or basis of their own (`_plan_employment`, `_plan_rent`)
  const byStatute = statutory && statutoryNoticeCounts(c);
  const [errors, setErrors] = useState<{ value?: string; basis?: string; day?: string }>({});
  const invalid = Boolean(errors.value || errors.basis || errors.day);
  const ids = {
    value: `${id}-value`,
    unit: `${id}-unit`,
    basis: `${id}-basis`,
    day: `${id}-day`,
    dayLabel: `${id}-day-label`,
    dayOf: `${id}-day-of`,
    dayHint: `${id}-day-hint`,
    hint: `${id}-hint`,
    valueErr: `${id}-value-err`,
    basisErr: `${id}-basis-err`,
    dayErr: `${id}-day-err`,
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const dayGiven = byDay && day.trim() !== "";
    // with a day of the month the period is optional: the day alone gives the dates — and for a job, which
    // without a period of its own has the law's four weeks (`_plan_employment` in `src/ordnung/rules/contracts.py`)
    const valueError = value.trim()
      ? noticeValueError(value, unit)
      : byDay
        ? dayGiven
          ? null
          : "Enter the notice period, or the day it must arrive by"
        : job || byStatute
          ? null
          : noticeValueError(value, unit);
    const basisError = basis || byStatute ? undefined : "Choose how it can be cancelled";
    const next = { value: valueError ?? undefined, basis: basisError, day: (byDay && noticeDayError(day)) || undefined };
    setErrors(next);
    if (next.value) return valueRef.current?.focus();
    if (next.basis) return basisRef.current?.focus();
    if (next.day) return dayRef.current?.focus();
    const patch: ContractPatch = {
      ...(value.trim() ? { notice_value: Number(value.trim()), notice_unit: unit } : { notice_value: null, notice_unit: null }),
      notice_basis: basis === BY_LAW || !basis ? null : basis,
      // saved without a day or the statutory periods, the terms clear the letter's (the API's `_update`)
      notice_day: dayGiven ? Number(day.trim()) : null,
      ...(statutoryShown ? { notice_statutory: statutory } : {}),
      ...(fixedTermJob ? { notice_before_end: early } : {}),
    };
    // the old terms, with the letter's day of the month and statutory periods, which saving without them clears
    const before: ContractPatch = {
      notice_value: c.notice_value,
      notice_unit: c.notice_unit,
      notice_basis: c.notice_basis,
      notice_day: c.notice_day,
      ...(statutoryShown ? { notice_statutory: c.notice_statutory } : {}),
      ...(fixedTermJob ? { notice_before_end: c.notice_before_end } : {}),
    };
    // The call's promise, not mutate's callbacks: those never come once this form has gone, and the
    // refreshed contract (dates known now) or the toast's Undo can come after it has.
    update.mutateAsync({ id: c.id, patch }).then(
      (fresh) => {
        onClose(fresh);
        const undo = () => update.mutateAsync({ id: c.id, patch: before }).then(onUndone, () => undefined);
        const description = fresh.computed?.summary || undefined;
        // saved either way; say so plainly when the dates still can't be worked out (e.g. no term)
        if (termsUnclear(fresh)) toast.warn("Notice period saved — the dates still need checking", { description, undo });
        else toast.success("Notice period saved", { description, undo });
      },
      () => undefined, // the error toast comes from the mutation's meta; the form stays open to try again
    );
  };

  const onKey = (e: KeyboardEvent<HTMLFormElement>) => {
    if (e.key !== "Escape") return;
    e.preventDefault();
    e.stopPropagation();
    onClose(null);
  };

  return (
    <form
      noValidate
      onSubmit={submit}
      onKeyDown={onKey}
      aria-label={`Notice period for ${c.name}`}
      data-testid="notice-form"
      className="mt-4 rounded-xl border border-line bg-surface-2/50 p-3 sm:p-4"
    >
      <div className="flex flex-wrap items-start gap-x-3 gap-y-3">
        <div className="flex flex-col gap-1.5">
          <label htmlFor={ids.value} className="text-sm font-medium text-ink">
            Notice period
          </label>
          <div className="flex items-center gap-2">
            <Input
              ref={valueRef}
              id={ids.value}
              inputMode="numeric"
              autoComplete="off"
              autoFocus
              value={value}
              onChange={(e) => setValue(e.target.value)}
              aria-invalid={errors.value ? true : undefined}
              aria-describedby={errors.value ? ids.valueErr : invalid ? undefined : ids.hint}
              className="w-16 text-right tabular-nums"
            />
            <label htmlFor={ids.unit} className="sr-only">
              Unit
            </label>
            <Select id={ids.unit} value={unit} onChange={(e) => setUnit(e.target.value as NoticeUnit)} className="w-28">
              {UNITS.map((u) => (
                <option key={u} value={u}>
                  {unitLabel(u, value)}
                </option>
              ))}
            </Select>
          </div>
        </div>
        <div className="flex min-w-0 flex-1 basis-48 flex-col gap-1.5">
          <label htmlFor={ids.basis} className="text-sm font-medium text-ink">
            Can be cancelled
          </label>
          <Select
            ref={basisRef}
            id={ids.basis}
            value={basis}
            onChange={(e) => {
              setBasis(e.target.value as NoticeChoice);
              setErrors((x) => ({ ...x, basis: undefined, day: undefined }));
            }}
            aria-invalid={errors.basis ? true : undefined}
            aria-describedby={errors.basis ? ids.basisErr : undefined}
          >
            <option value="" disabled>
              Choose…
            </option>
            {bases.map((b) => (
              <option key={b} value={b}>
                {choiceLabel(b)}
              </option>
            ))}
          </Select>
        </div>
      </div>
      {byDay ? (
        // "Must arrive by day [10] of the month": one name for the field, read around it
        <div className="mt-3 flex flex-col gap-1.5">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5">
            <label id={ids.dayLabel} htmlFor={ids.day} className="text-sm font-medium text-ink">
              Must arrive by day
            </label>
            <Input
              ref={dayRef}
              id={ids.day}
              inputMode="numeric"
              autoComplete="off"
              value={day}
              onChange={(e) => setDay(e.target.value)}
              aria-labelledby={`${ids.dayLabel} ${ids.dayOf}`}
              aria-invalid={errors.day ? true : undefined}
              aria-describedby={errors.day ? ids.dayErr : ids.dayHint}
              className="w-16 text-right tabular-nums"
            />
            <span id={ids.dayOf} className="text-sm font-medium text-ink">
              of the month
            </span>
          </div>
          <p id={ids.dayHint} className="text-[12.5px] leading-5 text-muted">
            To end at that month's end — leave it empty if the contract names no day.
          </p>
        </div>
      ) : null}
      {statutoryShown ? (
        <Checkbox
          checked={statutory}
          onChange={(e) => {
            setStatutory(e.target.checked);
            setErrors((x) => ({ ...x, value: undefined, basis: undefined }));
          }}
          label="The contract names the statutory notice periods"
          description={statutoryHint(c)}
          className="mt-3"
        />
      ) : null}
      {fixedTermJob ? (
        <Checkbox
          checked={early}
          onChange={(e) => setEarly(e.target.checked)}
          label="Can be ended early by notice"
          description={`Before its end date, ${formatDate(c.end_date, { style: "day", withYear: "always" })}, as the contract allows — usually once the probation period is over.`}
          className="mt-3"
        />
      ) : null}
      {invalid ? (
        <div className="mt-2 space-y-1 text-sm font-medium leading-5 text-danger-ink">
          {errors.value ? <p id={ids.valueErr}>{errors.value}</p> : null}
          {errors.basis ? <p id={ids.basisErr}>{errors.basis}</p> : null}
          {errors.day ? <p id={ids.dayErr}>{errors.day}</p> : null}
        </div>
      ) : (
        <p id={ids.hint} className="mt-2 text-[12.5px] leading-5 text-muted">
          As the letter or contract says it — Ordnung works out the dates from it.
        </p>
      )}
      {/* the two buttons stay together ("Cancel" never wraps alone) */}
      <div className="mt-3 flex items-center gap-2">
        <Button type="submit" size="sm" variant="primary" loading={update.isPending}>
          Save notice period
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={() => onClose(null)}>
          Cancel
        </Button>
      </div>
    </form>
  );
}
