/**
 * Your household in the mock backend (the static demo and `?mock=1`): the API's policy
 * (`ordnung.secretary.household`, ADR 0023) ported, held to it by the shared vectors in `householdVectors.json`
 * (`tests/test_household_vectors.py` holds the API to the same file).
 *
 * The household starts empty, as `ordnung demo`'s: no demo reading names anyone but Sam, so a letter asks only
 * once a test names its addressee (`ADDRESSEES`, `./data/documents`). A visitor can add people and file letters;
 * everything lives in the page's memory and goes with *Start over*. Nothing is ever filed without a press: a
 * suggestion is worked out on read. A letter deleted for good leaves no filing behind; the trash keeps it.
 */
import type { DocumentDetail, Household, HouseholdChange, HouseholdFiling, HouseholdMember, LetterFor, MemberIn } from "@/api/types";
import { addressedTo } from "./data/documents";
import type { MockDb } from "./db";

/** The `household` row as the API stores it (`StoredHousehold`): never an API body. */
export interface StoredHousehold {
  format: number;
  members: HouseholdMember[];
  /** letter id → member id, or `"me"` */
  links: Record<string, string>;
}

/** The version of a household with no people (the API's: 16 hex of the SHA-256 of `[]`). */
export const EMPTY_VERSION = "4f53cda18c2baa0c";

const MAX_PEOPLE = 12;
const MAX_NAME_CHARS = 120;
const MINE = "me";
const FORMAT = 1;
const MEMBER_ID = /^hhm_[0-9a-z]{12}$/;
const ID_ALPHABET = "0123456789abcdefghjkmnpqrstvwxyz";

// the API's words (`ordnung.secretary.household`)
const TYPE_A_NAME = "Type a name.";
const TOO_LONG = `Use at most ${MAX_NAME_CHARS} characters.`;
const NO_LETTERS = "Type a name with letters in it.";
const OWN_NAME = "That's your own name. Your household is the other people your letters come for.";
const ONE_AT_A_TIME = "Add one person at a time.";
const alreadyThere = (name: string) => `${name} is already in your household.`;
const TOO_MANY = `Your household can have at most ${MAX_PEOPLE} people.`;
const CHANGED_ELSEWHERE = "Your household changed in another window. Look again, then try once more.";
const NEWER_VERSION = "Your household was saved by a newer version of Ordnung. Update Ordnung on this computer.";
const NOT_IN_HOUSEHOLD = "That person isn't in your household any more.";
const NO_LETTER = "This letter doesn't exist (any more).";
const PROOF_FILE = "A proof file belongs to the letter it proves, not to a person.";
const ALSO_FILE_ALONE = "A letter can be filed only for the one person you add with it.";

/** A household refusal as the API answers it (`{detail}` with this status). */
export class HouseholdRefusal extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

/** The household a new demo starts with: nobody. */
export function emptyHousehold(): StoredHousehold {
  return { format: FORMAT, members: [], links: {} };
}

// ------------------------------------------------------------------------------------------------
// Names: the addressee policy's comparison (`ordnung.secretary.addressee`), ported
// ------------------------------------------------------------------------------------------------

const TRANSLIT: Record<string, string> = { ä: "ae", ö: "oe", ü: "ue" };
/** Letters (and numbers that aren't digits), as Python's `[^\W\d_]`. */
const WORD = /[\p{L}\p{Nl}\p{No}]+/gu;
const COURTESY = new Set(["herr", "herrn", "frau", "an", "z", "hd", "zhd", "mr", "mrs", "ms", "mx", "miss"]);
const TITLES = new Set(["dr", "prof"]);
const SEVERAL = new Set(["und", "and", "familie", "family", "eheleute", "ehepaar"]);
const SEVERAL_SIGN = /[&+]|\S\s+u\.\s+\S/i;
const CARE_OF = /\bc\s*\/\s*o\b/i;

/** `text` without case and accents: ä is ae (`umlauts`) or a, ß is ss. */
function fold(text: string, umlauts = true): string {
  let folded = text.normalize("NFKC").toLowerCase().replace(/ß/g, "ss");
  if (umlauts) folded = folded.replace(/[äöü]/g, (c) => TRANSLIT[c]!);
  return folded.normalize("NFKD").replace(/\p{M}/gu, "");
}

const wordsOf = (text: string): string[] => text.match(WORD) ?? [];
const words = (text: string) => wordsOf(fold(text)).filter((w) => !TITLES.has(w));

/** Each word of a name with the ways it is spelled ("Müller" is "Mueller" and "Muller"). */
function spellings(text: string): string[][] {
  const withE = wordsOf(fold(text));
  let plain = wordsOf(fold(text, false));
  if (plain.length !== withE.length) plain = withE;
  return withE.flatMap((word, i) => (TITLES.has(word) ? [] : [[word, plain[i]!]]));
}

