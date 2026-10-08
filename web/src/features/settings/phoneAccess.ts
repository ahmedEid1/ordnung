/**
 * Settings → Phone: the words, numbers and small rules its cards share (pure, so tests pin them).
 *
 * - The pairing code as people read it, its countdown, the certificate's fingerprint in two parts.
 * - The status line ("On · https://192.168.178.23:8767 · 1 phone paired, Anna's iPhone active now").
 * - The firewall's narrow rules for this address, port and home network — never "allow Python everywhere".
 * - Where the optional "Stop the security warning" step is offered: only on phones whose browser keeps the
 *   certificate to this computer's address (its name constraint) — a device check before release (design §19.1).
 * - How to install the certificate on a phone, and how to remove it again (after Start over, Delete everything,
 *   or a new address, which makes a new certificate).
 */
import type { PhoneDevice, PhoneNoticeCode, PhoneStatus } from "@/api/types";
import { NB_HYPHEN } from "@/lib/glue";
import { plural } from "@/lib/utils";

/** How long the pairing dialog waits for a phone to open the page before "Phone can't connect?" opens by itself. */
export const TROUBLESHOOT_AFTER_MS = 60_000;
/** How long Settings mentions a new certificate to phones paired before it ("your phone will warn once more"). */
export const NEW_CERTIFICATE_DAYS = 7;
/** The window of "changes from this phone" (`PhoneDevice.recent_changes`, counted by the API). */
export const RECENT_CHANGES_DAYS = 30;
/** About how wide the pairing QR code is drawn (CSS px): a phone camera reads it across a desk. */
export const PAIRING_QR_SIDE = 232;
/** Bytes of a fingerprint shown in bold: 64 bits nobody can forge while you compare them. */
export const FINGERPRINT_SHOWN_BYTES = 8;

const DAY_MS = 86_400_000;

/** What the attention line on Today and the dot on Settings call a notice (its detail says the rest). */
export const NOTICE_TITLES: Record<PhoneNoticeCode, string> = {
  pairing_stopped: "A pairing code was cancelled",
  code_reused: "A pairing code was used twice",
  token_reuse: "A phone was signed out",
};

/** "K7QM2XD9PA" → "K7QM2‑XD9PA": two halves to read out, joined by a hyphen that never breaks the line. */
export function formatPairingCode(code: string): string {
  const c = code.replace(/[\s\-‑]/g, "").toUpperCase();
  return c.length > 5 ? `${c.slice(0, 5)}${NB_HYPHEN}${c.slice(5)}` : c;
}

