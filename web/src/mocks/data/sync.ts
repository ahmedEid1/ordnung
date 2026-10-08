/**
 * Hand-off sync in the mock, as `src/ordnung/api/routes/sync.py` and the sync gate answer it (design §17, §19.5).
 *
 * - **Two computers**: this one ({@link SYNC_THIS_NAME}) and {@link SYNC_OTHER_NAME}, which set up a sync in
 *   {@link SYNC_EXISTING_FOLDER} — joining that folder brings its Ordnung over; any other full path starts a new
 *   sync. Joining while this computer has letters asks first which Ordnung to keep (the scripted choice).
 * - **What a test drives** (and nothing in the app): the other computer taking over ({@link MockSync.otherTakesOver}),
 *   its changes arriving ({@link MockSync.arriving}, {@link MockSync.arrived}), both computers changing
 *   ({@link MockSync.bothChanged}), problems, notices, kept copies and other computers.
 * - **The gate** ({@link MockSync.gate}): while this computer stands by (or brings changes over), every write
 *   outside `/sync` and the few allowed ones answers 409 `standby` — as the API does on both listeners.
 *
 * `?mock=1` pretends a sync folder and a password store; the static demo has nothing to hand over and says so
 * ({@link SYNC_STATIC_MESSAGE}). Its times are the real clock's, as the API's are ("this computer's clock").
 */
import type {
  SyncArriving,
  SyncChange,
  SyncChoice,
  SyncComputer,
  SyncConnect,
  SyncConnected,
  SyncDisconnect,
  SyncFolderInfo,
  SyncKept,
  SyncNotice,
  SyncNoticeCode,
  SyncProblem,
  SyncProblemCode,
  SyncProgress,
  SyncStatus,
  SyncUseHere,
} from "@/api/types";
import { SYNC_STATIC_MESSAGE, nameProblem, newPassphraseProblem } from "@/features/settings/sync";
import type { MockDb } from "../db";

export { SYNC_STATIC_MESSAGE };

/** `ordnung demo`'s answer (the API's `DEMO_MESSAGE`). */
export const SYNC_DEMO_MESSAGE = "This is the demo, so it doesn't sync. Your own Ordnung can.";
export const NOT_CONNECTED_MESSAGE = "This computer isn't syncing. Set it up in Settings → Your computers.";
export const ALREADY_CONNECTED_MESSAGE = "This computer already syncs. Disconnect it first.";
export const WRONG_PASSPHRASE_MESSAGE = "That passphrase doesn't open this folder.";
export const STANDBY_MESSAGE = (name: string) => `Ordnung is in use on ${name}. Use it here first (Settings → Your computers).`;
export const BRINGING_OVER_MESSAGE = (name: string) => `Bringing over changes from ${name} — one moment.`;
export const NO_KEPT_COPY = "There's no saved copy of that name (any more).";
export const NO_COMPUTER = "No other computer of this sync has that number.";

/** This computer's host name (`suggested_name`). */
export const SYNC_THIS_NAME = "sam-laptop";
/** The other computer, which set up the sync in {@link SYNC_EXISTING_FOLDER}. */
export const SYNC_OTHER_NAME = "sam-desktop";
/** A folder holding sam-desktop's sync: joining it brings that Ordnung over. */
export const SYNC_EXISTING_FOLDER = "/home/sam/Nextcloud/Ordnung";
/** A passphrase that doesn't open the existing folder (any passphrase starting with "wrong"). */
export const SYNC_WRONG_PASSPHRASE = "wrong";
/** The version every computer of the mock runs. */
export const SYNC_APP_VERSION = "0.9.0";

/** Why a request is refused, shaped like the API's `{detail, code}`. */
export class SyncRefusal extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly code: string,
  ) {
    super(message);
  }
}