/** The addressee without what follows "c/o" (where the letter goes). */
function forWhom(addressee: string): string {
  const found = CARE_OF.exec(addressee);
  return found ? addressee.slice(0, found.index) : addressee;
}

/** The addressee without its leading courtesy words ("An Frau Alex Rivera" → "Alex Rivera"). */
function withoutCourtesy(addressee: string): string {
  const parts = addressee.split(/\s+/).filter(Boolean);
  for (;;) {
    const letters = parts.length ? wordsOf(fold(parts[0]!)) : [];
    if (!letters.length || !letters.every((w) => COURTESY.has(w))) break;
    parts.shift();
  }
  return parts.join(" ");
}

const namesOthersRaw = (text: string) => SEVERAL_SIGN.test(text) || words(text).some((w) => SEVERAL.has(w));
const sameWord = (a: string[], b: string[]) =>
  a.some((x) => b.some((y) => x === y || ([...x].length === 1 && y.startsWith(x)) || ([...y].length === 1 && x.startsWith(y))));
const within = (ws: string[][], others: string[][]) => ws.every((w) => others.some((o) => sameWord(w, o)));

/** Whether `addressee` names the person called `name` alone (`addressee.names_alone`). */
export function namesAlone(addressee: string, name: string): boolean {
  const who = forWhom(addressee);
  if (namesOthersRaw(who)) return false;
  const theirs = spellings(withoutCourtesy(who));
  const mine = spellings(name);
  if (!theirs.length || !mine.length) return true;
  return within(theirs, mine) || within(mine, theirs);
}

/** Whether `addressee` (before "c/o") names more than one person (`addressee.names_others`). */
export const namesOthers = (addressee: string) => namesOthersRaw(forWhom(addressee));

/** Whether two names are one person's, spelled otherwise (`addressee.same_name`). */
export function sameName(a: string, b: string): boolean {
  const left = spellings(withoutCourtesy(a));
  const right = spellings(withoutCourtesy(b));
  return left.length > 0 && right.length > 0 && within(left, right) && within(right, left);
}

/** A name as a party keeps it: one line, no control or format characters, at most 120 characters (`link.party_name`). */
function partyName(name: string): string {
  const visible = name.replace(/\p{Cc}/gu, " ").replace(/\p{C}/gu, "");
  return [...visible.split(/\s+/).filter(Boolean).join(" ")].slice(0, MAX_NAME_CHARS).join("").trim();
}

/** How the letter's page names the addressee (`addressee.shown_name`). */
function shownName(addressee: string): string {
  const who = forWhom(addressee);
  return namesOthersRaw(who) ? partyName(who) : partyName(withoutCourtesy(partyName(who)));
}

// ------------------------------------------------------------------------------------------------
// The policy (`ordnung.secretary.household`)
// ------------------------------------------------------------------------------------------------

/** A tiny SHA-256 (the mock answers synchronously): the version must be the API's, byte for byte. */
function sha256Hex(text: string): string {
  // the round constants: the first 32 bits of the fractional parts of the cube roots of the first 64 primes
  const k = new Uint32Array(64);
  const isPrime = (n: number) => [...Array(Math.floor(Math.sqrt(n)) - 1).keys()].every((i) => n % (i + 2) !== 0);
  for (let n = 2, found = 0; found < 64; n++) if (isPrime(n)) k[found++] = Math.floor((Math.cbrt(n) % 1) * 2 ** 32) >>> 0;
  const h = new Uint32Array([0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19]);
  const bytes = new TextEncoder().encode(text);
  const length = Math.ceil((bytes.length + 9) / 64) * 64;
  const data = new Uint8Array(length);
  data.set(bytes);
  data[bytes.length] = 0x80;
  new DataView(data.buffer).setUint32(length - 4, bytes.length * 8);
  const w = new Uint32Array(64);
  const rotr = (x: number, n: number) => (x >>> n) | (x << (32 - n));
  for (let offset = 0; offset < length; offset += 64) {
    for (let t = 0; t < 16; t++) w[t] = new DataView(data.buffer).getUint32(offset + t * 4);
    for (let t = 16; t < 64; t++) {
      const s0 = rotr(w[t - 15]!, 7) ^ rotr(w[t - 15]!, 18) ^ (w[t - 15]! >>> 3);
      const s1 = rotr(w[t - 2]!, 17) ^ rotr(w[t - 2]!, 19) ^ (w[t - 2]! >>> 10);
      w[t] = (w[t - 16]! + s0 + w[t - 7]! + s1) >>> 0;
    }
    let [a, b, c, d, e, f, g, hh] = h as unknown as number[];
    for (let t = 0; t < 64; t++) {
      const t1 = (hh! + (rotr(e!, 6) ^ rotr(e!, 11) ^ rotr(e!, 25)) + ((e! & f!) ^ (~e! & g!)) + k[t]! + w[t]!) >>> 0;
      const t2 = ((rotr(a!, 2) ^ rotr(a!, 13) ^ rotr(a!, 22)) + ((a! & b!) ^ (a! & c!) ^ (b! & c!))) >>> 0;
      [hh, g, f, e, d, c, b, a] = [g, f, e, (d! + t1) >>> 0, c, b, a, (t1 + t2) >>> 0];
    }
    [a, b, c, d, e, f, g, hh].forEach((v, i) => (h[i] = (h[i]! + v!) >>> 0));
  }
  return [...h].map((v) => v.toString(16).padStart(8, "0")).join("");
}

