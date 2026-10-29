/**
 * My numbers per person in the mock backend (the static demo): the visitor files a letter for someone of the
 * household and its numbers move to their *About* group, as `ordnung/numbers.py` moves them. Held to the real code by
 * `MOCK_NUMBERS_FOR_ALEX` (`scripts/gen_mock_numbers.py`), the page the API gives for the same two filings.
 */
import { describe, expect, it } from "vitest";
import type { Household, NumbersPage } from "@/api/types";
import { createMockServer, type MockServer } from "./server";
import { mockNumbers } from "./numbers";
import { MOCK_ALEX, MOCK_NUMBERS, MOCK_NUMBERS_FOR_ALEX } from "./data/numbers";

const srv = () => createMockServer({ staticDemo: false, latency: 0 });

async function call<T>(s: MockServer, method: string, path: string, body?: unknown): Promise<T> {
  const res = await s.handle(method, path, new URLSearchParams(), body);
  expect(res.status, `${method} ${path}`).toBe(200);
  return (await res.json()) as T;
}

/** Add one person to the household, filing `letters` for them at once (as a letter's *Add … to your household* does). */
async function addPerson(s: MockServer, name: string, letters: string[] = []): Promise<string> {
  const before = await call<Household>(s, "GET", "/household");
  const members = [...before.members.map(({ id, name: kept, signs }) => ({ id, name: kept, signs })), { name }];
  const after = await call<Household>(s, "PUT", "/household", { base: before.version, members, also_file: letters });
  return after.members.find((m) => m.name === name)!.id;
}

/** The letters filed for Alex in the generated page: the first health insurance number's and the passport's. */
function alexLetters(): string[] {
  const health = MOCK_NUMBERS.about_you.find((n) => n.kind === "health_insurance")!;
  const passport = MOCK_NUMBERS.documents.find((d) => d.kind === "passport")!;
  return [health.letter!.id, passport.letter!.id];
}

/** A page with every `key` left out and a person's id put as `id`: the mock's keys are its own. */
function keysAside(page: NumbersPage, memberId: string, as: string): unknown {
  const text = JSON.stringify(page, (name, value: unknown) => (name === "key" ? undefined : value));
  return JSON.parse(text.split(memberId).join(as));
}

describe("My numbers per person in the mock", () => {
  it("regroups numbers when the visitor files a letter", async () => {
    const s = srv();
    const health = MOCK_NUMBERS.about_you.find((n) => n.kind === "health_insurance")!;
    const alex = await addPerson(s, "Alex Rivera");
    let page = await call<NumbersPage>(s, "GET", "/numbers");
    expect(page.household).toEqual([]);
    expect(page.about_you.map((n) => n.key)).toContain(health.key);

    await call<Household>(s, "PATCH", "/household", { letters: { [health.letter!.id]: alex } });
    page = await call<NumbersPage>(s, "GET", "/numbers");
    expect(page.about_you.map((n) => n.kind)).not.toContain("health_insurance");
    expect(page.household.map((p) => [p.id, p.name])).toEqual([[alex, "Alex Rivera"]]);
    const [moved] = page.household[0]!.about;
    expect(moved).toMatchObject({ kind: "health_insurance", value: health.value, letter: health.letter, letters: 1 });
    expect(moved!.key).not.toBe(health.key);
    // the organisation's call sheet stays one, and says whose the number is
    const sheet = page.organisations.find((o) => o.party_id === health.party_id)!;
    expect(sheet.numbers.map((n) => n.key)).toContain(health.key);
    expect(page.filed_for[health.key]).toBe(alex);

    // "No, it's mine": the person's again
    await call<Household>(s, "PATCH", "/household", { letters: { [health.letter!.id]: "me" } });
    page = await call<NumbersPage>(s, "GET", "/numbers");
    expect([page.household, page.filed_for, page.also_for]).toEqual([[], {}, {}]);
    expect(page.about_you).toEqual(mockNumbers(srv().db).about_you);
  });

  it("matches the real grouping for the two letters filed for Alex", async () => {
    const s = srv();
    const alex = await addPerson(s, MOCK_ALEX.name, alexLetters());
    const page = mockNumbers(s.db);
    expect(keysAside(page, alex, MOCK_ALEX.id)).toEqual(keysAside(MOCK_NUMBERS_FOR_ALEX, MOCK_ALEX.id, MOCK_ALEX.id));
    // the call-sheet numbers keep their keys, so filed_for is the real one
    expect(JSON.parse(JSON.stringify(page.filed_for).split(alex).join(MOCK_ALEX.id))).toEqual(MOCK_NUMBERS_FOR_ALEX.filed_for);
    // a person's keys are their own
    const own = new Set(MOCK_NUMBERS.about_you.map((n) => n.key));
    for (const n of page.household[0]!.about) expect(own.has(n.key)).toBe(false);
  });

  it("gives the numbers back when the member is removed", async () => {
    const s = srv();
    await addPerson(s, "Alex Rivera", alexLetters());
    expect(mockNumbers(s.db).household).toHaveLength(1);
    const before = await call<Household>(s, "GET", "/household");
    await call<Household>(s, "PUT", "/household", { base: before.version, members: [] });
    const page = mockNumbers(s.db);
    expect([page.household, page.filed_for, page.also_for]).toEqual([[], {}, {}]);
    expect(page).toEqual(mockNumbers(srv().db));
  });

  it("marks a call-sheet number as no one's in particular when two people's letters show it", async () => {
    const s = srv();
    // two letters of one organisation show the gym's member number: one filed for Alex, the other the person's
    const shared = MOCK_NUMBERS.organisations.flatMap((o) => o.numbers).find((n) => n.letters > 1)!;
    expect(shared).toBeDefined();
    const alex = await addPerson(s, "Alex Rivera", [shared.letter!.id]);
    const page = mockNumbers(s.db);
    // a call sheet's number of two people's letters is no one's in particular
    expect(page.filed_for[shared.key]).toBeUndefined();
    expect(page.household.map((p) => p.id)).not.toContain(alex);
  });

  it("names a member's residence permit note in their words", async () => {
    const s = srv();
    const permit = MOCK_NUMBERS.documents.find((d) => d.kind === "residence_permit")!;
    const item = s.db.state.items.find((i) => i.id === permit.item_id)!;
    await addPerson(s, "Alex Rivera", [item.doc_id!]);
    const page = mockNumbers(s.db);
    expect(page.documents.map((d) => d.kind)).not.toContain("residence_permit");
    const theirs = page.household[0]!.documents.find((d) => d.kind === "residence_permit")!;
    expect(theirs.note).toMatch(/^Apply before it expires: their permit then counts/);
    expect(theirs.note).not.toMatch(/\byour\b/);
  });
});
