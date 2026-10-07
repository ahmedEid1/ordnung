/**
 * Phone access in the mock (`src/mocks/phone.ts`): this computer's addresses, the limits and every sentence the
 * API answers with (`src/ordnung/api/routes/phone.py`, the phone listener's gate). The static demo has no
 * computer to reach, so it says so ({@link PHONE_STATIC_MESSAGE}).
 */
import type { AddressChoice, PhoneNoticeCode, PhoneProblemCode } from "@/api/types";

/** The static demo's answer: there is no computer a phone could reach. */
export const PHONE_STATIC_MESSAGE = "The online demo can't connect a phone. Install Ordnung to use it from your phone at home.";
/** `ordnung demo`'s answer (the API's `DEMO_MESSAGE`): the demo never listens on the network. */
export const PHONE_DEMO_MESSAGE = "The demo never opens itself to your network. Install Ordnung to use it from your phone.";

/** `POST /api/phone/pair` sent to the computer's own listener (404 `not_phone`). */
export const NOT_PHONE_MESSAGE = "Pairing works from a phone: scan the code in Settings → Phone with your phone's camera.";
/** Every request but pairing from a phone without a valid sign-in (401 `phone_not_paired`). */
export const PHONE_NOT_PAIRED_MESSAGE = "This phone isn't paired with Ordnung any more. Pair it again from Settings → Phone on your computer.";
/** An operation the phone's allow-list leaves out (403 `computer_only`). */
export const COMPUTER_ONLY_MESSAGE = "This works on your computer only.";
/** `DELETE /api/phone/devices/{id}` for a phone that isn't paired (404). */
export const NO_SUCH_PHONE_MESSAGE = "This phone isn't paired (any more).";
/** One answer for a wrong, expired or missing code (422 `wrong_code`), so a guess learns nothing. */
export const WRONG_CODE_MESSAGE = "That code didn't match, or it has expired.";
/** A code that already paired a phone (409 `code_used`): neither device stays paired. */
export const CODE_USED_MESSAGE = "This code was already used, so neither phone is paired. Make a new code on your computer and pair again.";
/** Too many wrong codes from one device for the open code (429 `too_many`). */
export const TOO_MANY_TRIES_MESSAGE = "Too many wrong codes from this phone. Make a new code on your computer and try again.";
/** The most phones are paired (409 `too_many_phones`). */
export const TOO_MANY_PHONES_MESSAGE = "Ordnung already has 10 phones paired. Remove one in Settings → Phone on your computer.";
/** A pairing code asked for while no phone can reach this computer (409 `not_listening`). */
export const NOT_LISTENING_MESSAGE = "Phone access is off or paused, so no phone can pair now.";
/** Pairing while phone access is off (409 `unavailable`). */
export const PHONE_OFF_MESSAGE = "Phone access is turned off on your computer.";
/** Turning it on with no home network (409 `no_network`). */
export const NO_NETWORK_MESSAGE = "This computer isn't on a home network right now.";
/** An address that isn't one of this computer's on a home network (422 `invalid`). */
export const INVALID_ADDRESS_MESSAGE = "That address isn't one of this computer's on a home network. Choose one of the addresses listed.";
/** A port out of range (422 `invalid`). */
export const INVALID_PORT_MESSAGE = "Choose a port from 1024 to 65535.";

/** The port phone access uses unless the person chose another. */
export const PHONE_DEFAULT_PORT = 8767;
/** Phones Ordnung pairs at most. */
export const MAX_PHONES = 10;
/** How long a pairing code works. */
export const PAIRING_TTL_MS = 10 * 60_000;
/** Wrong codes one device may type for the open code before it is locked out of it. */
export const PAIRING_TRIES_PER_CLIENT = 5;
/** Wrong codes from the whole network before the code is cancelled (and the computer told who typed them). */
export const PAIRING_TRIES_TOTAL = 100;
/** How long a notice stays on the computer. */
export const NOTICE_MS = 10 * 60_000;
/** How long the server certificate lasts (the most phones accept). */
export const CERTIFICATE_DAYS = 397;
/** The code's letters: Crockford's base 32 (no I, L, O or U). */
export const CODE_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
export const CODE_LENGTH = 10;

/** This computer's addresses on home networks: the Wi-Fi first (recommended), then a wired second network. */
export const PHONE_ADDRESSES: AddressChoice[] = [
  { address: "192.168.178.23", interface: "en0", subnet: "192.168.178.0/24", recommended: true },
  { address: "192.168.0.40", interface: "en7", subnet: "192.168.0.0/24", recommended: false },
];
/** Where the mock's own phone (the phone listener's client) asks from. */
export const THIS_PHONE_ADDRESS = "192.168.178.31";
/** What the mock calls a phone's browser (the API derives it from the User-Agent). */
export const PHONE_PLATFORM = "iPhone · Safari";
/** The phone a phone-listener mock answers for, paired before the page opened. */
export const THIS_PHONE_NAME = "Sam's iPhone";

/** Why phone access is on but not listening, as the API words it. */
export function problemDetail(code: PhoneProblemCode, address: string | null, port: number): string {
  switch (code) {
    case "no_network":
      return "Waiting for a home network.";
    case "address_gone":
      return `Paused: this computer isn't on ${address ?? "its address"} any more.`;
    case "other_network":
      return `Paused: this computer is on ${address ?? "its address"}, but on a different network than before.`;
    case "port_busy":
      return `Another program uses port ${port}.`;
    case "failed":
      return "Phone access couldn't start.";
  }
}

/** A notice on the computer, as the API words it. */
export function noticeDetail(code: PhoneNoticeCode, addresses: string[], name?: string): string {
  switch (code) {
    case "pairing_stopped":
      return `${PAIRING_TRIES_TOTAL} wrong pairing codes were typed on your network, so the code was cancelled. They came from ${addresses.join(", ") || "an unknown address"}.`;
    case "code_reused":
      return "Two devices used the same code, so neither is paired. Someone else may have seen your screen.";
    case "token_reuse":
      return `${name ?? "A phone"} was signed out because its sign-in was used from two places. Pair it again if it's yours.`;
  }
}

/** The two words a phone and the computer both show for a pairing (the API derives them from the phone's id). */
export const CHECK_ADJECTIVES = ["amber", "brave", "calm", "dusty", "eager", "fuzzy", "gentle", "hollow", "ivory", "jolly", "keen", "lucky", "misty", "noble", "olive", "proud"];
export const CHECK_NOUNS = ["tulip", "otter", "harbor", "maple", "comet", "pebble", "falcon", "willow", "lantern", "meadow", "orchid", "river", "saffron", "thistle", "violet", "walnut"];
