/**
 * Settings → Your computers → Your other computers (design §19.1, card 3): each with what it is now, when its last
 * change arrived here (this computer's clock), whether it has this computer's latest changes, what its calendar
 * sync means here, and **Forget…** for a lost, stolen or broken one. Forgetting doesn't lock a computer out: it
 * still knows the passphrase (finding 18).
 */
import { useRef, useState } from "react";
import { CalendarDays, CircleCheck, Clock, Laptop, TriangleAlert, UserX } from "lucide-react";
import { ApiError } from "@/api/client";
import { useForgetComputer } from "@/api/hooks";
import type { SyncComputer, SyncStatus } from "@/api/types";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Callout } from "@/components/ui/Callout";
import { Dialog } from "@/components/ui/Dialog";
import { toast } from "@/components/ui/Toast";
import { focusWhenReady } from "@/features/today/focus";
import { cn } from "@/lib/utils";
import { SettingsCard } from "./SettingsCard";
import { calendarLine, computerBadge, computerLine, latestLine, otherComputers } from "./sync";

const FORGET_ERROR_ID = "sync-forget-error";

/** "Forget anna-thinkpad?": a copy of its changes that are nowhere else is kept here first; it still knows the passphrase. */
function ForgetDialog({ computer, onClose }: { computer: SyncComputer | null; onClose: () => void }) {
  const forget = useForgetComputer();
  const cancelRef = useRef<HTMLButtonElement>(null);
  const name = computer?.name ?? "";
  const close = () => {
    if (forget.isPending) return;
    forget.reset();
    onClose();
  };
  const confirm = () => {
    if (!computer) return;
    forget.mutate(computer.key, {
      onSuccess: () => {
        forget.reset();
        onClose();
        toast.success(`${name} was removed from sync`, { description: "It still knows the passphrase: a new sync folder with a new passphrase locks it out." });
      },
      onError: () => focusWhenReady(() => document.getElementById(FORGET_ERROR_ID), 5000, { always: true }),
    });
  };
  return (
    <Dialog
      open={computer !== null}
      onClose={close}
      size="sm"
      title={`Forget ${name}?`}
      description="For a lost, stolen or broken computer. If it has changes that are nowhere else, a copy of them is kept on this computer first."
      initialFocus={cancelRef}
      dismissible={!forget.isPending}
      footer={
        <>
          <Button ref={cancelRef} onClick={close} disabled={forget.isPending}>
            Cancel
          </Button>
          <Button variant="danger" icon={UserX} loading={forget.isPending} onClick={confirm}>
            Forget
          </Button>
        </>
      }
    >
      <div className="space-y-4 text-[13.5px] leading-relaxed text-ink/85">
        <Callout tone="warn" title="Forgetting doesn't lock it out">
          {name} still knows the passphrase. To lock it out of future changes, start a new sync folder with a new passphrase (Disconnect, then set up again).
        </Callout>
        {forget.error ? (
          <div id={FORGET_ERROR_ID} tabIndex={-1} className="rounded-xl">
            <Callout tone="danger" alert title="Nothing was changed">
              <span className="[overflow-wrap:anywhere]">{forget.error instanceof ApiError ? forget.error.message : "Ordnung didn't answer. Is it still running?"}</span>
            </Callout>
          </div>
        ) : null}
      </div>
    </Dialog>
  );
}

/** One other computer of this sync. */
function ComputerRow({ computer, version, onForget }: { computer: SyncComputer; version: string | null; onForget: () => void }) {
  const badge = computerBadge(computer);
  const latest = latestLine(computer);
  const calendar = calendarLine(computer);
  return (
    <li className="flex flex-col gap-3 py-3.5 first:pt-0 last:pb-0 sm:flex-row sm:items-start">
      <span className="grid size-9 shrink-0 place-items-center rounded-xl bg-surface-2 text-muted" aria-hidden>
        <Laptop className="size-[18px]" />
      </span>
      <div className="min-w-0 flex-1 space-y-1 text-[13.5px] leading-5">
        <p className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className="min-w-0 font-semibold text-ink [overflow-wrap:anywhere]">{computer.name}</span>
          <Badge tone={badge.tone} dot>
            {badge.label}
          </Badge>
        </p>
        <p className="flex items-start gap-1.5 text-muted">
          <Clock className="mt-0.5 size-3.5 shrink-0" aria-hidden />
          {computerLine(computer)}
        </p>
        {latest ? (
          <p className={cn("flex items-start gap-1.5", latest.tone === "ok" ? "text-ok-ink" : "text-warn-ink")}>
            {latest.tone === "ok" ? <CircleCheck className="mt-0.5 size-3.5 shrink-0" aria-hidden /> : <TriangleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden />}
            {latest.text}
          </p>
        ) : null}
        {calendar ? (
          <p className="flex items-start gap-1.5 text-muted">
            <CalendarDays className="mt-0.5 size-3.5 shrink-0" aria-hidden />
            {calendar}
          </p>
        ) : null}
        {version && computer.app_version && computer.app_version !== version ? (
          <p className="text-muted">
            Runs Ordnung {computer.app_version} (this computer: {version}). Keep your computers on the same version.
          </p>
        ) : null}
      </div>
      {!computer.in_use ? (
        <Button size="sm" variant="ghost" icon={UserX} onClick={onForget} className="self-start">
          Forget…
        </Button>
      ) : null}
    </li>
  );
}

/** Your other computers: one row each, or how to add one. */
export function ComputersListCard({ status }: { status: SyncStatus }) {
  const [forgetting, setForgetting] = useState<SyncComputer | null>(null);
  const others = otherComputers(status);
  const version = status.computers.find((c) => c.this)?.app_version ?? null;
  return (
    <SettingsCard title="Your other computers" id="sync-other-computers">
      {others.length ? (
        <ul className="divide-y divide-line">
          {others.map((c) => (
            <ComputerRow key={c.key} computer={c} version={version} onForget={() => setForgetting(c)} />
          ))}
        </ul>
      ) : (
        <p className="text-[13.5px] leading-5 text-muted">
          No other computer has joined yet. On your other computer, choose “I already use Ordnung on another computer” when you set it up — or Settings → Your
          computers there — with the same folder and passphrase.
        </p>
      )}
      <ForgetDialog computer={forgetting} onClose={() => setForgetting(null)} />
    </SettingsCard>
  );
}
