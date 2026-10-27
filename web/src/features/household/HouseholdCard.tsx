/**
 * Settings → Profile & address → "Your household" (computer only; ADR 0023): the people whose letters come to the
 * person too. Add one at a time, edit a name or whether they sign their own letters, remove someone — asked first
 * when letters are filed for them, which then count as the person's again (nothing is deleted), with Undo that puts
 * the same person back so their letters are filed again. The API checks every name and says why it can't be one
 * person of the household; the reason shows under the field. A name typed but not added yet counts as unsaved (the
 * page's "Save and go"). Claude never sees this list.
 */
import { useEffect, useRef, useState, type FormEvent, type Ref, type RefObject } from "react";
import { Link } from "react-router";
import { useQueryClient } from "@tanstack/react-query";
import { useHousehold } from "@/api/hooks";
import type { Household, HouseholdPerson, MemberIn } from "@/api/types";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Checkbox, Field, Input } from "@/components/ui/Field";
import { SkeletonText } from "@/components/ui/Skeleton";
import { toast } from "@/components/ui/Toast";
import { useReportDirty } from "@/features/settings/dirty";
import { SettingsCard } from "@/features/settings/SettingsCard";
import { countAsYours, lettersLabel, membersOf, nameProblem, oneLine, refusal, useChangeHousehold } from "./save";

/** The card's title id: `/settings?section=profile#set-household` opens Settings at it. */
export const HOUSEHOLD_CARD_ID = "set-household";
const SIGNS_HINT = "Untick for a child: a reply to their letter then goes out in your name.";

/** The two fields of a person, as the add form and an edit show them. */
function PersonFields({
  name,
  signs,
  error,
  onName,
  onSigns,
  inputRef,
}: {
  name: string;
  signs: boolean;
  error: string | null;
  onName: (name: string) => void;
  onSigns: (signs: boolean) => void;
  inputRef?: Ref<HTMLInputElement>;
}) {
  return (
    <>
      <Field label="Name" error={error ?? undefined} className="sm:max-w-sm">
        <Input ref={inputRef} value={name} onChange={(e) => onName(e.target.value)} autoComplete="off" spellCheck={false} />
      </Field>
      <Checkbox checked={signs} onChange={(e) => onSigns(e.target.checked)} label="Signs their own letters" description={SIGNS_HINT} />
    </>
  );
}

/** Save a new list of people; resolves to the household after it, or `null` when refused (`onRefused` gets a name's reason). */
function useSaveList() {
  const qc = useQueryClient();
  const change = useChangeHousehold();
  const save = (h: Household, members: MemberIn[], onRefused?: (reason: string) => void): Promise<Household | null> =>
    change.mutateAsync({ base: h.version, members, also_file: [] }).catch((err: unknown) => {
      const reason = refusal(err, qc);
      if (reason) onRefused?.(reason);
      return null;
    });
  return { save, busy: change.isPending };
}

/** The add form: one person at a time. */
function AddPerson({ household, inputRef }: { household: Household; inputRef: RefObject<HTMLInputElement | null> }) {
  const { save, busy } = useSaveList();
  const [name, setName] = useState("");
  const [signs, setSigns] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const add = async (): Promise<boolean> => {
    const problem = nameProblem(name);
    const refuse = (reason: string) => {
      setError(reason);
      inputRef.current?.focus();
    };
    if (problem) {
      refuse(problem);
      return false;
    }
    const after = await save(household, [...membersOf(household), { id: null, name: oneLine(name), signs }], refuse);
    if (!after) return false;
    const added = after.members.find((m) => !household.members.some((before) => before.id === m.id));
    toast.success(`Added ${added?.name ?? name.trim()}`);
    setName("");
    setSigns(true);
    setError(null);
    inputRef.current?.focus();
    return true;
  };
  // a name typed but not added yet is an unsaved change ("Save and go" adds it)
  useReportDirty(name.trim() !== "", add);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    void add();
  };
  return (
    <form onSubmit={submit} noValidate className="mt-5 flex flex-col gap-4 border-t border-line pt-5" aria-label="Add someone to your household">
      <PersonFields
        name={name}
        signs={signs}
        error={error}
        inputRef={inputRef}
        onName={(value) => {
          setName(value);
          setError(null);
        }}
        onSigns={setSigns}
      />
      <div>
        <Button type="submit" variant="primary" size="sm" loading={busy}>
          Add to household
        </Button>
      </div>
    </form>
  );
}

