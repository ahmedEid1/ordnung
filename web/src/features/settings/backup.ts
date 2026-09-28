/** Settings → Data → the encrypted backup: pure helpers (the policy lives in `src/ordnung/backup`). */
import type { BackupInfo } from "@/api/types";
import { formatFileSize } from "@/lib/format";
import { NB_HYPHEN } from "@/lib/glue";

/** The API's minimum (`BackupInfo.min_passphrase`), used before the info has loaded. */
export const MIN_PASSPHRASE = 12;
export const MAX_PASSPHRASE = 1024;

export interface PassphraseProblem {
  field: "passphrase" | "repeat";
  message: string;
}

/** Why the two typed passphrases can't protect a backup (null: they can). */
export function passphraseProblem(passphrase: string, repeat: string, min = MIN_PASSPHRASE): PassphraseProblem | null {
  if (passphrase.length < min) return { field: "passphrase", message: `Use at least ${min} characters — a short sentence works well.` };
  if (passphrase.length > MAX_PASSPHRASE) return { field: "passphrase", message: `Use at most ${MAX_PASSPHRASE} characters.` };
  if (repeat !== passphrase) return { field: "repeat", message: "The two passphrases differ." };
  return null;
}

/** Letters and digits that can't be mistaken for each other when copied by hand (no 0/o, 1/l/i). */
const ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789";
const GROUPS = 4;
const GROUP_CHARS = 5;

/**
 * A random passphrase like `k7qmx-3vxdp-9tawr-2emnb` (20 characters from 31: about 99 bits), made
 * in the browser with the system's random numbers; each character is drawn without modulo bias.
 */
export function suggestPassphrase(random: (bytes: Uint8Array) => Uint8Array = (b) => crypto.getRandomValues(b)): string {
  const chars: string[] = [];
  const limit = 256 - (256 % ALPHABET.length);
  while (chars.length < GROUPS * GROUP_CHARS) {
    for (const byte of random(new Uint8Array(32))) {
      if (byte < limit && chars.length < GROUPS * GROUP_CHARS) chars.push(ALPHABET[byte % ALPHABET.length]!);
    }
  }
  return Array.from({ length: GROUPS }, (_, g) => chars.slice(g * GROUP_CHARS, (g + 1) * GROUP_CHARS).join("")).join("-");
}

const count = (n: number, one: string, many: string) => `${n.toLocaleString("en-GB")} ${n === 1 ? one : many}`;

/** "22 letters · 71 files · about 10.1 MB" (the size before encryption; the file is a little bigger). */
export function backupSummary(info: Pick<BackupInfo, "letters" | "files" | "bytes">): string {
  return [count(info.letters, "letter", "letters"), count(info.files, "file", "files"), `about ${formatFileSize(info.bytes)}`].join(" · ");
}

/** What the backup holds, after its summary — never "every letter" when a linked folder is left out. */
export function backupContents(leftOut: readonly string[]): string {
  return leftOut.length
    ? "the database and everything inside the data folder — not the linked folders named below."
    : "the database, every letter as you added it, page images and letter PDFs.";
}

/** What a backup leaves out (`BackupInfo.left_out`: links, never followed), in one sentence. */
export function leftOutSentence(names: string[]): string {
  const quoted = names.map((name) => `“${name}”`);
  const listed = quoted.length > 3 ? [...quoted.slice(0, 3), `${names.length - 3} more`] : quoted;
  const shown = listed.length > 1 ? `${listed.slice(0, -1).join(", ")} and ${listed.at(-1)}` : (listed[0] ?? "");
  const [what, it] = names.length === 1 ? ["is a link", "it"] : ["are links", "them"];
  return `${shown} ${what} to somewhere outside the data folder, and a backup never follows links. Back ${it === "it" ? "that" : "those"} up separately, or move ${it} into the data folder.`;
}

/** Why the backup couldn't be made, as a sentence the dialog can continue ("… Nothing was saved."). */
export function failureSentence(error: unknown): string {
  const text = error instanceof Error && error.message.trim() ? error.message.trim() : "Ordnung didn't answer. Is it still running?";
  return /[.!?…]$/.test(text) ? text : `${text}.`;
}

/** The command that restores the downloaded file (from the folder it was saved in). */
export function restoreCommand(fileName: string): string {
  return `ordnung restore ${fileName}`;
}

/**
 * The restore command as shown, in pieces a line may break between: the command, then the file
 * name at its "-" and "." (`ordnung-backup-` · `2026-09-28` · `.ordnung-backup`), with the hyphens
 * inside a date non-breaking — a date split over two lines is easy to misread when typed by hand.
 */
export function restoreCommandPieces(fileName: string): string[] {
  const pieces = fileName.split(/(?<=[a-z]-)(?=\d{4}-\d{2}-\d{2})|(?=\.)/i).map((p) => p.replace(/(\d)-(?=\d)/g, `$1${NB_HYPHEN}`));
  return ["ordnung restore ", ...pieces];
}

/** Save a Blob under `name` through the browser's download (the object URL is released after). */
export function saveBlob(blob: Blob, name: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
