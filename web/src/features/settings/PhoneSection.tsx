/**
 * Settings → Phone (computer only): use Ordnung in a phone's browser over the home Wi‑Fi (design §13.1, with the
 * security review's amendments).
 *
 * - **Use Ordnung on your phone**: what it is, three facts, the switch. Turning it on asks first — at which
 *   address (this computer's home networks, the one it reaches the internet from recommended; never a VPN), with the
 *   one-time certificate warning and the firewall said up front. The line under it: on, paused or off, the address,
 *   the phones paired and active. A pause says why and offers the way on: another address, another port, "This is
 *   my home network" (the same address on a different network), or wait.
 * - A **notice** in the danger tone when someone else may be involved: a pairing code used twice (neither phone
 *   stays paired), a phone's sign-in used from two places, wrong codes that cancelled a code (with their addresses).
 * - **Pair a phone** (while phones can reach it), **Paired phones**, **Certificate** — each its own card.
 * - After "Start over" or a new address (a new certificate), how to remove the old certificate from a phone.
 *
 * Never in the demo: the switch is off and says why (the API's `unavailable_reason`).
 */
import { useEffect, useId, useState } from "react";
import { Copy, Laptop, QrCode as QrIcon, RefreshCw, Wifi, X, type LucideIcon } from "lucide-react";
import { ApiError } from "@/api/client";
import { useChangePhoneAccess, usePhone, useUpdatePhone } from "@/api/hooks";
import type { AddressChoice, PhoneAccessChange, PhoneStatus } from "@/api/types";
import { Badge } from "@/components/ui/Badge";
import { Button, IconButton } from "@/components/ui/Button";
import { Callout } from "@/components/ui/Callout";
import { Dialog } from "@/components/ui/Dialog";
import { Switch } from "@/components/ui/Field";
import { LoadError } from "@/components/ui/LoadError";
import { LoadingLabel, SkeletonText } from "@/components/ui/Skeleton";
import { toast } from "@/components/ui/Toast";
import { copyText } from "@/features/document/actions";
import { focusWhenReady } from "@/features/today/focus";
import { cn } from "@/lib/utils";
import { PairPhoneDialog } from "./PairPhoneDialog";
import { PhoneCertificateCard, StartOverDialog } from "./PhoneCertificateCard";
import { PhoneDevicesCard } from "./PhoneDevicesCard";
import { RemoveCertificateSteps } from "./PhoneParts";
import { accessLine, nextPort, NOTICE_TITLES } from "./phoneAccess";
import { SectionHeading, SettingsCard } from "./SettingsCard";

const DESCRIPTION =
  "Open Ordnung in your phone's browser while it's on the same Wi‑Fi as this computer: photograph letters, see what's due, tick things off and pay. Your letters stay on this computer; the phone only shows them, while this computer is on and Ordnung is running.";

const FACTS: { icon: LucideIcon; text: string }[] = [
  { icon: QrIcon, text: "Only phones you pair here" },
  { icon: Wifi, text: "Home network only — nothing goes over the internet" },
  { icon: Laptop, text: "Settings, backups and deleting stay on this computer" },
];

const ADVICE_ID = "phone-certificate-advice";

/** Why to remove the old certificate from phones now: phone access started over, or a new address made a new one. */
type Advice = "reset" | "address";

const failed = (err: unknown) => (err instanceof ApiError ? err.message : "Ordnung didn't answer. Is it still running?");

/** "192.168.178.23 · Wi‑Fi (en0) · 192.168.178.0/24": one address to choose. */
function AddressRadio({ choice, checked, onChoose, name }: { choice: AddressChoice; checked: boolean; onChoose: () => void; name: string }) {
  return (
    <label
      className={cn(
        "flex cursor-pointer items-start gap-3 rounded-xl border px-3 py-2.5 transition-colors",
        "has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-accent",
        checked ? "border-accent/60 bg-accent-soft/50 shadow-[0_0_0_1px_var(--color-accent)]" : "border-line hover:border-line-strong",
      )}
    >
      <input type="radio" name={name} value={choice.address} checked={checked} onChange={onChoose} className="mt-1 size-4 shrink-0 accent-[var(--color-accent)]" />
      <span className="min-w-0 flex-1">
        <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className="font-mono text-[14px] font-medium text-ink">{choice.address}</span>
          {choice.recommended ? (
            <Badge tone="accent" size="sm">
              Recommended
            </Badge>
          ) : null}
        </span>
        <span className="block text-[12.5px] leading-5 text-muted [overflow-wrap:anywhere]">
          {choice.interface ? `${choice.interface} · ` : ""}network {choice.subnet}
        </span>
      </span>
    </label>
  );
}