/** Title, message and actions of every problem, as `ordnung.sync.status.PROBLEMS` words them (`{name}`: the other computer). */
const PROBLEMS: Record<SyncProblemCode, [string, string, SyncProblem["actions"]]> = {
  folder_missing: [
    "The sync folder isn't there",
    "Ordnung can't find the sync folder — is its drive or network share connected? Ordnung never creates it again by itself; if you moved it, choose it again. This computer keeps working, and its changes wait here.",
    ["choose_folder"],
  ],
  folder_empty: [
    "The sync folder is empty",
    "The sync folder is there, but Ordnung's files are gone (a share that isn't mounted looks like this too). Once you're sure it is the right folder, fill it again from this computer.",
    ["refill"],
  ],
  folder_other: ["The sync folder holds another sync", "This folder now holds a different Ordnung sync, so Ordnung stopped syncing to it. Choose the right folder again.", ["choose_folder"]],
  folder_full: ["The sync folder is full", "There's no space left in the sync folder (or in your sync provider's storage). Make some room there; Ordnung tries again by itself.", []],
  folder_unreachable: [
    "The sync folder doesn't answer",
    "The sync folder took too long to answer — a network share that hangs, or files your sync tool keeps online only. Ordnung tries again by itself; this computer keeps working meanwhile.",
    [],
  ],
  online_only: [
    "Some files are online only",
    "Your sync tool keeps some of the sync folder's files online only on this computer, so they can't be brought over. Make the folder available offline (in iCloud Drive, Dropbox or OneDrive: keep it on this device).",
    [],
  ],
  two_setups: ["Two separate syncs started", "Another computer started a separate sync in this folder at the same moment. Disconnect this computer and set it up again to join that one.", ["new_computer"]],
  passphrase_needed: [
    "Type the sync passphrase again",
    "This computer's password store no longer has the sync passphrase (or it no longer opens the folder). Type it again; Ordnung keeps it there.",
    ["passphrase"],
  ],
  keyring_unavailable: [
    "No password store",
    "This computer has no password store Ordnung can use, so it can't open the sync folder. On Linux, GNOME Keyring or KWallet must run and be unlocked.",
    [],
  ],
  keyring_locked: [
    "The password store is locked",
    "Unlock this computer's password store (it usually unlocks when you log in), so Ordnung can open the sync folder. This computer keeps working meanwhile.",
    [],
  ],
  newer_ordnung: [
    "Update Ordnung on this computer",
    "Another of your computers runs a newer Ordnung, so its changes can't be brought here. Update Ordnung on this computer; it keeps saving its own changes meanwhile.",
    [],
  ],
  arrival_stalled: [
    "Still waiting for your sync tool",
    "Nothing more has arrived for 30 minutes. Check that your sync tool is running and signed in on both computers, isn't paused, and has space. If the folder is in iCloud Drive, Dropbox or OneDrive, make it available offline on this computer.",
    [],
  ],
  not_received: ["Your other computer hasn't received your changes", "{name} hasn't received your latest changes for 30 minutes — is your sync tool running there?", []],
  pull_unfinished: [
    "Bringing Ordnung over didn't finish",
    "Ordnung couldn't finish putting the other computer's data in place here (it tries again each time it starts). You can give it up: this computer then keeps what it has and stands by.",
    ["abandon"],
  ],
  no_space: ["Not enough space on this computer", "This computer needs more free space to bring Ordnung over. Free some space, then try again.", []],
  damaged: [
    "A file in the sync folder is damaged",
    "A file in the sync folder doesn't open. The computer that saved it writes it again the next time it runs; nothing is brought over until it does.",
    [],
  ],
  local_damaged: [
    "A letter's file changed on this computer",
    "The file of a letter on this computer no longer matches what Ordnung stored (a disk problem?), so it isn't saved to the sync folder. Run “ordnung doctor”, or restore a backup.",
    [],
  ],
  copied_folder: [
    "This data folder moved or was copied",
    "Ordnung's data folder is in another place, or on another computer, than when sync was set up. If it is the same computer (renamed, or the folder moved), say so. If it is a copy on a new computer, set that computer up as a new one.",
    ["same_computer", "new_computer"],
  ],
  local_rollback: [
    "This computer's data went back in time",
    "Ordnung's data on this computer is older than what it last saved (a power cut?), and the saved state isn't in the sync folder to put back. You can keep this computer's data as it is.",
    ["keep_as_is"],
  ],
  save_failing: ["Saving to the sync folder keeps failing", "Ordnung couldn't save to the sync folder for 30 minutes. It keeps trying; your changes wait on this computer.", []],
  forgotten: [
    "This computer was removed from sync",
    "This computer was removed from sync on {name}, so it no longer saves or brings anything over. To sync it again, disconnect it and set it up again.",
    ["new_computer"],
  ],
};

