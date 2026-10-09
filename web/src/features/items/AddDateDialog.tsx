/**
 * "Add a date": a date of the person's own — a reminder, a deadline, a payment, an appointment … — on Timeline,
 * or in a letter's "To-dos & dates", where a letter kept private or one Claude couldn't read has none of its own
 * (feature audit G1: Settings and the wizard promised "add your own dates" with nowhere to do it). It is posted as
 * a to-do added by hand (`POST /api/items`): reading the letter again never changes it, and it is on Today, the
 * Timeline, the calendar file and the reminders like the dates Ordnung reads ("Your own reminders" for a reminder).
 *
 * It can repeat (audit item 26): every month on its day or on a working day, every 3 or 6 months, every year. A
 * repeating date is one entry at its next date; the server dates it by its rule and moves it on when it is marked
 * done. "Edit your date" (`EditDateDialog`, the same form) changes one later — what it says, how it repeats, which
 * dates move — or removes it (`status: dismissed`, with Undo).
 */
import { useId, useState, type FormEvent, type RefObject } from "react";
import { CalendarPlus, CalendarX2, Check, Plus } from "lucide-react";
import type { Document, Item, ItemCreate, ItemKind, ItemPatch } from "@/api/types";
import { useCreateItem, useDeleteItem, useDocuments, useUpdateItem } from "@/api/hooks";
import { Button, type ButtonProps } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Field, Input, Select } from "@/components/ui/Field";
import { MoneyInput, moneyReadBack } from "@/components/ui/MoneyInput";
import { toast } from "@/components/ui/Toast";
import { ordinal } from "@/features/contracts/model";
import { usePhoneCompanion } from "@/features/phone/client";
import { ITEM_KIND_COPY } from "@/lib/copy";
import { formatDate } from "@/lib/format";
import { parseMoney } from "@/lib/money";
import { cn } from "@/lib/utils";
import { DEFAULT_WORKING_DAY, WORKING_DAYS, repeatChoiceLabel, repeatChoiceOf, repeatLabel, repeatOptions, repeatRule, steps, type RepeatChoice } from "./repeat";

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
  /** How it repeats ("Repeats"). */
  repeat: RepeatChoice;
  /** With "Every month on a working day": which one (-1: the last). */
  workingDay: number;
  /** Editing a date that repeats on its day, given a new date: only this one moves, or every one after it too. */
  moves: "this" | "after";
}

const EMPTY: DateDraft = { title: "", date: "", kind: "reminder", amount: "", docId: "", repeat: "never", workingDay: DEFAULT_WORKING_DAY, moves: "this" };
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

const cleanTitle = (title: string) => title.replace(/\s+/g, " ").trim();
const amountOf = (d: DateDraft) => (d.amount.trim() ? parseMoney(d.amount) : null);

/**
 * The to-do the API is sent: the person's words, and the letter's sender, thread and area when it is for one; how it
 * repeats only when it repeats.
 */
export function dateBody(d: DateDraft, letter: DateLetter | null): ItemCreate {
  const amount = amountOf(d);
  const recurrence = repeatRule(d.repeat, d.workingDay);
  return {
    kind: d.kind,
    title: cleanTitle(d.title),
    due_date: d.date,
    amount,
    currency: amount !== null ? "EUR" : null,
    // a payment added by hand is one you make
    direction: d.kind === "payment" ? "out" : null,
    doc_id: letter?.id ?? null,
    party_id: letter?.party_id ?? null,
    case_id: letter?.case_id ?? null,
    area: letter?.area ?? "other",
    ...(recurrence ? { recurrence } : {}),
  };
}

/** Where a repeating date's schedule starts — its day of the month ("on the 14th"), not a shorter month's. */
const startOf = (item: Item): string | null => item.date_spec?.date ?? item.due_date ?? null;
/** An amount as the field shows it ("1500,50"), which it reads back as it was. */
const amountText = (amount: number | null) => (amount == null ? "" : amount.toFixed(2).replace(".", ","));

