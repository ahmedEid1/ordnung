/**
 * "How it was read" in words: what each step of a reading did, from the facts it kept
 * (`src/ordnung/trace/facts.py` is the vocabulary — counts, codes, scores, dates and ids, never the
 * letter's text). Pure functions; the names of records come from the API's `label`, looked up when
 * the trace is shown.
 */
import type { DateSpec, SpanKind, TraceChange, TraceRun, TraceSpan } from "@/api/types";
import type { Tone } from "@/lib/copy";
import { formatCompact, formatDate, formatFileSize, formatUsd } from "@/lib/format";
import { plural } from "@/lib/utils";
import { dueDateLabel, sendByLabel } from "../dateLabels";

type Attrs = Record<string, unknown>;

const num = (a: Attrs, k: string): number | null => (typeof a[k] === "number" ? (a[k] as number) : null);
const str = (a: Attrs, k: string): string | null => (typeof a[k] === "string" && a[k] !== "" ? (a[k] as string) : null);
const bool = (a: Attrs, k: string): boolean => a[k] === true;
const list = (a: Attrs, k: string): unknown[] => (Array.isArray(a[k]) ? (a[k] as unknown[]) : []);

/** What a kind of step is, for its icon and colour. */
export const KIND_LABEL: Record<SpanKind, string> = {
  run: "Reading",
  ocr: "Reading the pages",
  model: "Claude",
  verify: "Checking a quote",
  rules: "Rules engine",
  link: "Linking",
  plan: "Filing",
};

/** Colour of a step's bar: Claude's calls stand out; steps of code are quiet. */
export function barTone(span: TraceSpan): Tone {
  if (span.status === "error" || str(span.attributes, "outcome") === "failed") return "danger";
  if (str(span.attributes, "outcome") === "invalid") return "warn";
  if (span.kind === "model") return "accent";
  if (span.kind === "ocr") return "document";
  return "neutral";
}

// ------------------------------------------------------------------------------------------------
// Numbers
// ------------------------------------------------------------------------------------------------

/** "<1 ms", "12 ms", "4.2 s", "1 min 44 s". */
export function formatMs(ms: number): string {
  if (ms < 1) return ms > 0 ? "<1 ms" : "0 ms";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  const s = ms / 1000;
  if (s < 60) return `${s < 10 ? s.toFixed(1) : Math.round(s)} s`;
  const min = Math.floor(s / 60);
  const rest = Math.round(s - min * 60);
  return rest ? `${min} min ${rest} s` : `${min} min`;
}

const percent = (score: number) => `${Math.round(score)} %`;
/** "Wed 30 Sep" (the year only when it isn't `today`'s; always without a `today`). */
const day = (value: string | null, today?: string) => formatDate(value, { style: "short", today, withYear: today ? "auto" : "always" });
const modelName = (model: string | null) => {
  if (!model) return "Claude";
  const m = /(haiku|sonnet|opus)/i.exec(model);
  return m ? m[1]!.charAt(0).toUpperCase() + m[1]!.slice(1).toLowerCase() : model;
};

// ------------------------------------------------------------------------------------------------
// Vocabulary
// ------------------------------------------------------------------------------------------------

/** The kind of reference a sender or thread was found by (never its number). */
export const REFERENCE_KIND: Record<string, string> = {
  aktenzeichen: "file number (Aktenzeichen)",
  rechnungsnummer: "invoice number",
  kundennummer: "customer number",
  vertragsnummer: "contract number",
  steuernummer: "tax number",
  beitragsnummer: "contribution number",
  mitgliedsnummer: "membership number",
  account: "account number",
  personal: "personal number",
  other: "reference number",
};
const referenceKind = (kind: string | null) => (kind ? (REFERENCE_KIND[kind] ?? "reference number") : "reference number");

export const PLAN_ACTION: Record<string, string> = {
  created: "New to-do",
  updated: "Updated from this reading",
  kept_edited: "Kept as you edited it",
  kept_later_date: "Kept its later date — it repeats, and reading never moves it back",
};

export const CONTRACT_DECISION: Record<string, string> = {
  created: "Contract created from this letter",
  refreshed: "Contract refreshed — fields you edited were kept",
  filled: "Empty fields of a known contract filled in",
  change_recorded: "Change recorded on the contract (nothing applied)",
  no_match: "No contract found for this change",
  none: "Nothing to record on a contract",
};

