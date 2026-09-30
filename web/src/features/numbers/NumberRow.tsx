/**
 * One number: what it is, the value (hidden until "Show"), Copy, its check-digit test and the letter
 * it came from. Copy works while it is hidden; the confirmation is announced (aria-live).
 */
import { Fragment, useState } from "react";
import { Link } from "react-router";
import { Check, CircleCheck, Copy, Eye, EyeOff, TriangleAlert } from "lucide-react";
import type { MyNumber } from "@/api/types";
import { Button } from "@/components/ui/Button";
import { Tooltip } from "@/components/ui/Tooltip";
import { isGermanText } from "@/features/document/fact-text";
import { useClipboard } from "@/features/today/clipboard";
import { glueText } from "@/lib/format";
import { NBSP } from "@/lib/glue";
import { useFormatDate } from "@/lib/today";
import { cn } from "@/lib/utils";
import { hiddenLabel, maskValue } from "./mask";
import { LABEL_FIRST, numberTitle, printedLabel } from "./title";

/** " · " that never starts a line: the dot stays with the text before it. */
export function Sep() {
  return (
    <>
      <span aria-hidden>{`${NBSP}·`}</span>{" "}
    </>
  );
}

/**
 * A letter's own label as it wraps: after each "/" first ("Rentenversicherungsnummer/ ·
 * Sozialversicherungsnummer/ · Versicherungsnummer", never "…/Sozialvers · icherungsnummer…"), then —
 * marked German — by German hyphenation where the browser has it; mid-word only as the last resort.
 * Each part is its own inline block: hyphenation fills a line greedily, so plain text would split
 * "Versi- · cherungsnummer" to use the room after a slash; a block that fits moves to the next line
 * whole, and only a part longer than the line is hyphenated (or broken) inside itself. A space after
 * a slash ("Beitragsgruppe / Personengruppe") stays between the blocks: at a block's start it would vanish.
 * Display only: Copy and the buttons' names use the plain label.
 */
export function LabelText({ text, className }: { text: string; className?: string }) {
  const parts = text.split("/");
  const german = isGermanText(text);
  return (
    <p lang={german ? "de" : undefined} className={cn("[overflow-wrap:anywhere]", german && "hyphens-auto", className)}>
      {parts.length === 1
        ? text
        : parts.map((part, i) => {
            const space = i ? /^\s*/.exec(part)![0] : "";
            const words = part.slice(space.length);
            return (
              <Fragment key={i}>
                {i ? space || <wbr /> : null}
                <span className="inline-block max-w-full">{i < parts.length - 1 ? `${words}/` : words}</span>
              </Fragment>
            );
          })}
    </p>
  );
}

function CheckBadge({ number }: { number: MyNumber }) {
  if (number.check === "none") return null;
  const ok = number.check === "ok";
  return (
    <Tooltip content={number.check_note ?? (ok ? "Check digit OK" : "Does not check — compare with the letter")}>
      <button
        type="button"
        className={cn(
          "inline-flex min-h-6 max-w-full items-center gap-1 rounded-full px-2 py-0.5 text-left text-[12px] font-medium leading-4 outline-none focus-visible:ring-2 focus-visible:ring-accent",
          ok ? "bg-ok-soft text-ok-ink" : "bg-warn-soft text-warn-ink",
        )}
      >
        {ok ? <CircleCheck className="size-3.5 shrink-0" aria-hidden /> : <TriangleAlert className="size-3.5 shrink-0" aria-hidden />}
        {ok ? "Check digit OK" : "Does not check — compare with the letter"}
      </button>
    </Tooltip>
  );
}

export interface NumberRowProps {
  number: MyNumber;
  /**
   * Hidden until "Show" — by default the person's own identifiers (About you, identity documents,
   * customer and contract numbers), never a case's reference (an invoice number, a Kassenzeichen or
   * Aktenzeichen): the letter and the Pay panel print those in full, so hiding them protects nothing
   * and costs a click (the organisation's own public numbers need not be hidden either).
   */
  masked?: boolean;
  /** Say which organisation's letter it is from (About you lists numbers from many). */
  showParty?: boolean;
  /** Link to the letter it came from. */
  showLetter?: boolean;
  /** Only "From <letter>" (a card that names the organisation and its latest letter already). */
  compactLetter?: boolean;
  className?: string;
}

