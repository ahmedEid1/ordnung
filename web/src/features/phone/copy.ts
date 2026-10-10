/**
 * Words that depend on where the person is: on the computer Ordnung runs on, "this computer" is true; on a paired
 * phone it isn't (the letters are on the computer, not on the phone in their hand), so the same sentence says
 * "your computer". What only the computer does says where to do it instead.
 *
 * Pure strings: `api/client.ts`, `app/queryClient.ts` and components all use them (components pass
 * `usePhoneCompanion()`).
 */
import { PHONE_UNREACHABLE } from "@/api/client";

export { PHONE_UNREACHABLE };

/** "this computer" on the computer, "your computer" on a phone. */
export function theComputer(phone: boolean): string {
  return phone ? "your computer" : "this computer";
}

/** The privacy line under every "Add letters": the files go to the computer, never further. */
export function filesStay(phone: boolean): string {
  return `Your files stay on ${theComputer(phone)}.`;
}

/** The last-resort error screen on a phone (the computer's says "on this computer"). */
export const PHONE_SAFE = "Your letters and dates are safe on your computer. Please reload the page.";

/** The offline toast's title on a phone. */
export const PHONE_OFFLINE_TITLE = "Can't reach your computer";
/** …and its description, while the phone shows what it loaded last. */
export const PHONE_OFFLINE_DETAIL = "Showing what was last loaded. Is your computer on, with Ordnung running, and is this phone on the same Wi‑Fi?";

/** A letter's page on a phone, where Delete and Download original were. */
export const DELETE_ON_COMPUTER = "Delete or download it on your computer.";
/** The Tax year page on a phone, where "Export these letters…" is on the computer. */
export const EXPORT_ON_COMPUTER = "Export them on your computer.";
/** A letter you wrote, on a phone, where Download PDF and Delete were. */
export const PDF_ON_COMPUTER = "Download or print the PDF on your computer.";
/** A proof of sending on a phone, where its file and the Nachweis PDF could be downloaded. */
export const PROOF_ON_COMPUTER = "Download the proof or the Nachweis PDF on your computer.";
/** A file with no picture, on a phone (it can't be downloaded here). */
export const OPEN_ON_COMPUTER = "This kind of file has no picture here — open it on your computer.";
/** Letters from the watched folder that wait, on a phone: whether Claude reads them is decided on the computer. */
export const DECIDE_ON_COMPUTER = "Decide on your computer whether Claude may read these.";
/** One such letter. */
export const DECIDE_ONE_ON_COMPUTER = "Decide on your computer whether Claude may read it.";
/** A number shown masked on a phone (My numbers, the people & organisations drawer). */
export const FULL_NUMBER_ON_COMPUTER = "Full number on your computer";
/** Over My numbers on a phone. */
export const NUMBERS_MASKED = "On this phone your numbers show only their last 4 characters — the full numbers are on your computer.";
