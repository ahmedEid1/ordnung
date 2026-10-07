/**
 * The phone's side of the browser: what to call this phone when it pairs, whether this tab came from the phone
 * listener before the server said so, and the page loads the pairing flow makes.
 */
import { clientKind } from "@/api/clientKind";
import { isStaticDemo } from "@/mocks/mode";

/** What a phone is called when its name can't be guessed (the person can change it before pairing). */
export const DEFAULT_PHONE_NAME = "Phone";

/**
 * A first name for this phone in the pairing form: "iPhone", "iPad", "Android phone" or "Android tablet" from the
 * browser's User-Agent (an iPad asks for the desktop site, so it says "Macintosh" with a touch screen). Never the
 * User-Agent itself: the computer lists phones by this name.
 */
export function guessDeviceName(userAgent: string = navigator.userAgent, touchPoints: number = navigator.maxTouchPoints ?? 0): string {
  if (/\biPhone\b/.test(userAgent)) return "iPhone";
  if (/\biPad\b/.test(userAgent) || (/\bMacintosh\b/.test(userAgent) && touchPoints > 1)) return "iPad";
  if (/\bAndroid\b/.test(userAgent)) return /\bMobile\b/.test(userAgent) ? "Android phone" : "Android tablet";
  return DEFAULT_PHONE_NAME;
}

/**
 * This tab is a phone's: the server said so (`Health.client`, a `phone_not_paired` refusal), or — before it could
 * (the first health check failed) — the page came over HTTPS, which only the phone listener speaks (the computer's
 * own listener is plain HTTP on 127.0.0.1; the online demo is HTTPS but has no computer behind it).
 */
export function servedToPhone(): boolean {
  if (clientKind() === "phone") return true;
  return typeof window !== "undefined" && window.location.protocol === "https:" && !isStaticDemo();
}

/**
 * Full page loads (they drop what the tab had cached): after pairing, and when the computer removed this phone.
 * An object, so a test can replace them (jsdom can't navigate).
 */
export const pageLoad = {
  /** Open `url` in place of this page (Back doesn't return to it). */
  replace(url: string): void {
    window.location.replace(url);
  },
  /** Open `url` (Back returns here). */
  assign(url: string): void {
    window.location.assign(url);
  },
};
