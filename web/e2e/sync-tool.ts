/**
 * The sync tool, played by the tests (design §23.5): two folders — each one computer's copy of "the" synced
 * folder (`SYNC_A_DIR`, `SYNC_B_DIR` in e2e/env.ts) — kept in step only when a test says so. A test decides what
 * arrives where, when and in which order, and what the tool leaves next to it. What a real one (Nextcloud,
 * Syncthing, Dropbox, iCloud Drive) does that matters to Ordnung:
 *
 * - **late**: nothing moves until {@link SyncTool.deliver}; with `only`, some files move now and the rest later — a
 *   head before the objects it names, the case where a computer must wait and say so;
 * - **out of order**: the files of one delivery land in a shuffled order (seeded, so a failure repeats);
 * - **in pieces**: `inPlace` writes a file under its own name in two halves with a pause between, as tools that use
 *   no temporary name do — a reader may meet the first half, which must count as "not arrived yet";
 * - **conflict copies**: `conflictCopies` leaves the copies Dropbox and Nextcloud make ("… (conflicted copy
 *   2026-10-07)") next to the heads it delivers, and a file both sides changed keeps the other side's version as
 *   Syncthing does (`….sync-conflict-…`); Ordnung must ignore both and never delete them;
 * - **deletions travel**: a file deleted on one side since the two were last in step is deleted on the other (unless
 *   it changed there meanwhile), so Ordnung's clean-up reaches the other computer;
 * - **its own files**: {@link SyncTool.markFolders} leaves Syncthing's `.stfolder` marker in both copies.
 *
 * Files keep their modification time, as the tools keep it. Ordnung's own temporary files (`.<16 hex>.tmp`, a write
 * still in progress) are skipped unless `temps` is set, as a tool waits for a file to settle.
 */
