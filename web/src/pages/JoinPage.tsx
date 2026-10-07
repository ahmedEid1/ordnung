/**
 * `/join` (design §19.2): "I already use Ordnung on another computer" — bring that Ordnung over instead of setting
 * up a new one. Outside the app shell, like `/welcome` (the onboarding redirect doesn't apply: the other computer's
 * profile comes along). The setup card in its joining form, then what is arriving; once Ordnung is in use here, the
 * app opens with everything from the other computer.
 */
import { useEffect } from "react";
import { Link } from "react-router";
import { ArrowLeft, CircleCheck } from "lucide-react";
import { useSync } from "@/api/hooks";
import type { SyncStatus } from "@/api/types";
import { Logo } from "@/components/shell/Logo";
import { buttonVariants } from "@/components/ui/Button";
import { LoadError } from "@/components/ui/LoadError";
import { LoadingLabel, SkeletonText } from "@/components/ui/Skeleton";
import { Toaster } from "@/components/ui/Toast";
import { pageLoad } from "@/features/phone/platform";
import { SyncSetupCard } from "@/features/settings/SyncSetupCard";
import { inUseName, waitingLine } from "@/features/settings/sync";
import { ArrivingNote, ProgressLine, SyncProblemCallout } from "@/features/sync/parts";

/** Joined, and in use here with nothing left to bring over: the app can open. */
export function joinDone(status: SyncStatus | undefined): boolean {
  return Boolean(status?.connected && status.mode === "in_use" && status.activity === "idle" && !status.take_over_waiting);
}

/** After joining: what is still arriving or being brought over, and a problem if one stops it. */
function Bringing({ status }: { status: SyncStatus }) {
  const from = status.arriving?.from_computer ?? inUseName(status);
  return (
    <div className="card space-y-4 p-5 sm:p-7">
      <h2 className="text-[17px] font-semibold text-ink">Bringing Ordnung over from {from}</h2>
      {status.progress ? <ProgressLine progress={status.progress} what="Brought over" /> : null}
      {status.arriving ? <ArrivingNote arriving={status.arriving} /> : null}
      {status.take_over_waiting ? <p className="text-[13.5px] leading-5 text-muted">{waitingLine(from)}</p> : null}
      {!status.progress && !status.arriving ? (
        <p role="status" className="text-[13.5px] leading-5 text-ink/85">
          Putting everything in place…
        </p>
      ) : null}
      {status.problem ? <SyncProblemCallout status={status} problem={status.problem} /> : null}
    </div>
  );
}

export default function JoinPage() {
  const sync = useSync();
  const status = sync.data;
  const done = joinDone(status);

  useEffect(() => {
    document.title = "Bring Ordnung over · Ordnung";
  }, []);
  // in use here: open the app with everything from the other computer (a full load: nothing cached from before)
  useEffect(() => {
    if (done) pageLoad.assign("/");
  }, [done]);

  return (
    <div className="relative flex min-h-dvh flex-col overflow-x-hidden bg-canvas">
      <header className="relative mx-auto flex w-full max-w-2xl items-center justify-between gap-4 px-4 pb-4 pt-6 sm:px-6">
        <Logo />
      </header>
      <main id="main" tabIndex={-1} className="relative mx-auto flex w-full max-w-2xl flex-1 flex-col gap-5 px-4 pb-16 outline-none sm:px-6">
        <div>
          <h1 className="display text-balance text-2xl font-semibold text-ink">I already use Ordnung on another computer</h1>
          <p className="mt-2 text-pretty text-base leading-relaxed text-muted">
            Bring that Ordnung here: your letters, dates, settings and profile come along. Ordnung is then in use on this computer, and the other one stands by.
          </p>
        </div>
        {sync.isPending ? (
          <div aria-busy="true" className="card p-6">
            <LoadingLabel>Loading…</LoadingLabel>
            <SkeletonText lines={4} />
          </div>
        ) : sync.isError || !status ? (
          <LoadError what="hand-off sync" error={sync.error} onRetry={() => void sync.refetch()} retrying={sync.isFetching} headingLevel={2} />
        ) : done ? (
          <p role="status" className="card flex items-center gap-2 p-5 text-[15px] font-medium text-ok-ink">
            <CircleCheck className="size-5 shrink-0" aria-hidden /> Ordnung is in use on this computer — opening it…
          </p>
        ) : status.connected ? (
          <Bringing status={status} />
        ) : (
          <SyncSetupCard status={status} join />
        )}
        {!status?.connected ? (
          <Link to="/welcome" className={buttonVariants({ variant: "ghost", className: "self-start" })}>
            <ArrowLeft aria-hidden />
            Set up a new Ordnung instead
          </Link>
        ) : null}
      </main>
      <Toaster />
    </div>
  );
}