/** The list of people's version (a PUT's base), as the API works it out: 16 hex of the SHA-256 of their canonical JSON. */
export function householdVersion(members: readonly HouseholdMember[]): string {
  return sha256Hex(JSON.stringify(members.map((m) => ({ id: m.id, name: m.name, signs: m.signs })))).slice(0, 16);
}

const NOBODY: LetterFor = { filed_for: null, mine: false, suggested: null, add: null };

function matching(addressee: string, members: readonly HouseholdMember[]): HouseholdMember[] {
  if (namesOthers(addressee) || !sameName(addressee, addressee)) return [];
  return members.filter((m) => namesAlone(addressee, m.name));
}

/** Who one letter is for (`household.answer`), from the household, the reading's addressee and the profile's name. */
export function answerFor(docId: string, addressee: string | null, profileName: string, stored: StoredHousehold): LetterFor {
  const link = stored.links[docId];
  const filed = stored.members.find((m) => m.id === link);
  if (filed) return { ...NOBODY, filed_for: { ...filed } };
  if (link === MINE) return { ...NOBODY, mine: true };
  const text = (addressee ?? "").trim();
  if (!text || !profileName.trim() || namesAlone(text, profileName) || !shownName(text)) return { ...NOBODY };
  const found = matching(text, stored.members);
  if (found.length === 1) return { ...NOBODY, suggested: { ...found[0]! } };
  if (!found.length && !namesOthers(text) && stored.members.length < MAX_PEOPLE) return { ...NOBODY, add: shownName(text) };
  return { ...NOBODY };
}

/** A name as it is kept, or the refusal saying why it can't be one person of the household (`household.clean_name`). */
function cleanName(name: string, profileName: string): string {
  const kept = partyName(name);
  if (!kept) throw new HouseholdRefusal(422, TYPE_A_NAME);
  if ([...name.split(/\s+/).filter(Boolean).join(" ")].length > MAX_NAME_CHARS) throw new HouseholdRefusal(422, TOO_LONG);
  if (!/\p{L}/u.test(kept) || !sameName(kept, kept)) throw new HouseholdRefusal(422, NO_LETTERS);
  if (namesOthers(kept)) throw new HouseholdRefusal(422, ONE_AT_A_TIME);
  if (profileName.trim() && namesAlone(kept, profileName)) throw new HouseholdRefusal(422, OWN_NAME);
  return kept;
}

function newMemberId(): string {
  const random = new Uint8Array(12);
  crypto.getRandomValues(random);
  return `hhm_${[...random].map((n) => ID_ALPHABET[n % 32]).join("")}`;
}

/** The new list of people, checked as the API checks it (`household.check_members`). */
export function checkMembers(members: readonly MemberIn[], stored: StoredHousehold, profileName: string): HouseholdMember[] {
  if (members.length > MAX_PEOPLE) throw new HouseholdRefusal(422, TOO_MANY);
  const before = new Map(stored.members.map((m) => [m.id, m]));
  const seen = new Set<string>();
  const names = members.map((member): [string, boolean] => {
    if (member.id != null) {
      if (!MEMBER_ID.test(member.id) || seen.has(member.id)) throw new HouseholdRefusal(422, NOT_IN_HOUSEHOLD);
      seen.add(member.id);
    }
    const kept = member.id != null ? before.get(member.id) : undefined;
    if (kept && partyName(member.name) === kept.name) return [kept.name, false];
    return [cleanName(member.name, profileName), true];
  });
  names.forEach(([name, fresh], index) => {
    if (!fresh) return;
    const same = names.find(([other], at) => at !== index && sameName(name, other));
    if (same) throw new HouseholdRefusal(422, alreadyThere(same[0]));
  });
  return members.map((member, i) => ({ id: member.id ?? newMemberId(), name: names[i]![0], signs: member.signs ?? true }));
}

