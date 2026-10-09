/** Settings → Data → the encrypted backup: pure helpers (the policy lives in `src/ordnung/backup`). */
import type { BackupInfo } from "@/api/types";
import { formatFileSize } from "@/lib/format";
import { NB_HYPHEN } from "@/lib/glue";
import { COMMON_WORDS, isRun, passphraseStrength, strongEnough } from "./passphrase";

/** The API's minimum (`BackupInfo.min_passphrase`), used before the info has loaded. */
export const MIN_PASSPHRASE = 12;
export const MAX_PASSPHRASE = 1024;

/** The server's refusal of a new backup's passphrase that falls short of the strength (`WEAK_PASSPHRASE_MESSAGE`), said before asking it. */
export const WEAK_PASSPHRASE_MESSAGE =
  "Ordnung can't count this passphrase as strong enough for a backup kept on another drive or in the cloud. Use five or more words that don't belong together, each of three letters or more, or a password manager's random password of 16 characters or more with capital and small letters — or take the suggested one.";

/** What Ordnung 0.1.0's backup dialog suggested (`EARLIER_SUGGESTION`): four groups of five of 31 letters and digits, drawn at random (about 99 bits). */
const EARLIER_SUGGESTION = /^[a-hjkmnp-z2-9]{5}(?:-[a-hjkmnp-z2-9]{5}){3}$/;

/** `ordnung.backup.earlier_suggestion`: a passphrase Ordnung 0.1.0 could have suggested — four different groups, none a run, a keyboard walk or a common word — still protects a new backup. */
export function earlierSuggestion(passphrase: string): boolean {
  if (!EARLIER_SUGGESTION.test(passphrase)) return false;
  const groups = passphrase.split("-");
  return new Set(groups).size === groups.length && !groups.some((group) => isRun(group) || COMMON_WORDS.has(group));
}

export interface PassphraseProblem {
  field: "passphrase" | "repeat";
  message: string;
}

/**
 * Why the passphrase can't protect a new backup (`ordnung.backup.passphrase_problem`): `min`-1024 characters, then
 * the strength a new sync folder's needs or {@link earlierSuggestion} — and, with `repeat`, that the two typed agree
 * (null: it can).
 */
export function passphraseProblem(passphrase: string, repeat?: string, min = MIN_PASSPHRASE): PassphraseProblem | null {
  const length = [...passphrase].length;
  if (length < min) return { field: "passphrase", message: `Use a passphrase of at least ${min} characters — five or more words that don't belong together work well.` };
  if (length > MAX_PASSPHRASE) return { field: "passphrase", message: `Use a passphrase of at most ${MAX_PASSPHRASE} characters.` };
  if (!strongEnough(passphrase) && !earlierSuggestion(passphrase)) return { field: "passphrase", message: WEAK_PASSPHRASE_MESSAGE };
  if (repeat !== undefined && repeat !== passphrase) return { field: "repeat", message: "The two passphrases differ." };
  return null;
}

/** The strength said under a new backup's passphrase while it is typed (null: nothing typed yet). */
export function backupStrengthLine(passphrase: string, min = MIN_PASSPHRASE): { tone: "ok" | "warn"; text: string } | null {
  const enough = "Strong enough for a backup kept on another drive or in the cloud.";
  if (earlierSuggestion(passphrase) && [...passphrase].length >= min) return { tone: "ok", text: enough };
  return passphraseStrength(passphrase, enough, min);
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