import { createHash } from "node:crypto";
import { appendFileSync, copyFileSync, lstatSync, mkdirSync, readdirSync, readFileSync, renameSync, unlinkSync, utimesSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { setTimeout as sleep } from "node:timers/promises";

/** One of the two computers' copies of the synced folder. */
export type Side = "a" | "b";

/** What one delivery did to one file (its path relative to the folder, with "/"). */
export interface Delivered {
  path: string;
  change: "added" | "changed" | "deleted" | "conflict";
  bytes: number;
}

export interface DeliverOptions {
  /** Deliver only these files now; the others wait for a later delivery (late arrival). */
  only?: (path: string) => boolean;
  /** The order the files land in: by path (default), the reverse, or shuffled with `seed`. */
  order?: "listed" | "reversed" | "shuffled";
  seed?: number;
  /** Write each file in place in two halves, `pauseMs` apart (default 300), instead of a temporary name and a rename. */
  inPlace?: boolean;
  pauseMs?: number;
  /** Leave a Dropbox-style conflict copy next to every head delivered. */
  conflictCopies?: boolean;
  /** Carry deletions over too (default: yes). */
  deletions?: boolean;
  /** Also deliver Ordnung's temporary files (a write in progress). */
  temps?: boolean;
}

/**
 * The names Ordnung's sync folder may hold (design §4.1, `ordnung.sync`'s `KEY_FILE_RE`, `HEAD_RE`, `SHARD_RE`,
 * `OBJECT_RE` and `TEMP_RE`), as paths relative to the folder. Nothing else in it is Ordnung's.
 */
export const ORDNUNG_NAMES = {
  keyFile: /^[0-9a-f]{32}$/,
  head: /^h\/[0-9a-f]{32}$/,
  object: /^o\/[0-9a-f]{2}\/[0-9a-f]{30}$/,
  temp: /^(?:(?:h|o\/[0-9a-f]{2})\/)?\.[0-9a-f]{16}\.tmp$/,
} as const;

/** One of Ordnung's names ({@link ORDNUNG_NAMES}). */
export function isOrdnungName(path: string): boolean {
  return Object.values(ORDNUNG_NAMES).some((pattern) => pattern.test(path));
}

const isHead = (path: string) => ORDNUNG_NAMES.head.test(path);
const isTemp = (path: string) => ORDNUNG_NAMES.temp.test(path);
/** Syncthing's marker folder: the tool's, never delivered (each copy has its own). */
const MARKER = ".stfolder";

/** A file the sync tool made (its marker, a conflict copy — in either copy, as the tool carries those over too). */
export function isSyncToolFile(path: string): boolean {
  return path === MARKER || path.startsWith(`${MARKER}/`) || / \(conflicted copy \d{4}-\d{2}-\d{2}\)$/.test(path) || /\.sync-conflict-\d{8}-\d{6}-[A-Z0-9]+$/.test(path);
}

interface Seen {
  size: number;
  mtimeMs: number;
  sha: string;
}

/** A small seeded random number generator (mulberry32): the same seed, the same order. */
function random(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function shuffled<T>(items: T[], seed: number): T[] {
  const next = random(seed);
  const out = [...items];
  for (let i = out.length - 1; i > 0; i--) {
    const j = Math.floor(next() * (i + 1));
    [out[i], out[j]] = [out[j]!, out[i]!];
  }
  return out;
}

const sha256 = (bytes: Buffer): string => createHash("sha256").update(bytes).digest("hex");

interface Work {
  path: string;
  change: Delivered["change"];
}

export class SyncTool {
  /** What both copies held when they were last in step: path → SHA-256 (the tool's own record, as a real one keeps). */
  private readonly base = new Map<string, string>();
  /** The files the tool itself left in each copy (markers, conflict copies), relative to it. */
  readonly made: Record<Side, string[]> = { a: [], b: [] };

  constructor(readonly dirs: Record<Side, string>) {}

  /** Syncthing's `.stfolder` in both copies: a folder a sync tool keeps is never quite empty. */
  markFolders(): void {
    for (const side of ["a", "b"] as const) {
      mkdirSync(join(this.dirs[side], MARKER), { recursive: true });
      if (!this.made[side].includes(MARKER)) this.made[side].push(MARKER);
    }
  }

  /** Every regular file in one copy (links and the tool's marker folder are not walked), by relative path. */
  files(side: Side): Map<string, Seen> {
    const found = new Map<string, Seen>();
    const walk = (folder: string, prefix: string) => {
      for (const name of readdirSync(folder).sort()) {
        const path = prefix ? `${prefix}/${name}` : name;
        const full = join(folder, name);
        const stat = lstatSync(full);
        if (stat.isDirectory()) {
          if (path !== MARKER) walk(full, path);
        } else if (stat.isFile()) {
          found.set(path, { size: stat.size, mtimeMs: stat.mtimeMs, sha: sha256(readFileSync(full)) });
        }
      }
    };
    walk(this.dirs[side], "");
    return found;
  }

  /** The bytes of one file of one copy. */
  read(side: Side, path: string): Buffer {
    return readFileSync(join(this.dirs[side], path));
  }

  /** What {@link deliver} from `from` would do now (nothing is written). */
  pending(from: Side, options: Pick<DeliverOptions, "only" | "deletions" | "temps"> = {}): Delivered[] {
    const source = this.files(from);
    return this.plan(source, this.files(other(from)), options).map((w) => ({ ...w, bytes: source.get(w.path)?.size ?? 0 }));
  }

  /**
   * Carry what changed in `from`'s copy over to the other one: new and changed files, and deletions. Returns what
   * it did, in the order it did it.
   */
  async deliver(from: Side, options: DeliverOptions = {}): Promise<Delivered[]> {
    const to = other(from);
    const source = this.files(from);
    const target = this.files(to);
    let work = this.plan(source, target, options);
    if (options.order === "reversed") work = work.reverse();
    else if (options.order === "shuffled") work = shuffled(work, options.seed ?? 1);

    const done: Delivered[] = [];
    for (const { path, change } of work) {
      const destination = join(this.dirs[to], path);
      if (change === "deleted") {
        unlinkSync(destination);
        this.base.delete(path);
        done.push({ path, change, bytes: 0 });
        continue;
      }
      const seen = source.get(path)!;
      const bytes = this.read(from, path);
      mkdirSync(dirname(destination), { recursive: true, mode: 0o700 });
      if (change === "conflict") {
        // both sides changed it: the other side's version stays next to it, under Syncthing's conflict name
        const copy = `${path}.sync-conflict-20261007-091200-E2ESYNC`;
        copyFileSync(destination, join(this.dirs[to], copy));
        this.made[to].push(copy);
      }
      if (options.inPlace) {
        const half = Math.floor(bytes.length / 2);
        writeFileSync(destination, bytes.subarray(0, half));
        await sleep(options.pauseMs ?? 300);
        appendFileSync(destination, bytes.subarray(half));
      } else {
        const temporary = join(dirname(destination), `.syncthing.${path.split("/").pop()}.tmp`);
        writeFileSync(temporary, bytes);
        renameSync(temporary, destination);
      }
      utimesSync(destination, new Date(seen.mtimeMs), new Date(seen.mtimeMs));
      this.base.set(path, seen.sha);
      done.push({ path, change, bytes: bytes.length });
      if (options.conflictCopies && isHead(path)) {
        const copy = `${path} (conflicted copy 2026-10-07)`;
        writeFileSync(join(this.dirs[to], copy), bytes);
        this.made[to].push(copy);
      }
    }
    return done;
  }

  /** Every file one copy holds that the tool made itself and that is still there. */
  madeStillThere(side: Side): string[] {
    const files = this.files(side);
    return this.made[side].filter((path) => path === MARKER || files.has(path));
  }

  private plan(source: Map<string, Seen>, target: Map<string, Seen>, options: Pick<DeliverOptions, "only" | "deletions" | "temps">): Work[] {
    const wanted = (path: string) => (options.temps || !isTemp(path)) && (!options.only || options.only(path));
    const work: Work[] = [];
    for (const [path, seen] of source) {
      if (!wanted(path)) continue;
      const there = target.get(path);
      const was = this.base.get(path);
      if (there?.sha === seen.sha) {
        this.base.set(path, seen.sha); // in step already (both wrote the same bytes)
        continue;
      }
      if (!there) {
        // gone from the other copy since they were in step: that deletion travels the other way
        if (was !== undefined && was === seen.sha) continue;
        work.push({ path, change: "added" });
      } else if (was === there.sha || was === undefined) {
        work.push({ path, change: was === undefined ? "conflict" : "changed" });
      } else if (was !== seen.sha) {
        work.push({ path, change: "conflict" });
      }
      // else: only the other copy changed it — that travels the other way
    }
    if (options.deletions !== false) {
      for (const [path, there] of target) {
        if (source.has(path) || !wanted(path)) continue;
        if (this.base.get(path) === there.sha) work.push({ path, change: "deleted" });
      }
    }
    return work.sort((x, y) => (x.path < y.path ? -1 : x.path > y.path ? 1 : 0));
  }
}

function other(side: Side): Side {
  return side === "a" ? "b" : "a";
}