/** A person of the household: their name, whether they sign, their letters; Edit and Remove. */
function PersonRow({ person, household, onRemove }: { person: HouseholdPerson; household: Household; onRemove: (person: HouseholdPerson) => void }) {
  const { save, busy } = useSaveList();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(person.name);
  const [signs, setSigns] = useState(person.signs);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const editRef = useRef<HTMLButtonElement>(null);
  // after Save or Cancel, the keyboard goes back to the row's Edit button
  const backToEdit = useRef(false);
  useEffect(() => {
    if (!editing && backToEdit.current) {
      backToEdit.current = false;
      editRef.current?.focus();
    }
  }, [editing]);
  const changed = name !== person.name || signs !== person.signs;

  const start = () => {
    setName(person.name);
    setSigns(person.signs);
    setError(null);
    setEditing(true);
    requestAnimationFrame(() => inputRef.current?.focus());
  };
  const stop = () => {
    backToEdit.current = true;
    setEditing(false);
  };
  const saveEdit = async (): Promise<boolean> => {
    if (!changed) {
      stop();
      return true;
    }
    const refuse = (reason: string) => {
      setError(reason);
      inputRef.current?.focus();
    };
    const problem = nameProblem(name);
    if (problem) {
      refuse(problem);
      return false;
    }
    const members = membersOf(household).map((m) => (m.id === person.id ? { id: person.id, name: oneLine(name), signs } : m));
    if (!(await save(household, members, refuse))) return false;
    toast.success("Saved");
    stop();
    return true;
  };
  useReportDirty(editing && changed, saveEdit);

  if (editing) {
    return (
      <li className="py-4">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void saveEdit();
          }}
          noValidate
          className="flex flex-col gap-4"
          aria-label={`Edit ${person.name}`}
        >
          <PersonFields
            name={name}
            signs={signs}
            error={error}
            inputRef={inputRef}
            onName={(value) => {
              setName(value);
              setError(null);
            }}
            onSigns={setSigns}
          />
          <div className="flex flex-wrap gap-2">
            <Button type="submit" variant="primary" size="sm" loading={busy}>
              Save
            </Button>
            <Button size="sm" onClick={stop} disabled={busy}>
              Cancel
            </Button>
          </div>
        </form>
      </li>
    );
  }
  return (
    <li className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 py-3" data-person={person.id}>
      <div className="min-w-0 flex-1 basis-48">
        <p className="font-medium text-ink [overflow-wrap:anywhere]">{person.name}</p>
        <p className="mt-0.5 text-[13px] leading-5 text-muted">
          {person.signs ? "Signs their own letters" : "Doesn't sign letters"}
          {" · "}
          {person.letters ? (
            <Link to={`/inbox?for=${encodeURIComponent(person.id)}`} className="inline-flex min-h-6 items-center font-medium text-accent hover:underline">
              {lettersLabel(person.letters)}
            </Link>
          ) : (
            "No letters yet"
          )}
        </p>
      </div>
      <div className="flex shrink-0 gap-2">
        <Button ref={editRef} size="sm" aria-label={`Edit ${person.name}`} onClick={start}>
          Edit
        </Button>
        <Button size="sm" variant="ghost" aria-label={`Remove ${person.name}`} onClick={() => onRemove(person)}>
          Remove
        </Button>
      </div>
    </li>
  );
}

/** "Your household": the second card of Settings → Profile & address. */
export function HouseholdCard() {
  const household = useHousehold();
  const h = household.data;
  const { save } = useSaveList();
  const [asking, setAsking] = useState<HouseholdPerson | null>(null);
  const addRef = useRef<HTMLInputElement>(null);

  const remove = async (person: HouseholdPerson) => {
    if (!h) return;
    setAsking(null);
    const after = await save(
      h,
      membersOf(h).filter((m) => m.id !== person.id),
    );
    if (!after) return;
    // the row is gone: the keyboard goes on from the add form
    addRef.current?.focus();
    toast({
      title: `Removed ${person.name}`,
      description: person.letters ? countAsYours(person.letters) : undefined,
      // the same person, with the same id, where they were: their letters are filed for them again
      undo: () => save(after, membersOf(h)).then(() => undefined),
    });
  };

  return (
    <SettingsCard
      id={HOUSEHOLD_CARD_ID}
      title="Your household"
      description="The people whose letters come to you too — a partner, your children. Ordnung asks before it files a letter for one of them. Claude never sees this list."
    >
      {!h ? (
        household.isError ? (
          <div className="flex flex-wrap items-center gap-3 text-sm text-muted">
            <span>Couldn't load your household.</span>
            <Button size="sm" onClick={() => void household.refetch()} loading={household.isFetching}>
              Try again
            </Button>
          </div>
        ) : (
          <div aria-busy="true">
            <SkeletonText lines={3} />
          </div>
        )
      ) : (
        <>
          <div>
            {h.members.length ? (
              <ul aria-label="People in your household" className="-my-3 divide-y divide-line">
                {h.members.map((person) => (
                  <PersonRow key={person.id} person={person} household={h} onRemove={(p) => (p.letters ? setAsking(p) : void remove(p))} />
                ))}
              </ul>
            ) : (
              <p className="text-sm text-muted">No one yet.</p>
            )}
          </div>
          <AddPerson household={h} inputRef={addRef} />
        </>
      )}
      <Dialog
        open={asking !== null}
        onClose={() => setAsking(null)}
        size="sm"
        title={asking ? `Remove ${asking.name}?` : ""}
        description={asking ? `${countAsYours(asking.letters)} Nothing is deleted.` : undefined}
        footer={
          <>
            <Button onClick={() => setAsking(null)}>Cancel</Button>
            <Button variant="danger" onClick={() => asking && void remove(asking)}>
              Remove
            </Button>
          </>
        }
      />
    </SettingsCard>
  );
}
