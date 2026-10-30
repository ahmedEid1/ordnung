/**
 * Your household in the mock backend (the static demo, `?mock=1`): the API's policy ported to `./household`, held to
 * it by the shared vectors (`householdVectors.json`, which `tests/test_household_vectors.py` holds the API to), and
 * the three operations as the API answers them — on a paired phone too.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import type { DocumentDetail, Household, HouseholdMember } from "@/api/types";
import { openApiPhoneScope } from "@/test/mockFetch";
import { ADDRESSEES } from "./data/documents";
import { answerFor, checkMembers, emptyHousehold, HouseholdRefusal, householdVersion, possessive, type StoredHousehold } from "./household";
import { createMockServer } from "./server";

interface LetterVector {
  kind: "letter";
  case: string;
  profile: string;
  members: string[];
  link: string | null;
  addressee: string | null;
  expect: { filed_for: string | null; mine: boolean; suggested: string | null; add: string | null };
}
interface NameVector {
  kind: "name";
  case: string;
  profile: string;
  members: string[];
  name: string;
  expect: { kept: string } | { refused: string };
}
interface VersionVector {
  kind: "version";
  case: string;
  members: HouseholdMember[];
  expect: string;
}
/** A name's possessive in an Idea's title ("Alex Rivera's passport …"), or null: "For Kim 2: …". */
interface PossessiveVector {
  kind: "possessive";
  case: string;
  name: string;
  expect: string | null;
}
type Vector = LetterVector | NameVector | VersionVector | PossessiveVector;

const VECTORS = JSON.parse(readFileSync(resolve(__dirname, "householdVectors.json"), "utf8")) as Vector[];
const DOC = "doc_vector00000";
const SAM = "Sam Rivera";
const ALEX = "Alex Rivera";
const MIA = "Mia Rivera";

const members = (names: string[]): HouseholdMember[] => names.map((name, n) => ({ id: `hhm_${String(n).padStart(12, "0")}`, name, signs: true }));

function letterAnswer(v: LetterVector) {
  const people = members(v.members);
  const links: Record<string, string> = {};
  if (v.link === "me") links[DOC] = "me";
  else if (v.link === "removed") links[DOC] = "hhm_removed00000";
  else if (v.link) links[DOC] = people.find((m) => m.name === v.link)!.id;
  const found = answerFor(DOC, v.addressee, v.profile, { format: 1, members: people, links });
  return { filed_for: found.filed_for?.name ?? null, mine: found.mine, suggested: found.suggested?.name ?? null, add: found.add };
}

function nameAnswer(v: NameVector) {
  const stored: StoredHousehold = { format: 1, members: members(v.members), links: {} };
  try {
    const checked = checkMembers([...stored.members, { id: null, name: v.name, signs: true }], stored, v.profile);
    return { kept: checked.at(-1)!.name };
  } catch (err) {
    if (!(err instanceof HouseholdRefusal)) throw err;
    expect(err.status).toBe(422);
    return { refused: err.message };
  }
}

describe("the shared household vectors", () => {
  it("has every kind", () => {
    const kinds = VECTORS.map((v) => v.kind);
    expect(kinds.filter((k) => k === "letter").length).toBeGreaterThanOrEqual(30);
    expect(kinds.filter((k) => k === "name").length).toBeGreaterThanOrEqual(20);
    expect(kinds.filter((k) => k === "version").length).toBeGreaterThanOrEqual(3);
    expect(kinds.filter((k) => k === "possessive").length).toBeGreaterThanOrEqual(6);
  });

  it.each(VECTORS.map((v) => [v.case, v] as const))("meets “%s” as the API does", (_case, v) => {
    if (v.kind === "letter") expect(letterAnswer(v)).toEqual(v.expect);
    else if (v.kind === "name") expect(nameAnswer(v)).toEqual(v.expect);
    else if (v.kind === "possessive") expect(possessive(v.name)).toBe(v.expect);
    else expect(householdVersion(v.members)).toBe(v.expect);
  });
});

// ------------------------------------------------------------------------------------------------
// The three operations
// ------------------------------------------------------------------------------------------------

