/**
 * Settings → Phone → "Paired phones": each phone that can open Ordnung — its name and browser, the two words it
 * showed when it paired (a phone showing other words isn't this one), when and from where it was last used,
 * whether it has Ordnung open now, and what it changed lately (linking to the privacy log of that phone).
 *
 * "Remove…" asks first, naming what the phone changed in the last 30 days; the phone is signed out at once.
 */
import { useState } from "react";
import { Link } from "react-router";
import { Smartphone, Unlink } from "lucide-react";
import { ApiError } from "@/api/client";
import { useRemovePhone } from "@/api/hooks";
import type { PhoneDevice, PhoneStatus } from "@/api/types";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Callout } from "@/components/ui/Callout";
import { Dialog } from "@/components/ui/Dialog";
import { toast } from "@/components/ui/Toast";
import { focusWhenReady } from "@/features/today/focus";
import { formatDate, formatTimeAgo } from "@/lib/format";
import { useTodayISO } from "@/lib/today";
import { plural } from "@/lib/utils";
import { deviceActivityHref } from "./logic";
import { RECENT_CHANGES_DAYS } from "./phoneAccess";
import { SettingsCard } from "./SettingsCard";

export const DEVICES_HEADING_ID = "phone-devices";

/** "3 changes from this phone in the last 30 days" (or none). */
export function recentChangesLine(n: number): string {
  return n ? `${plural(n, "change")} from this phone in the last ${RECENT_CHANGES_DAYS} days` : `No changes from this phone in the last ${RECENT_CHANGES_DAYS} days`;
}

/** "Paired 7 Oct · last used 2 h ago from 192.168.178.31". */
function usedLine(d: PhoneDevice, today: string): string {
  const paired = `Paired ${formatDate(d.paired_at, { style: "day", today })}`;
  if (!d.last_seen_at) return paired;
  return `${paired} · last used ${formatTimeAgo(d.last_seen_at)}${d.last_address ? ` from ${d.last_address}` : ""}`;
}

/** "Remove Anna's iPhone?": what it changed lately, and the refusal in place. */
function RemovePhoneDialog({ device, onClose }: { device: PhoneDevice | null; onClose: () => void }) {
  const remove = useRemovePhone();
  // the phone stays named while the dialog closes
  const [shown, setShown] = useState(device);
  if (device && device !== shown) setShown(device);
  const close = () => {
    if (remove.isPending) return;
    remove.reset();
    onClose();
  };
  const confirm = () => {
    if (!shown) return;
    const name = shown.name;
    remove.mutate(shown.id, {
      onSuccess: () => {
        remove.reset();
        onClose();
        toast.success(`Removed ${name}`, { description: "It's signed out. To use Ordnung on it again, pair it again." });
        // the row (and its button) went: the list's heading takes the focus
        focusWhenReady(() => document.getElementById(DEVICES_HEADING_ID));
      },
    });
  };
  const error = remove.error ? (remove.error instanceof ApiError ? remove.error.message : "Ordnung didn't answer. Is it still running?") : null;
  const changes = shown?.recent_changes ?? 0;
  return (
    <Dialog
      open={device !== null}
      onClose={close}
      size="sm"
      title={`Remove ${shown?.name ?? "this phone"}?`}
      description="It is signed out at once. Letters it sent stay in Ordnung."
      dismissible={!remove.isPending}
      footer={
        <>
          <Button onClick={close} disabled={remove.isPending}>
            Cancel
          </Button>
          <Button variant="danger" icon={Unlink} loading={remove.isPending} onClick={confirm}>
            Remove
          </Button>
        </>
      }
    >
      <div className="space-y-3 text-[13.5px] leading-5 text-ink/85">
        <p>
          {recentChangesLine(changes)}
          {changes && shown ? (
            <>
              {" "}
              —{" "}
              <Link to={deviceActivityHref(shown.id)} onClick={close} className="font-medium text-accent hover:underline">
                see what it changed
              </Link>
            </>
          ) : null}
          .
        </p>
        {error ? (
          <Callout tone="danger" alert title="The phone wasn't removed">
            <span className="[overflow-wrap:anywhere]">{error}</span>
          </Callout>
        ) : null}
      </div>
    </Dialog>
  );
}

function DeviceRow({ device: d, onRemove }: { device: PhoneDevice; onRemove: () => void }) {
  const today = useTodayISO();
  return (
    <li className="flex flex-wrap items-start gap-x-3 gap-y-2 px-3.5 py-3 sm:px-4">
      <span className="mt-0.5 grid size-8 shrink-0 place-items-center rounded-lg bg-surface-2 text-muted">
        <Smartphone className="size-4" aria-hidden />
      </span>
      <div className="min-w-0 flex-1 basis-48">
        <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[14px] font-medium leading-5 text-ink">
          <span className="min-w-0 [overflow-wrap:anywhere]">{d.name}</span>
          {d.active ? (
            <Badge tone="ok" dot>
              Active now
            </Badge>
          ) : null}
        </p>
        <p className="mt-0.5 text-[13px] leading-5 text-muted [overflow-wrap:anywhere]">
          {d.platform ? `${d.platform} · ` : ""}showed <span className="font-medium text-ink/85">“{d.check_words}”</span> when it paired
        </p>
        <p className="text-[13px] leading-5 text-muted [overflow-wrap:anywhere]">{usedLine(d, today)}</p>
        {d.recent_changes ? (
          <Link to={deviceActivityHref(d.id)} className="mt-0.5 inline-flex min-h-6 items-center text-[13px] font-medium text-accent hover:underline">
            {plural(d.recent_changes, "change")} in the last {RECENT_CHANGES_DAYS} days{" "}
            <span className="sr-only">from {d.name}</span>
          </Link>
        ) : null}
      </div>
      <Button size="sm" variant="ghost" icon={Unlink} onClick={onRemove} aria-label={`Remove ${d.name}…`}>
        Remove…
      </Button>
    </li>
  );
}

/** The paired phones, each with "Remove…" (an empty card says none is paired yet). */
export function PhoneDevicesCard({ status }: { status: PhoneStatus }) {
  const [removing, setRemoving] = useState<PhoneDevice | null>(null);
  return (
    <SettingsCard
      title="Paired phones"
      id={DEVICES_HEADING_ID}
      description="Each phone signs in on its own. Remove one and it is signed out at once; what it added or changed stays in Ordnung."
    >
      {status.devices.length ? (
        <ul aria-labelledby={DEVICES_HEADING_ID} className="divide-y divide-line rounded-xl border border-line">
          {status.devices.map((d) => (
            <DeviceRow key={d.id} device={d} onRemove={() => setRemoving(d)} />
          ))}
        </ul>
      ) : (
        <p className="rounded-xl border border-dashed border-line-strong px-4 py-3 text-sm leading-5 text-muted">No phone is paired yet.</p>
      )}
      <RemovePhoneDialog device={removing} onClose={() => setRemoving(null)} />
    </SettingsCard>
  );
}