/**
 * "Turn on phone access?" (or "Use another address?"): the address phones will reach, chosen when this computer has
 * several; what the phone and the firewall will ask; and — for a new address — that phones pair again.
 */
function AccessDialog({
  open,
  mode,
  preset,
  status,
  onClose,
  onDone,
}: {
  open: boolean;
  mode: "on" | "address";
  preset: string | null;
  status: PhoneStatus;
  onClose: () => void;
  onDone: (before: PhoneStatus, after: PhoneStatus) => void;
}) {
  const update = useChangePhoneAccess();
  const name = useId();
  const choices = [...status.addresses].sort((a, b) => Number(b.recommended) - Number(a.recommended));
  const offered = (address: string | null | undefined) => (address && choices.some((c) => c.address === address) ? address : null);
  // turning on: the saved address while it is still this computer's, else the recommended one; moving: another one
  const fallback =
    offered(preset) ?? (mode === "on" ? offered(status.address) : offered(choices.find((c) => c.address !== status.address)?.address)) ?? choices[0]?.address ?? null;
  const [picked, setPicked] = useState<string | null>(null);
  const chosen = picked && choices.some((c) => c.address === picked) ? picked : fallback;
  const moving = status.address !== null && chosen !== null && chosen !== status.address;
  const close = () => {
    if (update.isPending) return;
    update.reset();
    setPicked(null);
    onClose();
  };
  const confirm = () => {
    if (!chosen) return;
    const before = status;
    update.mutate(
      { enabled: true, address: chosen },
      {
        onSuccess: (after) => {
          update.reset();
          setPicked(null);
          onDone(before, after);
        },
      },
    );
  };
  return (
    <Dialog
      open={open}
      onClose={close}
      size="md"
      title={mode === "on" ? "Turn on phone access?" : "Use another address?"}
      dismissible={!update.isPending}
      footer={
        <>
          <Button onClick={close} disabled={update.isPending}>
            Cancel
          </Button>
          <Button variant="primary" loading={update.isPending} disabled={!chosen} onClick={confirm}>
            {mode === "on" ? "Turn on" : "Use this address"}
          </Button>
        </>
      }
    >
      <div className="space-y-4 text-[14px] leading-relaxed text-ink/85">
        {chosen ? (
          <p>
            Phones on your home network will reach Ordnung at{" "}
            <strong className="font-mono font-semibold text-ink [overflow-wrap:anywhere]">
              https://{chosen}:{status.port}
            </strong>
            . Only phones you pair here can open it.
          </p>
        ) : (
          <Callout tone="warn" title="No home network">
            This computer isn't on a home network right now, so phones can't reach it. Connect it to your Wi‑Fi, then try again.
          </Callout>
        )}
        {choices.length > 1 ? (
          <fieldset>
            <legend className="mb-2 text-sm font-medium text-ink">Which network do your phones use?</legend>
            <div className="space-y-1.5">
              {choices.map((c) => (
                <AddressRadio key={c.address} choice={c} name={name} checked={c.address === chosen} onChoose={() => setPicked(c.address)} />
              ))}
            </div>
          </fieldset>
        ) : null}
        {chosen ? <p>Make sure this computer is on your home Wi‑Fi now — not a café's, a hotel's or a VPN: phones reach it on this network only.</p> : null}
        {moving && status.devices.length ? (
          <Callout tone="warn" title="Phones pair again">
            {status.devices.length === 1 ? "The phone" : `The ${status.devices.length} phones`} paired at {status.address} will need to pair again at the new
            address. A phone that trusted the certificate for {status.address} should remove it: the new address gets a new one.
          </Callout>
        ) : null}
        {mode === "on" ? (
          <ul className="list-disc space-y-1.5 pl-5 text-[13.5px] leading-5 marker:text-faint">
            <li>Your phone will warn once that the connection isn't private: Ordnung made its own certificate, so no company vouches for it.</li>
            <li>Your computer's firewall may ask whether Python may accept incoming connections: allow it on private networks only.</li>
          </ul>
        ) : null}
        {update.error ? (
          <Callout tone="danger" alert title={mode === "on" ? "Phone access didn't turn on" : "The address didn't change"}>
            <span className="[overflow-wrap:anywhere]">{failed(update.error)}</span>
          </Callout>
        ) : null}
      </div>
    </Dialog>
  );
}

