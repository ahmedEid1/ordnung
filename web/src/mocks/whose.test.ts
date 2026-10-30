/**
 * Whose an Idea, a calendar entry and the full notification are about in the mock backend (ADR 0023), as the API
 * words them (`secretary/triggers.py`, `calendar/ics.py`, `notify/desktop.py`): only a letter the visitor filed for
 * someone of the household names them, never a suggestion, "No, it's mine" or someone since removed.
 */
import { describe, expect, it } from "vitest";
import type { DesktopReminders, Household, Suggestion } from "@/api/types";
import { createMockServer } from "./server";

const srv = () => createMockServer({ staticDemo: false, latency: 0 });
type Srv = ReturnType<typeof srv>;

async function call<T>(s: Srv, method: string, path: string, body?: unknown): Promise<T> {
  const res = await s.handle(method, path, new URLSearchParams(), body);
  expect(res.ok, `${method} ${path} → ${res.status}`).toBe(true);
  return (await res.json()) as T;
}

/** Add one person, filing `letters` for them at once (as Settings and a letter's page do). */
async function addPerson(s: Srv, name: string, letters: string[] = []): Promise<string> {
  const before = await call<Household>(s, "GET", "/household");
  const after = await call<Household>(s, "PUT", "/household", {
    base: before.version,
    members: [...before.members.map(({ id, name: n, signs }) => ({ id, name: n, signs })), { name }],
    ...(letters.length ? { also_file: letters.slice(0, 1) } : {}),
  });
  const id = after.members.find((m) => m.name === name)!.id;
  if (letters.length > 1) await file(s, Object.fromEntries(letters.map((doc) => [doc, id])));
  return id;
}

const file = (s: Srv, letters: Record<string, string | null>) => call<Household>(s, "PATCH", "/household", { letters });

async function titles(s: Srv): Promise<Record<string, string>> {
  const ideas = await call<Suggestion[]>(s, "GET", "/suggestions");
  return Object.fromEntries(ideas.map((idea) => [idea.id, idea.title]));
}

function ics(s: Srv): string {
  const url = s.resolveAsset("/calendar.ics")!;
  return decodeURIComponent(url.slice(url.indexOf(",") + 1));
}

describe("whose it is in the mock (ADR 0023)", () => {
  it("names the member in a canned Idea about their letter, and nobody's otherwise", async () => {
    const s = srv();
    const own = await titles(s);
    await addPerson(s, "Alex Rivera", ["doc_parking", "doc_tm_dunning"]);
    const named = await titles(s);
    expect(named.sug_parking).toBe(`For Alex Rivera: ${own.sug_parking}`);
    expect(named.sug_techmarkt).toBe(`For Alex Rivera: ${own.sug_techmarkt}`);
    // a contract's decision, the calendar and an Idea of the weekly review never name anyone
    for (const id of ["sug_phone", "sug_calendar", "sug_ticket", "sug_bank"]) expect(named[id], id).toBe(own[id]);
    // nothing is stored: the canned Idea keeps its own title
    expect(s.db.state.suggestions.find((idea) => idea.id === "sug_parking")!.title).toBe(own.sug_parking);

    await file(s, { doc_parking: "me", doc_tm_dunning: null });
    expect(await titles(s)).toEqual(own);
  });

  it("says whose passport it is only when the passport and the permit are one person's", async () => {
    const s = srv();
    const own = await titles(s);
    const alex = await addPerson(s, "Alex Rivera", ["doc_passport"]);
    expect((await titles(s)).sug_passport).toBe(own.sug_passport); // the permit's letter is still the person's
    await file(s, { doc_abh: alex });
    expect((await titles(s)).sug_passport).toBe("Renew Alex Rivera's passport before their residence permit appointment");
    const kim = await addPerson(s, "Kim 2");
    await file(s, { doc_passport: kim, doc_abh: kim });
    expect((await titles(s)).sug_passport).toBe("For Kim 2: Renew the passport before the residence permit appointment");
  });

  it("names no one in an Idea about a letter kept private, whose title would reach Claude", async () => {
    const s = srv();
    const own = await titles(s);
    await addPerson(s, "Alex Rivera", ["doc_parking"]);
    expect((await titles(s)).sug_parking).toBe(`For Alex Rivera: ${own.sug_parking}`);
    s.db.document("doc_parking")!.ai_private = true;
    expect((await titles(s)).sug_parking).toBe(own.sug_parking);
  });

  it("forgets the name once the person is removed", async () => {
    const s = srv();
    const own = await titles(s);
    await addPerson(s, "Alex Rivera", ["doc_parking"]);
    const household = await call<Household>(s, "GET", "/household");
    await call<Household>(s, "PUT", "/household", { base: household.version, members: [] });
    expect(await titles(s)).toEqual(own);
  });

  it("names the member in the mock calendar and the full notification, never in the discreet one", async () => {
    const s = srv();
    const before = ics(s);
    const quiet = await call<DesktopReminders>(s, "GET", "/reminders/desktop");
    expect(before).toContain("SUMMARY:Pay the parking fine");
    await addPerson(s, "Alex Rivera", ["doc_parking"]);
    const after = ics(s);
    expect(after).toContain("SUMMARY:Alex Rivera: Pay the parking fine");
    expect(after).toContain("DESCRIPTION:Alex Rivera: Pay the parking fine");
    expect(after.replace(/Alex Rivera: /g, "")).toBe(before);
    const reminders = await call<DesktopReminders>(s, "GET", "/reminders/desktop");
    expect(reminders.preview.full?.body).toContain("Alex Rivera: Pay the parking fine");
    expect(reminders.preview.discreet).toEqual(quiet.preview.discreet);
    expect(JSON.stringify(reminders.preview.discreet)).not.toContain("Alex");
  });
});
