/**
 * "Why this date?" — one receipt for every computed date (a to-do, a letter's deadline, a
 * contract's notice window): the key dates as tiles, the plain sentence, how sure we are, what the
 * letter says, then "Show the rules" with every step and its citation, and always the
 * point-of-use disclaimer (SPEC §21). Opened from a {@link ReceiptTrigger} in a {@link ReceiptPopover}.
 */
import { useId, useState, type ComponentProps, type ReactNode } from "react";
import { CalendarDays, ChevronDown, ExternalLink, HelpCircle, Quote } from "lucide-react";
import type { ComputationStep, Confidence, Grounding } from "@/api/types";
import { useRules } from "@/api/hooks";
import { CONFIDENCE_COPY, TONES, copyFor } from "@/lib/copy";
import { formatInlineText, looksGerman } from "@/lib/format";
import { useToday } from "@/lib/today";
import { cn } from "@/lib/utils";
import { Button } from "./Button";
import { ConfidenceNote } from "./ConfidenceNote";
import { DateText } from "./DateText";
import { Disclaimer, type AdviceLink } from "./Disclaimer";
import { GroundingBadge } from "./GroundingBadge";
import { Popover, type PopoverProps } from "./Popover";

export interface ReceiptDate {
  /** "Post it by", "Must arrive by", "Renews on"… */
  label: string;
  date: string;
}

export interface ReceiptStep {
  label: string;
  date?: string | null;
  /** "§ 193 BGB" — a link when `href` is set. */
  citation?: string | null;
  /** The law text. */
  href?: string | null;
}

export interface ReceiptQuote {
  /** The sentence the date came from, as written. */
  text: string;
  grounding?: Grounding | null;
  page?: number | null;
  /**
   * Whose words these are: the letter's (default), or — for a deadline the law adds, which the letter
   * never states — Ordnung's short wording of the law, shown as "What the law says" with its citation,
   * never as the letter's.
   */
  source?: "letter" | "law";
  /** The law the words stand for ("§ 4 S. 1 KSchG"), for a `law` quote. */
  citation?: string | null;
}

export interface ReceiptProps {
  /** Eyebrow (hidden in a phone sheet, whose title says it): "Why this date?" / "Why these dates?". */
  heading?: string;
  /** What the receipt is for ("Pay outstanding invoice…"). */
  context?: ReactNode;
  /** The key dates, most important first; shown as tiles, two per row. */
  dates?: ReceiptDate[];
  /** The plain-words sentence. */
  summary: ReactNode;
  /** Extra notes after the sentence (a contract's notice rules, "You can cancel any month"…). */
  children?: ReactNode;
  confidence: Confidence;
  warnings?: string[];
  /** What the letter says. */
  quote?: ReceiptQuote | null;
  /** The rules engine's steps (see {@link useReceiptSteps}). */
  steps?: ReceiptStep[];
  holidayCalendar?: string | null;
  defaultShowRules?: boolean;
  /** Independent advice links for high-stakes areas. */
  advice?: AdviceLink[];
}

/** Steps with their citation and law link from the rules catalog. */
export function useReceiptSteps(steps: readonly ComputationStep[]): ReceiptStep[] {
  const rules = useRules();
  const byId = new Map((rules.data ?? []).map((r) => [r.id, r]));
  return steps.map((s) => {
    const rule = s.rule_id ? byId.get(s.rule_id) : undefined;
    return { label: s.label, date: s.date, citation: s.citation ?? rule?.citation ?? null, href: rule?.url ?? null };
  });
}

function DateTiles({ dates }: { dates: ReceiptDate[] }) {
  return (
    <dl className="grid grid-cols-2 gap-2">
      {dates.map((d, i) => (
        <div
          key={`${d.label}-${d.date}`}
          // an odd last tile takes the whole row
          className={cn("min-w-0 rounded-lg bg-surface-2 px-3 py-2", i === dates.length - 1 && dates.length % 2 === 1 && "col-span-2")}
        >
          <dt className="text-xs font-medium text-muted">{d.label}</dt>
          <dd className="display mt-0.5 text-lg font-semibold text-ink">
            <DateText date={d.date} />
          </dd>
        </div>
      ))}
    </dl>
  );
}

