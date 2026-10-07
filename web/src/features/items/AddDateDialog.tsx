/**
 * "Add a date": a date of the person's own — a reminder, a deadline, a payment, an appointment … — on Timeline,
 * or in a letter's "To-dos & dates", where a letter kept private or one Claude couldn't read has none of its own
 * (feature audit G1: Settings and the wizard promised "add your own dates" with nowhere to do it). It is posted as
 * a to-do added by hand (`POST /api/items`): reading the letter again never changes it, and it is on Today, the
 * Timeline, the calendar file and the reminders like the dates Ordnung reads ("Your own reminders" for a reminder).
 */
import { useId, useState, type FormEvent } from "react";
import { CalendarPlus, Check, Plus } from "lucide-react";
import type { Document, ItemCreate, ItemKind } from "@/api/types";
import { useCreateItem, useDeleteItem, useDocuments } from "@/api/hooks";
import { Button, type ButtonProps } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Field, Input, Select } from "@/components/ui/Field";
import { MoneyInput, moneyReadBack } from "@/components/ui/MoneyInput";
import { toast } from "@/components/ui/Toast";
import { usePhoneCompanion } from "@/features/phone/client";
import { ITEM_KIND_COPY } from "@/lib/copy";
import { formatDate } from "@/lib/format";
import { parseMoney } from "@/lib/money";
import { cn } from "@/lib/utils";

/** The letter a date is for: it joins that letter's to-dos, with its sender, thread and area. */
export type DateLetter = Pick<Document, "id" | "title" | "filename" | "party_id" | "case_id" | "area">;

/** The kinds a person adds, the plainest first ("Your own reminders" in Settings → Reminders). */
export const ADD_KINDS: readonly { kind: ItemKind; label: string }[] = [
  { kind: "reminder", label: "Reminder" },
  { kind: "deadline", label: "Deadline" },
  { kind: "payment", label: "Payment" },
  { kind: "appointment", label: "Appointment" },
  { kind: "task", label: "To-do" },
  { kind: "expiry", label: "Expiry date" },
];

export interface DateDraft {
  title: string;
  date: string;
  kind: ItemKind;
  amount: string;
  /** The letter chosen on Timeline (`""`: none). */
  docId: string;
}

const EMPTY: DateDraft = { title: "", date: "", kind: "reminder", amount: "", docId: "" };
/** The longest title the API takes. */
export const TITLE_MAX = 300;
/** The fields in order: the first one with a problem gets focus when adding fails. */
const FIELDS = ["title", "date", "amount"] as const;
type Problem = (typeof FIELDS)[number];

/** What keeps the draft from being added, by field, in plain words. */
export function dateProblems(d: DateDraft): Partial<Record<Problem, string>> {
  const out: Partial<Record<Problem, string>> = {};
  if (!d.title.trim()) out.title = "Say what it is — a few words are enough.";
  if (!/^\d{4}-\d{2}-\d{2}$/.test(d.date)) out.date = "Choose the day.";
  if (d.amount.trim() && parseMoney(d.amount) === null) out.amount = "Type an amount in euros, like 29,90 or 1.500.";
  return out;
}

/** The to-do the API is sent: the person's words, and the letter's sender, thread and area when it is for one. */
export function dateBody(d: DateDraft, letter: DateLetter | null): ItemCreate {
  const amount = d.amount.trim() ? parseMoney(d.amount) : null;
  return {
    kind: d.kind,
    title: d.title.replace(/\s+/g, " ").trim(),
    due_date: d.date,
    amount,
    currency: amount !== null ? "EUR" : null,
    // a payment added by hand is one you make
    direction: d.kind === "payment" ? "out" : null,
    doc_id: letter?.id ?? null,
    party_id: letter?.party_id ?? null,
    case_id: letter?.case_id ?? null,
    area: letter?.area ?? "other",
  };
}

const letterName = (d: Pick<Document, "title" | "filename">) => d.title || d.filename;

/** One kind to choose: a pill with its icon; the chosen one has a check mark too (never colour alone). */
function KindChoice({ name, kind, label, checked, onChange }: { name: string; kind: ItemKind; label: string; checked: boolean; onChange: () => void }) {
  const Icon = ITEM_KIND_COPY[kind].icon;
  return (
    <label
      className={cn(
        "relative inline-flex h-9 cursor-pointer items-center gap-1.5 rounded-full border px-3 text-[13.5px] font-medium transition-colors",
        "has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-accent",
        checked ? "border-accent bg-accent-soft text-accent shadow-[inset_0_0_0_1px_var(--color-accent)]" : "border-line-strong/80 bg-surface text-ink hover:border-line-strong hover:bg-surface-2",
      )}
    >
      {/* the radio covers the whole pill (its words and icon under it): the pill is the target, the label its name */}
      <input type="radio" name={name} value={kind} checked={checked} onChange={onChange} className="absolute inset-0 m-0 size-full cursor-pointer appearance-none rounded-full outline-none" />
      {checked ? <Check className="size-3.5 shrink-0" strokeWidth={3} aria-hidden /> : <Icon className="size-3.5 shrink-0" aria-hidden />}
      {label}
    </label>
  );
}