/** The problem `code` in words, as the API sends it (`name`: the other computer meant). */
export function syncProblem(code: SyncProblemCode, name = SYNC_OTHER_NAME, inUse = true): SyncProblem {
  const [title, message, actions] = PROBLEMS[code];
  return { code, title, message: message.replace("{name}", name), actions: actions.filter((a) => a !== "refill" || inUse) };
}

const now = () => new Date().toISOString().replace(/\.\d{3}Z$/, "Z");
const minutesAgo = (m: number) => new Date(Date.now() - m * 60_000).toISOString().replace(/\.\d{3}Z$/, "Z");

/** `ordnung-kept-2026-10-07-0912.ordnung-backup` (this computer's local time), with `-n` when taken. */
function keptName(taken: Set<string>): string {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  const base = `ordnung-kept-${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}`;
  let name = `${base}.ordnung-backup`;
  for (let n = 2; taken.has(name); n++) name = `${base}-${n}.ordnung-backup`;
  return name;
}

/** Hand-off sync as one computer's server keeps it (the mock's other computer is only what its head says). */
export class MockSync {
  connected = false;
  mode: SyncStatus["mode"] = "off";
  activity: SyncStatus["activity"] = "idle";
  progress: SyncProgress | null = null;
  folder: string | null = null;
  thisName: string | null = null;
  computers: SyncComputer[] = [];
  lastSavedAt: string | null = null;
  pending = false;
  upToDate = false;
  baseFrom: string | null = null;
  baseArrivedAt: string | null = null;
  arrivingNow: SyncArriving | null = null;
  takeOverWaiting = false;
  choice: SyncChoice | null = null;
  problem: SyncProblem | null = null;
  notices: SyncNotice[] = [];
  kept: SyncKept[] = [];
  dataFolderSynced = false;
  /** `ordnung demo`: unavailable, every write refused (the static demo is told apart by `staticDemo`). */
  demo = false;
  private noticeSeq = 0;

  constructor(
    private readonly db: MockDb,
    private readonly opts: { staticDemo: boolean },
  ) {}

  // ---------------------------------------------------------------------------------------------
  // the status
  // ---------------------------------------------------------------------------------------------

  private get unavailable(): string | null {
    if (this.opts.staticDemo) return SYNC_STATIC_MESSAGE;
    if (this.demo) return SYNC_DEMO_MESSAGE;
    return null;
  }

  /** The computer in use (another, or this one). */
  private get holder(): SyncComputer | undefined {
    return this.computers.find((c) => c.in_use);
  }

  private get others(): SyncComputer[] {
    return this.computers.filter((c) => !c.this);
  }

  status(): SyncStatus {
    const unavailable = this.unavailable;
    const others = this.others.filter((c) => c.state !== "left");
    return {
      available: unavailable === null,
      unavailable,
      install_command: null,
      connected: this.connected,
      mode: this.connected ? this.mode : "off",
      activity: this.activity,
      progress: this.progress,
      folder: this.folder,
      this_computer: this.thisName,
      suggested_name: SYNC_THIS_NAME,
      in_use_on: this.connected ? (this.holder?.name ?? null) : null,
      computers: this.computers.map((c) => ({ ...c })),
      last_saved_at: this.lastSavedAt,
      pending_changes: this.pending,
      others_have_latest: others.some((c) => c.has_latest === true),
      up_to_date: this.mode === "standing_by" && this.upToDate,
      base_from: this.baseFrom,
      base_arrived_at: this.baseArrivedAt,
      arriving: this.arrivingNow ? { ...this.arrivingNow } : null,
      take_over_waiting: this.takeOverWaiting,
      choice: this.choice ? { ...this.choice, sides: this.choice.sides.map((s) => ({ ...s })) } : null,
      problem: this.problem,
      notices: [...this.notices],
      kept: [...this.kept],
      kept_warning: this.kept.reduce((sum, k) => sum + k.size, 0) > 2 * 1024 ** 3,
      data_folder_synced: this.dataFolderSynced,
    };
  }

  // ---------------------------------------------------------------------------------------------
  // refusals
  // ---------------------------------------------------------------------------------------------

  private writable(): void {
    const unavailable = this.unavailable;
    if (unavailable) throw new SyncRefusal(409, unavailable, "unavailable");
  }

  private needConnected(): void {
    this.writable();
    if (!this.connected) throw new SyncRefusal(409, NOT_CONNECTED_MESSAGE, "not_connected");
  }

