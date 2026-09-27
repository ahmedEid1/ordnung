import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/render";
import { useMockApi } from "@/test/mockFetch";
import { assertNoRawEnumsInElement } from "@/lib/copy";
import { formatFileSize } from "@/lib/format";
import { __clearToasts } from "@/components/ui/Toast";
import SettingsPage from "@/pages/SettingsPage";
import { cacheRate, completeReminderDays, leadLabel, modelFamily, normalizeLeadDays, parseSection, purposeRows, sentSummary } from "./logic";

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

describe("settings logic", () => {
  it("sections default to the profile", () => {
    expect(parseSection("privacy")).toBe("privacy");
    expect(parseSection("nope")).toBe("profile");
    expect(parseSection(null)).toBe("profile");
  });

  it("reminder lead days: unique, whole, 0–365, largest first, in words", () => {
    expect(normalizeLeadDays([1, 14, 7, 7, 3.4, -2, 400, 0])).toEqual([14, 7, 3, 1, 0]);
    expect([0, 1, 3, 7, 14, 21, 30].map(leadLabel)).toEqual([
      "On the day",
      "1 day before",
      "3 days before",
      "1 week before",
      "2 weeks before",
      "3 weeks before",
      "30 days before",
    ]);
    expect(completeReminderDays({ deadline: [1, 14] })).toMatchObject({ deadline: [14, 1], payment: [], milestone: [] });
  });

  it("usage by purpose, most expensive first, with human labels", () => {
    const rows = purposeRows({
      calls: 3,
      cache_hits: 1,
      input_tokens: 0,
      output_tokens: 0,
      cost_usd: 0,
      recent: [],
      by_purpose: {
        brief: { calls: 1, cache_hits: 0, errors: 0, input_tokens: 10, output_tokens: 5, cost_usd: 0.01 },
        extract: { calls: 2, cache_hits: 1, errors: 0, input_tokens: 100, output_tokens: 50, cost_usd: 0.5 },
        mystery_job: { calls: 1, cache_hits: 0, errors: 0, input_tokens: 1, output_tokens: 1, cost_usd: 0 },
      },
    });
    expect(rows.map((r) => r.label)).toEqual(["Understanding letters", "Daily note", "Mystery job"]);
    expect(rows[0]).toMatchObject({ calls: 2, tokens: 150, cost: 0.5 });
    expect(cacheRate({ calls: 4, cache_hits: 1 })).toBe(0.25);
    expect(cacheRate({ calls: 0, cache_hits: 0 })).toBeNull();
    expect(modelFamily("claude-sonnet-4-6")).toBe("Sonnet");
    expect(modelFamily("claude-haiku-4-5")).toBe("Haiku");
  });

  it("says what a call sent without ever showing content", () => {
    const base = { doc_ids: [], pages_sent: 0, bytes_sent: 0, purpose: "extract", cache_hit: false };
    expect(sentSummary({ ...base, doc_ids: ["doc_a"], pages_sent: 2, bytes_sent: 2400 }, formatFileSize)).toBe("2 pages of 1 letter · 2.3 KB");
    expect(sentSummary({ ...base, cache_hit: true }, formatFileSize)).toMatch(/Nothing/);
    expect(sentSummary({ ...base, purpose: "ask" }, formatFileSize)).toBe("Your question and what Claude looked up");
    expect(sentSummary({ ...base, purpose: "brief" }, formatFileSize)).toMatch(/no letters/);
  });
});