/** A pause, in words, with the way on. */
function ProblemCallout({ status, onUseAddress }: { status: PhoneStatus; onUseAddress: (address: string) => void }) {
  const update = useUpdatePhone();
  const [waiting, setWaiting] = useState(false);
  const problem = status.problem;
  if (!problem) return null;
  const pairAgain = status.devices.length ? " Phones paired before will need to pair again." : "";
  const other = [...status.addresses].sort((a, b) => Number(b.recommended) - Number(a.recommended)).find((a) => a.address !== status.address);
  const change = (body: PhoneAccessChange, done: string) => update.mutate(body, { onSuccess: (s) => (s.listening ? toast.success(done) : undefined) });
  switch (problem.code) {
    case "no_network":
      return (
        <Callout tone="warn" title={problem.detail}>
          Phone access starts again by itself when this computer is back on a home network.
        </Callout>
      );
    case "address_gone":
      return (
        <Callout
          tone="warn"
          title={problem.detail}
          action={
            other && !waiting ? (
              <>
                <Button size="sm" variant="primary" onClick={() => onUseAddress(other.address)}>
                  Use {other.address} instead
                </Button>
                <Button size="sm" onClick={() => setWaiting(true)}>
                  Keep waiting
                </Button>
              </>
            ) : undefined
          }
        >
          {waiting || !other
            ? `Phone access starts again by itself when this computer is back on ${status.address ?? "its address"}.`
            : `Ordnung never moves to another address by itself: it can't tell a café's network from yours. If this computer has a new address at home, use it.${pairAgain}`}
        </Callout>
      );
    case "other_network":
      return (
        <Callout
          tone="warn"
          title={problem.detail}
          action={
            <Button size="sm" variant="primary" loading={update.isPending} onClick={() => change({ enabled: true, home_network: true }, "Phone access is on again")}>
              This is my home network
            </Button>
          }
        >
          The router answering now isn't the one phone access was turned on with — perhaps a café's or a friend's network that hands out the same address. Phone access
          waits until this computer is home again. A new router at home? Then say so.
        </Callout>
      );
    case "port_busy": {
      const port = nextPort(status.port);
      return (
        <Callout
          tone="warn"
          title={problem.detail}
          action={
            <Button size="sm" variant="primary" loading={update.isPending} onClick={() => change({ enabled: true, port }, `Phone access is on at port ${port}`)}>
              Use port {port}
            </Button>
          }
        >
          {`Phone access can use the next port instead.${pairAgain}`}
        </Callout>
      );
    }
    case "failed":
      return (
        <Callout
          tone="danger"
          title={problem.detail}
          action={
            <Button size="sm" icon={RefreshCw} loading={update.isPending} onClick={() => change({ enabled: true }, "Phone access is on")}>
              Try again
            </Button>
          }
        >
          Ordnung's log on this computer says why.
        </Callout>
      );
  }
}