export const PAYMENT_FINDING: Record<string, string> = {
  invalid_iban: "The IBAN's checksum is wrong",
  iban_changed: "The IBAN differs from the one this sender used before",
  similar_party_iban: "The IBAN belongs to another organisation you know",
  payee_changed: "The payee differs from the one this sender used before",
};

export const CONSISTENCY_REASON: Record<string, string> = {
  date_not_in_quote: "the quote doesn't state the date",
  date_without_year: "the quote's date has no year",
  period_not_in_quote: "the quote doesn't state the period",
  amount_not_in_quote: "the quote doesn't state the amount",
  working_day_not_in_quote: "the quote doesn't state the working day",
  day_of_month_not_in_quote: "the quote doesn't state the day of the month",
  reading_incomplete: "added by Ordnung because Claude's reading came back incomplete",
};
const reason = (code: unknown) => (typeof code === "string" ? (CONSISTENCY_REASON[code] ?? code.replace(/_/g, " ")) : "");

const LAW_REASON: Record<string, string> = {
  filed: "Filed as a to-do",
  covered: "Not filed: the letter's own date is the same or earlier",
  deleted_by_you: "Not filed again: you deleted it",
};

const ANCHOR: Record<string, string> = {
  document_date: "the letter's date",
  deemed_delivery: "the day it counts as delivered",
  receipt: "the day it reached you",
  explicit_date: "a date it names",
  today: "today",
};
const UNIT: Record<string, [string, string]> = {
  days: ["day", "days"],
  weeks: ["week", "weeks"],
  months: ["month", "months"],
  years: ["year", "years"],
  business_days: ["working day", "working days"],
  werktage: ["Werktag", "Werktage"],
};
const DELIVERY: Record<string, string> = {
  de_admin_post: "posted by an authority",
  de_admin_electronic: "sent electronically by an authority",
  de_admin_portal: "put in an authority's portal",
};

/** A DateSpec's structure in words ("1 week after the day it reached you"); the wording itself is never kept. */
export function specText(spec: Partial<DateSpec> | null | undefined): string {
  if (!spec) return "—";
  if (spec.type === "fixed") return spec.date ? `A fixed date: ${formatDate(spec.date, { style: "medium" })}` : "A fixed date";
  if (spec.type === "relative" && spec.amount != null && spec.unit) {
    const [one, many] = UNIT[spec.unit] ?? [spec.unit, spec.unit];
    const anchor =
      spec.anchor === "explicit_date" && spec.anchor_date ? formatDate(spec.anchor_date, { style: "medium" }) : (ANCHOR[spec.anchor ?? ""] ?? "a day it names");
    const delivery = spec.delivery_rule && spec.delivery_rule !== "none" ? ` (${DELIVERY[spec.delivery_rule] ?? spec.delivery_rule})` : "";
    return `${spec.amount} ${spec.amount === 1 ? one : many} after ${anchor}${delivery}`;
  }
  return "No date";
}

// ------------------------------------------------------------------------------------------------
// One line per step
// ------------------------------------------------------------------------------------------------

export interface SpanCopy {
  /** The step's title: its record's name when it has one ("Pay the parking fine"), else its name. */
  title: string;
  /** What the step decided, in a few words. */
  summary: string;
  /** A flag worth seeing without opening the step. */
  flag?: { text: string; tone: Tone };
}

const QUOTE_TARGET: Record<string, string> = {
  item: "To-do",
  key_fact: "Key fact",
  contract: "Contract",
  change: "The change",
  remedy: "How to object",
};

/** Where a quote's numbers were found: a photo's are only in Claude's transcript, not on the paper. */
function digitsText(a: Attrs): string {
  if (a.digits_matched === false) return "not all in the closest passage";
  if (a.digits_matched !== true) return "no close passage";
  switch (str(a, "grounding")) {
    case "verified":
      return "all in the letter's text";
    case "model_read":
      return "all in Claude's transcript — compare with the paper letter";
    default:
      return "all in the passage found";
  }
}

/** The nature of a date step's deadline (its DateSpec's). */
const natureOf = (a: Attrs): string | null => {
  const spec = a.spec;
  return spec && typeof spec === "object" && typeof (spec as Attrs).nature === "string" ? ((spec as Attrs).nature as string) : null;
};