  /**
   * The gate, before any route: while another computer is in use (or changes are being brought over), a write
   * outside `/sync` and the writes a standing-by computer allows (a backup, phone access) answers 409 `standby`.
   */
  gate(method: string, path: string): SyncRefusal | null {
    if (!this.connected || ["GET", "HEAD", "OPTIONS"].includes(method)) return null;
    const bringing = this.activity === "bringing_over";
    if (this.mode !== "standing_by" && !bringing) return null;
    if (path === "/sync" || path.startsWith("/sync/")) return null;
    if (method === "POST" && path === "/backup") return null;
    if (path === "/phone" || path.startsWith("/phone/")) return null;
    const name = bringing ? (this.arrivingNow?.from_computer ?? SYNC_OTHER_NAME) : (this.holder?.name ?? SYNC_OTHER_NAME);
    return new SyncRefusal(409, bringing ? BRINGING_OVER_MESSAGE(name) : STANDBY_MESSAGE(name), "standby");
  }

  // ---------------------------------------------------------------------------------------------
  // the routes
  // ---------------------------------------------------------------------------------------------

  inspect(body: { folder?: unknown }): SyncFolderInfo {
    this.writable();
    const folder = typeof body.folder === "string" ? body.folder.trim().replace(/\/+$/, "") : "";
    const base: SyncFolderInfo = { kind: "refused", folder, problem: null, examples: [], data_folder_synced: this.dataFolderSynced, links_left_out: [] };
    const dataDir = this.db.state.health.data_dir.replace(/\/+$/, "");
    if (!folder || !/^(\/|~\/)/.test(folder)) return { ...base, problem: "Enter the whole path, starting at the top: /home/you/Nextcloud/Vault." };
    if (folder === dataDir || folder.startsWith(`${dataDir}/`) || dataDir.startsWith(`${folder}/`))
      return { ...base, problem: "That is Ordnung's data folder (or holds it). Choose a folder of its own that your sync tool keeps in step." };
    if (folder === "/home/sam" || folder === "~") return { ...base, problem: "That is your home folder. Choose a folder of its own inside the folder your sync tool keeps in step." };
    if (folder === SYNC_EXISTING_FOLDER) return { ...base, kind: "existing" };
    if (folder.endsWith("/Documents")) return { ...base, problem: "This folder holds other files (like “Tax 2025.pdf”). Choose an empty folder, or a new one.", examples: ["Tax 2025.pdf", "Notes"] };
    return { ...base, kind: "new" };
  }

  connect(body: SyncConnect): SyncConnected {
    this.writable();
    if (this.connected) {
      // the folder went missing or holds another sync: the person points at it again
      if (this.problem && (this.problem.code === "folder_missing" || this.problem.code === "folder_other")) {
        const info = this.inspect({ folder: body.folder });
        if (info.kind !== "existing" && info.folder !== this.folder) throw new SyncRefusal(422, info.problem ?? "This folder doesn't hold this sync.", "folder");
        this.folder = info.folder;
        this.problem = null;
        return { status: this.status(), choice: null };
      }
      throw new SyncRefusal(409, ALREADY_CONNECTED_MESSAGE, "already_connected");
    }
    const wrongName = nameProblem(body.name);
    if (wrongName) throw new SyncRefusal(422, wrongName, "name");
    const info = this.inspect({ folder: body.folder });
    if (info.kind === "refused") throw new SyncRefusal(422, info.problem ?? "This folder can't be used.", "folder");
    if (info.kind === "new") {
      const weak = newPassphraseProblem(body.passphrase);
      if (weak) throw new SyncRefusal(422, weak.message, "passphrase");
      return { status: this.create(info.folder, body.name.trim()), choice: null };
    }
    if (!body.passphrase) throw new SyncRefusal(422, "Type the passphrase of this sync folder.", "passphrase");
    if (body.passphrase.trim().toLowerCase().startsWith(SYNC_WRONG_PASSPHRASE)) throw new SyncRefusal(422, WRONG_PASSPHRASE_MESSAGE, "wrong_passphrase");
    // a taken name gets " (2)" (finding 29)
    const name = body.name.trim() === SYNC_OTHER_NAME ? `${SYNC_OTHER_NAME} (2)` : body.name.trim();
    const letters = this.db.liveDocuments().length;
    if (letters && !body.keep) return { status: this.status(), choice: this.joiningChoice(name, letters) };
    return { status: this.join(info.folder, name, body.keep ?? null), choice: null };
  }

