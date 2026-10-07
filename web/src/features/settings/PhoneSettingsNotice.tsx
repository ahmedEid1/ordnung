/**
 * Settings on a paired phone: they live on the computer. The phone may not read or change them (the API refuses
 * with `computer_only`), so this asks for none of them — it says what the phone can do, how to remove it, and
 * offers the step that stops the certificate warning.
 *
 * That step (trusting the authority Ordnung made) is offered only where the phone's browser keeps the authority to
 * the computer's address — iOS and iPadOS, Chrome on Android ({@link trustStepPlatform}); anywhere else it would
 * let the authority vouch for more than Ordnung, so the phone warns once per certificate instead. Once trusted, a
 * warning means someone else is answering.
 */
import { Download, ShieldCheck, TriangleAlert } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { buttonVariants } from "@/components/ui/Button";
import { Callout } from "@/components/ui/Callout";
import { PageHeader } from "@/components/shell/Page";
import { AFTER_TRUST_WARNING, CERTIFICATE_PATH, INSTALL_STEPS, REMOVE_STEPS, TRUST_PLATFORM_LABELS, trustStepPlatform, type TrustPlatform } from "./phoneAccess";
import { Disclosure } from "./PhoneParts";
import { SettingsCard } from "./SettingsCard";

/** What a paired phone can do, and where everything else is. */
export const PHONE_SETTINGS_TEXT =
  "This phone can read your letters, add new ones, write letters and tick off to‑dos. Settings, backups, phone access and deleting stay in Ordnung on your computer. To remove this phone, open Settings → Phone there.";

/** The browser this page runs in (its user agent and touch points), for where the trust step is offered. */
function thisBrowser(): { userAgent: string; maxTouchPoints: number } {
  if (typeof navigator === "undefined") return { userAgent: "", maxTouchPoints: 0 };
  return { userAgent: navigator.userAgent, maxTouchPoints: navigator.maxTouchPoints ?? 0 };
}

/** "Stop the security warning": why, how (this phone's steps), and how to undo it. */
function TrustStep({ platform }: { platform: TrustPlatform }) {
  return (
    <SettingsCard
      title={
        <span className="flex flex-wrap items-center gap-2">
          Stop the security warning
          <Badge tone="accent" size="sm">
            Recommended
          </Badge>
        </span>
      }
      id="phone-trust"
      description="Optional, and best done at home: trust the certificate Ordnung made on your computer, and this phone opens Ordnung without a warning. It vouches for your computer's address only — never for your router, another device or any website."
    >
      <div className="space-y-4 text-[14px] leading-relaxed text-ink/85">
        <ol className="list-decimal space-y-2 pl-5 marker:font-medium marker:text-muted">
          {INSTALL_STEPS[platform].map((step) => (
            <li key={step}>{step}</li>
          ))}
        </ol>
        <a href={CERTIFICATE_PATH} download className={buttonVariants({ variant: "primary", className: "w-full sm:w-auto" })}>
          <Download aria-hidden />
          Download the certificate
        </a>
        <Callout tone="warn" icon={TriangleAlert} title="Afterwards">
          {AFTER_TRUST_WARNING}
        </Callout>
        <Disclosure summary="Remove it again">
          <p>
            {TRUST_PLATFORM_LABELS[platform]}: {REMOVE_STEPS[platform]}
          </p>
          <p>Remove it too when this phone is removed on your computer, or phone access starts over there.</p>
        </Disclosure>
      </div>
    </SettingsCard>
  );
}

/** Where the trust step isn't offered: the warning stays, once per certificate — and how to check it. */
function NoTrustStep() {
  return (
    <SettingsCard title="The security warning" id="phone-trust">
      <p className="text-[14px] leading-relaxed text-ink/85">
        This browser can't keep a trusted certificate to your computer's address, so Ordnung doesn't offer to install one here. It warns once per certificate: before you
        continue, check that the certificate's fingerprint matches the one in Settings → Phone on your computer.
      </p>
    </SettingsCard>
  );
}

/** The Settings page on a paired phone (rendered instead of every section, before any settings query). */
export function PhoneSettingsNotice({ browser = thisBrowser() }: { browser?: { userAgent: string; maxTouchPoints: number } }) {
  const platform = trustStepPlatform(browser.userAgent, browser.maxTouchPoints);
  return (
    <>
      <PageHeader title="Settings are on your computer" description={PHONE_SETTINGS_TEXT} />
      <div className="max-w-3xl space-y-5">
        <p className="flex items-start gap-2 text-[13.5px] leading-5 text-muted">
          <ShieldCheck className="mt-0.5 size-4 shrink-0 text-ok" aria-hidden />
          Your letters stay on your computer: this phone only shows them, over your home Wi‑Fi, while the computer is on and Ordnung is running.
        </p>
        {platform ? <TrustStep platform={platform} /> : <NoTrustStep />}
      </div>
    </>
  );
}
