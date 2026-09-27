import { Lightbulb, Send, Signature } from "lucide-react";
import type { SendChannel, SendGuidance } from "@/api/types";
import { Badge } from "@/components/ui/Badge";
import { Countdown } from "@/components/ui/Countdown";
import { DateText } from "@/components/ui/DateText";
import { Glossary } from "@/components/ui/Glossary";
import { SEND_CHANNEL_COPY, SEND_FORM_COPY, TONES, copyFor } from "@/lib/copy";
import { urgencyOf } from "@/lib/format";
import { useToday } from "@/lib/today";
import { cn } from "@/lib/utils";
import { rankChannels } from "./logic";

/** Channels that arrive the same day, as the must-arrive sentence names them. */
const INSTANT: Record<string, string> = { online_button: "online", portal: "online", fax: "by fax", email: "by email" };
/** Channels a written-form letter rules out, named when the guidance marks them not allowed. */
const NOT_ENOUGH: Record<string, string> = { email: "An email", fax: "a fax", online_button: "an online button" };

/** "online or by fax" — the same-day channels this letter allows, without repeats. */
export function instantPhrase(channels: SendChannel[]): string | null {
  const words = [...new Set(channels.filter((c) => c.allowed && INSTANT[c.channel]).map((c) => INSTANT[c.channel]!))];
  return words.length ? `${words.slice(0, -1).join(", ")}${words.length > 1 ? " or " : ""}${words[words.length - 1]}` : null;
}

/** "An email or a fax is not enough." — only what this guidance really rules out (a court takes a fax). */
export function notEnoughPhrase(channels: SendChannel[]): string | null {
  const words = [...new Set(channels.filter((c) => !c.allowed && NOT_ENOUGH[c.channel]).map((c) => NOT_ENOUGH[c.channel]!))];
  if (!words.length) return null;
  const list = `${words.slice(0, -1).join(", ")}${words.length > 1 ? " or " : ""}${words[words.length - 1]}`;
  return `${list.charAt(0).toUpperCase()}${list.slice(1)} is not enough.`;
}

function ChannelRow({ c, n }: { c: SendChannel; n: number }) {
  const copy = copyFor(SEND_CHANNEL_COPY, c.channel);
  const Icon = copy.icon;
  const t = TONES[c.allowed ? copy.tone : "neutral"];
  return (
    <li className={cn("flex gap-3 py-3 first:pt-0 last:pb-0", !c.allowed && "opacity-70")}>
      <span className="relative mt-0.5 shrink-0">
        <span className={cn("grid size-8 place-items-center rounded-lg", t.soft, t.icon)}>
          <Icon className="size-4" aria-hidden />
        </span>
        {c.allowed ? (
          <span className="absolute -right-1 -top-1 grid size-4 place-items-center rounded-full bg-surface text-[10px] font-bold text-muted ring-1 ring-line" aria-hidden>
            {n}
          </span>
        ) : null}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className={cn("text-[14px] font-medium", c.allowed ? "text-ink" : "text-muted line-through decoration-muted/50")}>{c.label || copy.label}</span>
          {c.recommended && c.allowed ? (
            <Badge tone="ok" size="sm">
              Recommended
            </Badge>
          ) : null}
          {!c.allowed ? (
            <Badge tone="neutral" size="sm">
              Not enough for this letter
            </Badge>
          ) : null}
        </div>
        {c.note ? <p className="mt-0.5 text-[13px] leading-5 text-muted">{c.note}</p> : null}
        {c.citation ? (
          <p className="mt-1 inline-flex rounded-md bg-surface-2 px-1.5 py-px text-[11.5px] font-medium text-muted" title="Legal basis">
            {c.citation}
          </p>
        ) : null}
      </div>
    </li>
  );
}

/**
 * "How to send it": the send-by date with a countdown, the must-arrive date, the form the letter
 * needs (text form vs. signed paper) and the ways to send it, best first.
 */