function groundingText(a: Attrs): string {
  const page = num(a, "page");
  switch (str(a, "grounding")) {
    case "verified":
      return page ? `Found on page ${page}` : "Found in the letter";
    case "model_read":
      return page ? `Found in the transcript of page ${page}` : "Found in the transcript";
    case "user":
      return "Confirmed by you";
    default: {
      const best = num(a, "best_score");
      return best ? `Not found (closest passage ${percent(best)})` : "Not found in the letter";
    }
  }
}

/** The title, a short summary and a flag for one step (see {@link SpanCopy}). */
export function spanCopy(span: TraceSpan, today?: string, transfer?: boolean): SpanCopy {
  const a = span.attributes;
  const named = span.label ? span.label : span.name;
  switch (span.kind) {
    case "ocr": {
      if (span.name === "Transcribe" || num(a, "to_transcribe") === null) {
        const pages = num(a, "pages") ?? 0;
        return {
          title: "Read from the photo",
          summary: pages > 1 ? `${plural(pages, "page")}, read at the same time` : "1 page",
        };
      }
      const pages = num(a, "pages") ?? 0;
      const textPages = num(a, "text_pages") ?? 0;
      const flag = bool(a, "hidden_text") ? { text: "Hidden text kept from Claude", tone: "warn" as Tone } : undefined;
      if (!textPages)
        return {
          title: "Text layer",
          summary: `No text layer — ${plural(pages, "page")} to read from the photo`,
          flag,
        };
      return {
        title: "Text layer",
        summary: `${textPages} of ${plural(pages, "page")} with text · ${formatCompact(num(a, "words") ?? 0)} words`,
        flag,
      };
    }
    case "model": {
      const outcome = str(a, "outcome");
      const call = span.call;
      const page = num(a, "page");
      // a comparison's step has no facts: its key still says which call it was
      const repair = str(a, "prompt") === "extract_repair" || span.key.endsWith("model:extract_repair");
      const title = page ? `Page ${page} read by Claude` : repair ? "Claude, asked again" : "Claude reads the letter";
      const flag: SpanCopy["flag"] =
        outcome === "invalid"
          ? { text: "Answer didn't fit — asked again", tone: "warn" }
          : outcome === "repaired"
            ? { text: "Fixed on the second try", tone: "ok" }
            : outcome === "failed" || span.status === "error"
              ? { text: "Failed", tone: "danger" }
              : bool(a, "cache_hit")
                ? { text: "From the cache", tone: "ok" }
                : undefined;
      const parts = [modelName(str(a, "served_model") ?? str(a, "request_model"))];
      if (page) parts.push(bool(a, "legible") ? `${formatCompact(num(a, "chars") ?? 0)} characters` : "not legible");
      if (call && !call.cache_hit) parts.push(`${formatCompact(call.output_tokens)} tokens out`, formatUsd(call.cost_usd));
      return { title, summary: parts.join(" · "), flag };
    }
    case "verify": {
      if (str(a, "target") === null) {
        const counts = [
          num(a, "verified") ? `${num(a, "verified")} in the text` : null,
          num(a, "model_read") ? `${num(a, "model_read")} in the transcript` : null,
          num(a, "unverified") ? `${num(a, "unverified")} not found` : null,
        ].filter(Boolean);
        const check = num(a, "needs_check") ?? 0;
        // a reading that came back incomplete: Ordnung filed a to-do of its own (src/ordnung/ingest/gaps.py)
        const incomplete = str(a, "reading_gap") !== null;
        return {
          title: "Quotes checked on the page",
          summary: `${plural(num(a, "quotes") ?? 0, "quote")}${counts.length ? `: ${counts.join(", ")}` : ""}${
            incomplete ? " · reading came back incomplete — Ordnung added a to-do" : ""
          }`,
          // the to-do Ordnung added is one of the `needs_check`: the others are said beside it
          flag: incomplete
            ? { text: check > 1 ? `Reading incomplete · ${check - 1} to check` : "Reading incomplete", tone: "warn" }
            : check
              ? { text: `${check} to check`, tone: "warn" }
              : undefined,
        };
      }
      const target = QUOTE_TARGET[str(a, "target") ?? ""] ?? "Quote";
      const reasons = list(a, "reasons").map(reason).filter(Boolean);
      const unverified = str(a, "grounding") === "unverified";
      return {
        title: span.label ?? target,
        summary: `${target} · ${groundingText(a)}${reasons.length ? ` · ${reasons.join(", ")}` : ""}`,
        flag: unverified ? { text: "Please check", tone: "warn" } : reasons.length ? { text: "Please check", tone: "warn" } : undefined,
      };
    }
    case "rules": {
      if (str(a, "rule_id") !== null) {
        const filed = bool(a, "filed");
        const due = str(a, "due_date");
        return {
          title: span.label ?? "Deadline the law adds",
          summary: `Deadline the law adds · ${LAW_REASON[str(a, "reason") ?? ""] ?? (filed ? "Filed" : "Not filed")}${filed && due ? ` · ${day(due, today)}` : ""}`,
        };
      }
      if (a.spec === undefined) {
        return {
          title: "Dates computed",
          summary: `${plural(num(a, "dated") ?? 0, "dated to-do")} of ${num(a, "items") ?? 0}`,
        };
      }
      const due = str(a, "due_date");
      const sendBy = str(a, "send_by");
      const low = str(a, "confidence") === "low";
      return {
        title: named,
        summary: due ? `→ ${day(due, today)}${sendBy ? ` · ${sendByLabel(natureOf(a), transfer).toLowerCase()} ${day(sendBy, today)}` : ""}` : "No date could be computed",
        flag: low ? { text: "Please check", tone: "warn" } : undefined,
      };
    }
    case "link": {
      if ("candidates" in a || span.name === "Sender") {
        const decision = str(a, "decision");
        const score = num(a, "score");
        const summary =
          decision === "identifier"
            ? `Known — found by its ${referenceKind(str(a, "reference_kind"))}`
            : decision === "name"
              ? "Known — same name"
              : decision === "similar_name"
                ? `Known — similar name (${percent(score ?? 0)})`
                : decision === "new"
                  ? "New organisation"
                  : "No sender found";
        return { title: span.label ?? "Sender", summary: span.label ? `Sender · ${summary}` : summary };
      }
      if ("finding" in a) {
        const finding = str(a, "finding");
        if (finding)
          return {
            title: "Payment check",
            summary: PAYMENT_FINDING[finding] ?? finding,
            flag: { text: "Double-check", tone: "danger" },
          };
        const summary =
          a.iban_valid === false
            ? "The IBAN's checksum is wrong"
            : bool(a, "iban_known")
              ? "IBAN known for this sender"
              : bool(a, "iban_added")
                ? "IBAN checks out — remembered for this sender"
                : "Nothing to check";
        return { title: "Payment check", summary };
      }
      if ("case_id" in a) {
        const decision = str(a, "decision");
        const summary =
          decision === "reference"
            ? `Joined by its ${referenceKind(str(a, "reference_kind"))}`
            : decision === "email"
              ? "Joined its e-mail's thread"
              : decision === "same_thread"
                ? "Joined its thread"
                : "New thread";
        return {
          title: span.label ?? "Thread",
          summary: `Thread · ${summary}`,
        };
      }
      if ("contract_id" in a) {
        const change = str(a, "change");
        return {
          title: span.label ?? "Contract",
          summary: `${CONTRACT_DECISION[str(a, "decision") ?? ""] ?? "Contract"}${change ? ` (${change.replace(/_/g, " ")})` : ""}`,
        };
      }
      if ("invoices" in a) {
        const n = num(a, "invoices") ?? 0;
        return {
          title: "Payment reminder",
          summary: n ? `About ${plural(n, "open invoice")} — pay once, not twice` : "No filed invoice found",
        };
      }
      return {
        title: "Thread, contract & payment",
        summary: span.name === "Thread & contract" ? "Which thread, contract and payment it belongs to" : span.name,
      };
    }
    case "plan": {
      if (str(a, "action") !== null) {
        return {
          title: named,
          summary: `${PLAN_ACTION[str(a, "action")!] ?? str(a, "action")}${bool(a, "moved") ? " (carried over from the earlier reading)" : ""}`,
        };
      }
      const check = num(a, "needs_check") ?? 0;
      const removed = num(a, "removed") ?? 0;
      return {
        title: "To-dos filed",
        summary: [check ? `${check} to check` : "Nothing to check", removed ? `${removed} old to-do${removed === 1 ? "" : "s"} removed` : null]
          .filter(Boolean)
          .join(" · "),
      };
    }
    default:
      return { title: named, summary: "" };
  }
}

