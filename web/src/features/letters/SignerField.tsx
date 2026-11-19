import { useEffect, useRef, useState } from "react";
import type { HouseholdMember } from "@/api/types";
import { Button } from "@/components/ui/Button";
import { Field, Input } from "@/components/ui/Field";
import {
  namesHousehold,
  sameName,
} from "./logic";

/**
 * The From field's hint for a letter filed for someone of the household: who it is filed for and, when the field holds
 * another name than the person's own (`otherName`), that it goes out in that name.
 */
export function filedLine(name: string, signs: boolean, otherName: string | null): string {
  if (otherName) return `This letter is filed for ${name}. It goes out in the name of ${otherName}, who signs it.`;
  return signs ? `This letter is filed for ${name}.` : `This letter is filed for ${name}, who doesn't sign letters, so it goes out in your name.`;
}

/**
 * The From field of a letter answering one addressed to someone else (`DocumentDetail.addressed_to`). It starts with
 * the person's own name: the addressee's is one press away, and "Use my name" goes back — offered, never set (a
 * child's letter answered in the child's name would be the worse mistake). A household ("Familie Rivera") has no
 * one-press name: the person is among the people named and signs as themselves. A press keeps the keyboard in place
 * (focus moves to the button that took the pressed one's place) and a status line says whose name it now is. Code
 * never adds the name to the draft request (the related letter's title and summary, sent as read, may still name the
 * addressee).
 *
 * A letter the person filed for someone of their household (`member`, ADR 0023) says so instead, still starting with
 * the person's own name: someone who signs their own letters is offered by the name typed in Settings (never as read
 * from the letter); someone who doesn't (a child) is offered not at all — the letter goes out in the person's name,
 * unless they type another. Without `member` the field is exactly the one above.
 */
export function SignerField({
  addressee,
  member,
  ownName,
  value,
  onChange,
  othersName,
}: {
  /** Who the answered letter was addressed to, when that isn't the person (`addressed_to`). */
  addressee: string | null;
  /** The person of the household the answered letter is filed for. */
  member?: Pick<HouseholdMember, "name" | "signs"> | null;
  ownName: string;
  value: string;
  onChange: (name: string) => void;
  /** The field holds a name that isn't the person's own. */
  othersName: boolean;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const theirsRef = useRef<HTMLButtonElement>(null);
  const mineRef = useRef<HTMLButtonElement>(null);
  // after a press, the button that took the pressed one's place (else the field) gets the focus
  const focusNext = useRef<"theirs" | "mine" | null>(null);
  const [said, setSaid] = useState("");
  useEffect(() => {
    const next = focusNext.current;
    if (!next) return;
    focusNext.current = null;
    ((next === "theirs" ? theirsRef.current : mineRef.current) ?? inputRef.current)?.focus();
  }, [value]);
  const press = (name: string, next: "theirs" | "mine", line: string) => {
    focusNext.current = next;
    setSaid(line);
    onChange(name);
  };
  // the one-press name: a member's who signs as typed in Settings; else the addressee's, unless it names a household
  const theirs = member ? (member.signs ? member.name : null) : addressee && !namesHousehold(addressee) ? addressee : null;
  return (
    <div className="mt-4" data-signer>
      <Field
        label="From"
        hint={
          <span className="[overflow-wrap:anywhere]">
            {member ? (
              filedLine(member.name, member.signs, othersName ? value.trim() : null)
            ) : (
              <>
                This letter was addressed to {addressee}.{othersName ? <> It goes out in the name of {value.trim()}, who signs it.</> : null}
              </>
            )}
          </span>
        }
      >
        <Input ref={inputRef} value={value} onChange={(e) => onChange(e.target.value)} maxLength={120} autoComplete="off" spellCheck={false} />
      </Field>
      <div className="mt-2 flex flex-wrap gap-2">
        {theirs && !sameName(value, theirs) ? (
          // an element, not a string: the Button truncates a string label, and a long name wraps at 320 px instead
          <Button
            ref={theirsRef}
            size="sm"
            className="h-auto min-h-8 max-w-full whitespace-normal py-1 text-left"
            onClick={() => press(theirs, "mine", `The letter now goes out in the name of ${theirs}.`)}
          >
            <span className="min-w-0 whitespace-normal [overflow-wrap:anywhere]">Reply in {theirs}'s name</span>
          </Button>
        ) : null}
        {ownName && !sameName(value, ownName) ? (
          <Button ref={mineRef} size="sm" variant="ghost" onClick={() => press(ownName, "theirs", "The letter now goes out in your name.")}>
            Use my name
          </Button>
        ) : null}
      </div>
      <p role="status" className="sr-only">
        {said}
      </p>
    </div>
  );
}