/** The form an edit starts from: the date as it is. */
export function draftOf(item: Item): DateDraft {
  const { choice, workingDay } = repeatChoiceOf(item.recurrence, startOf(item));
  return { title: item.title, date: item.due_date ?? "", kind: item.kind, amount: amountText(item.amount), docId: item.doc_id ?? "", repeat: choice, workingDay, moves: "this" };
}

/** Whether the draft repeats otherwise than the date does. */
function repeatChanged(d: DateDraft, item: Item): boolean {
  const was = repeatChoiceOf(item.recurrence, startOf(item));
  return d.repeat !== was.choice || (d.repeat === "working_day" && d.workingDay !== was.workingDay);
}

/**
 * Whether "Which dates move?" is asked: the date changed, it repeats on its day (a working day has no day to move: a
 * new date is only this one) and "Repeats" stayed as it was (a new rule starts at the date shown anyway).
 */
export function asksWhichMove(d: DateDraft, item: Item): boolean {
  if (!item.recurrence || steps(item.recurrence).workingDay !== null) return false;
  return d.date !== (item.due_date ?? "") && !repeatChanged(d, item);
}

/**
 * What "Save" sends (`PATCH /api/items/{id}`): only what changed. A new rule starts at the date shown (with it, when
 * that changed too) and "Doesn't repeat" stops it; a new date alone stands in for this one only, and sent with the
 * same rule ("This one and every one after") the schedule starts again there (`ordnung.recurrence`, points 2 and 7).
 */
export function patchFor(d: DateDraft, item: Item): ItemPatch {
  const patch: ItemPatch = {};
  const title = cleanTitle(d.title);
  if (title !== item.title) patch.title = title;
  const amount = amountOf(d);
  if (amount !== (item.amount ?? null)) patch.amount = amount;
  if (d.date !== (item.due_date ?? "")) patch.due_date = d.date;
  if (repeatChanged(d, item)) patch.recurrence = repeatRule(d.repeat, d.workingDay, item.recurrence);
  else if (d.moves === "after" && asksWhichMove(d, item)) patch.recurrence = item.recurrence;
  return patch;
}

/** The toast's line: "UStVA — Mon 5 Oct, repeats every month on the 3rd working day", from the server's answer. */
function savedLine(item: Item): string {
  const rule = repeatLabel(item.recurrence);
  if (!item.due_date) return item.title;
  return `${item.title} — ${formatDate(item.due_date, { style: "short" })}${rule ? `, repeats ${rule}` : ""}`;
}

/** How "Which working day?" counts, and the month the first one is in (the month of "When?"). */
function workingDayHint(date: string): string {
  const counted = "Counted from the 1st of each month: Monday to Saturday, without public holidays (rent: Monday to Friday).";
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) return `${counted} The first one is in the month of the day you choose, or in the next month once that one's has passed.`;
  return `${counted} The first one is in ${formatDate(date, { style: "month" })}, or in the next month once ${formatDate(date, { style: "month" }).split(" ")[0]}'s has passed.`;
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

/** One answer to "Which dates move?": the row is its label; a native radio, with the focus ring on the row. */
function MoveChoice({ name, checked, onChange, children }: { name: string; checked: boolean; onChange: () => void; children: string }) {
  return (
    <label
      className={cn(
        "flex cursor-pointer items-start gap-2.5 rounded-lg border px-3 py-2 text-[14px] leading-5 transition-colors",
        "has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-accent",
        checked ? "border-accent/60 bg-accent-soft/50 text-ink" : "border-line text-ink hover:border-line-strong",
      )}
    >
      {/* a 24 px target (WCAG 2.5.8) around the 16 px circle drawn under it */}
      <span className="relative -my-0.5 grid size-6 shrink-0 place-items-center">
        <input type="radio" name={name} checked={checked} onChange={onChange} className="peer absolute inset-0 m-0 size-6 cursor-pointer appearance-none rounded-full outline-none" />
        <span aria-hidden className="pointer-events-none size-4 rounded-full border border-control-border bg-surface transition-[border] peer-checked:border-[5px] peer-checked:border-accent" />
      </span>
      <span className="min-w-0">{children}</span>
    </label>
  );
}

