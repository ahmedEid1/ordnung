/**
 * "2 letters from your folder wait for you" — letters the watched folder brought in that nobody has
 * read yet (docs/privacy.md, "The watched folder"). They are in no other part of Today: until the
 * person lets Claude read them (or keeps them private), Ordnung doesn't know what they ask or by
 * when — so Today says they wait instead of "nothing needs you". A waiting letter never reminds on
 * its own; this card is how the person hears of it.
 */
import { Link } from "react-router";
import { motion } from "motion/react";
import { ArrowRight, Hourglass } from "lucide-react";
import { buttonVariants } from "@/components/ui/Button";
import { plural } from "@/lib/utils";
import { fadeUp } from "./motion";

/** "2 letters from your folder wait for you" / "1 letter from your folder waits for you". */
export function waitingTitle(count: number): string {
  return `${plural(count, "letter")} from your folder ${count === 1 ? "waits" : "wait"} for you`;
}

export function WaitingCard({ count }: { count: number }) {
  if (!count) return null;
  return (
    <motion.section
      variants={fadeUp}
      aria-labelledby="waiting-card-title"
      className="flex flex-wrap items-center gap-x-4 gap-y-3 rounded-[var(--radius-card)] border border-accent/25 bg-accent-soft/60 p-4 sm:p-5"
    >
      <span className="grid size-9 shrink-0 place-items-center rounded-xl bg-surface text-accent shadow-[var(--shadow-card)]">
        <Hourglass className="size-4" aria-hidden />
      </span>
      <div className="min-w-0 flex-1 basis-44">
        <h2 id="waiting-card-title" className="text-[15px] font-semibold leading-snug text-ink">
          {waitingTitle(count)}
        </h2>
        <p className="mt-0.5 text-[13.5px] leading-snug text-ink/80">
          Not read yet, so Ordnung can't tell you what {count === 1 ? "it asks" : "they ask"} or by when. Nothing has been sent to Claude.
        </p>
      </div>
      <Link to="/inbox" className={buttonVariants({ variant: "primary", size: "sm", className: "max-sm:w-full" })}>
        Review {count === 1 ? "it" : "them"}
        <ArrowRight className="size-4" aria-hidden />
      </Link>
    </motion.section>
  );
}
