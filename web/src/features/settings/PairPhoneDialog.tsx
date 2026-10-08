/**
 * "Pair a phone" (Settings → Phone): a code that pairs one phone, once, within minutes — as a QR code for the
 * phone's camera and as letters to type — and what happens with it, asked again every 2 s while the dialog is open.
 *
 * - **Waiting**: the QR code (the URL carries the code after `#`, so it never travels in a request line), the
 *   code, how long it still works, the steps per phone (with the certificate's fingerprint to compare on the
 *   warning page) and the address to type. "Your phone reached this computer" once a phone opened the page, with
 *   its address; wrong codes typed on the network, with theirs.
 * - **Phone can't connect?** opens by itself after 60 s without a phone on the page: same Wi‑Fi (not a guest
 *   network), the firewall's narrowest rule for this computer, a VPN, typing the address.
 * - **Paired**: the phone's name, browser and address, and the two words it shows — a phone showing other words
 *   isn't the person's own. "Not you? Remove" signs it out at once.
 * - **Ended**: the code expired, was used twice (neither phone stays paired), or too many wrong codes cancelled
 *   it — "Make a new code".
 *
 * Closing cancels a code nobody used. `data-pairing-url` carries the URL for the browser tests (not shown).
 */
import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { CircleCheck, Hourglass, RefreshCw, Smartphone, Unlink } from "lucide-react";
import { ApiError } from "@/api/client";
import { PHONE_POLL_MS, qk, useCancelPhonePairing, useCreatePhonePairing, usePhone, useRemovePhone } from "@/api/hooks";
import type { PhonePairing, PhoneStatus } from "@/api/types";
import { Button } from "@/components/ui/Button";
import { Callout } from "@/components/ui/Callout";
import { Dialog } from "@/components/ui/Dialog";
import { Skeleton } from "@/components/ui/Skeleton";
import { Spinner } from "@/components/ui/Spinner";
import { Tabs } from "@/components/ui/Tabs";
import { QrCode } from "@/features/girocode/GiroCode";
import { CopyCommand } from "@/features/onboarding/CopyCommand";
import { plural } from "@/lib/utils";
import {
  accessUrl,
  COMPUTER_OS_LABELS,
  computerOs,
  countdown,
  fingerprintParts,
  firewallCommands,
  formatPairingCode,
  homeSubnet,
  newDevice,
  NOTICE_TITLES,
  PAIRING_QR_SIDE,
  TROUBLESHOOT_AFTER_MS,
  type ComputerOs,
} from "./phoneAccess";
import { Disclosure, PlatformTabs } from "./PhoneParts";

/** A clock that ticks every second while `active` (the countdown, and when to offer help). */
function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [active]);
  return now;
}

/** One code and when it was made: the phones paired before it don't count as "paired with this code". */
interface Session {
  pairing: PhonePairing;
  known: ReadonlySet<string>;
  madeAt: number;
}

const OS_ORDER: ComputerOs[] = ["mac", "windows", "linux"];

/** The firewall, per system of this computer: only this address and port, only from the home network. */
function FirewallSteps({ status }: { status: PhoneStatus }) {
  const id = useId();
  const [os, setOs] = useState<ComputerOs>(() => computerOs(typeof navigator === "undefined" ? "" : navigator.userAgent));
  const address = status.address ?? "";
  const subnet = homeSubnet(status) ?? "";
  const commands = firewallCommands(address, status.port, subnet);
  return (
    <div>
      <Tabs id={id} label="This computer's system" variant="pill" value={os} onChange={setOs} items={OS_ORDER.map((o) => ({ value: o, label: COMPUTER_OS_LABELS[o] }))} />
      <div role="tabpanel" id={`${id}-panel-${os}`} aria-labelledby={`${id}-tab-${os}`} className="mt-2 space-y-2">
        {os === "mac" ? (
          <p>
            System Settings → Network → Firewall → Options…: find Python and choose <em>Allow incoming connections</em>. The rule is for that Python program — the one
            Ordnung runs with — not for every program.
          </p>
        ) : os === "windows" ? (
          <>
            <p>
              First make this Wi‑Fi a private network: Settings → Network &amp; internet → Wi‑Fi → your network → <em>Private network</em>. Then let only phone access
              in — from your home network, to {address} port {status.port} — in PowerShell run as administrator:
            </p>
            <CopyCommand command={commands.windows} label="let phone access through the firewall" />
            <p>If Windows asked about Python instead, tick “Private networks” only — never “Public”.</p>
          </>
        ) : (
          <>
            <p>If the ufw firewall is on, let only your home network ({subnet}) reach phone access:</p>
            <CopyCommand command={commands.linux} label="let phone access through the firewall" />
          </>
        )}
      </div>
    </div>
  );
}

