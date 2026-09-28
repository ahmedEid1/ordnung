/** "Decide by" callouts: contracts whose send-by date is within the next 60 days. */
import { Link } from "react-router";
import { FilePen } from "lucide-react";
import type { Contract, Party } from "@/api/types";
import { buttonVariants } from "@/components/ui/Button";
import { Countdown } from "@/components/ui/Countdown";
import { DateLeaf, type DateLeafTone } from "@/components/ui/DateLeaf";
import { Glossary } from "@/components/ui/Glossary";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { MEANING_ICONS } from "@/lib/copy";
import { formatDate, protectRefs, urgencyOf, urgencyTone, type UrgencyLevel } from "@/lib/format";
import { cn } from "@/lib/utils";
import { ContractWhy } from "./ContractWhy";
import { composerHrefFor, endingLetterLabel } from "./links";

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

/** The leaf's colour for an urgency level (the app's one scale: red, amber, then plain). */
const LEAF_TONE: Record<UrgencyLevel, DateLeafTone> = { danger: "danger", warn: "warn", ink: "default", muted: "default" };

function DecideCard({ contract: c, party, today }: { contract: Contract; party: Party | undefined; today: string }) {
  const comp = c.computed!;
  const sendBy = comp.send_by!;
  // the stripe, the leaf and the countdown all follow the one urgency scale
  const tone = urgencyTone(urgencyOf(sendBy, today));
  const end = comp.current_term_end ?? comp.earliest_exit;
  const d = (iso: string) => formatDate(iso, { style: "short", today });
  return (
    <li className="card relative flex gap-4 overflow-hidden p-4 sm:p-5" data-urgency={tone.level}>
      <span aria-hidden data-part="stripe" className={cn("absolute inset-y-0 left-0 w-[3px]", tone.stripe)} />
      {/* from sm up the date is a calendar leaf with the countdown under it (the phone pill says both) */}
      <div aria-hidden className="hidden shrink-0 flex-col items-center gap-2 self-start sm:flex">
        <DateLeaf date={sendBy} size="lg" tone={LEAF_TONE[tone.level]} decorative />
        <Countdown date={sendBy} variant="pill" />
      </div>
      <div className="min-w-0 flex-1">
        <Countdown date={sendBy} prefix="Send by" variant="pill" className="sm:sr-only" />
        <h3 className="mt-2 text-[16px] font-semibold leading-snug text-ink sm:mt-0">
          {protectRefs(c.name)}
          {party ? (
            <span className="font-normal text-muted">
              {/* on phones the organisation takes its own line (no "·" left hanging at a line end) */}
              <span className="sr-only sm:not-sr-only"> · </span>
              <span className="max-sm:block">{party.name}</span>
            </span>
          ) : null}
        </h3>
        <p className="mt-1.5 max-w-3xl text-[13.5px] leading-relaxed text-ink/85">
          To leave {end ? <>when the current term ends on {d(end)}</> : "at the next possible date"}, send your <Glossary term="Kündigung" /> by{" "}
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
        icon={MEANING_ICONS.decideBy}
        title="Decide by"
        count={contracts.length}
        description="The window to cancel closes soon. Keeping a contract is fine too — then there is nothing to do."
      />
      {/* two side by side only when the content column has room for two (not by the window's width) */}
      <ul className={cn("grid gap-3", contracts.length > 1 && "grid-cols-[repeat(auto-fit,minmax(min(100%,28rem),1fr))]")}>
        {contracts.map((c) => (
          <DecideCard key={c.id} contract={c} party={c.party_id ? partyById.get(c.party_id) : undefined} today={today} />
        ))}
      </ul>
    </section>
  );
}