/** Time left on a code: "9:41", "0:05", "0:00". */
export function countdown(msLeft: number): string {
  const s = Math.max(0, Math.ceil(msLeft / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/** A fingerprint's first bytes (shown in bold, enough to compare) and the rest ("Show all"). */
export function fingerprintParts(fingerprint: string, bytes = FINGERPRINT_SHOWN_BYTES): { head: string; rest: string } {
  const all = fingerprint.trim().split(/\s+/);
  return { head: all.slice(0, bytes).join(" "), rest: all.slice(bytes).join(" ") };
}

/** The phone a pairing just added: one that wasn't paired when the code was made. */
export function newDevice(devices: readonly PhoneDevice[], known: ReadonlySet<string>): PhoneDevice | null {
  return devices.find((d) => !known.has(d.id)) ?? null;
}

/** Where phones reach Ordnung: the listening address, else the saved one. */
export function accessUrl(status: Pick<PhoneStatus, "url" | "address" | "port">): string | null {
  return status.url ?? (status.address ? `https://${status.address}:${status.port}` : null);
}

/**
 * One line under the switch: "On · https://192.168.178.23:8767 · 1 phone paired, Anna's iPhone active now",
 * "Paused · …" while a problem keeps phones out, "Off · 2 phones paired" (they stay paired while it is off).
 */
export function accessLine(status: Pick<PhoneStatus, "enabled" | "listening" | "url" | "address" | "port" | "devices">): string {
  const n = status.devices.length;
  const phones = n ? `${plural(n, "phone")} paired` : "no phone paired yet";
  if (!status.enabled) return n ? `Off · ${phones}` : "Off";
  const active = status.listening ? status.devices.filter((d) => d.active) : [];
  const now = active.length === 1 ? `, ${active[0]!.name} active now` : active.length > 1 ? `, ${active.length} active now` : "";
  return [status.listening ? "On" : "Paused", accessUrl(status), `${phones}${now}`].filter(Boolean).join(" · ");
}

/**
 * The certificate changed in the last {@link NEW_CERTIFICATE_DAYS} days and a phone paired before that will warn
 * once more (a phone paired after it never saw the old one).
 */
export function certificateNewsFor(status: Pick<PhoneStatus, "certificate_changed_at" | "devices">, now = Date.now()): boolean {
  const at = status.certificate_changed_at ? Date.parse(status.certificate_changed_at) : Number.NaN;
  if (!Number.isFinite(at) || now - at > NEW_CERTIFICATE_DAYS * DAY_MS) return false;
  return status.devices.some((d) => Date.parse(d.paired_at) < at);
}

/** The port to offer when another program has this one (`port_busy`). */
export function nextPort(port: number): number {
  return port >= 65535 ? 1024 : port + 1;
}

/** The home network phone access answers ("192.168.178.0/24"): as saved, else the address's /24. */
export function homeSubnet(status: Pick<PhoneStatus, "subnet" | "address">): string | null {
  if (status.subnet) return status.subnet;
  return status.address ? `${status.address.replace(/\.\d+$/, ".0")}/24` : null;
}

// ------------------------------------------------------------------------------------------------
// The firewall: only this address and port, only from the home network
// ------------------------------------------------------------------------------------------------

export type ComputerOs = "mac" | "windows" | "linux";

export const COMPUTER_OS_LABELS: Record<ComputerOs, string> = { mac: "Mac", windows: "Windows", linux: "Linux" };

/** Which computer this is (the browser on it), for the firewall steps it needs first. */
export function computerOs(userAgent: string): ComputerOs {
  if (/Windows/i.test(userAgent)) return "windows";
  if (/Mac OS X|Macintosh/i.test(userAgent)) return "mac";
  return "linux";
}

/**
 * The narrowest firewall rules for phone access: inbound TCP to this address and port only, from the home
 * network only — Windows only on a private network profile.
 */
export function firewallCommands(address: string, port: number, subnet: string): { windows: string; linux: string } {
  return {
    windows: `New-NetFirewallRule -DisplayName "Ordnung phone access" -Direction Inbound -Protocol TCP -LocalAddress ${address} -LocalPort ${port} -RemoteAddress LocalSubnet -Profile Private -Action Allow`,
    linux: `sudo ufw allow in from ${subnet} to ${address} port ${port} proto tcp`,
  };
}

// ------------------------------------------------------------------------------------------------
// The optional trust step on a phone, and removing the certificate again
// ------------------------------------------------------------------------------------------------

export type TrustPlatform = "ios" | "android";

/** Phones the trust step is offered on, in words (Settings on the computer says where to find it). */
export const TRUST_STEP_WHERE = "an iPhone or iPad, or an Android phone in Chrome";

/** Android browsers that bring their own certificate store or engine (not yet checked to keep the constraint). */
const OTHER_ANDROID_BROWSERS = /SamsungBrowser|Firefox|OPR\/|EdgA|YaBrowser|UCBrowser|MiuiBrowser|HuaweiBrowser|DuckDuckGo|; wv\)/;

/**
 * Whether this phone's browser keeps a trusted certificate to this computer's address (the authority's name
 * constraint), so offering to trust it can't let it stand in for the router or any other device: iOS and iPadOS
 * (every browser there uses the system's checks) and Chrome on Android. Anything else gets no offer — it warns
 * once per certificate instead. DEVICE CHECK (design §19.1 #4): widen or narrow this list from the device tests.
 */
export function trustStepPlatform(userAgent: string, maxTouchPoints = 0): TrustPlatform | null {
  if (/\b(iPhone|iPad|iPod)\b/.test(userAgent)) return "ios";
  // iPadOS asks for the desktop site: a Mac that has a touch screen is an iPad
  if (/Macintosh/.test(userAgent) && maxTouchPoints > 1) return "ios";
  if (/Android/.test(userAgent) && /Chrome\/\d+/.test(userAgent) && !OTHER_ANDROID_BROWSERS.test(userAgent)) return "android";
  return null;
}

export const TRUST_PLATFORM_LABELS: Record<TrustPlatform, string> = { ios: "iPhone and iPad", android: "Android" };

/** Where a phone serves the authority to trust (the phone listener's gate, to a paired phone only). */
export const CERTIFICATE_PATH = "/ordnung-certificate.crt";

/** What the certificate is called on the phone (a neutral name: the whole network sees it). */
export const CERTIFICATE_NAME = "Home network certificate";

/** Installing the authority, step by step (the wording follows each system's menus; DEVICE CHECK §19.1 #9). */
export const INSTALL_STEPS: Record<TrustPlatform, string[]> = {
  ios: [
    "Tap Download the certificate, then Allow.",
    `Open Settings → General → VPN & Device Management and tap “${CERTIFICATE_NAME}”. Tap More Details: its SHA‑256 must match the authority's fingerprint in Settings → Phone on your computer. Only then tap Install.`,
    `Open Settings → General → About → Certificate Trust Settings and turn on “${CERTIFICATE_NAME}”.`,
  ],
  android: [
    "Tap Download the certificate.",
    "Open Settings, search for “CA certificate”, tap Install anyway and choose the file you just downloaded.",
    "Under Trusted credentials → User, tap the certificate: its SHA‑256 must match the authority's fingerprint in Settings → Phone on your computer. If it doesn't, remove it.",
  ],
};

/** Removing the authority from a phone (after Start over, Delete everything or a new address). */
export const REMOVE_STEPS: Record<TrustPlatform, string> = {
  ios: `Settings → General → VPN & Device Management → “${CERTIFICATE_NAME}” → Remove Profile.`,
  android: `Settings → search for “User credentials” (or Trusted credentials → User) → “${CERTIFICATE_NAME}” → Remove.`,
};

/** After trusting it: a warning means another device is answering in the computer's place. */
export const AFTER_TRUST_WARNING = "Once a phone trusts the certificate, it opens Ordnung without a warning. If it ever warns again, someone else is answering — don't continue.";
