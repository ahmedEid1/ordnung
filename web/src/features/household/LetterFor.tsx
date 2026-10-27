/**
 * Who a letter is for, on its page (ADR 0023): in the verdict card's header, after "Addressed to …".
 *
 * - Filed for someone of the household: "For Alex Rivera" and *Change*. A letter of the person's own, or one not
 *   answered with no one suggested, while the household has people: "For you" and *Change*.
 * - Not answered, and its addressee names exactly one person of the household: the question *Is this letter for Alex
 *   Rivera?* under the header's line — *Yes*, *No, it's mine*, and with two people or more *Someone else…*.
 * - *Change* (and *Someone else…*) open *Who is this letter for?*: You, then each person; one press files and closes.
 * - Its addressee names one person no one of the household could be: *Add Alex Rivera to your household* (computer
 *   only), a small form with the name, whether they sign, and the visible, ticked *Also file this letter for …*.
 *
 * Ordnung only asks: nothing is filed without a press (the API suggests; `PATCH /api/household` files). Every toast's
 * Undo puts back exactly the answer before, "not answered" included. Who the letter is for comes from the household
 * (`GET /api/household`, refreshed in every window when it changes), the letter's page (`household`) until it has
 * loaded. A paired phone answers and changes who a letter is for, never the household's list.
 */
import { useId, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router";
import { useQueryClient } from "@tanstack/react-query";
import { Check, Pencil, UserPlus } from "lucide-react";
import { useFileLetters, useHousehold, useProfile } from "@/api/hooks";
import type { DocumentDetail, Household, HouseholdMember } from "@/api/types";
import { Button } from "@/components/ui/Button";
import { Checkbox, Field, Input } from "@/components/ui/Field";
import { Popover } from "@/components/ui/Popover";
import { toast } from "@/components/ui/Toast";
import { usePhoneCompanion } from "@/features/phone/client";
import { focusWhenReady } from "@/features/today/focus";
import { cn } from "@/lib/utils";
import { answerOf, memberById, MINE } from "./logic";
import { MANAGE_HOUSEHOLD_HREF, MAX_PEOPLE, membersOf, nameProblem, oneLine, refusal, useChangeHousehold } from "./save";

const SIGNS_HINT = "Untick for a child: a reply to their letter then goes out in your name.";
const CHOICES_LABEL = "Who is this letter for?";

/** One choice of *Who is this letter for?*: pressed when it is the letter's answer now. */
function Choice({ pressed, onClick, children }: { pressed: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      onClick={onClick}
      className={cn(
        "flex min-h-10 w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm text-ink outline-none transition-colors",
        "hover:bg-surface-3/70 focus-visible:ring-2 focus-visible:ring-accent",
        pressed && "bg-accent-soft font-medium",
      )}
    >
      <span className="min-w-0 flex-1 [overflow-wrap:anywhere]">{children}</span>
      {pressed ? <Check className="size-4 shrink-0 text-accent" aria-hidden /> : null}
    </button>
  );
}

/** *Who is this letter for?*: You, then each person in the list's order; one press files and closes. */
function Choices({
  current,
  people,
  ownName,
  manage,
  onChoose,
}: {
  current: string | null;
  people: readonly HouseholdMember[];
  ownName: string;
  /** Link to Settings (computer only). */
  manage: boolean;
  onChoose: (answer: string, name: string | null) => void;
}) {
  return (
    <div className="space-y-3">
      <div>
        {/* a phone sheet shows the label as its title */}
        <h2 className="text-md font-semibold text-ink in-sheet:hidden">{CHOICES_LABEL}</h2>
        <p className="mt-1 text-sm leading-5 text-muted in-sheet:mt-0">Its dates, reminders and numbers stay in your Ordnung either way.</p>
      </div>
      <ul className="space-y-1">
        <li>
          <Choice pressed={current === MINE} onClick={() => onChoose(MINE, null)}>
            You{ownName ? <span className="font-normal text-muted"> {ownName}</span> : null}
          </Choice>
        </li>
        {people.map((person) => (
          <li key={person.id}>
            <Choice pressed={current === person.id} onClick={() => onChoose(person.id, person.name)}>
              {person.name}
            </Choice>
          </li>
        ))}
      </ul>
      {manage ? (
        <Link to={MANAGE_HOUSEHOLD_HREF} className="inline-flex min-h-6 items-center text-sm font-medium text-accent hover:underline">
          Manage your household
        </Link>
      ) : null}
    </div>
  );
}

/** *Add … to your household*'s form: the name as read (editable), whether they sign, and *Also file this letter for …*. */
function AddForm({
  addressee,
  household,
  docId,
  close,
  onAdded,
}: {
  addressee: string;
  household: Household | undefined;
  docId: string;
  close: () => void;
  onAdded: (added: HouseholdMember, filed: boolean, before: Household, after: Household) => void;
}) {
  const qc = useQueryClient();
  const change = useChangeHousehold();
  const [name, setName] = useState(addressee);
  const [signs, setSigns] = useState(true);
  const [alsoFile, setAlsoFile] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const named = oneLine(name) || addressee;

  const add = () => {
    const problem = nameProblem(name);
    if (problem || !household) {
      setError(problem);
      inputRef.current?.focus();
      return;
    }
    change.mutateAsync({ base: household.version, members: [...membersOf(household), { id: null, name: oneLine(name), signs }], also_file: alsoFile ? [docId] : [] }).then(
      (after) => {
        const added = after.members.find((m) => !household.members.some((before) => before.id === m.id));
        close();
        if (added) onAdded(added, alsoFile, household, after);
      },
      (err: unknown) => {
        const reason = refusal(err, qc);
        if (!reason) return;
        setError(reason);
        inputRef.current?.focus();
      },
    );
  };
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        add();
      }}
      noValidate
      className="space-y-3"
    >
      <h2 className="text-md font-semibold text-ink in-sheet:hidden">Add to your household</h2>
      <Field label="Name" error={error ?? undefined}>
        <Input
          ref={inputRef}
          value={name}
          onChange={(e) => {
            setName(e.target.value);
            setError(null);
          }}
          autoComplete="off"
          spellCheck={false}
        />
      </Field>
      <Checkbox checked={signs} onChange={(e) => setSigns(e.target.checked)} label="Signs their own letters" description={SIGNS_HINT} />
      <Checkbox checked={alsoFile} onChange={(e) => setAlsoFile(e.target.checked)} label={`Also file this letter for ${named}`} />
      <div className="flex flex-wrap justify-end gap-2">
        <Button size="sm" onClick={close}>
          Cancel
        </Button>
        <Button size="sm" type="submit" variant="primary" loading={change.isPending} disabled={!household}>
          Add
        </Button>
      </div>
    </form>
  );
}

