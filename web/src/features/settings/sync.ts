/**
 * Settings → Your computers (hand-off sync): pure helpers. The policy lives in `src/ordnung/sync/__init__.py`;
 * the numbers mirrored here are pinned to it by `sync.test.tsx` (a new passphrase's strength: `./passphrase`).
 *
 * The person's model, in the words every screen uses: Ordnung is **in use** on one computer at a time, the others
 * are **standing by**; "**Use Ordnung here**" brings everything over; when both computers changed something,
 * Ordnung asks once which computer's Ordnung to keep, and the other is **kept** as an encrypted copy.
 */
import type { SyncArriving, SyncComputer, SyncKept, SyncProblem, SyncProblemAction, SyncProblemCode, SyncSide, SyncStatus } from "@/api/types";
import { formatDate, formatDateTime, formatFileSize, formatTimeAgo } from "@/lib/format";
import { plural } from "@/lib/utils";
import { MAX_PASSPHRASE, MIN_PASSPHRASE, type PassphraseProblem } from "./backup";
import { passphraseStrength, strongEnough } from "./passphrase";

// ------------------------------------------------------------------------------------------------
// The numbers of the policy (`ordnung.sync`)
// ------------------------------------------------------------------------------------------------

/** A computer's name, at most (`NAME_MAX_CHARS`). */
export const NAME_MAX_CHARS = 40;
/** A waiting take-over gives up after this long (`TAKE_OVER_WAIT_MAX_S`), or when the other computer changes. */
export const TAKE_OVER_WAIT_MINUTES = 30;
/** Waiting without progress this long is a problem (`ARRIVAL_PATIENCE_S`). */
export const ARRIVAL_PATIENCE_MINUTES = 30;
/** Kept copies above this size in all get a warning (`KEPT_WARN_BYTES`). */
export const KEPT_WARN_BYTES = 2 * 1024 ** 3;

/** The server's refusal of a weak new passphrase (`WEAK_PASSPHRASE_MESSAGE`), said before asking it. */
export const WEAK_PASSPHRASE_MESSAGE =
  "This passphrase would be too easy to guess for a folder your sync provider keeps. Use five or more words that don't belong together, each of three letters or more — or take the suggested one.";

/** Where the passphrase lives, said wherever one is typed (never the backup's "Ordnung never stores it"). */
export const PASSPHRASE_WORDING =
  "Ordnung keeps this passphrase in this computer's password store, and you type it once on each of your computers. Save it in your password manager too: without it nobody can open the copy in the sync folder — not your sync provider, not Ordnung's makers, not you.";

/** The static demo's answer: there is nothing on the visitor's computer to hand over. */
export const SYNC_STATIC_MESSAGE = "Not available in the online demo: it keeps nothing on your computer, so there's nothing to hand over.";

// ------------------------------------------------------------------------------------------------
// The passphrase of a new sync folder: the server's estimator (`./passphrase`), counted the same way
// ------------------------------------------------------------------------------------------------

const characters = (s: string) => [...s].length;

/**
 * Why the passphrase can't protect a *new* sync folder (`ordnung.sync.passphrase_problem`): the backup's length
 * (12-1024 characters), then the strength — and, with `repeat`, that the two typed agree. Joining a folder, or
 * typing the passphrase again, checks only that it opens the folder (the server says so).
 */
export function newPassphraseProblem(passphrase: string, repeat?: string): PassphraseProblem | null {
  if (characters(passphrase) < MIN_PASSPHRASE) return { field: "passphrase", message: `Use a passphrase of at least ${MIN_PASSPHRASE} characters — five or more words that don't belong together work well.` };
  if (characters(passphrase) > MAX_PASSPHRASE) return { field: "passphrase", message: `Use a passphrase of at most ${MAX_PASSPHRASE} characters.` };
  if (!strongEnough(passphrase)) return { field: "passphrase", message: WEAK_PASSPHRASE_MESSAGE };
  if (repeat !== undefined && repeat !== passphrase) return { field: "repeat", message: "The two passphrases differ." };
  return null;
}

/** The strength said under a new sync passphrase while it is typed (null: nothing typed yet). */
export function strengthLine(passphrase: string): { tone: "ok" | "warn"; text: string } | null {
  return passphraseStrength(passphrase, "Strong enough for a folder your sync provider keeps.", MIN_PASSPHRASE);
}