function Steps({ steps, holidayCalendar }: { steps: ReceiptStep[]; holidayCalendar?: string | null }) {
  const today = useToday();
  const inline = (text: string) => formatInlineText(text, { today });
  return (
    <>
      {steps.length ? (
        <ol className="relative mt-3 space-y-3 pl-5 before:absolute before:bottom-1.5 before:left-[5px] before:top-1.5 before:w-px before:bg-line-strong">
          {steps.map((s, i) => {
            const last = i === steps.length - 1;
            return (
              <li key={`${s.label}-${i}`} className="relative text-sm">
                <span
                  aria-hidden
                  className={cn("absolute -left-5 top-[5px] size-[11px] rounded-full border-2 border-surface", last ? "bg-accent" : "bg-line-strong")}
                />
                <div className="flex items-baseline justify-between gap-3">
                  <span className={cn("leading-snug", last ? "font-medium text-ink" : "text-ink/90")}>{inline(s.label)}</span>
                  {s.date ? <DateText date={s.date} className="shrink-0 text-xs font-medium text-ink" /> : null}
                </div>
                {s.citation ? (
                  <div className="mt-0.5 text-xs">
                    {s.href ? (
                      <a
                        href={s.href}
                        target="_blank"
                        rel="noreferrer noopener"
                        className="-my-0.5 inline-flex items-center gap-1 rounded-sm py-0.5 font-medium text-accent underline-offset-2 hover:underline"
                      >
                        {inline(s.citation)}
                        <ExternalLink className="size-3 shrink-0" aria-hidden />
                        <span className="sr-only">(opens the law text in a new tab)</span>
                      </a>
                    ) : (
                      <span className="text-muted">{inline(s.citation)}</span>
                    )}
                  </div>
                ) : null}
              </li>
            );
          })}
        </ol>
      ) : null}
      {holidayCalendar ? (
        <p className="mt-3 flex items-start gap-1.5 text-xs leading-5 text-muted">
          <CalendarDays className="mt-0.5 size-3.5 shrink-0" aria-hidden />
          <span>
            Weekends and public holidays counted: <span className="font-medium text-ink/85">{holidayCalendar}</span>
          </span>
        </p>
      ) : null}
    </>
  );
}

/**
 * How sure the date is. High confidence without warnings is good news, said in one quiet line;
 * medium and low get the note with their reasons.
 */
function Confidence({ confidence, warnings }: { confidence: Confidence; warnings: string[] }) {
  if (confidence !== "high" || warnings.length) return <ConfidenceNote confidence={confidence} warnings={warnings} hideWhenHigh={false} />;
  const c = copyFor(CONFIDENCE_COPY, confidence);
  const Icon = c.icon;
  return (
    <p className={cn("flex items-center gap-1.5 text-sm font-medium", TONES[c.tone].text)}>
      <Icon className="size-4 shrink-0" aria-hidden />
      {c.label}
    </p>
  );
}

