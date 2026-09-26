import { CirclePause } from "lucide-react";
import { useEvents } from "@/api/sse";

/**
 * Shown while the AI worker is paused (Claude usage limit): letters stay safely queued and are
 * read automatically once the pause is over.
 */
export function PausedBanner() {
  const { paused } = useEvents();
  if (!paused) return null;
  const until = new Date(paused.until);
  const when = Number.isNaN(until.getTime())
    ? "a little while"
    : until.toLocaleString("en-GB", { weekday: "short", hour: "2-digit", minute: "2-digit" });
  return (
    <div role="status" className="border-b border-warn/25 bg-warn-soft px-4 py-2.5 text-base md:px-8">
      <div className="mx-auto flex max-w-6xl items-start gap-2.5">
        <CirclePause className="mt-0.5 size-4 shrink-0 text-warn" aria-hidden />
        <p className="text-ink/90">
          <span className="font-semibold text-warn-ink">Claude is taking a break until {when}.</span>{" "}
          {paused.reason ? `${paused.reason} ` : ""}Your letters are safe in the queue and will be read automatically — nothing gets lost.
        </p>
      </div>
    </div>
  );
}