export function NumberRow({ number, masked = number.group !== "case", showParty = false, showLetter = true, compactLetter = false, className }: NumberRowProps) {
  const [shown, setShown] = useState(!masked);
  const { copy, copied } = useClipboard();
  const formatDate = useFormatDate();
  const title = numberTitle(number);
  const printed = printedLabel(number);
  const done = copied === number.key;
  const letter = number.letter;
  const valueId = `num-${number.key}`;

  return (
    <div className={cn("flex flex-wrap items-center gap-x-3 gap-y-2 py-3", className)}>
      <div className="min-w-0 flex-1 basis-[13rem]">
        {/* the title is the letter's label for the generic kinds, the plain-English name for the others */}
        {LABEL_FIRST.has(number.kind) ? (
          <LabelText text={title} className="text-[13px] font-medium leading-5 text-ink/80" />
        ) : (
          <p className="text-[13px] font-medium leading-5 text-ink/80 [overflow-wrap:anywhere]">{title}</p>
        )}
        {printed ? <LabelText text={printed} className="text-[12.5px] leading-5 text-muted" /> : null}
        <p id={valueId} className="mt-0.5 font-ident text-[17px] font-semibold leading-6 tabular-nums tracking-[0.01em] text-ink [overflow-wrap:anywhere]">
          {shown ? (
            number.display
          ) : (
            <>
              <span aria-hidden>{maskValue(number.display)}</span>
              <span className="sr-only">{hiddenLabel(number.display)}</span>
            </>
          )}
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-1">
        {masked ? (
          // the name says what a press does ("Show …" / "Hide …"): no aria-pressed as well, which would
          // announce the state twice with opposite meanings
          <Button
            variant="ghost"
            size="sm"
            icon={shown ? EyeOff : Eye}
            aria-label={`${shown ? "Hide" : "Show"} ${title}`}
            aria-controls={valueId}
            onClick={() => setShown((s) => !s)}
            className="text-accent"
          >
            {shown ? "Hide" : "Show"}
          </Button>
        ) : null}
        <Button
          variant="ghost"
          size="sm"
          icon={done ? Check : Copy}
          aria-label={done ? `${title} copied` : `Copy ${title}`}
          onClick={() => void copy(number.copy_value, number.key)}
          className="text-accent"
        >
          {done ? "Copied" : "Copy"}
        </Button>
        <span className="sr-only" aria-live="polite">
          {done ? `${title} copied` : ""}
        </span>
      </div>
      {number.check !== "none" || (showLetter && letter) ? (
        <div className="flex basis-full flex-wrap items-center gap-x-2 gap-y-1 text-[12.5px] leading-5 text-muted">
          <CheckBadge number={number} />
          {showLetter && letter ? (
            <span className="min-w-0">
              From{" "}
              <Link
                to={`/documents/${encodeURIComponent(letter.id)}`}
                className="inline rounded font-medium text-accent outline-none hover:underline focus-visible:ring-2 focus-visible:ring-accent [overflow-wrap:anywhere]"
              >
                {glueText(letter.title)}
              </Link>
              {showParty && number.party_name ? (
                <>
                  <Sep />
                  <span>{glueText(number.party_name)}</span>
                </>
              ) : null}
              {letter.date && !compactLetter ? (
                <>
                  <Sep />
                  <span className="whitespace-nowrap">{formatDate(letter.date, { style: "day" })}</span>
                </>
              ) : null}
              {number.letters > 1 && !compactLetter ? (
                <>
                  <Sep />
                  <span className="whitespace-nowrap">on {number.letters} letters</span>
                </>
              ) : null}
            </span>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