/** The receipt itself (popover or sheet content). */
export function Receipt({
  heading = "Why this date?",
  context,
  dates = [],
  summary,
  children,
  confidence,
  warnings = [],
  quote,
  steps = [],
  holidayCalendar,
  defaultShowRules = false,
  advice,
}: ReceiptProps) {
  const [open, setOpen] = useState(defaultShowRules);
  const rulesId = useId();
  const today = useToday();
  const german = quote ? looksGerman(quote.text) : false;
  const hasRules = steps.length > 0 || Boolean(holidayCalendar);
  return (
    <div className="space-y-3.5">
      <div>
        {/* a phone sheet shows the heading as its title */}
        <p className="text-xs font-semibold uppercase tracking-[0.07em] text-muted in-sheet:hidden">{heading}</p>
        {context ? <p className="mt-0.5 text-sm text-muted in-sheet:mt-0">{context}</p> : null}
      </div>

      {dates.length ? <DateTiles dates={dates} /> : null}

      <p className="text-base leading-relaxed text-ink">{typeof summary === "string" ? formatInlineText(summary, { today }) : summary}</p>

      {children}

      <Confidence confidence={confidence} warnings={warnings} />

      {quote?.text ? (
        <figure className="rounded-lg border border-line px-3 py-2.5">
          <figcaption className="mb-1 flex items-start gap-1.5 text-xs font-medium text-muted">
            <Quote className="mt-0.5 size-3.5 shrink-0" aria-hidden />
            <span>
              {quote.source === "law"
                ? `What the law says${quote.citation ? ` (${quote.citation}, in short)` : " (in short)"}`
                : "What the letter says"}
              {german ? " (in German — the sentence above says it in English)" : ""}
            </span>
          </figcaption>
          <blockquote lang={german ? "de" : undefined} className="text-sm leading-relaxed text-ink">
            <span className="marker box-decoration-clone px-0.5">{formatInlineText(quote.text, { rewrite: false })}</span>
          </blockquote>
          {quote.grounding ? <GroundingBadge grounding={quote.grounding} page={quote.page} className="mt-2" /> : null}
        </figure>
      ) : null}

      {hasRules ? (
        <div>
          <Button
            variant="link"
            size="sm"
            iconRight={ChevronDown}
            aria-expanded={open}
            aria-controls={rulesId}
            onClick={() => setOpen((v) => !v)}
            className={cn("[&_svg]:transition-transform motion-reduce:[&_svg]:transition-none", open && "[&_svg]:rotate-180")}
          >
            {open ? "Hide the rules" : "Show the rules"}
          </Button>
          <div id={rulesId} hidden={!open}>
            <Steps steps={steps} holidayCalendar={holidayCalendar} />
          </div>
        </div>
      ) : null}

      <Disclaimer variant="block" advice={advice} />
    </div>
  );
}

export interface ReceiptTriggerProps extends ComponentProps<"button"> {
  /** What the receipt is about, for screen readers: "Why this date? (Pay TechMarkt)". */
  context?: string;
}

/**
 * The "Why this date?" link: help icon, accent text with a soft underline, a 24 px tall target.
 * Use it as the child of a {@link ReceiptPopover} (or a Popover).
 */
export function ReceiptTrigger({ children = "Why this date?", context, className, ...rest }: ReceiptTriggerProps) {
  return (
    <button
      type="button"
      aria-label={context && typeof children === "string" ? `${children} (${context})` : undefined}
      {...rest}
      className={cn(
        "inline-flex min-h-6 items-center gap-1 rounded-md text-sm font-medium text-accent underline decoration-accent/30 underline-offset-[3px] transition-[text-decoration-color] hover:decoration-accent",
        className,
      )}
    >
      <HelpCircle className="size-3.5 shrink-0" aria-hidden />
      {children}
    </button>
  );
}

export interface ReceiptPopoverProps {
  /** The receipt (usually a {@link Receipt}). */
  content: ReactNode;
  /** Trigger text and popover title (default "Why this date?"). */
  title?: string;
  /** What it is about ("Pay TechMarkt"): in the popover's name and, for screen readers, the trigger's. */
  context?: string;
  placement?: PopoverProps["placement"];
  className?: string;
}

/** A {@link ReceiptTrigger} that opens the receipt: one width everywhere, a bottom sheet on phones. */
export function ReceiptPopover({ content, title = "Why this date?", context, placement = "bottom-start", className }: ReceiptPopoverProps) {
  return (
    <Popover content={content} label={context ? `${title} ${context}` : title} title={title} placement={placement} className="w-[24rem]">
      <ReceiptTrigger context={context} className={className}>
        {title}
      </ReceiptTrigger>
    </Popover>
  );
}