describe("Settings page", () => {
  it("edits the profile and saves it", async () => {
    const { calls } = useMockApi();
    const user = userEvent.setup();
    renderWithProviders(<SettingsPage />, { route: "/settings" });
    const name = await screen.findByLabelText("Full name");
    expect(name).toHaveValue("Sam Rivera");
    await user.clear(name);
    await user.type(name, "Sam R. Rivera");
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT" && c.path === "/profile")).toBe(true));
    expect(calls.find((c) => c.method === "PUT")?.body).toMatchObject({ name: "Sam R. Rivera" });
    // confirmed in the save bar (no toast over it)
    expect(await screen.findByText("New letters use this name and address.")).toBeInTheDocument();
    expect(screen.getByText("Saved.")).toBeInTheDocument();
  });

  it("changes reminder lead days", async () => {
    const { calls } = useMockApi();
    const user = userEvent.setup();
    renderWithProviders(<SettingsPage />, { route: "/settings?section=reminders" });
    const deadlines = await screen.findByRole("list", { name: "Reminders for deadlines" });
    expect(within(deadlines).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["2 weeks before", "1 week before", "3 days before", "1 day before"]);
    await user.click(within(deadlines).getByRole("button", { name: "Remove reminder 1 day before for deadlines" }));
    await user.click(screen.getByRole("button", { name: "Add a reminder for deadlines" }));
    await user.type(screen.getByLabelText("Days before, for deadlines"), "30{Enter}");
    expect(within(deadlines).getAllByRole("listitem")[0]).toHaveTextContent("30 days before");
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    expect((calls.find((c) => c.method === "PUT")?.body as { reminder_days: Record<string, number[]> }).reminder_days.deadline).toEqual([30, 14, 7, 3]);
  });

  it("privacy & AI usage: the statement, what was sent per call, and the activity log", async () => {
    useMockApi();
    const user = userEvent.setup();
    const { container } = renderWithProviders(<SettingsPage />, { route: "/settings?section=privacy" });
    expect(await screen.findByRole("heading", { level: 2, name: "Privacy & AI usage" })).toBeInTheDocument();
    expect(screen.getByText(/Ordnung has no server, no telemetry and never sees your credentials/)).toBeInTheDocument();
    expect(await screen.findByText("$2.91")).toBeInTheDocument();
    const calls = screen.getByRole("region", { name: "What was sent, call by call" });
    // wide panes: a table (narrow ones get the same calls as a stacked list — both are in the DOM)
    const table = within(calls).getByRole("table");
    expect(within(table).getAllByText("Understanding letters").length).toBeGreaterThan(3);
    expect(within(table).getByText("1 page of 1 letter · 2.1 KB")).toBeInTheDocument();
    // the first 8 of the latest calls, the rest on request
    expect(within(table).getAllByRole("row")).toHaveLength(1 + 8);
    await user.click(within(calls).getByRole("button", { name: "Show all 10 calls" }));
    expect(within(table).getAllByRole("row")).toHaveLength(1 + 10);
    expect(within(table).getByText("Cache")).toBeInTheDocument();
    expect(within(calls).getAllByRole("list")[0]).toHaveTextContent("1 page of 1 letter · 2.1 KB");
    // screen-reader table behind the chart
    const costs = screen.getByRole("table", { name: "API-equivalent cost by purpose" });
    // a table grows to fit its cells whatever its width, so sr-only on the table itself widened phone pages
    expect(costs).not.toHaveClass("sr-only");
    expect(costs.parentElement).toHaveClass("sr-only");
    expect(await screen.findByText("Weekly review: 2 new Ideas")).toBeInTheDocument();
    assertNoRawEnumsInElement(container);
  });

  it("how dates are computed: the rules with citations, links and the disclaimer", async () => {
    useMockApi();
    const user = userEvent.setup();
    renderWithProviders(<SettingsPage />, { route: "/settings?section=rules" });
    expect(await screen.findByText("Tax letters count as delivered 4 days after posting")).toBeInTheDocument();
    expect(screen.getByText("§ 122 Abs. 2 Nr. 1 AO")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: /Read the law/ }).length).toBeGreaterThan(5);
    await user.type(screen.getByLabelText("Find a rule"), "TKG");
    expect(screen.getByText("Phone & internet contracts")).toBeInTheDocument();
    expect(screen.queryByText("Tax objection: one month")).toBeNull();
    expect(screen.getByText(/Not legal advice/)).toBeInTheDocument();
  });

  it("Claude connection: status, version and the probe", async () => {
    const { calls } = useMockApi();
    const user = userEvent.setup();
    renderWithProviders(<SettingsPage />, { route: "/settings?section=claude" });
    expect(await screen.findByText("Claude is ready")).toBeInTheDocument();
    expect(screen.getByText("Yes — working")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Run check" }));
    await waitFor(() => expect(calls.some((c) => c.path === "/health" && c.method === "GET")).toBe(true));
    // the probe's answer replaces the cached status
    // the row is called "Claude Code": its value is the bare version
    expect(await screen.findByText("2.1.4")).toBeInTheDocument();
    expect(screen.queryByText(/\(Claude Code\)/)).not.toBeInTheDocument();
  });

  it("promises only what is true about the address and IBAN: they stay out of Ordnung's requests, letters are read as printed", async () => {
    useMockApi();
    renderWithProviders(<SettingsPage />, { route: "/settings" });
    expect(await screen.findByText(/never puts the address and IBAN you enter here into its requests to Claude/)).toBeInTheDocument();
    expect(screen.getByText(/letters you add are read as they are printed/)).toBeInTheDocument();
    expect(screen.queryByText(/Your address and IBAN are never sent to Claude/)).toBeNull();
  });

  it("switches sections from the sub-navigation", async () => {
    useMockApi();
    const user = userEvent.setup();
    const { router } = renderWithProviders(<SettingsPage />, { route: "/settings" });
    const nav = await screen.findByRole("navigation", { name: "Settings sections" });
    expect(within(nav).getByRole("link", { name: "Profile & address" })).toHaveAttribute("aria-current", "page");
    await user.click(within(nav).getByRole("link", { name: "Data" }));
    expect(router.state.location.search).toBe("?section=data");
    expect(await screen.findByRole("heading", { level: 2, name: "Data" })).toBeInTheDocument();
    expect(screen.getByText("/tmp/ordnung-test")).toBeInTheDocument();
  });
});