export function SendGuidancePanel({ guidance, sent }: { guidance: SendGuidance | null; sent?: boolean }) {
  const today = useToday();
  if (!guidance) {
    return <p className="text-base text-muted">No special rules for sending this letter. Post or email both work — keep a copy.</p>;
  }
  const ranked = rankChannels(guidance.channels);
  const allowed = ranked.filter((c) => c.allowed);
  const instant = instantPhrase(allowed);
  const notEnough = notEnoughPhrase(ranked);
  const form = copyFor(SEND_FORM_COPY, guidance.form);
  const due = guidance.send_by ?? guidance.must_arrive_by;
  const u = due ? urgencyOf(due, today) : null;

  return (
    <div className="space-y-5">
      {due && !sent ? (
        <div
          className={cn(
            "rounded-xl border px-4 py-3.5",
            u === "overdue" || u === "today" || u === "soon" ? "border-danger/25 bg-danger-soft/60" : u === "week" ? "border-warn/30 bg-warn-soft/60" : "border-accent/20 bg-accent-soft/50",
          )}
        >
          <p className="text-[11.5px] font-semibold uppercase tracking-[0.07em] text-muted">{guidance.send_by ? "Send it by" : "Must arrive by"}</p>
          <div className="mt-1 flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
            <DateText date={due} style="short" className="display text-[26px] font-semibold leading-tight text-ink" />
            <Countdown date={due} variant="pill" />
          </div>
          {guidance.send_by && guidance.must_arrive_by && guidance.must_arrive_by !== guidance.send_by ? (
            <p className="mt-1.5 text-[13px] leading-5 text-ink/80">
              It must <strong className="font-semibold">arrive</strong> by <DateText date={guidance.must_arrive_by} className="font-medium" />. That's why the post needs a head start
              {instant ? `; ${instant} you have until then` : ""}.
            </p>
          ) : null}
        </div>
      ) : null}

      <div>
        <h3 className="mb-1.5 text-[12px] font-semibold uppercase tracking-[0.07em] text-muted">Form</h3>
        <p className="flex items-start gap-2 text-[14px] font-medium text-ink">
          <form.icon className={cn("mt-0.5 size-4 shrink-0", TONES[form.tone].icon)} aria-hidden />
          {form.label}
        </p>
        {guidance.form === "written_form" ? (
          <div className="mt-2 flex gap-2.5 rounded-xl border border-warn/30 bg-warn-soft/70 px-3 py-2.5 text-[13px] leading-5 text-ink/90">
            <Signature className="mt-0.5 size-4 shrink-0 text-warn" aria-hidden />
            <p>
              <strong className="font-semibold text-warn-ink">Print it and sign it by hand.</strong> By post, send it by <Glossary term="Einschreiben" /> —
              ideally Einwurf-Einschreiben — and keep the receipt.{notEnough ? ` ${notEnough}` : ""}
            </p>
          </div>
        ) : null}
        {/* a written-form letter's note is among the letter's own notes ("Good to know") */}
        {guidance.form_note && guidance.form !== "written_form" ? <p className="mt-1 text-[13px] leading-5 text-muted">{guidance.form_note}</p> : null}
      </div>

      {ranked.length ? (
        <div>
          <h3 className="mb-2.5 flex items-center gap-1.5 text-[12px] font-semibold uppercase tracking-[0.07em] text-muted">
            <Send className="size-3.5" aria-hidden /> Ways to send it, best first
          </h3>
          <ol className="divide-y divide-line">
            {ranked.map((c, i) => (
              <ChannelRow key={`${c.channel}-${i}`} c={c} n={allowed.indexOf(c) + 1} />
            ))}
          </ol>
        </div>
      ) : null}

      {guidance.tips.length ? (
        <ul className="space-y-1.5 rounded-xl bg-surface-2/70 px-3.5 py-3 text-[13px] leading-5 text-ink/85">
          {guidance.tips.map((t) => (
            <li key={t} className="flex gap-2">
              <Lightbulb className="mt-0.5 size-3.5 shrink-0 text-k-payment" aria-hidden />
              {t}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