// ------------------------------------------------------------------------------------------------
// The setup form
// ------------------------------------------------------------------------------------------------

export type SetupField = "folder" | "name" | "passphrase" | "repeat" | "form";

/** Which field an API refusal (`ApiError.code`) belongs next to. */
export function fieldFor(code: string | null | undefined): SetupField {
  switch (code) {
    case "folder":
    case "full":
    case "not_arrived":
    case "newer_ordnung":
      return "folder";
    case "name":
      return "name";
    case "passphrase":
    case "wrong_passphrase":
      return "passphrase";
    default:
      return "form";
  }
}

/** Why this computer's name can't be used (null: it can) — as the server checks it. */
export function nameProblem(name: string): string | null {
  const trimmed = name.trim();
  if (!trimmed) return "Give this computer a name, like “anna-thinkpad” or “desktop”.";
  if (characters(trimmed) > NAME_MAX_CHARS) return `Use at most ${NAME_MAX_CHARS} characters.`;
  // eslint-disable-next-line no-control-regex
  if (/[\u0000-\u001f\u007f]/.test(trimmed)) return "Use letters, digits and spaces — no line breaks.";
  return null;
}

/** "/home/sam/Nextcloud/Vault", "C:\\Users\\Sam\\Dropbox\\Vault", "~/Dropbox/Vault" or "\\\\nas\\share": a full path. */
export function looksAbsolute(path: string): boolean {
  return /^(\/|~(\/|$)|[A-Za-z]:[\\/]|\\\\)/.test(path.trim());
}

/**
 * What must be fixed before asking the server (null: nothing). `kind` is what the folder turned out to be: a new
 * sync asks for the passphrase twice and checks its strength; joining one asks for it once.
 */
export function syncFormProblem(
  values: { folder: string; name: string; passphrase: string; repeat: string },
  kind: "new" | "existing" | null,
): { field: Exclude<SetupField, "form">; message: string } | null {
  if (!values.folder.trim()) return { field: "folder", message: "Enter the folder your sync tool keeps in step, like /home/you/Nextcloud/Vault." };
  if (!looksAbsolute(values.folder)) return { field: "folder", message: "Enter the whole path, starting at the top: /home/you/Nextcloud/Vault." };
  const name = nameProblem(values.name);
  if (name) return { field: "name", message: name };
  if (kind === "existing" && !values.passphrase) return { field: "passphrase", message: "Type the passphrase you chose when you set up sync on your other computer." };
  if (kind === "new") {
    const problem = newPassphraseProblem(values.passphrase, values.repeat);
    if (problem) return problem;
  }
  return null;
}

// ------------------------------------------------------------------------------------------------
// The status, in words
// ------------------------------------------------------------------------------------------------

type Tone = "ok" | "neutral" | "warn" | "accent";

/** The other computers of this sync (not this one, not those that disconnected). */
export function otherComputers(status: Pick<SyncStatus, "computers">): SyncComputer[] {
  return status.computers.filter((c) => !c.this);
}

/** The others that still take part (a computer that disconnected is gone from the conversation). */
function liveOthers(status: Pick<SyncStatus, "computers">): SyncComputer[] {
  return otherComputers(status).filter((c) => c.state !== "left");
}

/** The computer in use, as a name to say ("desktop"; "your other computer" when it isn't known). */
export function inUseName(status: Pick<SyncStatus, "in_use_on" | "computers">): string {
  return status.in_use_on ?? status.computers.find((c) => c.in_use && !c.this)?.name ?? "your other computer";
}

/**
 * No computer is in use while this one stands by: the one in use left sync (Disconnect, Delete everything) — its last
 * version still counts. Returns who left ("desktop", "desktop and mac"; null: someone is in use, or nothing is known).
 */
export function nobodyInUse(status: Pick<SyncStatus, "mode" | "in_use_on" | "computers">): string | null {
  if (status.mode !== "standing_by" || status.in_use_on || !status.computers.length) return null;
  if (status.computers.some((c) => c.in_use)) return null;
  const left = status.computers.filter((c) => !c.this && c.state === "left").map((c) => c.name);
  if (!left.length) return "Your other computer";
  return left.length === 1 ? left[0]! : `${left.slice(0, -1).join(", ")} and ${left.at(-1)}`;
}

