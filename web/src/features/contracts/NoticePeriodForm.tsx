/**
 * The notice period of a contract whose terms we couldn't work out, entered by hand on its card
 * (`PATCH /api/contracts/{id}`): the rules engine then works out the dates from it.
 */
import { useId, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { useUpdateContract } from "@/api/hooks";
import type { Contract, NoticeBasis, NoticeUnit } from "@/api/types";
import { Button } from "@/components/ui/Button";
import { Input, Select } from "@/components/ui/Field";
import { toast } from "@/components/ui/Toast";
import { NOTICE_BASIS_COPY } from "@/lib/copy";
import { termsUnclear } from "./model";

/** The longest notice period the form takes per unit (longer ones are misreadings). */
export const NOTICE_MAX: Record<NoticeUnit, number> = { days: 730, weeks: 104, months: 24 };
const UNITS: readonly NoticeUnit[] = ["days", "weeks", "months"];

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
 * The ways a contract can be ended that give dates for this one: "to the end of the term" only
 * with a term to count from (else the engine can't place it), or when the letter already said so.
 */
export function noticeBases(c: Pick<Contract, "initial_term_months" | "start_date" | "concluded_date" | "notice_basis">): NoticeBasis[] {
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
  const [value, setValue] = useState(c.notice_value ? String(c.notice_value) : "");
  const [unit, setUnit] = useState<NoticeUnit>(c.notice_unit ?? "months");
  const bases = noticeBases(c);
  const [basis, setBasis] = useState<NoticeBasis | "">(c.notice_basis && bases.includes(c.notice_basis) ? c.notice_basis : "");
  const [errors, setErrors] = useState<{ value?: string; basis?: string }>({});
  const invalid = Boolean(errors.value || errors.basis);
  const ids = { value: `${id}-value`, unit: `${id}-unit`, basis: `${id}-basis`, hint: `${id}-hint`, valueErr: `${id}-value-err`, basisErr: `${id}-basis-err` };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const next = { value: noticeValueError(value, unit) ?? undefined, basis: basis ? undefined : "Choose how it can be cancelled" };
    setErrors(next);
    if (next.value) return valueRef.current?.focus();
    if (next.basis || !basis) return basisRef.current?.focus();
    // with the letter's day of the month, which saving notice terms clears (the API's `_update`)
    const before = { notice_value: c.notice_value, notice_unit: c.notice_unit, notice_basis: c.notice_basis, notice_day: c.notice_day };
    // The call's promise, not mutate's callbacks: those never come once this form has gone, and the
    // refreshed contract (dates known now) or the toast's Undo can come after it has.
    update.mutateAsync({ id: c.id, patch: { notice_value: Number(value.trim()), notice_unit: unit, notice_basis: basis } }).then(
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
              setBasis(e.target.value as NoticeBasis);
              setErrors((x) => ({ ...x, basis: undefined }));
            }}
            aria-invalid={errors.basis ? true : undefined}
            aria-describedby={errors.basis ? ids.basisErr : undefined}
          >
            <option value="" disabled>
              Choose…
            </option>
            {bases.map((b) => (
              <option key={b} value={b}>
                {NOTICE_BASIS_COPY[b].label}
              </option>
            ))}
          </Select>
        </div>
      </div>
      {invalid ? (
        <div className="mt-2 space-y-1 text-sm font-medium leading-5 text-danger-ink">
          {errors.value ? <p id={ids.valueErr}>{errors.value}</p> : null}
          {errors.basis ? <p id={ids.basisErr}>{errors.basis}</p> : null}
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
