/** "Decide by" callouts: contracts whose send-by date is within the next 60 days. */
import { Link } from "react-router";
import { format, parseISO } from "date-fns";
import { FilePen, Hourglass } from "lucide-react";
import type { Contract, Party } from "@/api/types";
import { buttonVariants } from "@/components/ui/Button";
import { Countdown } from "@/components/ui/Countdown";
import { Glossary } from "@/components/ui/Glossary";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { formatDate } from "@/lib/format";
import { cn } from "@/lib/utils";
import { dayNumber } from "@/features/lanes/scale";
import { ContractWhy } from "./ContractWhy";
import { composerHrefFor, endingLetterLabel } from "./links";

function BigLeaf({ date, urgent }: { date: string; urgent: boolean }) {
  const d = parseISO(date);
  return (
    <time
      dateTime={date}
      className={cn(
        "hidden w-16 shrink-0 flex-col items-center self-start rounded-xl border py-2 leading-none sm:flex",
        urgent ? "border-danger/30 bg-danger-soft text-danger-ink" : "border-warn/30 bg-warn-soft text-warn-ink",
      )}
    >
      <span className="text-[11px] font-semibold uppercase tracking-[0.08em]">{format(d, "EEE")}</span>
      <span className="display mt-1 text-[28px] font-semibold tabular-nums">{format(d, "d")}</span>
      <span className="mt-1 text-[11px] font-semibold uppercase tracking-[0.08em]">{format(d, "MMM")}</span>
    </time>
  );
}

function otherwise(c: Contract): string {
  switch (c.computed?.regime) {
    case "vvg11":
      return "If you do nothing, it renews for another insurance year.";
    case "tkg56":
    case "bgb309_new":
      return "If you do nothing, it simply continues — and you can cancel any time with one month's notice.";
    default:
      return "If you do nothing, it simply continues.";
  }
}

function DecideCard({ contract: c, party, today }: { contract: Contract; party: Party | undefined; today: string }) {
  const comp = c.computed!;
  const sendBy = comp.send_by!;
  const days = dayNumber(sendBy) - dayNumber(today);
  const urgent = days <= 14;
  const end = comp.current_term_end ?? comp.earliest_exit;
  const d = (iso: string) => formatDate(iso, { style: "short", today });
  return (
    <li className={cn("card relative flex gap-4 overflow-hidden p-4 sm:p-5", "before:absolute before:inset-y-0 before:left-0 before:w-[3px]", urgent ? "before:bg-danger" : "before:bg-warn")}>
      <BigLeaf date={sendBy} urgent={urgent} />
      <div className="min-w-0 flex-1">
        <Countdown date={sendBy} prefix="Decide by" variant="pill" />
        <h3 className="mt-2 text-[16px] font-semibold leading-snug text-ink">
          {c.name}
          {party ? <span className="font-normal text-muted"> · {party.name}</span> : null}
        </h3>
        <p className="mt-1.5 max-w-3xl text-[13.5px] leading-relaxed text-ink/85">
          To leave {end ? <>when the current term ends on {d(end)}</> : "at the next possible date"}, post your <Glossary term="Kündigung" /> by{" "}
          <span className="font-semibold text-ink">{d(sendBy)}</span>
          {comp.cancel_by ? <> — it must arrive by {d(comp.cancel_by)}</> : null}. {otherwise(c)}
        </p>
        <div className="mt-3.5 flex flex-wrap items-center gap-x-4 gap-y-2">
          <Link to={composerHrefFor(c)} className={buttonVariants({ variant: "primary", size: "sm" })}>
            <FilePen aria-hidden />
            {endingLetterLabel(c)}
            <span className="sr-only"> for {c.name}</span>
          </Link>
          <ContractWhy contract={c} />
        </div>
      </div>
    </li>
  );
}

export function DecideBy({ contracts, partyById, today }: { contracts: Contract[]; partyById: Map<string, Party>; today: string }) {
  if (!contracts.length) return null;
  return (
    <section aria-labelledby="decide-by-title" className="mb-8">
      <SectionHeader
        id="decide-by-title"
        icon={Hourglass}
        title="Decide by"
        count={contracts.length}
        description="The window to cancel closes soon. Keeping a contract is fine too — then there is nothing to do."
      />
      <ul className={cn("grid gap-3", contracts.length > 1 && "lg:grid-cols-2")}>
        {contracts.map((c) => (
          <DecideCard key={c.id} contract={c} party={c.party_id ? partyById.get(c.party_id) : undefined} today={today} />
        ))}
      </ul>
    </section>
  );
}