/** The standing-by screen's heading. */
export function standbyHeading(status: Pick<SyncStatus, "mode" | "in_use_on" | "computers">): string {
  return nobodyInUse(status) ? "No computer is using Ordnung now" : `Ordnung is in use on ${inUseName(status)}`;
}

/** This computer's badge in "Your computers": what it is now, and whether it needs the person. */
export function modeLabel(status: Pick<SyncStatus, "connected" | "mode" | "choice" | "problem">): { label: string; tone: Tone } {
  if (!status.connected) return { label: "Not syncing", tone: "neutral" };
  if (status.choice) return { label: "Needs a choice", tone: "warn" };
  if (status.problem) return { label: "Paused", tone: "warn" };
  if (status.mode === "in_use") return { label: "In use", tone: "ok" };
  if (status.mode === "standing_by") return { label: "Standing by", tone: "neutral" };
  return { label: "Starting", tone: "neutral" };
}

/** Another computer's badge. */
export function computerBadge(computer: Pick<SyncComputer, "state" | "in_use">): { label: string; tone: Tone } {
  if (computer.in_use) return { label: "In use", tone: "ok" };
  switch (computer.state) {
    case "in_use":
    case "standing_by":
      return { label: "Standing by", tone: "neutral" };
    case "closed":
      return { label: "Closed", tone: "neutral" };
    case "left":
      return { label: "Disconnected", tone: "neutral" };
    case "unknown":
      return { label: "Can't read it now", tone: "warn" };
  }
}

/** "Last change arrived 3 h ago" — this computer's clock, never the other's. */
export function computerLine(computer: Pick<SyncComputer, "arrived_at" | "state">, now: Date = new Date()): string {
  if (computer.state === "left") return "It stopped syncing.";
  if (!computer.arrived_at) return "Nothing of it has arrived here yet.";
  return `Last change arrived ${formatTimeAgo(computer.arrived_at, now)}.`;
}

/** Whether this computer's latest saved changes have reached another computer (null: can't tell). */
export function latestLine(computer: Pick<SyncComputer, "has_latest" | "state">): { tone: "ok" | "warn"; text: string } | null {
  if (computer.state === "left" || computer.has_latest === null) return null;
  return computer.has_latest ? { tone: "ok", text: "Has your latest changes" } : { tone: "warn", text: "Hasn't received your latest changes yet" };
}

/** What another computer's calendar sync means here (null: nothing to say). */
export function calendarLine(computer: Pick<SyncComputer, "calendar" | "name">): string | null {
  switch (computer.calendar) {
    case "same":
      return "Sends to the same calendar as this computer.";
    case "different_mode":
      return "Sends to the same calendar, but with other details: each switch rewrites Ordnung's events there.";
    case "other":
      return "Sends to a calendar this computer isn't connected to.";
    case "none":
      return null;
  }
}

/** The Calendar card's note on the computer in use without calendar sync while another has it (design §6.4). */
export function calendarElsewhereNote(status: Pick<SyncStatus, "connected" | "mode" | "computers"> | undefined, connectedHere: boolean): string | null {
  if (!status?.connected || status.mode !== "in_use" || connectedHere) return null;
  const elsewhere = otherComputers(status).filter((c) => c.state !== "left" && c.calendar !== "none");
  if (!elsewhere.length) return null;
  const names = elsewhere.map((c) => c.name);
  const where = names.length === 1 ? names[0]! : `${names.slice(0, -1).join(", ")} and ${names.at(-1)}`;
  return `Calendar sync is set up on ${where} only. Connect it here too, so your calendar stays current while you use this computer.`;
}

/** "Saved to the sync folder 2 min ago." — what the computer in use last did (this computer's clock). */
export function lastSavedLine(status: Pick<SyncStatus, "activity" | "last_saved_at" | "pending_changes">, now: Date = new Date()): string {
  if (status.activity === "saving") return "Saving to the sync folder…";
  if (!status.last_saved_at) return status.pending_changes ? "Not saved to the sync folder yet." : "Nothing saved to the sync folder yet.";
  const when = `Saved to the sync folder ${formatTimeAgo(status.last_saved_at, now)}.`;
  return status.pending_changes ? `${when} Newer changes follow in a moment.` : when;
}

