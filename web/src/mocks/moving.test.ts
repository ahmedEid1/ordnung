/**
 * The static demo's moving checklist (`./moving.ts`): the same rows as `secretary/moving.py` on the shared
 * cases (`moving-cases.json`, which tests/test_moving.py reads too), and the mock API's "I moved", "Stop the
 * checklist" and a new-address letter marked sent, as the API answers them.
 */
import { describe, expect, it } from "vitest";
import type { Contract, Dashboard, Party, Profile, Suggestion } from "@/api/types";
import { createMockServer } from "./server";
import { MOVE_WINDOW_PROBLEM, MOVED_HOUSE_RULE, movingIdeas } from "./moving";
import cases from "./moving-cases.json";

interface CaseRow {
  entity: string;
  title: string;
  body: string;
  rationale: string | null;
  kind: string;
  priority: string;
  due_date: string | null;
  action: { type: string; target_type: string | null; target_id: string | null; label: string | null };
}

const srv = () => createMockServer({ staticDemo: false, latency: 0 });
const rows = (ideas: readonly Suggestion[]) => ideas.filter((s) => s.rule_id === MOVED_HOUSE_RULE);

describe("the moving checklist in the static demo", () => {
  it.each(cases.cases.map((c) => [c.name, c] as const))("says what the API says: %s", (_name, c) => {
    const parties = c.parties.map((p) => ({ id: p.id, name: p.name, kind: p.kind }) as Party);
    const contracts = c.contracts.map((x, i) => ({ id: `ctr_${i}`, party_id: x.party_id, name: x.name, category: x.category, status: x.status }) as Contract);
    const profile = { ...c.profile } as Pick<Profile, "moved_on" | "address" | "old_address">;
    const found = movingIdeas({ profile, parties, contracts, drafts: [], today: c.today }).map(
      (s): CaseRow => ({
        entity: s.fingerprint.split(":")[1]!,
        title: s.title,
        body: s.body,
        rationale: s.rationale,
        kind: s.kind,
        priority: s.priority,
        due_date: s.due_date,
        action: { type: s.action!.type, target_type: s.action!.target_type, target_id: s.action!.target_id, label: s.action!.label },
      }),
    );
    expect(found).toEqual(c.rows);
  });

  it("“I moved” lists who to tell on Today; stopping the checklist takes the rows away again", async () => {
    const s = srv();
    const put = (body: Record<string, unknown>) => s.handle("PUT", "/profile", new URLSearchParams(), body);
    const dashboard = async () => (await (await s.handle("GET", "/dashboard", new URLSearchParams(), undefined)).json()) as Dashboard;
    expect(rows((await dashboard()).suggestions)).toEqual([]);

    expect((await put({ moved_on: "2026-09-21", old_address: "Beispielweg 5\n12345 Musterstadt" })).status).toBe(200);
    const listed = rows((await dashboard()).suggestions);
    expect(listed.map((r) => r.title)).toContain("Register your new address by Mon 5 Oct");
    expect(listed.map((r) => r.title)).toContain("Tell FunkNetz Mobil GmbH your new address");
    // the flat's contract is named after it: counted, never named
    const landlord = listed.find((r) => r.action?.target_id === "pty_wohnbau")!;
    expect(landlord.body).toMatch(/^Your contract with them is running\./);

    expect((await put({ moved_on: "", old_address: "" })).status).toBe(200);
    expect(rows((await dashboard()).suggestions)).toEqual([]);
    expect(s.db.state.suggestions.filter((x) => x.rule_id === MOVED_HOUSE_RULE).every((x) => x.status === "expired")).toBe(true);
  });

  it("a move outside the last six months or the next three is refused, with the API's words", async () => {
    const s = srv();
    for (const day of ["2026-03-31", "2026-12-28"]) {
      const res = await s.handle("PUT", "/profile", new URLSearchParams(), { moved_on: day });
      expect(res.status).toBe(422);
      expect(((await res.json()) as { detail: string }).detail).toBe(MOVE_WINDOW_PROBLEM);
    }
    expect(s.db.state.profile.moved_on).toBeNull();
    for (const day of ["2026-04-01", "2026-12-27"]) expect((await s.handle("PUT", "/profile", new URLSearchParams(), { moved_on: day })).status).toBe(200);
  });

  it("a ticked row stays ticked, and a new-address letter marked sent takes its sender's row away", async () => {
    const s = srv();
    await s.handle("PUT", "/profile", new URLSearchParams(), { moved_on: "2026-09-21", old_address: "Beispielweg 5\n12345 Musterstadt" });
    const bank = rows(s.db.state.suggestions).find((r) => r.action?.target_id === "pty_musterbank")!;
    await s.handle("PATCH", `/suggestions/${bank.id}`, new URLSearchParams(), { status: "done" });
    await s.handle("PUT", "/profile", new URLSearchParams(), { name: "Sam Rivera" });
    expect(s.db.state.suggestions.find((x) => x.id === bank.id)?.status).toBe("done");

    const telecom = rows(s.db.state.suggestions).find((r) => r.action?.target_id === "pty_funknetz")!;
    s.db.state.drafts.push({ ...s.db.state.drafts[0]!, id: "drf_move", kind: "address_change", party_id: "pty_funknetz", status: "final", sent_at: null });
    const sent = await s.handle("POST", "/drafts/drf_move/sent", new URLSearchParams(), { channel: "letter", date: "2026-09-28" });
    expect(sent.status).toBe(200);
    expect(s.db.state.suggestions.find((x) => x.id === telecom.id)?.status).toBe("expired");
  });
});