export interface AddDateDialogProps {
  open: boolean;
  onClose: () => void;
  /** The letter it is for (a letter's page): not asked for. Without one (Timeline) a letter can be chosen. */
  letter?: DateLetter | null;
  /**
   * A date of the person's own to edit ("Edit your date"): the form starts from it; its kind and letter stay as they
   * are (the API's `ItemPatch` has neither). `letter` then only names its letter.
   */
  item?: Item | null;
  /** Where focus goes on close when the element that opened it is gone (a Timeline row that moved to another month). */
  returnFocus?: RefObject<HTMLElement | null>;
}

export function AddDateDialog({ open, onClose, letter = null, item = null, returnFocus }: AddDateDialogProps) {
  const ids = useId();
  const fieldId = (k: keyof DateDraft) => `${ids}-${k}`;
  const create = useCreateItem();
  const update = useUpdateItem();
  const remove = useDeleteItem();
  const phone = usePhoneCompanion();
  // every letter, kept private and unread ones too — asked for only once the dialog is open on Timeline
  const letters = useDocuments({}, { enabled: open && !letter && !item });
  const [d, setD] = useState<DateDraft>(() => (item ? draftOf(item) : EMPTY));
  const [tried, setTried] = useState(false);
  // opened again: a fresh form (not the last date's words), or the date to edit as it is now
  const [wasOpen, setWasOpen] = useState(open);
  if (open !== wasOpen) {
    setWasOpen(open);
    if (open) {
      setD(item ? draftOf(item) : EMPTY);
      setTried(false);
    }
  }
  const problems = dateProblems(d);
  const shown = tried ? problems : {};
  const set = (k: "title" | "date" | "amount" | "docId") => (e: { target: { value: string } }) => setD((prev) => ({ ...prev, [k]: e.target.value }));
  const chosen = letter ?? letters.data?.find((l) => l.id === d.docId) ?? null;
  const busy = create.isPending || update.isPending;
  const options = repeatOptions(d.date, item?.recurrence, item ? startOf(item) : null);
  const asksMove = item ? asksWhichMove(d, item) : false;

  const added = (created: Item) => {
    toast.success("Date added", {
      description: savedLine(created),
      // undone by deleting it, which a paired phone leaves to the computer
      undo: phone ? undefined : () => remove.mutate(created.id),
    });
    onClose();
  };

  const save = (own: Item) => {
    const patch = patchFor(d, own);
    if (!Object.keys(patch).length) return onClose();
    update.mutate(
      { id: own.id, patch },
      {
        onSuccess: (saved) => {
          // no Undo: a deliberate step with Cancel, and the dialog changes it back
          toast.success("Date saved", { description: savedLine(saved) });
          onClose();
        },
      },
    );
  };

  // dismissed, not deleted: it ends the series, a paired phone may do it, and "Undo" sets it open again
  const removeIt = (own: Item) => {
    if (busy) return;
    update.mutate(
      { id: own.id, patch: { status: "dismissed" } },
      {
        onSuccess: () => {
          toast({
            title: "Removed from your dates",
            description: `“${own.title}” won't remind you any more.`,
            undo: () => update.mutate({ id: own.id, patch: { status: "open" } }),
          });
          onClose();
        },
      },
    );
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setTried(true);
    const first = FIELDS.find((k) => problems[k]);
    if (first) {
      document.getElementById(fieldId(first))?.focus();
      return;
    }
    if (item) save(item);
    else create.mutate(dateBody(d, chosen), { onSuccess: added });
  };

  const after =
    item && d.repeat === "current"
      ? `${repeatLabel(item.recurrence)} from ${formatDate(d.date, { style: "short" })}`
      : repeatChoiceLabel(d.repeat, d.date)
          .replace(/ \(or the month's last day\)$/, "")
          .replace(/^E/, "e");

  return (
    <Dialog
      open={open}
      onClose={onClose}
      returnFocus={returnFocus}
      title={item ? "Edit your date" : "Add a date"}
      description={
        item
          ? letter
            ? `For “${letterName(letter)}”.`
            : "A date you added yourself."
          : letter
            ? `For “${letterName(letter)}”. A date you add stays as you set it.`
            : "A reminder, a payment or an appointment of your own. It shows on Today and here like the dates Ordnung reads."
      }
      footer={
        <>
          {item ? (
            <Button variant="ghost" icon={CalendarX2} onClick={() => removeIt(item)} className="sm:mr-auto">
              Remove
            </Button>
          ) : null}
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" form={`${ids}-form`} variant="primary" icon={item ? Check : CalendarPlus} loading={busy}>
            {item ? "Save" : "Add date"}
          </Button>
        </>
      }
    >
      <form id={`${ids}-form`} onSubmit={submit} noValidate aria-label={item ? "Edit your date" : "Add a date"} className="space-y-4">
        <Field id={fieldId("title")} label="What is it?" error={shown.title}>
          <Input value={d.title} onChange={set("title")} maxLength={TITLE_MAX} placeholder="e.g. Renew the residence permit" autoComplete="off" required autoFocus />
        </Field>
        {/* the date of a repeating one is its next date: the ones after it follow the rule */}
        <Field id={fieldId("date")} label={item && d.repeat !== "never" ? "Next date" : "When?"} error={shown.date}>
          <Input type="date" value={d.date} onChange={set("date")} className="w-44" required />
        </Field>
        <Field id={fieldId("repeat")} label="Repeats" className="sm:max-w-sm">
          <Select value={d.repeat} onChange={(e) => setD((prev) => ({ ...prev, repeat: e.target.value as RepeatChoice }))}>
            {options.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </Select>
        </Field>
        {d.repeat === "working_day" ? (
          <Field id={fieldId("workingDay")} label="Which working day?" hint={workingDayHint(d.date)} className="sm:max-w-sm">
            <Select value={String(d.workingDay)} onChange={(e) => setD((prev) => ({ ...prev, workingDay: Number(e.target.value) }))} className="sm:max-w-40">
              {WORKING_DAYS.map((n) => (
                <option key={n} value={n}>
                  {n === -1 ? "Last" : ordinal(n)}
                </option>
              ))}
            </Select>
          </Field>
        ) : null}
        {asksMove ? (
          // min-w-0: a fieldset is as wide as its widest row by default
          <fieldset className="min-w-0">
            <legend className="mb-1.5 text-sm font-medium text-ink">Which dates move?</legend>
            <div className="space-y-2">
              <MoveChoice name={`${ids}-moves`} checked={d.moves === "this"} onChange={() => setD((prev) => ({ ...prev, moves: "this" }))}>
                {`Only this one (${formatDate(d.date, { style: "short" })})`}
              </MoveChoice>
              <MoveChoice name={`${ids}-moves`} checked={d.moves === "after"} onChange={() => setD((prev) => ({ ...prev, moves: "after" }))}>
                {`This one and every one after (${after})`}
              </MoveChoice>
            </div>
          </fieldset>
        ) : null}
        {item ? null : (
          <fieldset className="min-w-0">
            <legend className="mb-1.5 text-sm font-medium text-ink">Kind</legend>
            <div className="flex flex-wrap gap-2">
              {ADD_KINDS.map((k) => (
                <KindChoice key={k.kind} name={`${ids}-kind`} kind={k.kind} label={k.label} checked={d.kind === k.kind} onChange={() => setD((prev) => ({ ...prev, kind: k.kind }))} />
              ))}
            </div>
          </fieldset>
        )}
        <Field id={fieldId("amount")} label="Amount" optional error={shown.amount} hint={moneyReadBack(d.amount)} className="sm:max-w-56">
          <MoneyInput value={d.amount} onChange={set("amount")} />
        </Field>
        {letter || item ? null : (
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
 * "Edit your date": a date of the person's own, changed later (on a letter's page, its row's "Edit"; on Timeline, the
 * row of one with no letter).
 *
 * @example <EditDateDialog item={item} open={open} onClose={close} letter={doc} />
 */
export function EditDateDialog({ item, letter = null, ...rest }: Omit<AddDateDialogProps, "item" | "letter"> & { item: Item; letter?: Pick<Document, "title" | "filename"> | null }) {
  // only its name is shown: nothing is filed with the letter again
  const named = letter ? { id: item.doc_id ?? "", party_id: null, case_id: null, area: item.area, title: letter.title, filename: letter.filename } : null;
  return <AddDateDialog {...rest} item={item} letter={named} />;
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
