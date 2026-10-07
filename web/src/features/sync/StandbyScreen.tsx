/**
 * The standing-by screen (design §19.3): another computer is the one in use, so this one changes nothing — the app
 * shows this instead of its pages (Settings → Your computers and the privacy log stay open, under a banner).
 *
 * It says whose Ordnung is in use (or that none is: the one in use left sync) and whether everything from there has
 * arrived, and offers one button, **Use Ordnung here** (focused; never an "Are you sure?" — a take-over loses
 * nothing). While the other computer's latest
 * changes are still on their way it waits for them ("Use it here as soon as they've arrived", with Cancel and when
 * it stops waiting), or uses the copy this computer has now. A choice, a problem (the passphrase field, …) and
 * notices show here too.
 */
import { useEffect, useState } from "react";
import { Link } from "react-router";
import { ArrowRightLeft, Hourglass, Laptop, ShieldCheck, X } from "lucide-react";
import { ApiError } from "@/api/client";
import { useTakeOver } from "@/api/hooks";
import type { SyncStatus } from "@/api/types";
import { LogoMark } from "@/components/shell/Logo";
import { Button, buttonVariants } from "@/components/ui/Button";
import { Callout } from "@/components/ui/Callout";
import { toast } from "@/components/ui/Toast";
import { inUseName, olderCopyLabel, reassuranceLine, standbyHeading, standbyStatusLine, waitingLine } from "@/features/settings/sync";
import { focusWhenReady } from "@/features/today/focus";
import { cn } from "@/lib/utils";
import { ChoiceDialog } from "./ChoiceDialog";
import { ArrivingNote, ProgressLine, SyncNotices, SyncProblemCallout } from "./parts";

const ERROR_ID = "standby-error";

/** Where the standing-by screen leads without taking over (they work while standing by). */
export const STANDBY_LINKS = [
  { to: "/settings?section=computers", label: "Your computers settings", icon: Laptop },
  { to: "/settings?section=privacy", label: "Privacy log", icon: ShieldCheck },
] as const;

/** The pages that stay open while standing by (Settings → Your computers, the privacy log): no screen over them. */
export function standbyKeepsPage(pathname: string, search: string): boolean {
  if (pathname !== "/settings") return false;
  const section = new URLSearchParams(search).get("section");
  return section === "computers" || section === "privacy";
}

/** What a take-over said, once it is done: in use here now (a toast), or waiting for what is still arriving. */
function tookOverToast(after: SyncStatus, from: string) {
  if (after.mode !== "in_use") return;
  toast.success("Ordnung is in use here now", { description: after.base_from && after.base_from !== after.this_computer ? `Everything from ${after.base_from} is here.` : `${from} switches to standing by.` });
}