type Srv = ReturnType<typeof createMockServer>;
const srv = (phone = false) => createMockServer({ staticDemo: false, latency: 0, phoneScope: phone ? openApiPhoneScope() : undefined });

async function call(s: Srv, method: string, path: string, body?: unknown): Promise<{ status: number; json: unknown }> {
  const res = await s.handle(method, path, new URLSearchParams(), body);
  return { status: res.status, json: await res.json() };
}

async function household(s: Srv): Promise<Household> {
  return (await call(s, "GET", "/household")).json as Household;
}

async function put(s: Srv, people: { id?: string | null; name: string; signs?: boolean }[], also_file: string[] = [], base?: string) {
  return call(s, "PUT", "/household", { base: base ?? (await household(s)).version, members: people.map((p) => ({ id: null, signs: true, ...p })), also_file });
}

/** Two demo letters addressed to someone else (the test hook the letter's page reads), handed back afterwards. */
function addressed(s: Srv, ...names: string[]): string[] {
  const docs = s.db.liveDocuments().filter((d) => d.direction === "incoming");
  return names.map((name, i) => {
    const id = docs[i]!.id;
    ADDRESSEES[id] = name;
    return id;
  });
}
afterEach(() => {
  for (const id of Object.keys(ADDRESSEES)) delete ADDRESSEES[id];
});