export interface AddDateDialogProps {
  open: boolean;
  onClose: () => void;
  /** The letter it is for (a letter's page): not asked for. Without one (Timeline) a letter can be chosen. */
  letter?: DateLetter | null;
}

export function AddDateDialog({ open, onClose, letter = null }: AddDateDialogProps) {
  const ids = useId();
  const fieldId = (k: keyof DateDraft) => `${ids}-${k}`;
  const create = useCreateItem();
  const remove = useDeleteItem();
  const phone = usePhoneCompanion();
  // every letter, kept private and unread ones too — asked for only once the dialog is open on Timeline
  const letters = useDocuments({}, { enabled: open && !letter });
  const [d, setD] = useState<DateDraft>(EMPTY);
  const [tried, setTried] = useState(false);
  // opened again: a fresh form (not the last date's words)
  const [wasOpen, setWasOpen] = useState(open);
  if (open !== wasOpen) {
    setWasOpen(open);
    if (open) {
      setD(EMPTY);
      setTried(false);
    }
  }
  const problems = dateProblems(d);
  const shown = tried ? problems : {};
  const set = (k: keyof DateDraft) => (e: { target: { value: string } }) => setD((prev) => ({ ...prev, [k]: e.target.value }));
  const chosen = letter ?? letters.data?.find((l) => l.id === d.docId) ?? null;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (create.isPending) return;
    setTried(true);
    const first = FIELDS.find((k) => problems[k]);
    if (first) {
      document.getElementById(fieldId(first))?.focus();
      return;
    }
    create.mutate(dateBody(d, chosen), {
      onSuccess: (item) => {
        toast.success("Date added", {
          description: `${item.title} — ${formatDate(d.date, { style: "short" })}`,
          // undone by deleting it, which a paired phone leaves to the computer
          undo: phone ? undefined : () => remove.mutate(item.id),
        });
        onClose();
      },
    });
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Add a date"
      description={
        letter
          ? `For “${letterName(letter)}”. A date you add stays as you set it.`
          : "A reminder, a payment or an appointment of your own. It shows on Today and here like the dates Ordnung reads."
      }
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" form={`${ids}-form`} variant="primary" icon={CalendarPlus} loading={create.isPending}>
            Add date
          </Button>
        </>
      }
    >
      <form id={`${ids}-form`} onSubmit={submit} noValidate aria-label="Add a date" className="space-y-4">
        <Field id={fieldId("title")} label="What is it?" error={shown.title}>
          <Input value={d.title} onChange={set("title")} maxLength={TITLE_MAX} placeholder="e.g. Renew the residence permit" autoComplete="off" required autoFocus />
        </Field>
        <Field id={fieldId("date")} label="When?" error={shown.date}>
          <Input type="date" value={d.date} onChange={set("date")} className="w-44" required />
        </Field>
        {/* min-w-0: a fieldset is as wide as its widest row by default */}
        <fieldset className="min-w-0">
          <legend className="mb-1.5 text-sm font-medium text-ink">Kind</legend>
          <div className="flex flex-wrap gap-2">
            {ADD_KINDS.map((k) => (
              <KindChoice key={k.kind} name={`${ids}-kind`} kind={k.kind} label={k.label} checked={d.kind === k.kind} onChange={() => setD((prev) => ({ ...prev, kind: k.kind }))} />
            ))}
          </div>
        </fieldset>
        <Field id={fieldId("amount")} label="Amount" optional error={shown.amount} hint={moneyReadBack(d.amount)} className="sm:max-w-56">
          <MoneyInput value={d.amount} onChange={set("amount")} />
        </Field>
        {letter ? null : (
          <Field id={fieldId("docId")} label="Letter" optional hint="The date is listed with that letter too.">
            <Select value={d.docId} onChange={set("docId")}>
              <option value="">No letter</option>
              {(letters.data ?? []).map((l) => (
                <option key={l.id} value={l.id}>
                  {letterName(l)}
                </option>
              ))}
            </Select>
          </Field>
        )}
      </form>
    </Dialog>
  );
}

/**
 * The "Add a date" button and its dialog.
 *
 * @example <AddDateButton letter={doc} variant="link" size="sm" />
 */
export function AddDateButton({ letter, variant, size, className }: { letter?: DateLetter | null } & Pick<ButtonProps, "variant" | "size" | "className">) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button variant={variant} size={size} icon={Plus} className={className} onClick={() => setOpen(true)}>
        Add a date
      </Button>
      <AddDateDialog open={open} onClose={() => setOpen(false)} letter={letter} />
    </>
  );
}