export function StandbyScreen({ status }: { status: SyncStatus }) {
  const takeOver = useTakeOver();
  const [choosing, setChoosing] = useState(false);
  const name = inUseName(status);
  const arriving = status.arriving;
  const waiting = status.take_over_waiting;
  const problem = status.problem;

  useEffect(() => {
    document.title = `Standing by · Ordnung`;
  }, []);

  const takeOverHere = (older = false) =>
    takeOver.mutate(older ? { older_copy: true } : {}, {
      onSuccess: (after) => tookOverToast(after, name),
      onError: () => focusWhenReady(() => document.getElementById(ERROR_ID), 5000, { always: true }),
    });
  const stopWaiting = () => takeOver.mutate({ cancel: true });

  return (
    <main id="main" tabIndex={-1} className="grid min-h-dvh place-items-center bg-canvas px-4 py-8 outline-none">
      <div className="card w-full max-w-xl px-5 py-8 sm:px-9 sm:py-10">
        <div className="flex items-center gap-2.5 text-[13px] font-medium text-muted">
          <LogoMark className="size-7" />
          <span>Standing by</span>
        </div>
        <h1 className="display mt-4 text-balance text-2xl font-semibold text-ink [overflow-wrap:anywhere]">{standbyHeading(status)}</h1>
        <p className="mt-2 text-pretty text-base leading-relaxed text-ink/85">{standbyStatusLine(status)}</p>
        <p className="mt-1 text-pretty text-[14px] leading-relaxed text-muted">{reassuranceLine(status)}</p>

        <SyncNotices notices={status.notices} className="mt-5" />

        {status.choice ? (
          <Callout
            tone="warn"
            title="Your two computers both have changes."
            className="mt-5"
            action={
              <Button size="sm" variant="primary" onClick={() => setChoosing(true)}>
                Choose…
              </Button>
            }
          >
            Nothing is lost: choose which computer's Ordnung to keep.
          </Callout>
        ) : null}

        {problem ? <SyncProblemCallout status={status} problem={problem} className="mt-5" /> : null}

        <div className="mt-6 space-y-4">
          {status.progress && (status.activity === "bringing_over" || status.activity === "keeping") ? (
            <ProgressLine progress={status.progress} what={status.activity === "keeping" ? "Keeping a copy of this computer's data" : `Bringing Ordnung over from ${name}`} />
          ) : null}
          {waiting ? (
            <Callout title={`Waiting for ${arriving?.from_computer ?? name}'s latest changes`} icon={Hourglass} action={<Button size="sm" icon={X} onClick={stopWaiting} loading={takeOver.isPending}>Cancel</Button>}>
              {arriving ? <ArrivingNote arriving={arriving} /> : null}
              <p className={cn(arriving && "mt-2")}>{waitingLine(arriving?.from_computer ?? name)}</p>
            </Callout>
          ) : (
            <>
              {arriving ? <ArrivingNote arriving={arriving} /> : null}
              {!status.choice ? (
                <Button
                  variant="primary"
                  size="lg"
                  icon={ArrowRightLeft}
                  autoFocus
                  loading={takeOver.isPending}
                  onClick={() => takeOverHere()}
                  // its longer label wraps on a narrow phone instead of widening the page (320 px): a label of
                  // its own, not the button's one-line one
                  className="h-auto! min-h-11 w-full whitespace-normal py-2.5 sm:w-auto"
                >
                  <span className="min-w-0 text-center">{arriving ? "Use it here as soon as they've arrived" : "Use Ordnung here"}</span>
                </Button>
              ) : null}
              {arriving && !status.choice ? (
                <div className="text-[13.5px] leading-5">
                  <Button variant="link" size="sm" onClick={() => takeOverHere(true)} disabled={takeOver.isPending} className="shrink whitespace-normal text-left">
                    <span className="min-w-0">{olderCopyLabel(status)}</span>
                  </Button>
                  <p className="mt-1 text-muted">
                    If you change something here before {arriving.from_computer}'s changes arrive, Ordnung will ask which computer's to keep. If you don't, they're
                    brought in by themselves when they arrive.
                  </p>
                </div>
              ) : null}
            </>
          )}
          {takeOver.error ? (
            <div id={ERROR_ID} tabIndex={-1} className="rounded-xl">
              <Callout tone="danger" alert title="Ordnung isn't in use here yet">
                <span className="[overflow-wrap:anywhere]">{takeOver.error instanceof ApiError ? takeOver.error.message : "Ordnung didn't answer. Is it still running?"}</span>
              </Callout>
            </div>
          ) : null}
        </div>

        <nav aria-label="While standing by" className="mt-8 flex flex-wrap gap-x-5 gap-y-2 border-t border-line pt-5">
          {STANDBY_LINKS.map((l) => (
            <Link key={l.to} to={l.to} className={cn(buttonVariants({ variant: "link", size: "sm" }), "gap-1.5")}>
              <l.icon className="size-4" aria-hidden />
              {l.label}
            </Link>
          ))}
        </nav>
      </div>
      <ChoiceDialog open={choosing} onClose={() => setChoosing(false)} status={status} />
    </main>
  );
}