describe("your household in the mock", () => {
  it("starts empty, with the API's version of a household with no people", () => {
    expect(householdVersion([])).toBe("4f53cda18c2baa0c");
    expect(emptyHousehold()).toEqual({ format: 1, members: [], links: {} });
  });

  it("adds, renames and removes people, from the version the page saw", async () => {
    const s = srv();
    const added = await put(s, [{ name: ALEX }, { name: MIA, signs: false }]);
    expect(added.status).toBe(200);
    const [alex, mia] = (added.json as Household).members;
    expect([alex!.name, alex!.signs, alex!.letters, mia!.signs]).toEqual([ALEX, true, 0, false]);
    expect(alex!.id).toMatch(/^hhm_[0-9a-z]{12}$/);
    const renamed = await put(s, [{ id: mia!.id, name: "Mia Rivera-Smith" }, { id: alex!.id, name: ALEX }]);
    expect((renamed.json as Household).members.map((m) => m.name)).toEqual(["Mia Rivera-Smith", ALEX]);
    const stale = await put(s, [{ name: "Kim Rivera" }], [], added.json ? (added.json as Household).version : undefined);
    expect(stale).toEqual({ status: 409, json: { detail: "Your household changed in another window. Look again, then try once more." } });
    const own = await put(s, [{ id: alex!.id, name: ALEX }, { name: SAM }]);
    expect(own).toEqual({ status: 422, json: { detail: "That's your own name. Your household is the other people your letters come for." } });
    const removed = await put(s, [{ id: alex!.id, name: ALEX }]);
    expect((removed.json as Household).members.map((m) => m.id)).toEqual([alex!.id]);
    expect(await household(s)).toEqual(removed.json);
  });

  it("suggests from the addressee, files on a press, says mine, forgets, and Undo puts a removed person's letters back", async () => {
    const s = srv();
    const [forAlex, alsoAlex] = addressed(s, "Frau Alex Rivera", ALEX);
    const alex = ((await put(s, [{ name: ALEX }, { name: MIA }])).json as Household).members[0]!;
    const mia = (await household(s)).members[1]!;
    expect((await household(s)).suggested).toEqual({ [forAlex!]: alex.id, [alsoAlex!]: alex.id });
    expect(s.db.state.household.links).toEqual({}); // a suggestion files nothing
    const filed = (await call(s, "PATCH", "/household", { letters: { [forAlex!]: alex.id, [alsoAlex!]: "me" } })).json as Household;
    expect([filed.filed, filed.mine, filed.suggested, filed.members[0]!.letters]).toEqual([{ [forAlex!]: alex.id }, [alsoAlex], {}, 1]);
    const page = (await call(s, "GET", `/documents/${forAlex}`)).json as DocumentDetail;
    expect(page.household).toEqual({ filed_for: { id: alex.id, name: ALEX, signs: true }, mine: false, suggested: null, add: null });
    // removed: the letter counts as the person's again; Undo (the same id) files it again
    const removed = (await put(s, [{ id: mia.id, name: MIA }])).json as Household;
    expect(removed.filed).toEqual({});
    const back = (await put(s, [{ id: mia.id, name: MIA }, { id: alex.id, name: ALEX }])).json as Household;
    expect(back.filed).toEqual({ [forAlex!]: alex.id });
    const undone = (await call(s, "PATCH", "/household", { letters: { [forAlex!]: null, [alsoAlex!]: null } })).json as Household;
    expect([undone.filed, undone.mine]).toEqual([{}, []]);
  });

  it("offers to add the one person a letter names, and files it for them with the person in one change", async () => {
    const s = srv();
    const [forKim] = addressed(s, "Herrn Dr. Kim Rivera");
    const page = (await call(s, "GET", `/documents/${forKim}`)).json as DocumentDetail;
    expect(page.household).toEqual({ filed_for: null, mine: false, suggested: null, add: "Dr. Kim Rivera" });
    const added = (await put(s, [{ name: "Dr. Kim Rivera" }], [forKim!])).json as Household;
    expect(added.filed).toEqual({ [forKim!]: added.members[0]!.id });
  });

  it("refuses unknown people, letters in the trash or gone, and proof files, and keeps nothing of them", async () => {
    const s = srv();
    const [letter, trashed] = addressed(s, ALEX, ALEX);
    const alex = ((await put(s, [{ name: ALEX }])).json as Household).members[0]!;
    expect((await call(s, "DELETE", `/documents/${trashed}`)).status).toBe(200);
    const proof = s.db.state.documents.find((d) => d.source === "proof");
    const cases: [Record<string, string | null>, number][] = [
      [{ [letter!]: "hhm_000000000000" }, 422],
      [{ [letter!]: alex.id, [trashed!]: alex.id }, 404],
      [{ doc_nothere: "me" }, 404],
      ...(proof ? ([[{ [proof.id]: "me" }, 422]] as [Record<string, string | null>, number][]) : []),
    ];
    for (const [letters, status] of cases) expect((await call(s, "PATCH", "/household", { letters })).status, JSON.stringify(letters)).toBe(status);
    expect(s.db.state.household.links).toEqual({});
  });

  it("keeps a trashed letter's filing for its return and forgets one deleted for good", async () => {
    const s = srv();
    const [trashed, purged] = addressed(s, ALEX, ALEX);
    const alex = ((await put(s, [{ name: ALEX }])).json as Household).members[0]!;
    await call(s, "PATCH", "/household", { letters: { [trashed!]: alex.id, [purged!]: alex.id } });
    await call(s, "DELETE", `/documents/${trashed}`);
    await s.handle("DELETE", `/documents/${purged}`, new URLSearchParams("purge=true"), undefined);
    expect((await household(s)).filed).toEqual({});
    expect(s.db.state.household.links).toEqual({ [trashed!]: alex.id });
  });

  it("lets a paired phone read and file, never edit the list", async () => {
    const s = srv(true);
    s.db.state.household = { format: 1, members: [{ id: "hhm_000000000000", name: ALEX, signs: true }], links: {} };
    const [letter] = addressed(s, ALEX);
    expect((await call(s, "GET", "/household")).status).toBe(200);
    expect((await call(s, "PATCH", "/household", { letters: { [letter!]: "hhm_000000000000" } })).status).toBe(200);
    const refused = await put(s, [], [], (await household(s)).version);
    expect([refused.status, (refused.json as { code: string }).code]).toEqual([403, "computer_only"]);
    expect(s.db.state.household.members.map((m) => m.name)).toEqual([ALEX]);
  });

  it("never overwrites a household saved by a newer Ordnung", async () => {
    const s = srv();
    s.db.state.household = { format: 2, members: [{ id: "hhm_000000000000", name: ALEX, signs: true }], links: {} };
    const refused = await put(s, [{ name: MIA }]);
    expect(refused).toEqual({ status: 409, json: { detail: "Your household was saved by a newer version of Ordnung. Update Ordnung on this computer." } });
    expect((await household(s)).members.map((m) => m.name)).toEqual([ALEX]);
  });
});