// ------------------------------------------------------------------------------------------------
// Details of one step (a definition list)
// ------------------------------------------------------------------------------------------------

export interface DetailRow {
  label: string;
  value: string;
}

/** The facts of one step as label/value rows (the view adds "Why this date?" and links). */
export function spanDetails(
  span: TraceSpan,
  partyName: (id: string) => string | null = () => null,
  today?: string,
  /** A date step's to-do is money you transfer (`isTransfer`; unknown: a payment is). */
  transfer?: boolean,
): DetailRow[] {
  const a = span.attributes;
  const rows: DetailRow[] = [];
  const add = (label: string, value: string | null | undefined) => {
    if (value) rows.push({ label, value });
  };
  switch (span.kind) {
    case "ocr":
      if (num(a, "to_transcribe") !== null) {
        add("Pages", String(num(a, "pages") ?? 0));
        add("With a text layer", String(num(a, "text_pages") ?? 0));
        add("To read from the photo", String(num(a, "to_transcribe") ?? 0));
        add("Words in the text layer", formatCompact(num(a, "words") ?? 0));
        add("Hidden text", bool(a, "hidden_text") ? "Found — removed before Claude read the letter" : "None found");
      } else add("Pages read at the same time", String(num(a, "pages") ?? 0));
      break;
    case "model": {
      const call = span.call;
      const version = str(a, "prompt_version");
      const prompt = (str(a, "prompt") ?? "—").replace(/_repair$/, " (repair)");
      add("Prompt", `${prompt}${version ? `, version ${version}` : ""}`);
      const asked = modelName(str(a, "request_model"));
      const served = str(a, "served_model");
      add("Model", served && modelName(served) !== asked ? `${asked} asked · ${modelName(served)} answered` : asked);
      if (num(a, "page")) add("Transcript", bool(a, "legible") ? `${formatCompact(num(a, "chars") ?? 0)} characters (not kept here)` : "Not legible");
      if (call) {
        if (call.cache_hit) add("Answer", "From the cache on this computer — nothing was sent");
        else {
          add("Tokens", `${formatCompact(call.input_tokens + call.cache_read_tokens + call.cache_creation_tokens)} in · ${formatCompact(call.output_tokens)} out`);
          add("API-equivalent cost", formatUsd(call.cost_usd));
          add("Claude's time", formatMs(call.duration_ms));
          add("Sent", call.pages_sent ? plural(call.pages_sent, "page image") : call.bytes_sent ? `${formatFileSize(call.bytes_sent)} of text` : null);
        }
      }
      const outcome = str(a, "outcome");
      add(
        "Answer",
        outcome === "invalid"
          ? `Didn't match the form${num(a, "problems") ? ` (${plural(num(a, "problems")!, "problem")})` : ""} — asked again with the problems listed`
          : outcome === "repaired"
            ? "Usable on the second try"
            : outcome === "failed"
              ? "Not usable"
              : call?.cache_hit
                ? null
                : "Usable",
      );
      break;
    }
    case "verify":
      // the stage's counts are its summary; its steps are listed under it
      if (str(a, "target") === null) break;
      add("Where", groundingText(a));
      if (num(a, "score") !== null) add("Match", percent(num(a, "score")!));
      {
        const groups = num(a, "digit_groups") ?? 0;
        add(
          "Numbers",
          groups ? `${plural(groups, "number")} checked digit by digit — ${digitsText(a)}` : "No numbers in the quote",
        );
      }
      {
        const reasons = list(a, "reasons").map(reason).filter(Boolean);
        add("Consistency", reasons.length ? `Please check: ${reasons.join(", ")}` : "The quote says what was read from it");
      }
      break;
    case "rules":
      if (str(a, "rule_id") !== null) {
        add("Date", str(a, "due_date") ? day(str(a, "due_date"), today) : null);
        add("Outcome", LAW_REASON[str(a, "reason") ?? ""] ?? null);
        break;
      }
      if (a.spec === undefined) break;
      add("What the letter says", specText(a.spec as Partial<DateSpec>));
      add(dueDateLabel(natureOf(a), str(a, "send_by") !== null), str(a, "due_date") ? day(str(a, "due_date"), today) : "—");
      add(sendByLabel(natureOf(a), transfer), str(a, "send_by") ? day(str(a, "send_by"), today) : null);
      add("How sure", str(a, "confidence") ? ({ high: "High", medium: "Medium", low: "Low — please check" }[str(a, "confidence")!] ?? null) : null);
      add("Holidays", str(a, "holiday_calendar"));
      break;
    case "link": {
      if ("candidates" in a) {
        const candidates = list(a, "candidates") as {
          party_id?: string;
          score?: number;
        }[];
        add(
          "Compared with",
          candidates.length ? candidates.map((c) => `${(c.party_id && partyName(c.party_id)) || "another organisation"} (${percent(c.score ?? 0)})`).join(", ") : null,
        );
      }
      if ("finding" in a) {
        add("IBAN checksum", a.iban_valid === null || a.iban_valid === undefined ? "No IBAN" : a.iban_valid ? "Correct" : "Wrong");
        add("Known for this sender", bool(a, "iban_known") ? "Yes" : "No");
        if (bool(a, "iban_added")) add("Remembered", "Added to this sender's known accounts");
      }
      break;
    }
    case "plan":
      if (str(a, "action") !== null) {
        add("What happened", PLAN_ACTION[str(a, "action")!] ?? str(a, "action"));
        add("Date", str(a, "due_date") ? day(str(a, "due_date"), today) : "No date");
      } else {
        add("Old to-dos removed", String(num(a, "removed") ?? 0));
        if (bool(a, "rolled_forward")) add("Repeating to-dos", "Moved on to their next date");
      }
      break;
    default:
      break;
  }
  if (span.status === "error") add("Error", span.error ?? "Failed");
  return rows;
}

