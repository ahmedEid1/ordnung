import { useState } from "react";
import { Link } from "react-router";
import { ArrowRightLeft, Hourglass, Laptop, Split } from "lucide-react";
import { useSync, useTakeOver } from "@/api/hooks";
import type { SyncStatus } from "@/api/types";
import { Button } from "@/components/ui/Button";
import { toast } from "@/components/ui/Toast";
import { usePhoneCompanion } from "@/features/phone/client";
import { inUseName } from "@/features/settings/sync";
import { ChoiceDialog } from "@/features/sync/ChoiceDialog";
import { cn } from "@/lib/utils";
import { SHELL_GUTTERS, shellWidth } from "./layout";
import { usePageMeta } from "./page-meta";

/** What the banner says now (null: nothing). */
export function bannerKind(status: SyncStatus | undefined): "standby" | "choice" | "bringing" | null {
  if (!status?.connected) return null;
  if (status.mode === "standing_by") return "standby";
  if (status.choice) return "choice";
  if (status.activity === "bringing_over") return "bringing";
  return null;
}

const LINK = "font-medium text-accent underline underline-offset-2 hover:no-underline";

/**
 * Hand-off sync's line under the top bar, next to the "Claude paused" one (design §19.4):
 * - **both computers changed**: "Your two computers both have changes. Nothing is lost: choose which to keep." —
 *   Choose… opens the choice; the person can keep working meanwhile;
 * - **standing by**, on the pages that stay open then (Settings → Your computers, the privacy log): whose Ordnung is
 *   in use, and "Use Ordnung here";
 * - **bringing a late change over** on the computer in use: writes wait a moment.
 *
 * Never on a phone (sync is the computer's).
 */
export function SyncBanner() {
  const phone = usePhoneCompanion();
  const { data: status } = useSync(!phone);
  const { width } = usePageMeta();
  const takeOver = useTakeOver();
  const [choosing, setChoosing] = useState(false);
  const kind = phone ? null : bannerKind(status);
  // always there while there is a status, so it closes itself when the choice goes (and a later choice never
  // opens it by itself)
  const dialog = status && !phone ? <ChoiceDialog open={choosing} onClose={() => setChoosing(false)} status={status} /> : null;
  if (!kind || !status) return dialog;
  const name = inUseName(status);
  const warn = kind !== "bringing";
  const Icon = kind === "choice" ? Split : kind === "standby" ? Laptop : Hourglass;
  const takeOverHere = () =>
    takeOver.mutate(
      {},
      {
        onSuccess: (after) => (after.mode === "in_use" ? toast.success("Ordnung is in use here now") : undefined),
        onError: (err) => toast.error("Ordnung isn't in use here yet", { description: err instanceof Error ? err.message : undefined }),
      },
    );
  return (
    <>
      <div role="status" className={cn("border-b py-2.5 text-base", warn ? "border-warn/25 bg-warn-soft" : "border-accent/20 bg-accent-soft/70")}>
        <div className={cn("mx-auto flex w-full flex-wrap items-center gap-x-3 gap-y-2", SHELL_GUTTERS, shellWidth(width))}>
          <p className="flex min-w-0 flex-1 basis-64 items-start gap-2.5 text-balance text-ink/90">
            <Icon className={cn("mt-0.5 size-4 shrink-0", warn ? "text-warn" : "text-accent")} aria-hidden />
            {kind === "choice" ? (
              <span>
                <span className="font-semibold text-warn-ink">Your two computers both have changes.</span> Nothing is lost: choose which to keep.
              </span>
            ) : kind === "standby" ? (
              <span>
                <span className="font-semibold text-warn-ink">Ordnung is in use on {name}.</span> This computer is standing by: it changes nothing until you use Ordnung here.{" "}
                <Link to="/settings?section=computers" className={LINK}>
                  Your computers
                </Link>
              </span>
            ) : (
              <span>
                <span className="font-semibold text-ink">Bringing over a change from {status.arriving?.from_computer ?? "your other computer"}</span> — one moment; changes wait until it's in.
              </span>
            )}
          </p>
          {kind === "choice" || (kind === "standby" && status.choice) ? (
            <Button size="sm" variant="primary" onClick={() => setChoosing(true)}>
              Choose…
            </Button>
          ) : kind === "standby" ? (
            <Button size="sm" variant="primary" icon={ArrowRightLeft} loading={takeOver.isPending} onClick={takeOverHere}>
              Use Ordnung here
            </Button>
          ) : null}
        </div>
      </div>
      {dialog}
    </>
  );
}
