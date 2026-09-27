/**
 * The weekly session: one step at a time (URL state), Back / Next with the focus on the new step's
 * heading, Pay and Confirm right in the rows, "Finish" → "All clear until …"; Today's one prompt with
 * "Not now", and the quiet link afterwards; the static demo following what the visitor does.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api } from "@/api/endpoints";
import { Toaster, __clearToasts } from "@/components/ui/Toast";
import { MOCK_WEEK } from "@/mocks/data/numbers";
import { mockWeek } from "@/mocks/numbers";
import { renderWithProviders } from "@/test/render";
import { useMockApi } from "@/test/mockFetch";
import { entryHref, sessionHighlights, stepCount } from "./steps";
import { WeekView } from "./WeekView";
import { WeeklyLink, WeeklyPrompt } from "./WeeklyPrompt";

beforeEach(() => {
  vi.stubGlobal("scrollTo", () => {});
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  act(() => __clearToasts());
});

async function renderWeek(route = "/week") {
  const user = userEvent.setup();
  const out = renderWithProviders(
    <>
      <WeekView />
      <Toaster />
    </>,
    { route },
  );
  await screen.findByText(/^Step \d of 7$/);
  return { user, ...out };
}

describe("steps", () => {
  it("say where each row leads and what is waiting", () => {
    expect(entryHref({ ref: { type: "document", id: "doc_a" }, doc_id: "doc_a" })).toBe("/documents/doc_a");
    expect(entryHref({ ref: { type: "item", id: "itm_a" }, doc_id: "doc_b" })).toBe("/documents/doc_b");
    expect(entryHref({ ref: { type: "item", id: "itm_a" }, doc_id: null })).toBe("/timeline");
    expect(entryHref({ ref: { type: "contract", id: "ctr_a" }, doc_id: null })).toBe("/contracts?contract=ctr_a");
    expect(entryHref({ ref: { type: "draft", id: "drf_a" }, doc_id: null })).toBe("/letters/drf_a");
    expect(stepCount({ entries: [], more: 3 })).toBe(3);
    expect(sessionHighlights(MOCK_WEEK)).toEqual(["5 new letters", "2 to check", "4 to pay", "1 to post", "2 decisions"]);
  });
});

describe("the session page", () => {
  it("walks through the steps one at a time", async () => {
    useMockApi();
    const { user, router } = await renderWeek();
    expect(screen.getByText("Step 1 of 7")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Back" })).toBeDisabled();
    const next = screen.getByRole("button", { name: `Next: ${MOCK_WEEK.steps[1]!.title}` });
    await user.click(next);
    const heading = await screen.findByRole("heading", { level: 2, name: "Please check" });
    expect(router.state.location.search).toBe("?step=check");
    await waitFor(() => expect(heading).toHaveFocus());
    expect(screen.getByText("Step 2 of 7")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Back" }));
    expect(await screen.findByRole("heading", { level: 2, name: MOCK_WEEK.steps[0]!.title })).toBeInTheDocument();
  });

  it("pays and confirms right in the rows", async () => {
    useMockApi();
    const { user } = await renderWeek("/week?step=pay");
    const step = screen.getByRole("heading", { level: 2, name: "Pay this week" }).closest("section")!;
    expect(within(step).getByText("To transfer this week:")).toBeInTheDocument();
    await user.click(within(step).getByRole("button", { name: "Pay: Pay TechMarkt reminder" }));
    expect(await screen.findByRole("dialog", { name: /Pay/ })).toBeInTheDocument();
  });

  it("confirms a value read from a photo", async () => {
    const { calls } = useMockApi();
    const { user } = await renderWeek("/week?step=check");
    const confirm = screen.getByRole("button", { name: "Confirm: Passport expires" });
    await user.click(confirm);
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && /\/items\/.+\/confirm$/.test(c.path))).toBe(true));
    expect(await screen.findByText("Confirmed")).toBeInTheDocument();
  });

  it("finishes with “All clear until …” and remembers the session", async () => {
    const { calls } = useMockApi();
    const { user } = await renderWeek("/week?step=file");
    expect(screen.getByText("Nothing here this week — on to the next step.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^Finish/ }));
    expect(await screen.findByRole("heading", { name: /^All clear until Tue 29 Sep$/ })).toBeInTheDocument();
    expect(calls.some((c) => c.method === "POST" && c.path === "/week/done")).toBe(true);
    expect(screen.getByRole("link", { name: "Back to Today" })).toHaveAttribute("href", "/");
    expect(screen.getByRole("heading", { name: /^All clear until/ })).toHaveFocus();
    expect(screen.getByText("Session saved — Today suggests the next one in a week.")).toBeInTheDocument();
  });

  it("shows how many more a long step has, and where to see them", async () => {
    useMockApi();
    const many = { ...MOCK_WEEK, steps: MOCK_WEEK.steps.map((s) => (s.id === "new" ? { ...s, more: 4 } : s)) };
    vi.spyOn(api, "week").mockResolvedValue(many);
    await renderWeek();
    expect(screen.getByText(/And 4 more\./)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "See all in the Inbox" })).toHaveAttribute("href", "/inbox");
  });
});

describe("Today's prompt", () => {
  it("suggests the session once, and “Not now” leaves a quiet link", async () => {
    const { calls } = useMockApi();
    const user = userEvent.setup();
    renderWithProviders(
      <>
        <WeeklyPrompt />
        <WeeklyLink />
        <Toaster />
      </>,
    );
    const prompt = await screen.findByRole("region", { name: "Time for your weekly review" });
    expect(within(prompt).getByText(/About 10 minutes: 5 new letters · 2 to check · 4 to pay/)).toBeInTheDocument();
    expect(within(prompt).getByRole("link", { name: "Start" })).toHaveAttribute("href", "/week");
    expect(screen.queryByRole("link", { name: /Weekly review/ })).toBeNull();

    await user.click(within(prompt).getByRole("button", { name: "Not now" }));
    await waitFor(() => expect(screen.queryByRole("region", { name: "Time for your weekly review" })).toBeNull());
    expect(calls.some((c) => c.method === "POST" && c.path === "/week/dismiss")).toBe(true);
    expect(screen.getByRole("link", { name: /Weekly review/ })).toHaveAttribute("href", "/week");
  });
});

describe("the static demo's session follows the visitor", () => {
  it("a paid to-do leaves its step and the prompt goes after Finish", () => {
    const { srv } = useMockApi();
    const before = mockWeek(srv.db);
    expect(before.due).toBe(true);
    const pay = before.steps.find((s) => s.id === "pay")!;
    const first = pay.entries[0]!;
    srv.db.state.items.find((i) => i.id === first.ref.id)!.status = "done";
    const after = mockWeek(srv.db).steps.find((s) => s.id === "pay")!;
    expect(after.entries.map((e) => e.key)).not.toContain(first.key);
    expect(after.summary).toBe(`${pay.entries.length - 1} left to look at`);
    srv.handle("POST", "/week/done", new URLSearchParams(), undefined, null);
    const done = mockWeek(srv.db);
    expect(done.due).toBe(false);
    expect(done.last_session).toBe("2026-09-28");
  });
});