/** "Waiting for 12 of 340 files from your sync tool (3.2 MB)." */
export function arrivingLine(arriving: Pick<SyncArriving, "have" | "need" | "have_bytes" | "need_bytes">): string {
  const missing = Math.max(0, arriving.need - arriving.have);
  const bytes = Math.max(0, arriving.need_bytes - arriving.have_bytes);
  return `Waiting for ${missing} of ${plural(arriving.need, "file")} from your sync tool${bytes ? ` (${formatFileSize(bytes)})` : ""}.`;
}

/** What to do when files don't arrive: online-only placeholders, then a stall (null: keep waiting quietly). */
export function arrivalAdvice(arriving: Pick<SyncArriving, "stalled" | "online_only">): string | null {
  if (arriving.online_only)
    return `${arriving.online_only === 1 ? "1 file is" : `${arriving.online_only} files are`} online only on this computer, so ${arriving.online_only === 1 ? "it doesn't" : "they don't"} arrive: make the sync folder available offline (in iCloud Drive, Dropbox or OneDrive: keep it on this device).`;
  if (arriving.stalled)
    return `Nothing more has arrived for ${ARRIVAL_PATIENCE_MINUTES} minutes. Check that your sync tool is running and signed in on both computers, isn't paused, and has space. If the folder is in iCloud Drive, Dropbox or OneDrive, make it available offline on this computer.`;
  return null;
}

/** "Ordnung takes over as soon as everything is here …" — and when it stops waiting (finding 23). */
export function waitingLine(from: string): string {
  return `Ordnung takes over as soon as everything is here. It stops waiting after ${TAKE_OVER_WAIT_MINUTES} minutes, or if ${from} saves a new change meanwhile — then just ask again.`;
}

/** The standing-by screen's status line. */
export function standbyStatusLine(
  status: Pick<SyncStatus, "arriving" | "up_to_date" | "computers" | "in_use_on" | "base_arrived_at"> & Partial<Pick<SyncStatus, "mode">>,
  now: Date = new Date(),
): string {
  const name = inUseName(status);
  const left = nobodyInUse({ mode: status.mode ?? "standing_by", in_use_on: status.in_use_on, computers: status.computers });
  if (left && !status.arriving) {
    const said = `${left} stopped syncing`;
    return status.up_to_date ? `${said}; everything it saved last has arrived here.` : `${said}. Ordnung hasn't seen everything it saved last yet.`;
  }
  if (status.arriving) {
    const { have, need } = status.arriving;
    return `${status.arriving.from_computer}'s latest changes are still on their way: ${have} of ${plural(need, "file")} ${have === 1 ? "is" : "are"} here.`;
  }
  const holder = status.computers.find((c) => c.in_use && !c.this);
  const arrived = holder?.arrived_at ?? status.base_arrived_at;
  if (status.up_to_date) return `Everything from ${name} has arrived here${arrived ? ` (the last change arrived ${formatTimeAgo(arrived, now)})` : ""}.`;
  return `Ordnung hasn't seen everything from ${name} yet.`;
}

/** Whether the computer in use was closed there, or is still open (changes only the reassurance). */
export function reassuranceLine(status: Pick<SyncStatus, "computers" | "in_use_on"> & Partial<Pick<SyncStatus, "mode">>): string {
  if (nobodyInUse({ mode: status.mode ?? "standing_by", in_use_on: status.in_use_on, computers: status.computers }))
    return "Use Ordnung here to go on with it on this computer — nothing is lost.";
  const name = inUseName(status);
  const holder = status.computers.find((c) => c.in_use && !c.this);
  if (holder?.state === "closed") return `${name} was closed. Use Ordnung here: nothing is lost.`;
  return `${name}'s Ordnung is still open. If you use it here, ${name} switches to standing by — nothing is lost.`;
}

/** "Use the copy this computer has now (from Tue 6 Oct, 18:20)". */
export function olderCopyLabel(status: Pick<SyncStatus, "base_arrived_at">): string {
  return status.base_arrived_at ? `Use the copy this computer has now (from ${formatDateTime(status.base_arrived_at)})` : "Use the copy this computer has now";
}

