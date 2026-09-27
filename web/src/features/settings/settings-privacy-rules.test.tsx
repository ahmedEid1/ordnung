/**
 * Settings → "How dates are computed" and "Privacy & AI usage": rules by topic with every source
 * readable, a search that counts and clears, and a privacy log that fits phones and reads short.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { qk } from "@/api/hooks";
import type { Activity, LLMCallRecord, RuleInfo, UsageStats } from "@/api/types";
import { __clearToasts } from "@/components/ui/Toast";
import { RULES, USAGE } from "@/mocks/data/system";
import { makeTestQueryClient, renderWithProviders } from "@/test/render";
import { useMockApi } from "@/test/mockFetch";
import SettingsPage from "@/pages/SettingsPage";
import { activityHref, groupActivity, groupRules, matchesRule, OTHER_RULES_TOPIC, splitCitation } from "./logic";

class RO {
  observe() {}
  unobserve() {}
  disconnect() {}
}

beforeEach(() => {
  vi.stubGlobal("ResizeObserver", RO);
  vi.stubGlobal("scrollTo", () => {});
});
afterEach(() => {
  vi.unstubAllGlobals();
  act(() => __clearToasts());
});

const activity = (id: number, kind: string, message: string, ref_type: string | null = null, ref_id: string | null = null): Activity => ({
  id,
  ts: "2026-09-28T10:57:00",
  kind,
  message,
  ref_type,
  ref_id,
  data: {},
});

describe("rules logic", () => {
  it("splits a citation into its sources — a “;” inside brackets stays", () => {
    expect(splitCitation("§ 193 BGB")).toEqual(["§ 193 BGB"]);
    expect(splitCitation("§ 193 BGB; §§ 269, 270 Abs. 4 BGB; BAG 8 AZN 808/11; BGH VI ZA 27/11")).toEqual([
      "§ 193 BGB",
      "§§ 269, 270 Abs. 4 BGB",
      "BAG 8 AZN 808/11",
      "BGH VI ZA 27/11",
    ]);
    expect(splitCitation("§ 41 Abs. 2 of the Länder VwVfGs (e.g. Art. 41 BayVwVfG; § 102b LVwVfG BW)")).toEqual([
      "§ 41 Abs. 2 of the Länder VwVfGs (e.g. Art. 41 BayVwVfG; § 102b LVwVfG BW)",
    ]);
    expect(splitCitation(" ; § 1 BGB ;")).toEqual(["§ 1 BGB"]);
  });

  it("groups rules by topic in catalog order, rules without one last", () => {
    const r = (id: string, topic: string | null) => ({ id, topic });
    const groups = groupRules([r("a", "Counting periods"), r("x", null), r("b", "Price increases"), r("c", "Counting periods")]);
    expect(groups.map((g) => [g.topic, g.rules.map((x) => x.id)])).toEqual([
      ["Counting periods", ["a", "c"]],
      ["Price increases", ["b"]],
      [OTHER_RULES_TOPIC, ["x"]],
    ]);
  });

  it("finds a rule by title, source, summary or topic", () => {
    const rule = { title: "Phone & internet contracts", citation: "§ 56 TKG", summary: "Max. 24 months minimum term.", topic: "Contracts and notice" };
    for (const q of ["phone", "tkg", "minimum", "contracts and", "  "]) expect(matchesRule(rule, q)).toBe(true);
    expect(matchesRule(rule, "tax")).toBe(false);
  });
});

describe("activity logic", () => {
  it("links letters, drafts and Ask's checks of an answer", () => {
    expect(activityHref(activity(1, "document.processed", "Read", "document", "doc_1"))).toBe("/documents/doc_1");
    expect(activityHref(activity(1, "draft.sent", "Sent", "draft", "drf_1"))).toBe("/letters/drf_1");
    expect(activityHref(activity(1, "ask.sentences_removed", "Checked an answer in Ask", "chat", "msg_1"))).toBe("/ask");
    expect(activityHref(activity(1, "review", "Weekly review"))).toBeNull();
  });

  it("folds a run of the same entry into one row with a count", () => {
    const rows = groupActivity([
      activity(5, "ask.sentences_removed", "Checked", "chat", "m5"),
      activity(4, "ask.sentences_removed", "Checked", "chat", "m4"),
      activity(3, "ask.sentences_removed", "Checked", "chat", "m3"),
      activity(2, "document.added", "Added “x.pdf”", "document", "d1"),
      activity(1, "ask.sentences_removed", "Checked", "chat", "m1"),
    ]);
    expect(rows.map((r) => [r.entry.id, r.count])).toEqual([
      [5, 3],
      [2, 1],
      [1, 1],
    ]);
  });
});

describe("How dates are computed", () => {
  it("lists the rules under topics with a jump row and a link per rule that names it", async () => {
    useMockApi();
    const user = userEvent.setup();
    renderWithProviders(<SettingsPage />, { route: "/settings?section=rules" });
    const jump = await screen.findByRole("navigation", { name: "Rule topics" });
    const topics = [...new Set(RULES.map((r) => r.topic ?? OTHER_RULES_TOPIC))];
    expect(within(jump).getAllByRole("button")).toHaveLength(topics.length);
    for (const t of topics) expect(screen.getByRole("heading", { level: 3, name: t })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 4, name: "Tax objection: one month" })).toBeInTheDocument();

    const links = screen.getAllByRole("link", { name: /^Read the law on “/ });
    expect(links).toHaveLength(RULES.filter((r) => r.url).length);
    expect(new Set(links.map((l) => l.textContent)).size).toBe(links.length);
    expect(links[0]).toHaveTextContent("(opens in a new tab)");

    const priceIncreases = RULES.filter((r) => r.topic === "Price increases").length;
    await user.click(within(jump).getByRole("button", { name: `Price increases, ${priceIncreases} ${priceIncreases === 1 ? "rule" : "rules"}` }));
    expect(screen.getByRole("heading", { level: 3, name: "Price increases" })).toHaveFocus();
  });

  it("shows each source of a long citation as its own chip that may wrap", async () => {
    useMockApi();
    const client = makeTestQueryClient();
    const rule: RuleInfo = {
      id: "holidays_place",
      title: "Which public holidays count",
      citation: "§ 193 BGB; §§ 269, 270 Abs. 4 BGB; BAG 8 AZN 808/11; BGH VI ZA 27/11",
      summary: "Holidays count at the place where the declaration must be received.",
      url: "https://www.gesetze-im-internet.de/bgb/__193.html",
      effective_from: null,
      topic: "Counting periods",
    };
    client.setQueryData(qk.rules, [rule]);
    renderWithProviders(<SettingsPage />, { route: "/settings?section=rules", client });
    const title = await screen.findByRole("heading", { level: 4, name: rule.title });
    const item = title.closest("li")!;
    for (const source of splitCitation(rule.citation)) {
      const chip = within(item).getByText(source);
      expect(chip.className).not.toMatch(/whitespace-nowrap|truncate/);
      expect(chip).toHaveClass("wrap-anywhere");
    }
    // one topic: no jump row
    expect(screen.queryByRole("navigation", { name: "Rule topics" })).not.toBeInTheDocument();
  });

  it("search: says how many match, clears with the × or Escape, and has a way out when nothing matches", async () => {
    useMockApi();
    const user = userEvent.setup();
    renderWithProviders(<SettingsPage />, { route: "/settings?section=rules" });
    const input = await screen.findByRole("searchbox", { name: "Find a rule" });
    await screen.findByRole("navigation", { name: "Rule topics" });
    const status = screen.getAllByRole("status").find((s) => s.classList.contains("sr-only"))!;
    expect(status).toHaveTextContent("");

    await user.type(input, "TKG");
    const hits = RULES.filter((r) => matchesRule(r, "TKG")).length;
    expect(status).toHaveTextContent(`${hits} of ${RULES.length} rules match “TKG”`);
    expect(screen.getByText(`${hits} of ${RULES.length} rules`)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Clear search" }));
    expect(input).toHaveValue("");
    expect(input).toHaveFocus();

    await user.type(input, "zzz");
    expect(screen.getByRole("heading", { name: "No rule matches “zzz”" })).toBeInTheDocument();
    expect(status).toHaveTextContent("No rule matches “zzz”");
    const clearButtons = screen.getAllByRole("button", { name: "Clear search" });
    expect(clearButtons).toHaveLength(2);
    await user.click(clearButtons[1]!);
    expect(input).toHaveValue("");
    expect(await screen.findByRole("heading", { level: 4, name: "Tax objection: one month" })).toBeInTheDocument();

    await user.type(input, "tax{Escape}");
    expect(input).toHaveValue("");
  });
});

describe("Privacy & AI usage", () => {
  const withUsage = (usage: UsageStats) => {
    const client = makeTestQueryClient();
    client.setQueryData(qk.usage, usage);
    return client;
  };

  it("keeps the screen-reader table from widening the page (it sits in an sr-only box)", async () => {
    useMockApi();
    renderWithProviders(<SettingsPage />, { route: "/settings?section=privacy" });
    const table = await screen.findByRole("table", { name: "API-equivalent cost by purpose" });
    expect(table).not.toHaveClass("sr-only");
    expect(table.parentElement).toHaveClass("sr-only");
    // the statement reads as text, not as a quotation
    expect(screen.getByText(/Ordnung has no server/).tagName).toBe("P");
    expect(within(screen.getByRole("region", { name: "AI usage" })).getByText(`${USAGE.cache_hits} of ${USAGE.calls} calls`)).toBeInTheDocument();
  });

  it("names the first two letters of a call, the rest behind “+N more”", async () => {
    useMockApi();
    const call: LLMCallRecord = { ...USAGE.recent[0]!, id: 99, purpose: "review", doc_ids: ["doc_library", "doc_dentist", "doc_parking", "doc_uni", "doc_abh"] };
    const user = userEvent.setup();
    renderWithProviders(<SettingsPage />, { route: "/settings?section=privacy", client: withUsage({ ...USAGE, recent: [call] }) });
    const calls = await screen.findByRole("region", { name: "What was sent, call by call" });
    const table = within(calls).getByRole("table");
    expect(within(table).getAllByRole("link")).toHaveLength(2);
    const more = within(table).getByRole("button", { name: "+3 more letters" });
    expect(more).toHaveAttribute("aria-expanded", "false");
    await user.click(more);
    expect(within(table).getAllByRole("link")).toHaveLength(5);
    expect(within(table).getByRole("button", { name: "Show fewer" })).toHaveAttribute("aria-expanded", "true");
    // the phone list of the same call starts collapsed on its own
    expect(within(within(calls).getAllByRole("list")[0]!).getByRole("button", { name: "+3 more letters" })).toBeInTheDocument();
  });

  it("with no calls yet: one empty state, and no empty call-by-call card", async () => {
    useMockApi();
    const none: UsageStats = { ...USAGE, calls: 0, cache_hits: 0, input_tokens: 0, output_tokens: 0, cost_usd: 0, by_purpose: {}, recent: [] };
    renderWithProviders(<SettingsPage />, { route: "/settings?section=privacy", client: withUsage(none) });
    expect(await screen.findByRole("heading", { name: "No calls to Claude yet" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "What was sent, call by call" })).not.toBeInTheDocument();
    expect(screen.queryByText("No calls yet.")).not.toBeInTheDocument();
  });

  it("activity: a run of the same entry is one row, Ask's checks link to Ask, older entries on request", async () => {
    const { srv } = useMockApi();
    const checked = (id: number) =>
      activity(id, "ask.sentences_removed", "Checked an answer in Ask: took out sentences with dates, amounts or laws not in your records", "chat", `msg_${id}`);
    const before = srv.db.state.activity.length;
    srv.db.state.activity = [...Array.from({ length: 10 }, (_, i) => checked(300 - i)), ...srv.db.state.activity];
    const user = userEvent.setup();
    renderWithProviders(<SettingsPage />, { route: "/settings?section=privacy" });
    const log = await screen.findByRole("region", { name: "Activity" });
    const row = await within(log).findByRole("link", { name: /^Checked an answer in Ask.*\(10 times\)/ });
    expect(row).toHaveAttribute("href", "/ask");

    const rows = before + 1;
    expect(within(log).getAllByRole("listitem")).toHaveLength(Math.min(rows, 10));
    const older = within(log).getByRole("button", { name: `Show ${rows - 10} older ${rows - 10 === 1 ? "entry" : "entries"}` });
    await user.click(older);
    await waitFor(() => expect(within(log).getAllByRole("listitem")).toHaveLength(rows));
    expect(within(log).getByRole("button", { name: "Show fewer" })).toHaveAttribute("aria-expanded", "true");
  });

  it("an empty activity log says so the way the other empty cards do", async () => {
    const { srv } = useMockApi();
    srv.db.state.activity = [];
    renderWithProviders(<SettingsPage />, { route: "/settings?section=privacy" });
    const log = await screen.findByRole("region", { name: "Activity" });
    expect(await within(log).findByRole("heading", { level: 4, name: "Nothing yet" })).toBeInTheDocument();
  });
});