  private computer(over: Partial<SyncComputer> & Pick<SyncComputer, "key" | "name">): SyncComputer {
    return { this: false, in_use: false, state: "standing_by", arrived_at: null, has_latest: null, app_version: SYNC_APP_VERSION, calendar: "none", ...over };
  }

  private create(folder: string, name: string): SyncStatus {
    Object.assign(this, { connected: true, mode: "in_use", folder, thisName: name, lastSavedAt: now(), pending: false, baseFrom: name, baseArrivedAt: now(), problem: null, choice: null });
    this.computers = [this.computer({ key: 1, name, this: true, in_use: true, state: "in_use" })];
    this.db.log("sync.connected", `Started syncing through ${folder} as ${name}.`);
    return this.status();
  }

  private joiningChoice(name: string, letters: number): SyncChoice {
    const newest = this.db
      .liveDocuments()
      .slice(0, 3)
      .map((d) => ({ label: d.title ?? d.filename, added_on: d.created_at.slice(0, 10) }));
    return {
      joining: true,
      chosen: null,
      sides: [
        { key: 1, computer: name, this: true, letters, added: letters, newest, items: 0, done: 0, notes: 0, latest: [], saved_at: null, arrived_at: null, complete: true, arriving: null },
        {
          key: 2,
          computer: SYNC_OTHER_NAME,
          this: false,
          letters: 340,
          added: 0,
          newest: [{ label: "Vodafone Rechnung Oktober", added_on: "2026-10-06" }],
          items: 23,
          done: 41,
          notes: 3,
          latest: [{ kind: "letter", label: "Vodafone Rechnung Oktober", on: "2026-10-06" }],
          saved_at: minutesAgo(12),
          arrived_at: minutesAgo(10),
          complete: true,
          arriving: null,
        },
      ],
    };
  }

  private join(folder: string, name: string, keep: "this" | "folder" | null): SyncStatus {
    const fromHere = keep === "this";
    if (keep === "folder" && this.db.liveDocuments().length) this.keep(`before you brought ${SYNC_OTHER_NAME}'s Ordnung here`);
    Object.assign(this, { connected: true, mode: "in_use", folder, thisName: name, lastSavedAt: now(), pending: false, problem: null, choice: null, upToDate: true });
    this.baseFrom = fromHere ? name : SYNC_OTHER_NAME;
    this.baseArrivedAt = now();
    this.computers = [
      this.computer({ key: 1, name, this: true, in_use: true, state: "in_use" }),
      this.computer({ key: 2, name: SYNC_OTHER_NAME, state: "standing_by", arrived_at: minutesAgo(10), has_latest: false }),
    ];
    this.db.log("sync.joined", fromHere ? `Started syncing through ${folder}; this computer's Ordnung was kept.` : `Brought Ordnung over from ${SYNC_OTHER_NAME} and started syncing.`);
    return this.status();
  }

  /** A kept copy of this computer's data (Rule K), named by this computer's clock. */
  private keep(why: string): SyncKept {
    const name = keptName(new Set(this.kept.map((k) => k.name)));
    const kept: SyncKept = { name, path: `${this.db.state.health.data_dir}/sync/kept/${name}`, size: 4_620_000 + this.kept.length, created_at: now(), why };
    this.kept = [kept, ...this.kept];
    this.notice("kept", `This computer's data was saved as ${name} ${why}.`, name);
    return kept;
  }

  private notice(code: SyncNoticeCode, message: string, kept: string | null = null): SyncNotice {
    const notice: SyncNotice = { id: `n${++this.noticeSeq}`, code, message, kept, at: now() };
    this.notices = [notice, ...this.notices];
    return notice;
  }