/** What the person must know at once (danger), with the addresses involved when the words don't name them. */
function NoticeCallout({ status, onPair, onDismiss }: { status: PhoneStatus; onPair: () => void; onDismiss: () => void }) {
  const notice = status.notice;
  if (!notice) return null;
  const unnamed = notice.addresses.filter((a) => !notice.detail.includes(a));
  return (
    <Callout
      tone="danger"
      alert
      title={NOTICE_TITLES[notice.code]}
      action={
        <>
          {status.listening ? (
            <Button size="sm" variant="primary" icon={QrIcon} onClick={onPair}>
              Pair a phone
            </Button>
          ) : null}
          <Button size="sm" variant="ghost" icon={X} onClick={onDismiss}>
            Dismiss
          </Button>
        </>
      }
    >
      <p className="[overflow-wrap:anywhere]">{notice.detail}</p>
      {unnamed.length ? <p className="mt-1 [overflow-wrap:anywhere]">Addresses involved: {unnamed.join(", ")}.</p> : null}
    </Callout>
  );
}

/** After Start over or a new address: remove the old certificate from phones that trusted it. */
function CertificateAdvice({ advice, onDismiss }: { advice: Advice; onDismiss: () => void }) {
  const stepsId = useId();
  return (
    <div id={ADVICE_ID} tabIndex={-1} className="rounded-xl outline-none">
      <Callout
        title={advice === "reset" ? "Phone access started over" : "New address, new certificate"}
        action={
          <Button size="sm" variant="ghost" icon={X} onClick={onDismiss}>
            Got it
          </Button>
        }
      >
        <p>
          {advice === "reset"
            ? "Every phone was removed and the certificate deleted. If a phone trusted Ordnung's certificate, remove it there too:"
            : "Phones pair again at the new address. A phone that trusted the old certificate should remove it — after pairing, it can trust the new one from its Settings:"}
        </p>
        <div className="mt-2">
          <RemoveCertificateSteps id={stepsId} />
        </div>
      </Callout>
    </div>
  );
}

