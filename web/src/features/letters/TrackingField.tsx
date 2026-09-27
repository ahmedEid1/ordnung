import { useEffect, useRef, useState } from "react";
import { CircleCheck, Info } from "lucide-react";
import { Field, Input } from "@/components/ui/Field";
import { checkTracking, trackingComplete, TRACKING_EXAMPLE, TRACKING_MAX, type TrackingCheck } from "@/lib/tracking";

export interface TrackingFieldProps {
  value: string;
  onChange: (value: string) => void;
  /** The input's id (to move focus to it). */
  id?: string;
  label?: string;
  optional?: boolean;
  /** An empty field is a mistake too (the form exists to save a number). */
  required?: boolean;
  /** Say what's wrong now (the person tried to save), not only once the number is complete. */
  showError?: boolean;
  /** Focus the field when it appears (the person asked to edit the number). */
  autoFocus?: boolean;
  className?: string;
}

/** Whether a typed number can be saved (empty counts: the field is optional). */
export function trackingSavable(value: string): boolean {
  return checkTracking(value).state !== "invalid";
}

export const TRACKING_REQUIRED = "Type the tracking number from your posting receipt.";

function hintFor(check: TrackingCheck) {
  if (check.state === "valid" && check.checked) {
    return (
      <span className="flex items-start gap-1.5 text-ok-ink">
        <CircleCheck className="mt-0.5 size-4 shrink-0" aria-hidden />
        <span>
          Check digit correct: <span className="font-ident whitespace-nowrap">{check.display}</span>
          {check.note ? <span className="block text-muted">{check.note}</span> : null}
        </span>
      </span>
    );
  }
  if (check.state === "valid") {
    return (
      <span className="flex items-start gap-1.5">
        <Info className="mt-0.5 size-4 shrink-0" aria-hidden />
        <span>{check.note}</span>
      </span>
    );
  }
  return (
    <>
      As on your posting receipt (like <span className="font-ident whitespace-nowrap">{TRACKING_EXAMPLE}</span>), or the 20 characters next to the square code of an online stamp.
    </>
  );
}

/**
 * The Einschreiben's tracking number with the check the server makes, as the person types: a
 * correct check digit is confirmed, a mistake is named once the number is complete (13 characters, or
 * 20 for what may still become an online stamp's number), the field is left or the person tries to
 * save; an online stamp's and a twelve-digit number are accepted with a note that they can't be
 * checked. A mistake opens under the field: it is brought into view with the field (never left under a
 * dialog's footer). No placeholder: an example number in the empty field would look like a saved one.
 */
export function TrackingField({ value, onChange, id, label = "Tracking number", optional, required, showError, autoFocus, className }: TrackingFieldProps) {
  const [left, setLeft] = useState(false);
  const check = checkTracking(value);
  const complete = trackingComplete(value);
  const error = check.state === "invalid" && (left || complete || showError) ? check.message : required && showError && check.state === "empty" ? TRACKING_REQUIRED : undefined;
  const wrapper = useRef<HTMLDivElement>(null);
  const said = Boolean(error);
  useEffect(() => {
    // focusing the field scrolls only the field into view: the message under it comes too (while the
    // person is on the field — typing, or sent back to it — never when they just left it)
    const box = wrapper.current;
    if (said && box?.contains(document.activeElement)) box.scrollIntoView?.({ block: "nearest" });
  }, [said]);
  return (
    <div ref={wrapper} className={className}>
      <Field id={id} label={label} optional={optional} hint={hintFor(check)} error={error}>
        <Input
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onBlur={() => setLeft(true)}
          onFocus={() => setLeft(false)}
          maxLength={TRACKING_MAX}
          autoComplete="off"
          autoCapitalize="characters"
          spellCheck={false}
          inputMode="text"
          autoFocus={autoFocus}
          className="font-ident tracking-wide"
        />
      </Field>
    </div>
  );
}