/** The letters a link may name: every letter (the trash too) by id. */
const letterOf = (db: MockDb, id: string) => db.state.documents.find((d) => d.id === id) ?? null;

function fileable(db: MockDb, id: string): void {
  const d = letterOf(db, id);
  if (!d || d.deleted_at) throw new HouseholdRefusal(404, NO_LETTER);
  if (d.source === "proof") throw new HouseholdRefusal(422, PROOF_FILE);
}

function writable(stored: StoredHousehold): void {
  if (stored.format > FORMAT) throw new HouseholdRefusal(409, NEWER_VERSION);
}

/** `links` without letters that no longer exist at all (the trash keeps its own). */
const withoutGone = (db: MockDb, links: Record<string, string>) => Object.fromEntries(Object.entries(links).filter(([id]) => letterOf(db, id)));

/** Who a letter received is addressed to, as read (the test hook: Sam's mock life is one person). */
function addresseeOf(d: DocumentDetail["document"]): string | null {
  return d.direction === "incoming" ? addressedTo(d.id) : null;
}

/** `GET /api/household`. */
export function householdView(db: MockDb): Household {
  const stored = db.state.household;
  if (!stored.members.length && !Object.keys(stored.links).length) return { members: [], filed: {}, mine: [], suggested: {}, version: EMPTY_VERSION };
  const live = db.liveDocuments();
  const liveIds = new Set(live.map((d) => d.id));
  const ids = new Set(stored.members.map((m) => m.id));
  const filed = Object.fromEntries(Object.entries(stored.links).filter(([doc, link]) => liveIds.has(doc) && ids.has(link)));
  const mine = Object.entries(stored.links)
    .filter(([doc, link]) => liveIds.has(doc) && link === MINE)
    .map(([doc]) => doc)
    .sort();
  const suggested: Record<string, string> = {};
  if (stored.members.length) {
    const unanswered: StoredHousehold = { format: stored.format, members: stored.members, links: {} };
    for (const d of live) {
      if (d.id in filed || stored.links[d.id] === MINE) continue;
      const found = answerFor(d.id, addresseeOf(d), db.state.profile.name, unanswered).suggested;
      if (found) suggested[d.id] = found.id;
    }
  }
  return {
    members: stored.members.map((m) => ({ ...m, letters: Object.values(filed).filter((link) => link === m.id).length })),
    filed,
    mine,
    suggested,
    version: householdVersion(stored.members),
  };
}

/** `PUT /api/household`: replace the list of people, from the version the page saw. */
export function saveHousehold(db: MockDb, body: HouseholdChange): Household {
  const stored = db.state.household;
  writable(stored);
  if (body.base !== householdVersion(stored.members)) throw new HouseholdRefusal(409, CHANGED_ELSEWHERE);
  const checked = checkMembers(body.members, stored, db.state.profile.name);
  const added = checked.filter((_, i) => body.members[i]!.id == null).map((m) => m.id);
  const known = new Set([...stored.members, ...checked].map((m) => m.id));
  const links = withoutGone(db, Object.fromEntries(Object.entries(stored.links).filter(([, link]) => link === MINE || known.has(link))));
  const alsoFile = body.also_file ?? [];
  if (alsoFile.length) {
    if (added.length !== 1) throw new HouseholdRefusal(422, ALSO_FILE_ALONE);
    for (const id of alsoFile) {
      fileable(db, id);
      links[id] = added[0]!;
    }
  }
  db.state.household = { format: FORMAT, members: checked, links };
  return householdView(db);
}

/** `PATCH /api/household`: file letters for a person, as the person's own, or forget the answer. */
export function fileLetters(db: MockDb, body: HouseholdFiling): Household {
  const stored = db.state.household;
  writable(stored);
  const ids = new Set(stored.members.map((m) => m.id));
  const links = { ...stored.links };
  for (const [id, link] of Object.entries(body.letters)) {
    fileable(db, id);
    if (link != null && link !== MINE && !ids.has(link)) throw new HouseholdRefusal(422, NOT_IN_HOUSEHOLD);
    if (link == null) delete links[id];
    else links[id] = link;
  }
  db.state.household = { ...stored, links: withoutGone(db, links) };
  return householdView(db);
}

/** Who a letter is for, on its page (`LetterDetail.household`): nothing for one in the trash or a proof file. */
export function letterFor(db: MockDb, doc: DocumentDetail["document"]): LetterFor {
  if (doc.deleted_at || doc.source === "proof") return { ...NOBODY };
  return answerFor(doc.id, addresseeOf(doc), db.state.profile.name, db.state.household);
}

/** A letter deleted for good: its filing goes with it (the trash keeps it). */
export function forgetLetterFiling(db: MockDb, docId: string): void {
  delete db.state.household.links[docId];
}
