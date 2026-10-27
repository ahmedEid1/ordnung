/**
 * *File these N* (the Inbox's view of one person in the household, ADR 0023): the letters whose addressee names
 * them and that aren't filed yet — as the list is narrowed now (search, kind, year, tab) — in a card above the
 * list, with one button that files exactly the letters it lists. Ordnung only suggests: nothing is filed until
 * the press. The toast says how many were filed, and its Undo puts each letter back as it was (not answered).
 *
 * The button keeps focus while it files (`AnswerButton`); when the card is gone, `onFiled` says where focus goes
 * (the letters list), and after an Undo it comes back to the button. A paired phone files too.
 */
import { Link } from "react-router";
import { User, UserCheck } from "lucide-react";
import type { Household, HouseholdPerson, ListedLetter, Party } from "@/api/types";
import { useFileLetters } from "@/api/hooks";
import { protectRefs } from "@/lib/glue";
import { plural } from "@/lib/utils";
import { DateText } from "@/components/ui/DateText";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { toast } from "@/components/ui/Toast";
import { AnswerButton } from "@/features/inbox/AnswerButton";
import { inboxDateInfo } from "@/features/inbox/filters";
import { Thumb } from "@/features/inbox/LettersList";
import { focusWhenReady } from "@/features/today/focus";
import { fileTheseLabel, undoLetters } from "./logic";

/** The card's button: after an Undo, focus comes back to it. */
export const FILE_THESE_BUTTON_ID = "file-these-button";

export function FileThese({
  member,
  letters,
  household,
  parties,
  onFiled,
}: {
  /** The person the letters are addressed to. */
  member: HouseholdPerson;
  /** Their letters not filed yet, as the list is narrowed now: exactly what the button files. */
  letters: readonly ListedLetter[];
  /** The household now: what an Undo sends back. */
  household: Household | undefined;
  parties: ReadonlyMap<string, Party>;
  /** The letters are filed (the card goes): move focus on. */
  onFiled?: () => void;
}) {
  const file = useFileLetters();
  if (!letters.length) return null;
  const n = letters.length;
  const title = `Addressed to ${member.name}, not filed yet`;

  const fileThem = () => {
    const ids = letters.map((d) => d.id);
    // each letter's answer before the press (not answered): what Undo sends back
    const before = undoLetters(household, ids);
    file
      .mutateAsync({ letters: Object.fromEntries(ids.map((id) => [id, member.id])) })
      .then(() => {
        toast.success(`Filed ${plural(n, "letter")} for ${member.name}`, {
          undo: () =>
            file
              .mutateAsync({ letters: before })
              .then(() => focusWhenReady(() => document.getElementById(FILE_THESE_BUTTON_ID)))
              .catch(() => undefined),
        });
        onFiled?.();
      })
      .catch(() => undefined); // the request's own error toast says what went wrong
  };

  return (
    <section aria-labelledby="file-these-title" className="mb-8">
      <SectionHeader
        id="file-these-title"
        icon={User}
        title={
          <>
            <span aria-hidden>
              {title}
              <span className="font-medium tabular-nums">{` · ${n}`}</span>
            </span>
            <span className="sr-only">{`${title}, ${plural(n, "letter")}`}</span>
          </>
        }
        description={`Ordnung read ${member.name}'s name on these letters. They count as yours until you file them.`}
      />
      <div className="card overflow-hidden">
        <ul className="divide-y divide-line" aria-label={`Letters addressed to ${member.name}`}>
          {letters.map((d) => (
            <AddressedLetter key={d.id} doc={d} party={d.party_id ? (parties.get(d.party_id) ?? null) : null} />
          ))}
        </ul>
        <div className="flex justify-end border-t border-line bg-surface-2/40 px-4 py-3 sm:px-5">
          <AnswerButton
            id={FILE_THESE_BUTTON_ID}
            size="sm"
            variant="primary"
            icon={UserCheck}
            onClick={fileThem}
            busy={file.isPending}
            className="max-w-full max-sm:w-full"
          >
            {fileTheseLabel(n, member.name)}
          </AnswerButton>
        </div>
      </div>
    </section>
  );
}

/** A letter of the card: its page, title, sender and the day it arrived. */
function AddressedLetter({ doc, party }: { doc: ListedLetter; party: Party | null }) {
  const { date, verb } = inboxDateInfo(doc);
  const title = doc.title ?? doc.filename;
  return (
    <li className="group relative flex items-start gap-3.5 px-4 py-3.5 transition-colors hover:bg-surface-2/50 focus-within:bg-surface-2/50 sm:px-5">
      <Thumb doc={doc} />
      <div className="min-w-0 flex-1">
        <Link
          to={`/documents/${doc.id}`}
          title={title}
          className="line-clamp-2 break-words text-[14.5px] font-medium leading-snug text-ink outline-none [overflow-wrap:anywhere] after:absolute after:inset-0 after:content-[''] focus-visible:after:ring-2 focus-visible:after:ring-inset focus-visible:after:ring-accent"
        >
          {protectRefs(title)}
        </Link>
        <p className="mt-1 text-sm leading-5 text-muted [overflow-wrap:anywhere]">
          {party ? `${party.name} · ` : null}
          <span className="whitespace-nowrap">
            <span className="sr-only">{verb} </span>
            <DateText date={date} style="day" />
          </span>
        </p>
      </div>
    </li>
  );
}