// ------------------------------------------------------------------------------------------------
// A reading, and what changed between two
// ------------------------------------------------------------------------------------------------

/**
 * "Read on 28 Sep 2026" / "Read again on …" (+ the reading's number when there are several). A letter the
 * watched folder brought in is only stored until the person answers: "Stored on …" — never "Read" next to
 * "Stored — not read yet" (UI audit round 2).
 */
export function runTitle(run: TraceRun, several: boolean): string {
  const when = formatDate(run.started_at, { style: "medium" });
  const verb = run.result === "held" ? "Stored" : run.trigger === "read_again" ? "Read again" : "Read";
  return several ? `Reading ${run.reading} · ${verb.toLowerCase()} on ${when}` : `${verb} on ${when}`;
}

/** How a reading ended, in words. */
export function runResult(run: TraceRun): { text: string; tone: Tone } {
  // the sentence itself is shown next to the steps; a paused or stopped reading is read again later
  if (run.ended === "paused") return { text: "Paused — read again later", tone: "warn" };
  if (run.ended === "stopped") return { text: "Stopped — read again later", tone: "warn" };
  if (run.ended === "failed" || run.status === "error") return { text: "Couldn't be read", tone: "danger" };
  if (run.result === "needs_review") return { text: "Filed — something to check", tone: "warn" };
  if (run.result === "failed") return { text: "Couldn't be read", tone: "danger" };
  // a letter from the watched folder is only stored on this computer until the person answers
  if (run.result === "held") return { text: "Stored — not read yet", tone: "neutral" };
  return { text: "Filed", tone: "ok" };
}