  change(body: SyncChange): SyncStatus {
    this.needConnected();
    if (body.name != null) {
      const wrong = nameProblem(body.name);
      if (wrong) throw new SyncRefusal(422, wrong, "name");
      this.thisName = body.name.trim();
      for (const c of this.computers) if (c.this) c.name = this.thisName;
    }
    const answers: [boolean | undefined, SyncProblemCode][] = [
      [body.confirm_same_computer, "copied_folder"],
      [body.keep_as_is, "local_rollback"],
      [body.abandon_pull, "pull_unfinished"],
    ];
    for (const [asked, code] of answers) {
      if (!asked) continue;
      if (this.problem?.code !== code) throw new SyncRefusal(409, "There's nothing to confirm or give up now.", "not_needed");
      this.problem = null;
      if (code === "pull_unfinished") {
        this.mode = "standing_by";
        this.notice("pull_abandoned", "Bringing Ordnung over was given up: this computer keeps what it had, and stands by.");
      }
    }
    if (body.dismiss_notice) this.notices = this.notices.filter((n) => n.id !== body.dismiss_notice);
    return this.status();
  }

  disconnect(body: SyncDisconnect): SyncStatus {
    this.writable();
    if (!this.connected) return this.status();
    if (!this.status().others_have_latest && this.mode === "in_use" && !body.unreceived_ok)
      throw new SyncRefusal(409, "No other computer has this computer's latest changes yet. Disconnect anyway?", "not_received");
    this.leave();
    return this.status();
  }

  /** Disconnect (also Delete everything): the head says it left, `sync/` goes — kept copies stay (not on Delete everything). */
  leave(): void {
    this.db.log("sync.disconnected", "This computer stopped syncing.");
    Object.assign(this, {
      connected: false,
      mode: "off",
      activity: "idle",
      progress: null,
      folder: null,
      thisName: null,
      computers: [],
      lastSavedAt: null,
      pending: false,
      upToDate: false,
      baseFrom: null,
      baseArrivedAt: null,
      arrivingNow: null,
      takeOverWaiting: false,
      choice: null,
      problem: null,
      notices: [],
    });
  }

  /** The other computer that shares this computer's calendar (Delete everything leaves Ordnung's events there). */
  calendarSharedWith(): string | null {
    return this.connected ? (this.others.find((c) => c.state !== "left" && c.calendar === "same")?.name ?? null) : null;
  }

  /** "Use Ordnung here". */
  useHere(body: SyncUseHere): SyncStatus {
    this.needConnected();
    if (body.cancel) {
      this.takeOverWaiting = false;
      if (this.choice) this.choice.chosen = null;
      return this.status();
    }
    if (this.problem?.code === "pull_unfinished") throw new SyncRefusal(409, "A take-over must finish first.", "pull_unfinished");
    if (this.problem?.code === "passphrase_needed") throw new SyncRefusal(409, this.problem.message, "passphrase_needed");
    if (this.mode === "in_use") return this.status();
    if (this.choice) return this.status();
    if (this.arrivingNow && !body.older_copy) {
      this.takeOverWaiting = true;
      return this.status();
    }
    this.claim(body.older_copy ? null : (this.holder?.name ?? null));
    return this.status();
  }

  /** This computer is the one in use from now on (`from`: whose data it brought over; null: it kept its own). */
  private claim(from: string | null): void {
    const before = this.holder;
    for (const c of this.computers) {
      c.in_use = c.this;
      if (c.this) c.state = "in_use";
      else if (c.state === "in_use" || c.state === "closed") c.state = "standing_by";
      if (!c.this) c.has_latest = false;
    }
    Object.assign(this, { mode: "in_use", activity: "idle", takeOverWaiting: false, arrivingNow: null, upToDate: false, lastSavedAt: now(), pending: false });
    if (from) {
      this.baseFrom = from;
      this.baseArrivedAt = now();
    }
    if (!before?.this) this.db.log("sync.taken_over", `Ordnung moved here from ${before?.name ?? SYNC_OTHER_NAME}.`);
  }

  choose(body: { keep?: unknown }): SyncStatus {
    this.needConnected();
    const choice = this.choice;
    const side = choice?.sides.find((s) => s.key === body.keep);
    if (!choice || !side) throw new SyncRefusal(409, "There's nothing to choose (any more).", "no_choice");
    if (!side.complete) {
      choice.chosen = side.key;
      this.takeOverWaiting = true;
      return this.status();
    }
    const losers = choice.sides.filter((s) => s !== side);
    if (side.this) {
      this.db.log("sync.chosen", `You kept this computer's Ordnung. ${losers.map((s) => s.computer).join(" and ")}'s version stays on that computer as a kept copy once it next starts.`);
    } else {
      const kept = this.keep(`before you kept ${side.computer}'s Ordnung`);
      this.db.log("sync.chosen", `You kept ${side.computer}'s Ordnung. This computer's was saved as ${kept.name.replace(/\.ordnung-backup$/, "")}.`);
    }
    this.choice = null;
    this.claim(side.this ? null : side.computer);
    return this.status();
  }