/** "Phone can't connect?": what keeps a phone from reaching this computer. */
function Troubleshooting({ status, open, onToggle }: { status: PhoneStatus; open: boolean; onToggle: (open: boolean) => void }) {
  const url = accessUrl(status);
  return (
    <Disclosure summary="Phone can't connect?" open={open} onToggle={onToggle}>
      <ul className="list-disc space-y-2.5 pl-5 marker:text-faint">
        <li>
          <span className="font-medium text-ink">The same Wi‑Fi.</span> The phone must be on the Wi‑Fi this computer is on — not a guest network: guest networks
          and “client isolation” keep devices apart.
        </li>
        <li>
          <span className="font-medium text-ink">The firewall.</span> This computer may block phones until you allow phone access:
          <div className="mt-2">
            <FirewallSteps status={status} />
          </div>
        </li>
        <li>
          <span className="font-medium text-ink">A VPN</span> on the phone or on this computer can send the phone somewhere else: turn it off while you pair.
        </li>
        {url ? (
          <li>
            <span className="font-medium text-ink">Type the address</span> with <span className="font-mono text-[13px]">https://</span>:{" "}
            <span className="font-mono text-[13px] [overflow-wrap:anywhere]">{url}/pair</span>
          </li>
        ) : null}
      </ul>
    </Disclosure>
  );
}

/** The steps on the phone, per system: the camera, the warning page (with the fingerprint), the name. */
function PairingSteps({ status, url }: { status: PhoneStatus; url: string }) {
  const id = useId();
  const head = status.fingerprint ? fingerprintParts(status.fingerprint).head : null;
  const address = status.address ?? "this computer";
  const warning = (platform: "ios" | "android"): ReactNode => (
    <>
      Your phone warns that the connection isn't private. That's expected — Ordnung made its own certificate:{" "}
      {platform === "ios" ? (
        <>
          tap <em>Show Details</em>, then <em>visit this website</em>, then <em>Visit Website</em>.
        </>
      ) : (
        <>
          tap <em>Advanced</em>, then <em>Proceed to {address}</em>.
        </>
      )}
      {head ? (
        <>
          {" "}
          To be sure it's this computer, the certificate's SHA‑256 starts with <strong className="font-mono font-semibold text-ink">{head}</strong>.
        </>
      ) : null}
    </>
  );
  return (
    <div className="space-y-3">
      <PlatformTabs
        id={id}
        label="Your phone"
        render={(platform) => (
          <ol className="list-decimal space-y-1.5 pl-5 text-[13.5px] leading-5 text-ink/85 marker:font-medium marker:text-muted">
            <li>Open your phone's camera and point it at the code.</li>
            <li>{warning(platform)}</li>
            <li>
              Name the phone and tap <em>Pair this phone</em>.
            </li>
          </ol>
        )}
      />
      <p className="text-[13px] leading-5 text-muted">
        Can't scan? On the phone, open <span className="font-mono text-ink [overflow-wrap:anywhere]">{url}/pair</span> and type the code.
      </p>
    </div>
  );
}