/**
 * The reading `run` is compared with by default (`runs` newest first): the newest earlier reading
 * that was done — a paused or stopped attempt has almost no steps, so nearly every step would show
 * as new — else the newest earlier one (as `ordnung/trace/compare.py` decides).
 */
export function compareBase(runs: TraceRun[], run: TraceRun): TraceRun | undefined {
  const older = runs.filter((r) => r.reading < run.reading);
  return older.find((r) => r.ended === "done") ?? older[0];
}

/** A folder for the shell, in double quotes (single quotes when it has a `"`, `$` or backtick). */
export function shellPath(path: string): string {
  return /["$`]/.test(path) ? `'${path.replace(/'/g, "'\\''")}'` : `"${path}"`;
}

/**
 * `ordnung trace` for one reading: `--reading N` unless it is the newest kept, and the data folder
 * of the server this app talks to (the demo's is not the default one `ordnung trace` looks in).
 */
export function exportCommand(docId: string, { reading, dataDir }: { reading: number | null; dataDir: string | null }): string {
  return [`ordnung trace ${docId}`, reading ? `--reading ${reading}` : null, "--otel -o trace.json", dataDir ? `--data-dir ${shellPath(dataDir)}` : null]
    .filter(Boolean)
    .join(" ");
}

const FIELD: Record<string, string> = {
  present: "step",
  result: "result",
  needs_check: "to-dos to check",
  items: "to-dos",
  outcome: "answer",
  cache_hit: "from the cache",
  served_model: "model",
  prompt_version: "prompt version",
  legible: "legible",
  pages: "pages",
  text_pages: "pages with text",
  to_transcribe: "pages to read from the photo",
  hidden_text: "hidden text",
  grounding: "where it was found",
  page: "page",
  digits_matched: "numbers in the passage found",
  consistent: "consistent",
  reasons: "what to check",
  due_date: "date",
  send_by: "send-by date",
  confidence: "how sure",
  rule_ids: "rules checked",
  filed: "filed",
  party_id: "sender",
  case_id: "thread",
  contract_id: "contract",
  change: "change",
  finding: "payment check",
  item_id: "to-do",
  action: "what happened",
  removed: "removed",
};

const GROUNDING_WORD: Record<string, string> = {
  verified: "in the text",
  model_read: "in the transcript",
  unverified: "not found",
  user: "confirmed by you",
};
const OUTCOME_WORD: Record<string, string> = {
  ok: "usable",
  invalid: "didn't fit",
  repaired: "fixed on the second try",
  failed: "not usable",
};

function valueText(field: string, value: unknown, today?: string): string {
  if (value === null || value === undefined || (Array.isArray(value) && !value.length)) return "none";
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (field === "due_date" || field === "send_by") return typeof value === "string" ? day(value, today) : String(value);
  if (field === "grounding" && typeof value === "string") return GROUNDING_WORD[value] ?? value;
  if (field === "outcome" && typeof value === "string") return OUTCOME_WORD[value] ?? value;
  if (field === "action" && typeof value === "string") return (PLAN_ACTION[value] ?? value).toLowerCase();
  if (field === "reasons" && Array.isArray(value)) return value.map(reason).join(", ");
  if (field === "served_model" && typeof value === "string") return modelName(value);
  if (field === "finding" && typeof value === "string") return (PAYMENT_FINDING[value] ?? value).toLowerCase();
  if (Array.isArray(value)) return value.join(", ");
  if (typeof value === "object") return "changed";
  // ids of records: the label says which one; the id itself means nothing to a person
  if (/_id$/.test(field)) return "another one";
  return String(value);
}

/** One change between two readings in words: what, and from → to. */
export function changeText(
  change: TraceChange,
  today?: string,
): {
  what: string;
  detail: string;
} {
  const what =
    change.label ??
    spanCopy({
      ...emptySpan,
      kind: change.kind,
      name: change.name,
      key: change.key,
      attributes: {},
    }).title;
  if (change.field === "present")
    return {
      what,
      detail: change.after ? "Only in the newer reading" : "Only in the earlier reading",
    };
  const field = FIELD[change.field] ?? change.field.replace(/_/g, " ");
  if (/_id$/.test(change.field)) return { what, detail: `A different ${field} than before` };
  // a newer model of the same family: its family alone would read "Sonnet → Sonnet"
  if (change.field === "served_model" && typeof change.before === "string" && typeof change.after === "string" && modelName(change.before) === modelName(change.after))
    return { what, detail: `Model: ${change.before} → ${change.after}` };
  return {
    what,
    detail: `${field.charAt(0).toUpperCase()}${field.slice(1)}: ${valueText(change.field, change.before, today)} → ${valueText(change.field, change.after, today)}`,
  };
}

const emptySpan: TraceSpan = {
  id: "",
  parent_id: null,
  depth: 0,
  key: "",
  kind: "run",
  name: "",
  stage: null,
  start_ms: 0,
  duration_ms: 0,
  status: "ok",
  error: null,
  attributes: {},
  call: null,
  ref: null,
  label: null,
};