/** The section once the status is in. */
function PhoneAccess({ status }: { status: PhoneStatus }) {
  const update = useUpdatePhone();
  // the access dialog keeps its words while it closes (`access` is what it was last opened for)
  const [access, setAccess] = useState<{ mode: "on" | "address"; preset: string | null }>({ mode: "on", preset: null });
  const [accessOpen, setAccessOpen] = useState(false);
  const openAccess = (mode: "on" | "address", preset: string | null = null) => {
    setAccess({ mode, preset });
    setAccessOpen(true);
  };
  // the pairing dialog is mounted anew for each opening (one code each)
  const [pairOpen, setPairOpen] = useState(false);
  const [pairKey, setPairKey] = useState(0);
  const [startingOver, setStartingOver] = useState(false);
  const [advice, setAdvice] = useState<Advice | null>(null);
  const [dismissed, setDismissed] = useState<string | null>(null);
  const showNotice = status.notice !== null && status.notice.at !== dismissed;

  const openPairing = () => {
    setPairKey((k) => k + 1);
    setPairOpen(true);
  };
  const onSwitch = (on: boolean) => {
    if (on) {
      openAccess("on");
      return;
    }
    update.mutate(
      { enabled: false },
      {
        onSuccess: (s) =>
          toast.success("Phone access is off", {
            description: s.devices.length ? "Paired phones stay paired: they reach Ordnung again when you turn it back on." : "No phone can reach Ordnung now.",
          }),
      },
    );
  };
  const accessDone = (before: PhoneStatus, after: PhoneStatus) => {
    const mode = access.mode;
    setAccessOpen(false);
    // a new address makes a new certificate authority: phones that trusted the old one should drop it
    if (before.ca_fingerprint && after.ca_fingerprint !== before.ca_fingerprint) setAdvice("address");
    if (after.listening) toast.success(mode === "on" ? "Phone access is on" : "Phone access moved", { description: `Phones on your home network reach Ordnung at ${after.url}.` });
  };

  // the answer to "Start over" is in: the advice takes the focus the gone "Start over…" button had
  useEffect(() => {
    if (advice === "reset") focusWhenReady(() => document.getElementById(ADVICE_ID), 5000, { always: true });
  }, [advice]);

  return (
    <div className="space-y-5">
      {showNotice ? <NoticeCallout status={status} onPair={openPairing} onDismiss={() => setDismissed(status.notice?.at ?? null)} /> : null}
      {advice ? <CertificateAdvice advice={advice} onDismiss={() => setAdvice(null)} /> : null}

      <SettingsCard title="Use Ordnung on your phone" id="phone-access" description={DESCRIPTION}>
        <ul className="grid gap-2 sm:grid-cols-3">
          {FACTS.map((f) => (
            <li key={f.text} className="flex min-w-0 items-start gap-2 rounded-xl bg-surface-2/60 px-3 py-2.5 text-[13.5px] leading-5 text-ink/85">
              <f.icon className="mt-0.5 size-4 shrink-0 text-accent" aria-hidden />
              <span className="min-w-0">{f.text}</span>
            </li>
          ))}
        </ul>
        <div className="mt-5 space-y-3 border-t border-line pt-5">
          <Switch checked={status.enabled} onCheckedChange={onSwitch} disabled={!status.available || update.isPending} label="Phone access" />
          {!status.available ? (
            <p role="note" className="rounded-lg bg-surface-2/70 px-3 py-2 text-[13px] leading-5 text-muted">
              {status.unavailable_reason ?? "Phone access can't be used here."}
            </p>
          ) : (
            <div className="flex items-start gap-1">
              <p className="min-w-0 flex-1 text-[13.5px] leading-6 text-ink/85 [overflow-wrap:anywhere]">{accessLine(status)}</p>
              {status.listening && status.url ? (
                <IconButton icon={Copy} label="Copy the address" size="sm" variant="ghost" className="-my-1 shrink-0 text-muted" onClick={() => void copyText(status.url!, "The address")} />
              ) : null}
            </div>
          )}
          {status.available && status.enabled ? <ProblemCallout status={status} onUseAddress={(address) => openAccess("address", address)} /> : null}
          {status.available && status.enabled && !status.problem && status.addresses.length > 1 ? (
            <Button variant="link" size="sm" onClick={() => openAccess("address")}>
              Use another address…
            </Button>
          ) : null}
        </div>
      </SettingsCard>

      {status.available && status.listening ? (
        <SettingsCard
          title="Pair a phone"
          id="phone-pair"
          description="Show a code here and scan it with the phone's camera. A code pairs one phone, once, within minutes — pair where nobody else can see your screen."
          footer={
            <Button variant="primary" icon={QrIcon} onClick={openPairing}>
              Pair a phone
            </Button>
          }
        >
          <p className="text-[13.5px] leading-5 text-muted">The phone warns about the certificate first. That's expected: the steps say what to tap, and how to tell it's this computer.</p>
        </SettingsCard>
      ) : null}

      {status.available && (status.enabled || status.devices.length) ? <PhoneDevicesCard status={status} /> : null}
      {status.available ? <PhoneCertificateCard status={status} onStartOver={() => setStartingOver(true)} /> : null}

      <AccessDialog
        open={accessOpen}
        mode={access.mode}
        preset={access.preset}
        status={status}
        onClose={() => setAccessOpen(false)}
        onDone={accessDone}
      />
      <PairPhoneDialog key={pairKey} open={pairOpen} onClose={() => setPairOpen(false)} />
      <StartOverDialog
        open={startingOver}
        onClose={() => setStartingOver(false)}
        onDone={() => {
          setStartingOver(false);
          setAdvice("reset");
        }}
      />
    </div>
  );
}

/** Settings → Phone. */
export function PhoneSection() {
  const phone = usePhone();
  return (
    <section aria-labelledby="set-phone">
      <SectionHeading
        id="set-phone"
        title="Phone"
        description="Use Ordnung in your phone's browser at home: the phone shows what's on this computer and adds to it — nothing is copied to the phone or the internet."
      />
      {phone.isPending ? (
        <div aria-busy="true" className="card p-6">
          <LoadingLabel>Loading phone access…</LoadingLabel>
          <SkeletonText lines={5} />
        </div>
      ) : phone.isError || !phone.data ? (
        <LoadError what="phone access" error={phone.error} onRetry={() => void phone.refetch()} retrying={phone.isFetching} headingLevel={3} />
      ) : (
        <PhoneAccess status={phone.data} />
      )}
    </section>
  );
}