/** The dialog. Mount it per opening (`key`): each opening makes one code. */
export function PairPhoneDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const phone = usePhone({ poll: open });
  const status = phone.data;
  const { mutate: createCode, ...create } = useCreatePhonePairing();
  const cancel = useCancelPhonePairing();
  const remove = useRemovePhone();
  const [session, setSession] = useState<Session | null>(null);
  const [removedName, setRemovedName] = useState<string | null>(null);
  const [troubleOpen, setTroubleOpen] = useState(false);
  const [troubleOffered, setTroubleOffered] = useState(false);
  const now = useNow(open && session !== null);

  const start = useCallback(
    () =>
      createCode(undefined, {
        onSuccess: (pairing) => {
          // the phones paired before this code (the status as last asked — the answer above asks again)
          const known = new Set((qc.getQueryData<PhoneStatus>(qk.phone)?.devices ?? []).map((d) => d.id));
          setSession({ pairing, known, madeAt: Date.now() });
        },
      }),
    [createCode, qc],
  );

  // one code per opening (the dialog is mounted anew for each)
  const started = useRef(false);
  useEffect(() => {
    if (!open || started.current) return;
    started.current = true;
    start();
  }, [open, start]);

  const pairing = session?.pairing ?? null;
  const at = Math.max(now, session?.madeAt ?? 0);
  const msLeft = pairing ? Date.parse(pairing.expires_at) - at : 0;
  const paired = session && status ? newDevice(status.devices, session.known) : null;
  // what the code ran into since it was made: used twice, or too many wrong codes on the network
  const notice =
    session && status?.notice && status.notice.code !== "token_reuse" && Date.parse(status.notice.at) >= session.madeAt - 5_000 ? status.notice : null;
  const expired = Boolean(pairing) && !paired && msLeft <= 0;
  // the server no longer has the code — in an answer a whole poll after it was made (an earlier one may have been
  // asked before the code existed): another code replaced it, or phone access stopped
  const ended = Boolean(session && status) && !paired && !notice && !expired && phone.dataUpdatedAt > session!.madeAt + PHONE_POLL_MS && !status!.pairing;
  const waiting = Boolean(pairing) && !paired && !notice && !expired && !ended && !removedName;
  const reached = waiting ? (status?.pairing?.opened_at ?? null) : null;

  // a minute without a phone on the page: open the help once (the person may close it again)
  const unreached = waiting && !reached && at - (session?.madeAt ?? at) >= TROUBLESHOOT_AFTER_MS;
  if (unreached && !troubleOffered) {
    setTroubleOffered(true);
    setTroubleOpen(true);
  }

  const again = () => {
    setRemovedName(null);
    setTroubleOpen(false);
    setTroubleOffered(false);
    remove.reset();
    start();
  };
  const close = () => {
    // a code nobody used ends now (one that paired, or that the server stopped, has nothing to cancel)
    if (session && !paired && !removedName && !notice && !expired && !ended) cancel.mutate();
    onClose();
  };
  const notMe = () => {
    if (!paired) return;
    const name = paired.name;
    remove.mutate(paired.id, { onSuccess: () => setRemovedName(name) });
  };

  const createError = create.error ? (create.error instanceof ApiError ? create.error.message : "Ordnung didn't answer. Is it still running?") : null;
  const removeError = remove.error ? (remove.error instanceof ApiError ? remove.error.message : "Ordnung didn't answer. Is it still running?") : null;
  const over = Boolean(removedName || notice || expired || ended);

  // what a screen reader hears as the state changes (the QR code and the steps aren't repeated)
  const said = removedName
    ? `Removed ${removedName}.`
    : notice
      ? `${NOTICE_TITLES[notice.code]}. ${notice.detail}`
      : paired
        ? `Paired: ${paired.name}. Your phone should show ${paired.check_words}.`
        : expired
          ? "This code expired."
          : ended
            ? "This code ended."
            : reached
              ? "Your phone reached this computer. Finish on the phone."
              : pairing
                ? "Waiting for your phone."
                : "";

  const footer = paired ? (
    <>
      <Button variant="ghost" icon={Unlink} className="text-danger-ink hover:bg-danger-soft hover:text-danger-ink sm:mr-auto" loading={remove.isPending} onClick={notMe}>
        Not you? Remove
      </Button>
      <Button variant="primary" onClick={onClose}>
        Done
      </Button>
    </>
  ) : over || createError ? (
    <>
      <Button onClick={close}>Done</Button>
      <Button variant="primary" icon={RefreshCw} loading={create.isPending} onClick={again}>
        {createError && !session ? "Try again" : "Make a new code"}
      </Button>
    </>
  ) : (
    // while a code waits, closing cancels it
    <Button onClick={close}>Cancel</Button>
  );

  return (
    <Dialog
      open={open}
      onClose={close}
      size="lg"
      title="Pair a phone"
      description="Scan the code with the phone's camera. It pairs one phone, once, and works for a few minutes."
      footer={footer}
    >
      <p role="status" className="sr-only">
        {said}
      </p>
      {createError && !session ? (
        <Callout tone="danger" alert title="Couldn't make a pairing code">
          <span className="[overflow-wrap:anywhere]">{createError}</span>
        </Callout>
      ) : !pairing || !status ? (
        <div aria-busy="true" className="flex flex-col gap-4 sm:flex-row">
          <Skeleton className="size-[205px] shrink-0 rounded-xl" />
          <div className="flex-1 space-y-3">
            <Skeleton className="h-8 w-48" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-2/3" />
          </div>
        </div>
      ) : removedName ? (
        <Callout tone="success" title={`Removed ${removedName}`}>
          It's signed out. Make a new code to pair your own phone — where nobody else can see your screen.
        </Callout>
      ) : notice ? (
        <Callout tone="danger" title={NOTICE_TITLES[notice.code]}>
          <p className="[overflow-wrap:anywhere]">{notice.detail}</p>
          <p className="mt-1">Make a new code and pair again where nobody else can see your screen.</p>
        </Callout>
      ) : paired ? (
        <div className="space-y-4">
          <div className="flex items-start gap-3">
            <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-ok-soft text-ok">
              <CircleCheck className="size-5" aria-hidden />
            </span>
            <div className="min-w-0">
              <p className="text-[16px] font-semibold leading-6 text-ink [overflow-wrap:anywhere]">Paired: {paired.name}</p>
              <p className="text-[13.5px] leading-5 text-muted [overflow-wrap:anywhere]">
                {paired.platform ? `${paired.platform} · ` : ""}
                {paired.last_address ? `from ${paired.last_address}` : "on your network"}
              </p>
            </div>
          </div>
          <Callout icon={Smartphone} title={<>Your phone should show “{paired.check_words}”</>}>
            If it shows other words — or none — it isn't your phone: remove it, then make a new code.
          </Callout>
          {removeError ? (
            <Callout tone="danger" alert title="The phone wasn't removed">
              <span className="[overflow-wrap:anywhere]">{removeError}</span>
            </Callout>
          ) : null}
        </div>
      ) : expired || ended ? (
        <Callout tone="warn" icon={Hourglass} title={expired ? "This code expired" : "This code ended"}>
          {expired
            ? "Make a new code when your phone is ready."
            : status.listening
              ? "Another code replaced it, or phone access stopped it. Make a new code to pair a phone."
              : "Phone access is off or paused, so no phone can pair now."}
        </Callout>
      ) : (
        <div className="space-y-5" data-pairing-url={pairing.url}>
          <div className="flex flex-col items-center gap-4 sm:flex-row sm:items-start sm:gap-6">
            <div className="shrink-0 rounded-xl border border-line bg-white p-2">
              <QrCode payload={pairing.url} label="Pairing code as a QR code — point your phone's camera at it" size={PAIRING_QR_SIDE} />
            </div>
            <div className="min-w-0 flex-1 space-y-3 self-stretch">
              <div>
                <p className="eyebrow">Code</p>
                <p className="font-mono text-[28px] font-semibold leading-tight tracking-[0.08em] text-ink">{formatPairingCode(pairing.code)}</p>
                <p className="mt-0.5 text-[13px] leading-5 text-muted tabular-nums">
                  Valid for <time dateTime={pairing.expires_at}>{countdown(msLeft)}</time>
                </p>
              </div>
              {reached ? (
                <p className="flex items-start gap-2 rounded-xl bg-ok-soft px-3 py-2 text-[13.5px] leading-5 text-ok-ink">
                  <CircleCheck className="mt-0.5 size-4 shrink-0" aria-hidden />
                  <span>
                    Your phone reached this computer — finish on the phone.
                    {status.pairing?.opened_from ? <span className="text-ink/80"> From {status.pairing.opened_from}.</span> : null}
                  </span>
                </p>
              ) : (
                <p className="flex items-center gap-2 text-[13.5px] leading-5 text-muted">
                  <Spinner className="size-4" />
                  Waiting for your phone…
                </p>
              )}
              {status.pairing?.wrong_tries ? (
                <p className="text-[13px] leading-5 text-warn-ink [overflow-wrap:anywhere]">
                  {plural(status.pairing.wrong_tries, "wrong code")} typed so far
                  {status.pairing.wrong_from.length ? `, from ${status.pairing.wrong_from.join(", ")}` : ""}.
                </p>
              ) : null}
            </div>
          </div>
          <PairingSteps status={status} url={accessUrl(status) ?? pairing.url.replace(/\/pair#.*$/, "")} />
          <Troubleshooting status={status} open={troubleOpen} onToggle={setTroubleOpen} />
        </div>
      )}
    </Dialog>
  );
}
