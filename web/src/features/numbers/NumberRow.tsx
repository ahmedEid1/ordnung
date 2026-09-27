/**
 * One number: what it is, the value (hidden until "Show"), Copy, its check-digit test and the letter
 * it came from. Copy works while it is hidden; the confirmation is announced (aria-live).
 */
import { useState } from "react";
import { Link } from "react-router";
import { Check, CircleCheck, Copy, Eye, EyeOff, TriangleAlert } from "lucide-react";
import type { MyNumber } from "@/api/types";
import { Button } from "@/components/ui/Button";
import { Tooltip } from "@/components/ui/Tooltip";
import { useClipboard } from "@/features/today/clipboard";
import { glueText } from "@/lib/format";
import { NBSP } from "@/lib/glue";
import { useFormatDate } from "@/lib/today";
import { cn } from "@/lib/utils";
import { hiddenLabel, maskValue } from "./mask";

/** " · " that never starts a line: the dot stays with the text before it. */
export function Sep() {
  return (
    <>
      <span aria-hidden>{`${NBSP}·`}</span>{" "}
    </>
  );
}

/** Kinds whose plain-English name says less than the letter's own label ("Your number" → "Scholarship ID"). */
const LABEL_FIRST = new Set<MyNumber["kind"]>(["other", "their_other", "reference", "register"]);

/** The row's heading: the plain-English name, or the letter's label where the name is generic. */
export function numberTitle(n: Pick<MyNumber, "kind" | "name" | "label">): string {
  return LABEL_FIRST.has(n.kind) ? n.label : n.name;
}

/** The letter's own label when it adds something to the title ("Tax ID (Steuer-ID)" · "Steuerliche Identifikationsnummer"). */
export function printedLabel(n: Pick<MyNumber, "kind" | "name" | "label">): string | null {
  const title = numberTitle(n);
  const label = n.label.trim();
  if (!label || title.toLowerCase().includes(label.toLowerCase().replace(/[.:]+$/, ""))) return null;
  return label;
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
  /** Hidden until "Show" (the organisation's own public numbers need not be). */
  masked?: boolean;
  /** Say which organisation's letter it is from (About you lists numbers from many). */
  showParty?: boolean;
  /** Link to the letter it came from. */
  showLetter?: boolean;
  /** Only "From <letter>" (a card that names the organisation and its latest letter already). */
  compactLetter?: boolean;
  className?: string;
}

export function NumberRow({ number, masked = true, showParty = false, showLetter = true, compactLetter = false, className }: NumberRowProps) {
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
        <p className="text-[13px] font-medium leading-5 text-ink/80">{title}</p>
        {printed ? <p className="text-[12.5px] leading-5 text-muted [overflow-wrap:anywhere]">{printed}</p> : null}
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