/** The household, once an answer with its lists has loaded (anything else counts as not loaded yet). */
function complete(h: Household | undefined): Household | undefined {
  return h && Array.isArray(h.members) && Array.isArray(h.mine) && h.filed && h.suggested ? h : undefined;
}

export interface LetterForParts {
  /** For the header's line, after "Addressed to …": "For Alex Rivera" / "For you" with *Change*, and *Add … to your household*. */
  line: ReactNode;
  /** Under the header's line: *Is this letter for Alex Rivera?* */
  question: ReactNode;
}

/**
 * Who `detail`'s letter is for, as the parts its page shows. `editable`: the letter may be answered here — not while
 * it is being read, in the trash, a proof file, or a possible scam (where the kind's *Change* isn't offered either).
 */
export function useLetterFor(detail: DocumentDetail, editable: boolean): LetterForParts {
  const doc = detail.document;
  const phone = usePhoneCompanion();
  const h = complete(useHousehold().data);
  const ownName = useProfile().data?.name?.trim() ?? "";
  const file = useFileLetters();
  const change = useChangeHousehold();
  const qc = useQueryClient();
  const changeRef = useRef<HTMLButtonElement>(null);
  const questionRef = useRef<HTMLDivElement>(null);
  const questionId = useId();

  // the household when it has loaded (live in every window), else the letter's page
  const known = detail.household;
  const filed: HouseholdMember | null = h ? memberById(h, h.filed[doc.id]) : known.filed_for;
  const mine = h ? h.mine.includes(doc.id) : known.mine;
  const suggested: HouseholdMember | null = filed || mine ? null : h ? memberById(h, h.suggested[doc.id]) : known.suggested;
  const people = h?.members ?? [];
  const current = filed?.id ?? (mine ? MINE : null);
  const add = known.add && !phone && editable && !filed && !mine && !suggested && people.length < MAX_PEOPLE ? known.add : null;

  /** File the letter (a person's id, or {@link MINE}); the toast's Undo puts back the answer it had. */
  const answer = (next: string, name: string | null) => {
    const before = h ? answerOf(h, doc.id) : current;
    if (next === before) return;
    file.mutateAsync({ letters: { [doc.id]: next } }).then(
      () => {
        // the pressed button is gone with the question: the keyboard goes on from Change
        focusWhenReady(() => changeRef.current);
        toast({
          title: next === MINE ? "Filed as yours" : `Filed for ${name ?? ""}`,
          undo: () => file.mutateAsync({ letters: { [doc.id]: before } }).then(() => undefined),
        });
      },
      () => undefined, // the mutation's error toast says what went wrong
    );
  };
  const choices = (close: () => void) => (
    <Choices
      current={current}
      people={people}
      ownName={ownName}
      manage={!phone}
      onChoose={(next, name) => {
        close();
        answer(next, name);
      }}
    />
  );
  const added = (person: HouseholdMember, filedToo: boolean, before: Household, after: Household) => {
    // filed: Change takes the offer's place; not filed: the letter now asks
    focusWhenReady(() => (filedToo ? changeRef.current : (questionRef.current?.querySelector("button") ?? null)));
    toast({
      title: `Added ${person.name} to your household`,
      description: filedToo ? `This letter is filed for ${person.name}.` : "Ordnung asks before it files a letter for them.",
      undo: () =>
        change.mutateAsync({ base: after.version, members: membersOf(before), also_file: [] }).then(
          () => undefined,
          (err: unknown) => void refusal(err, qc),
        ),
    });
  };

  const changeButton = editable ? (
    <Popover label={CHOICES_LABEL} placement="bottom-start" className="w-[20rem] p-4" content={choices}>
      <Button ref={changeRef} size="sm" variant="ghost" icon={Pencil} aria-label="Change who this letter is for" className="h-7 px-2 text-xs">
        Change
      </Button>
    </Popover>
  ) : null;
  const forLine = filed ? `For ${filed.name}` : !suggested && people.length ? "For you" : null;
  const line = (
    <>
      {forLine ? (
        <span className="inline-flex min-w-0 max-w-full items-center gap-1">
          <span className="min-w-0 font-medium text-ink/85 [overflow-wrap:anywhere]">{forLine}</span>
          {changeButton}
        </span>
      ) : null}
      {add ? (
        <Popover
          label="Add to your household"
          placement="bottom-start"
          className="w-[22rem] p-4"
          content={(close) => <AddForm addressee={add} household={h} docId={doc.id} close={close} onAdded={added} />}
        >
          <Button variant="link" size="sm" icon={UserPlus} className="max-w-full whitespace-normal text-left text-[13px]">
            <span className="min-w-0 whitespace-normal [overflow-wrap:anywhere]">Add {add} to your household</span>
          </Button>
        </Popover>
      ) : null}
    </>
  );
  const question =
    suggested && editable ? (
      <div
        ref={questionRef}
        role="group"
        aria-labelledby={questionId}
        className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-lg bg-surface-2/60 px-3 py-2.5"
      >
        <p id={questionId} className="min-w-0 text-[14px] font-medium leading-snug text-ink [overflow-wrap:anywhere]">
          Is this letter for {suggested.name}?
        </p>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="primary" onClick={() => answer(suggested.id, suggested.name)} disabled={file.isPending}>
            Yes
          </Button>
          <Button size="sm" onClick={() => answer(MINE, null)} disabled={file.isPending}>
            No, it's mine
          </Button>
          {people.length >= 2 ? (
            <Popover label={CHOICES_LABEL} placement="bottom-start" className="w-[20rem] p-4" content={choices}>
              <Button size="sm" variant="ghost" disabled={file.isPending}>
                Someone else…
              </Button>
            </Popover>
          ) : null}
        </div>
      </div>
    ) : null;
  return { line, question };
}