  save(body: { hand_over?: boolean }): SyncStatus {
    this.needConnected();
    if (this.mode !== "in_use") throw new SyncRefusal(409, STANDBY_MESSAGE(this.holder?.name ?? SYNC_OTHER_NAME), "standby");
    if (this.problem && ["folder_missing", "folder_empty", "folder_other", "folder_full", "folder_unreachable", "copied_folder"].includes(this.problem.code))
      throw new SyncRefusal(409, this.problem.message, "folder_problem");
    this.lastSavedAt = now();
    this.pending = false;
    if (body.hand_over) {
      this.mode = "standing_by";
      for (const c of this.computers) {
        if (c.this) c.state = "closed";
      }
    }
    return this.status();
  }

  passphrase(body: { passphrase?: unknown }): SyncStatus {
    this.needConnected();
    const typed = typeof body.passphrase === "string" ? body.passphrase : "";
    if (!typed || typed.trim().toLowerCase().startsWith(SYNC_WRONG_PASSPHRASE)) throw new SyncRefusal(422, WRONG_PASSPHRASE_MESSAGE, "wrong_passphrase");
    if (this.problem?.code === "passphrase_needed") this.problem = null;
    return this.status();
  }

  refill(): SyncStatus {
    this.needConnected();
    if (this.problem?.code !== "folder_empty" || this.mode !== "in_use") throw new SyncRefusal(409, "The folder isn't empty, or another computer is in use.", "not_needed");
    this.problem = null;
    this.lastSavedAt = now();
    return this.status();
  }

  forget(key: number): SyncStatus {
    this.needConnected();
    const computer = this.others.find((c) => c.key === key);
    if (!computer) throw new SyncRefusal(404, NO_COMPUTER, "not_found");
    if (computer.in_use) throw new SyncRefusal(409, `${computer.name} is the one in use. Use Ordnung here first, then forget it.`, "in_use");
    this.computers = this.computers.filter((c) => c !== computer);
    this.db.log("sync.forgot", `Removed ${computer.name} from sync.`);
    return this.status();
  }

  keptFile(name: string): SyncKept {
    const kept = this.kept.find((k) => k.name === name);
    if (!kept) throw new SyncRefusal(404, NO_KEPT_COPY, "not_found");
    return kept;
  }

  deleteKept(name: string): void {
    this.writable();
    this.keptFile(name);
    this.kept = this.kept.filter((k) => k.name !== name);
    this.notices = this.notices.filter((n) => n.kept !== name);
  }

  // ---------------------------------------------------------------------------------------------
  // what a test drives
  // ---------------------------------------------------------------------------------------------

  /** Connected and in use here, with `others` standing by (their latest changes arrived ten minutes ago). */
  setUp({ others = [SYNC_OTHER_NAME], folder = SYNC_EXISTING_FOLDER, name = SYNC_THIS_NAME }: { others?: string[]; folder?: string; name?: string } = {}): this {
    Object.assign(this, { connected: true, mode: "in_use", activity: "idle", folder, thisName: name, lastSavedAt: minutesAgo(2), pending: false, baseFrom: name, baseArrivedAt: minutesAgo(60) });
    this.computers = [
      this.computer({ key: 1, name, this: true, in_use: true, state: "in_use" }),
      ...others.map((other, i) => this.computer({ key: i + 2, name: other, arrived_at: minutesAgo(10), has_latest: true })),
    ];
    return this;
  }

  /** Another computer took over (`closed`: then closed Ordnung there): this one stands by, everything arrived. */
  otherTakesOver(name = SYNC_OTHER_NAME, { closed = false }: { closed?: boolean } = {}): this {
    if (!this.connected) this.setUp({ others: [name] });
    for (const c of this.computers) {
      c.in_use = c.name === name;
      if (c.this) c.state = "standing_by";
      else if (c.name === name) {
        c.state = closed ? "closed" : "in_use";
        c.arrived_at = minutesAgo(4);
      }
    }
    Object.assign(this, { mode: "standing_by", upToDate: true, baseArrivedAt: minutesAgo(40), baseFrom: name });
    return this;
  }

