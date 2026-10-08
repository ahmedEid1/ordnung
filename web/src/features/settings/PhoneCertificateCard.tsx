/**
 * Settings → Phone → "Certificate": the certificate phone access made on this computer — when, until when, and its
 * fingerprints, so the person can tell this computer from anyone else answering on the network.
 *
 * - The certificate's and its authority's SHA-256: the first 8 bytes in bold (enough to compare), "Show all".
 * - "Your phone will warn once more" after a new certificate, to phones paired before it.
 * - Why a phone warns at all; where the optional trust step is offered (iPhone, iPad, Chrome on Android: phones
 *   that keep the authority to this computer's address) and what a warning means after it; how to remove it.
 * - "Start over": off, every phone removed, the certificate deleted (a new one next time) — after which the person
 *   is told to remove the old certificate from phones that trusted it.
 */
import { useId, useState } from "react";
import { RotateCcw } from "lucide-react";
import { ApiError } from "@/api/client";
import { useResetPhone } from "@/api/hooks";
import type { PhoneStatus } from "@/api/types";
import { Button } from "@/components/ui/Button";
import { Callout } from "@/components/ui/Callout";
import { Dialog } from "@/components/ui/Dialog";
import { formatDate } from "@/lib/format";
import { useTodayISO } from "@/lib/today";
import { AFTER_TRUST_WARNING, certificateNewsFor, fingerprintParts, TRUST_STEP_WHERE } from "./phoneAccess";
import { Disclosure, RemoveCertificateSteps } from "./PhoneParts";
import { SettingsCard } from "./SettingsCard";

/** The card's heading (focus goes here when the card comes back). */
export const CERTIFICATE_HEADING_ID = "phone-certificate";

/** A fingerprint: its first bytes in bold, the rest behind "Show all". */
function Fingerprint({ label, value, note }: { label: string; value: string; note?: string }) {
  const [all, setAll] = useState(false);
  const { head, rest } = fingerprintParts(value);
  const restId = useId();
  return (
    <div className="min-w-0">
      <dt className="text-[13px] leading-5 text-muted">{label}</dt>
      <dd className="mt-0.5 font-mono text-[13px] leading-6 text-ink [overflow-wrap:anywhere]">
        <strong className="font-semibold">{head}</strong>
        {rest ? (
          <>
            {all ? (
              <span id={restId}> {rest}</span>
            ) : (
              <span aria-hidden className="text-muted">
                {" "}
                …
              </span>
            )}{" "}
            <button
              type="button"
              aria-expanded={all}
              aria-controls={all ? restId : undefined}
              onClick={() => setAll(!all)}
              className="inline-flex min-h-6 items-center font-sans text-[12.5px] font-medium text-accent hover:underline"
            >
              {all ? "Show fewer" : "Show all"}
            </button>
          </>
        ) : null}
      </dd>
      {note ? <dd className="mt-0.5 text-[12.5px] leading-5 text-muted">{note}</dd> : null}
    </div>
  );
}

/**
 * "Start over": the confirmation, and the refusal in place. It lives with the section (the certificate card goes
 * away with the certificate); `onDone` runs once phone access started over.
 */
export function StartOverDialog({ open, onClose, onDone }: { open: boolean; onClose: () => void; onDone: () => void }) {
  const reset = useResetPhone();
  const close = () => {
    if (reset.isPending) return;
    reset.reset();
    onClose();
  };
  const error = reset.error ? (reset.error instanceof ApiError ? reset.error.message : "Ordnung didn't answer. Is it still running?") : null;
  return (
    <Dialog
      open={open}
      onClose={close}
      size="sm"
      title="Start over with phone access?"
      description="Phone access turns off, every phone is removed and this certificate is deleted; turning it on again makes a new one. Phones that trust the old certificate should remove it."
      dismissible={!reset.isPending}
      footer={
        <>
          <Button onClick={close} disabled={reset.isPending}>
            Cancel
          </Button>
          <Button variant="danger" icon={RotateCcw} loading={reset.isPending} onClick={() => reset.mutate(undefined, { onSuccess: () => onDone() })}>
            Start over
          </Button>
        </>
      }
    >
      {error ? (
        <Callout tone="danger" alert title="Nothing changed">
          <span className="[overflow-wrap:anywhere]">{error}</span>
        </Callout>
      ) : null}
    </Dialog>
  );
}

/** The certificate card (nothing before phone access made one). `onStartOver` opens {@link StartOverDialog}. */
export function PhoneCertificateCard({ status, onStartOver }: { status: PhoneStatus; onStartOver: () => void }) {
  const today = useTodayISO();
  const removeId = useId();
  if (!status.fingerprint || !status.ca_fingerprint) return null;
  const fmt = (iso: string | null) => formatDate(iso, { style: "medium", today });
  return (
    <SettingsCard
      title="Certificate"
      id={CERTIFICATE_HEADING_ID}
      description="Phone access uses a certificate Ordnung made on this computer, so no company vouches for it: a phone warns once. Its fingerprint tells this computer from anything else on your network."
      footer={
        <Button variant="ghost" size="sm" icon={RotateCcw} className="text-danger-ink hover:bg-danger-soft hover:text-danger-ink" onClick={onStartOver}>
          Start over…
        </Button>
      }
    >
      <div className="space-y-4">
        <p className="text-[13.5px] leading-5 text-ink/85">
          {status.certificate_changed_at ? <>Made on {fmt(status.certificate_changed_at)}</> : "Made by Ordnung"}
          {status.certificate_until ? <> · renews by itself before {fmt(status.certificate_until)}</> : null}
        </p>
        {certificateNewsFor(status) ? (
          <Callout title={`New certificate since ${formatDate(status.certificate_changed_at, { style: "day", today })}`}>
            A phone paired before then warns once more. Compare the fingerprint below before you continue on it.
          </Callout>
        ) : null}
        <dl className="grid gap-3">
          <Fingerprint label="This computer's certificate (SHA‑256)" value={status.fingerprint} />
          <Fingerprint
            label="The authority that issues it — what a phone can trust (SHA‑256)"
            value={status.ca_fingerprint}
            note={status.ca_made_at ? `Made on ${fmt(status.ca_made_at)} for ${status.address ?? "this computer's address"} only.` : undefined}
          />
        </dl>
        <div className="space-y-2">
          <Disclosure summary="Why does my phone warn me?">
            <p>
              Websites get their certificates from companies every browser trusts. Ordnung runs on your computer at home, with no such company behind it, so it made its own
              — and your phone says it can't tell who vouches for it. That is expected once per certificate.
            </p>
            <p>To be sure it's this computer: the certificate your phone shows has the fingerprint above. If it differs, something else is answering — don't continue.</p>
          </Disclosure>
          <Disclosure summary="Stop the warning on a phone (recommended)">
            <p>
              On {TRUST_STEP_WHERE}, open Settings in Ordnung on the phone after pairing: it offers to trust the authority above. The authority vouches for this computer's
              address only ({status.address ?? "the address phone access uses"}) — never for your router, another device or any website.
            </p>
            <p>{AFTER_TRUST_WARNING}</p>
            <p>Other phones aren't offered this step: they warn once per certificate.</p>
          </Disclosure>
          <Disclosure summary="Remove the certificate from a phone">
            <p>A phone that trusted Ordnung's certificate keeps it after you remove the phone here, start over or delete everything. To remove it:</p>
            <RemoveCertificateSteps id={removeId} />
          </Disclosure>
        </div>
      </div>
    </SettingsCard>
  );
}
