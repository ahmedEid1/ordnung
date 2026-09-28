/**
 * "Not read yet: 2 letters from your folder" — letters the watched folder brought in that nobody has
 * read yet (docs/privacy.md, "The watched folder"). They are in no other part of Today: until the
 * person lets Claude read them (or keeps them private), Ordnung doesn't know what they ask or by
 * when — so Today says they wait instead of "nothing needs you". A waiting letter never reminds on
 * its own; this card is how the person hears of it.
 */
import { Link } from "react-router";
import { motion } from "motion/react";
import { ArrowRight } from "lucide-react";
import { buttonVariants } from "@/components/ui/Button";
import { MEANING_ICONS } from "@/lib/copy";
import { plural } from "@/lib/utils";
import { fadeUp } from "./motion";

/** "Not read yet: 2 letters from your folder" — never "waiting for", which is what you wait for from others. */
export function waitingTitle(count: number): string {
  return `Not read yet: ${plural(count, "letter")} from your folder`;
}

/** The Inbox's mark for these letters — not the hourglass, which is a deadline's (UI audit round 2). */
const Icon = MEANING_ICONS.notReadYet;

export function WaitingCard({ count }: { count: number }) {
  if (!count) return null;
  const one = count === 1;
  return (
    <motion.section
      variants={fadeUp}
      aria-labelledby="waiting-card-title"
      className="flex flex-wrap items-center gap-x-4 gap-y-3 rounded-[var(--radius-card)] border border-accent/25 bg-accent-soft/60 p-4 sm:p-5"
    >
      <span className="grid size-9 shrink-0 place-items-center rounded-xl bg-surface text-accent shadow-[var(--shadow-card)]">
        <Icon className="size-4" aria-hidden />
      </span>
      <div className="min-w-0 flex-1 basis-44">
        <h2 id="waiting-card-title" className="text-[15px] font-semibold leading-snug text-ink">
          {waitingTitle(count)}
        </h2>
        {/* what the heading doesn't say already (UI audit round 2: "not read yet" three times in a row) */}
        <p className="mt-0.5 text-[13.5px] leading-snug text-ink/80">
          Ordnung can't tell you what {one ? "it asks" : "they ask"} or by when until {one ? "it's" : "they're"} read. Nothing has been sent
          to Claude.
        </p>
      </div>
      <Link to="/inbox" className={buttonVariants({ variant: "primary", size: "sm", className: "max-sm:w-full" })}>
        Review {one ? "it" : "them"}
        <ArrowRight className="size-4" aria-hidden />
      </Link>
    </motion.section>
  );
}