/** The top bar's word on saving (only on the computer in use). */
export function indicatorLabel(status: Pick<SyncStatus, "activity" | "problem" | "pending_changes" | "last_saved_at" | "computers">): {
  state: "saved" | "saving" | "problem";
  label: string;
} {
  if (status.problem) return { state: "problem", label: `Not saved: ${problemTitle(status.problem)}` };
  if (status.activity === "saving" || status.pending_changes) return { state: "saving", label: "Saving…" };
  if (!status.last_saved_at) return { state: "saving", label: "Not saved yet" };
  const others = liveOthers(status);
  if (!others.length) return { state: "saved", label: "Saved to the sync folder" };
  const missing = others.filter((c) => c.has_latest === false);
  if (others.length === 1) {
    const [other] = others as [SyncComputer];
    if (other.has_latest === null) return { state: "saved", label: "Saved to the sync folder" };
    return { state: "saved", label: other.has_latest ? `Saved · ${other.name} has it` : `Saved · ${other.name} hasn't received it yet` };
  }
  if (!missing.length && others.every((c) => c.has_latest)) return { state: "saved", label: "Saved · your other computers have it" };
  if (missing.length === 1) return { state: "saved", label: `Saved · ${missing[0]!.name} hasn't received it yet` };
  return { state: "saved", label: missing.length ? "Saved · your other computers haven't received it yet" : "Saved to the sync folder" };
}

// ------------------------------------------------------------------------------------------------
// Problems
// ------------------------------------------------------------------------------------------------

/** A problem's title when the server sent none (it always does; this keeps a code off the screen regardless). */
export const PROBLEM_TITLES: Record<SyncProblemCode, string> = {
  folder_missing: "The sync folder isn't there",
  folder_empty: "The sync folder is empty",
  folder_other: "The sync folder holds another sync",
  folder_full: "The sync folder is full",
  folder_unreachable: "The sync folder doesn't answer",
  online_only: "Some files are online only",
  two_setups: "Two separate syncs started",
  passphrase_needed: "Type the sync passphrase again",
  keyring_unavailable: "No password store",
  keyring_locked: "The password store is locked",
  newer_ordnung: "Update Ordnung on this computer",
  arrival_stalled: "Still waiting for your sync tool",
  not_received: "Your other computer hasn't received your changes",
  pull_unfinished: "Bringing Ordnung over didn't finish",
  no_space: "Not enough space on this computer",
  damaged: "A file in the sync folder is damaged",
  local_damaged: "A letter's file changed on this computer",
  copied_folder: "This data folder moved or was copied",
  local_rollback: "This computer's data went back in time",
  save_failing: "Saving to the sync folder keeps failing",
  forgotten: "This computer was removed from sync",
};

/** What a problem is called (the server's title; the web never shows the code). */
export function problemTitle(problem: Pick<SyncProblem, "code" | "title">): string {
  return problem.title.trim() || PROBLEM_TITLES[problem.code];
}

/** The button for each thing the person can do about a problem. */
export const ACTION_LABELS: Record<SyncProblemAction, string> = {
  passphrase: "Type the passphrase again",
  choose_folder: "Choose the folder again",
  refill: "Fill it again from this computer",
  same_computer: "This is the same computer",
  new_computer: "Set up as a new computer",
  keep_as_is: "Keep this computer's data as it is",
  abandon: "Give up bringing it over",
};

// ------------------------------------------------------------------------------------------------
// The choice
// ------------------------------------------------------------------------------------------------

/** "342 letters, 2 added since you last switched" — one side of the choice. */
export function choiceSideLine(side: Pick<SyncSide, "letters" | "added">, joining = false): string {
  const letters = plural(side.letters, "letter");
  if (joining || !side.added) return letters;
  return `${letters}, ${side.added} added since you last switched`;
}

/** "2 open dates and to-dos · 1 done · 1 note" — what tells two sides apart besides their letters. */
export function sideContentsLine(side: Pick<SyncSide, "items" | "done" | "notes">): string {
  const parts = [`${side.items} open ${side.items === 1 ? "date or to-do" : "dates and to-dos"}`, `${side.done} done`];
  if (side.notes) parts.push(plural(side.notes, "note"));
  return parts.join(" · ");
}