  /** The computer in use left sync (Disconnect, Delete everything): this one stands by, no computer is in use. */
  otherLeft(name = SYNC_OTHER_NAME): this {
    this.otherTakesOver(name);
    for (const c of this.computers) {
      c.in_use = false;
      if (c.name === name) c.state = "left";
    }
    return this;
  }

  /** The computer in use saved changes that are still arriving here (`have` of `need` files). */
  arriving(have: number, need: number, { stalled = false, onlyOnline = 0 }: { stalled?: boolean; onlyOnline?: number } = {}): this {
    this.arrivingNow = {
      from_computer: this.holder && !this.holder.this ? this.holder.name : SYNC_OTHER_NAME,
      have,
      need,
      have_bytes: have * 120_000,
      need_bytes: need * 120_000,
      since: minutesAgo(stalled ? 45 : 2),
      stalled,
      online_only: onlyOnline,
    };
    this.upToDate = false;
    return this;
  }

  /** Everything arrived: a waiting take-over completes by itself (its data replaced this computer's). */
  arrived(): this {
    const waiting = this.takeOverWaiting;
    this.arrivingNow = null;
    this.upToDate = true;
    if (waiting) {
      if (this.choice?.chosen != null) this.choose({ keep: this.choice.chosen });
      else this.claim(this.holder?.name ?? SYNC_OTHER_NAME);
    }
    return this;
  }

  /** Both computers changed something while apart: the choice (the other side still arriving, if `arriving`). */
  bothChanged({ arriving = false }: { arriving?: boolean } = {}): this {
    if (!this.connected) this.setUp();
    const other = this.others.find((c) => c.state !== "left")!;
    const here = this.computers.find((c) => c.this)!;
    this.choice = {
      joining: false,
      chosen: null,
      sides: [
        {
          key: here.key,
          computer: here.name,
          this: true,
          letters: 342,
          added: 2,
          newest: [
            { label: "Stadtwerke Abschlag 2027", added_on: "2026-10-06" },
            { label: "Allianz Beitragsanpassung", added_on: "2026-10-05" },
          ],
          items: 24,
          done: 40,
          notes: 3,
          latest: [
            { kind: "to-do", label: "Pay the Stadtwerke instalment", on: "2026-10-07" },
            { kind: "letter", label: "Stadtwerke Abschlag 2027", on: "2026-10-06" },
          ],
          saved_at: null,
          arrived_at: null,
          complete: true,
          arriving: null,
        },
        {
          key: other.key,
          computer: other.name,
          this: false,
          letters: 341,
          added: 1,
          newest: [{ label: "Vodafone Rechnung Oktober", added_on: "2026-10-06" }],
          items: 23,
          done: 41,
          notes: 3,
          latest: [
            { kind: "date", label: "Vodafone payment", on: "2026-10-06" },
            { kind: "letter", label: "Vodafone Rechnung Oktober", on: "2026-10-06" },
          ],
          saved_at: minutesAgo(12),
          arrived_at: minutesAgo(10),
          complete: !arriving,
          arriving: arriving ? { from_computer: other.name, have: 5, need: 9, have_bytes: 600_000, need_bytes: 1_080_000, since: minutesAgo(3), stalled: false, online_only: 0 } : null,
        },
      ],
    };
    return this;
  }

  /** A problem, as the API words it. */
  setProblem(code: SyncProblemCode | null, name = SYNC_OTHER_NAME): this {
    this.problem = code ? syncProblem(code, name, this.mode === "in_use") : null;
    return this;
  }

  /** A kept copy on this computer (with its notice). */
  addKept(why = `before you kept ${SYNC_OTHER_NAME}'s Ordnung`): SyncKept {
    return this.keep(why);
  }

  /** Another computer of this sync (standing by unless said otherwise). */
  addComputer(over: Partial<SyncComputer> & { name: string }): SyncComputer {
    const key = Math.max(0, ...this.computers.map((c) => c.key)) + 1;
    const computer = this.computer({ key, arrived_at: minutesAgo(180), has_latest: false, ...over });
    this.computers.push(computer);
    return computer;
  }

  /** A notice to know about once. */
  addNotice(code: SyncNoticeCode, message: string, kept: string | null = null): SyncNotice {
    return this.notice(code, message, kept);
  }
}