const CHANGE_KIND: Record<SyncSide["latest"][number]["kind"], string> = {
  letter: "letter",
  date: "date",
  "to-do": "to-do",
  note: "note",
  contract: "contract",
};

/** "Latest: to-do “Renew the passport” (7 Oct), date “Rent” (6 Oct)" — its newest changes (null: none). */
export function sideLatestLine(side: Pick<SyncSide, "latest">): string | null {
  if (!side.latest.length) return null;
  const changes = side.latest.map((change) => `${CHANGE_KIND[change.kind]} “${change.label}” (${formatDate(change.on, { style: "day" })})`);
  return `Latest: ${changes.join(", ")}`;
}

/** "Still arriving: 5 of 9 files" for a side whose version isn't all here (null: it is). */
export function sideArrivingLine(side: Pick<SyncSide, "complete" | "arriving">): string | null {
  if (side.complete) return null;
  if (!side.arriving) return "Still arriving";
  return `Still arriving: ${side.arriving.have} of ${plural(side.arriving.need, "file")}`;
}

/** A side as the dialog names it: "This computer (desktop)" or "anna-thinkpad". */
export function sideName(side: Pick<SyncSide, "this" | "computer">): string {
  return side.this ? `This computer (${side.computer})` : side.computer;
}

/** What the toast says once a side was kept (the loser's copy is made by its own computer — finding 28). */
export function chosenMessage(kept: Pick<SyncSide, "this" | "computer">, sides: Pick<SyncSide, "this" | "computer">[]): { title: string; description: string } {
  const others = sides.filter((s) => s !== kept && !s.this).map((s) => s.computer);
  const named = others.length ? (others.length === 1 ? others[0]! : `${others.slice(0, -1).join(", ")} and ${others.at(-1)}`) : "the other computer";
  if (kept.this)
    return {
      title: "Kept this computer's Ordnung",
      description: `${named}'s version stays on ${others.length > 1 ? "those computers" : "that computer"} as a kept copy once ${others.length > 1 ? "each" : "it"} next starts. Nothing is thrown away.`,
    };
  return { title: `Kept ${kept.computer}'s Ordnung`, description: "This computer's is saved as a backup (Settings → Your computers)." };
}

// ------------------------------------------------------------------------------------------------
// Disconnect and Delete everything: the second confirmation (finding 2)
// ------------------------------------------------------------------------------------------------

/**
 * Why going now loses this computer's latest changes for the other computers — said when no other computer has
 * them yet (null: one has, nothing to add).
 */
export function unreceivedLine(status: Pick<SyncStatus, "connected" | "others_have_latest" | "computers">): string | null {
  if (!status.connected || status.others_have_latest) return null;
  const others = liveOthers(status);
  if (!others.length) return "No other computer has joined this sync yet, so this computer's latest changes are only here and in the sync folder.";
  const behind = others.filter((c) => c.has_latest !== true).map((c) => c.name);
  const names = behind.length === 1 ? behind[0]! : `${behind.slice(0, -1).join(", ")} and ${behind.at(-1)}`;
  return `${names} ${behind.length === 1 ? "hasn't" : "haven't"} received your latest changes yet. Once this computer stops syncing, they won't get them — leave it on until your sync tool has delivered them.`;
}

// ------------------------------------------------------------------------------------------------
// Kept copies
// ------------------------------------------------------------------------------------------------

/** A path as typed in a terminal (quoted when it has a space or a quote). */
function shellPath(path: string): string {
  return /[\s'"$`\\!*?&;|<>(){}]/.test(path) ? `'${path.replace(/'/g, `'\\''`)}'` : path;
}

/** The command that opens a kept copy into another data folder (with the sync passphrase). */
export function keptRestoreCommand(kept: Pick<SyncKept, "path" | "name">): string {
  return `ordnung restore ${shellPath(kept.path || kept.name)} --data-dir ~/Ordnung-kept`;
}

/** "7 Oct 2026 · 412 MB · before you kept desktop's Ordnung". */
export function keptLine(kept: Pick<SyncKept, "created_at" | "size" | "why">): string {
  return [formatDate(kept.created_at, { style: "medium" }), formatFileSize(kept.size), kept.why].filter(Boolean).join(" · ");
}
