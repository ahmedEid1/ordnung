import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { qk } from "@/api/hooks";
import type { Contract, Item, Lane, Party, Profile, TimelineEntry } from "@/api/types";
import { AddLettersProvider } from "@/components/shell/AddLetters";
import { assertNoRawEnumsInElement } from "@/lib/copy";
import { createMockServer, type MockServer } from "@/mocks/server";
import { makeTestQueryClient, renderWithProviders, TEST_TODAY } from "@/test/render";
import { defaultLaneRange } from "@/features/lanes/scale";
import { TimelineView } from "./TimelineView";

/** jsdom has no layout: answer `(min-width: …)` queries for a viewport `px` wide. */
function viewport(px: number) {
  vi.stubGlobal("matchMedia", (query: string) => {
    const min = Number(/min-width:\s*(\d+)px/.exec(query)?.[1] ?? 0);
    return { matches: px >= min, media: query, addEventListener() {}, removeEventListener() {} };
  });
}

beforeEach(() => {
  vi.stubGlobal("scrollTo", () => {});
  viewport(1280);
});
afterEach(() => {
  vi.unstubAllGlobals();
});

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

async function seededClient(edit?: { lanes?: Lane[]; timeline?: TimelineEntry[]; setup?: (srv: MockServer) => void }) {
  const srv = createMockServer({ staticDemo: false, latency: 0 });
  srv.openAllMail();
  edit?.setup?.(srv);
  const get = async <T,>(path: string, q = "") => (await (await srv.handle("GET", path, new URLSearchParams(q), undefined)).json()) as T;
  const { from, to } = defaultLaneRange(TEST_TODAY);
  const qc = makeTestQueryClient();
  qc.setQueryData(qk.lanes(from, to), edit?.lanes ?? (await get<Lane[]>("/lanes", `from=${from}&to=${to}`)));
  qc.setQueryData(qk.timeline(from, to), edit?.timeline ?? (await get<TimelineEntry[]>("/timeline", `from=${from}&to=${to}`)));
  qc.setQueryData(qk.items.list({}), await get<Item[]>("/items"));
  qc.setQueryData(qk.contracts.list({}), await get<Contract[]>("/contracts"));
  qc.setQueryData(qk.parties.list(), await get<Party[]>("/parties"));
  qc.setQueryData(qk.profile, await get<Profile>("/profile"));
  return qc;
}

const laneNames = (region: HTMLElement) =>
  within(within(region).getByRole("list", { name: "Lanes" }))
    .getAllByRole("listitem")
    .map((l) => l.getAttribute("aria-label"));

describe("Timeline page", () => {
  it("shows the life lanes and every date month by month, without raw enum values", async () => {
    const client = await seededClient();
    const { container } = renderWithProviders(<TimelineView />, { client, route: "/timeline" });

    expect(screen.getByRole("heading", { level: 1, name: "Timeline" })).toBeInTheDocument();
    const lanesRegion = screen.getByRole("region", { name: "Your year ahead" });
    expect(lanesRegion).toHaveAttribute("data-tour", "timeline-lanes");
    expect(laneNames(lanesRegion)).toEqual(expect.arrayContaining(["Residence permit", "Passport", "Tax", "Phone · FunkNetz", "Study", "Money"]));
    expect(within(lanesRegion).getByRole("button", { name: /^Residence permit\..*Opens the letter/ })).toBeInTheDocument();
    expect(within(lanesRegion).getByText(/Not legal advice/)).toBeInTheDocument();

    const list = screen.getByRole("region", { name: "Every date" });
    expect(within(list).getByRole("heading", { name: /September 2026/ })).toBeInTheDocument();
    expect(within(list).getByLabelText(/^Today, Monday, 28 September 2026/)).toBeInTheDocument();
    // items open the letter they came from; contracts open the contract
    expect(within(list).getByRole("link", { name: /Pay the parking fine/ })).toHaveAttribute("href", expect.stringMatching(/^\/documents\//));
    expect(within(list).getByRole("link", { name: /FunkNetz Allnet L: current term ends/ })).toHaveAttribute("href", "/contracts?contract=ctr_phone");
    // each row says what its date is, not only by the colour of its icon
    expect(within(list).getByRole("link", { name: /Pay the parking fine.*Payment due/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add your dates to your calendar" })).toBeInTheDocument();

    assertNoRawEnumsInElement(container);
  });

  it("gives a phone row's detail two lines: its day is never cut short (R2-inbox-timeline-contracts-3)", async () => {
    const client = await seededClient();
    const timeline = client.getQueryData<TimelineEntry[]>(qk.timeline(defaultLaneRange(TEST_TODAY).from, defaultLaneRange(TEST_TODAY).to))!;
    const parking = timeline.find((e) => e.ref.id === "itm_parking")!;
    parking.subtitle = "Transfer by Thu 14 Jan 2027";
    renderWithProviders(<TimelineView />, { client, route: "/timeline" });
    const row = within(screen.getByRole("region", { name: "Every date" })).getByRole("link", { name: /Pay the parking fine/ });
    const phone = within(row).getByTitle("Transfer by Thu 14 Jan 2027");
    expect(phone).toHaveClass("line-clamp-2", "break-words", "sm:hidden");
    expect(phone).not.toHaveClass("truncate");
  });

  it("filters by area from the URL (Today's area tiles link here) — lanes and list", async () => {
    const client = await seededClient();
    renderWithProviders(<TimelineView />, { client, route: "/timeline?area=residence" });
    const lanesRegion = screen.getByRole("region", { name: "Your year ahead" });
    expect(laneNames(lanesRegion)).toEqual(expect.arrayContaining(["Residence permit", "Passport"]));
    expect(laneNames(lanesRegion)).not.toContain("Study");
    expect(within(lanesRegion).getByText(/showing Residence permit only/)).toBeInTheDocument();
    const list = screen.getByRole("region", { name: "Every date" });
    expect(within(list).getByRole("combobox", { name: "Life area" })).toHaveValue("residence");
    expect(within(list).queryByText("Rent for October")).not.toBeInTheDocument();
    expect(within(list).getByText("Ausländerbehörde: extend residence permit")).toBeInTheDocument();

    fireEvent.click(within(lanesRegion).getByRole("button", { name: "Show all areas" }));
    expect(laneNames(lanesRegion).length).toBeGreaterThan(5);
  });

  it("filters the lanes by kind and person too, and says so", async () => {
    const client = await seededClient();
    renderWithProviders(<TimelineView />, { client, route: "/timeline?type=payment" });
    const lanesRegion = screen.getByRole("region", { name: "Your year ahead" });
    // contracts have no payment dates: their lanes go; the payment markers stay
    expect(laneNames(lanesRegion)).not.toContain("Phone · FunkNetz");
    expect(laneNames(lanesRegion)).toContain("Money");
    expect(within(lanesRegion).getByText(/showing Payments only/)).toBeInTheDocument();
    fireEvent.click(within(lanesRegion).getByRole("button", { name: "Show all kinds" }));
    expect(laneNames(lanesRegion)).toContain("Phone · FunkNetz");
  });

  it("says when the chosen dates aren't drawn on the lanes, instead of 'nothing for this'", async () => {
    const client = await seededClient();
    renderWithProviders(<TimelineView />, { client, route: "/timeline?area=mobility" });
    const lanesRegion = screen.getByRole("region", { name: "Your year ahead" });
    expect(within(lanesRegion).getByRole("heading", { level: 3, name: "These dates aren't on the lanes" })).toBeInTheDocument();
    expect(lanesRegion).toHaveTextContent(/All \d+ are in the list below/);
    expect(lanesRegion).not.toHaveTextContent(/Nothing for/);
    const list = screen.getByRole("region", { name: "Every date" });
    expect(within(list).getAllByRole("link").length).toBeGreaterThan(0);
  });

  it("says letters are never drawn on the lanes", async () => {
    const client = await seededClient();
    renderWithProviders(<TimelineView />, { client, route: "/timeline?type=document" });
    const lanesRegion = screen.getByRole("region", { name: "Your year ahead" });
    expect(within(lanesRegion).getByRole("heading", { level: 3, name: "Letters aren't drawn on the lanes" })).toBeInTheDocument();
    expect(lanesRegion).toHaveTextContent("They're in the list below.");
  });

  it("counts each menu's options against the other filters and greys out the ones that would show nothing", async () => {
    const client = await seededClient();
    renderWithProviders(<TimelineView />, { client, route: "/timeline?type=document" });
    const list = screen.getByRole("region", { name: "Every date" });
    const kind = within(list).getByRole("combobox", { name: "Kind" });
    // the chosen option shows just its name (the closed menu never cuts a count off)
    expect(within(kind).getByRole("option", { selected: true })).toHaveTextContent(/^Letters received$/);
    const people = within(list).getByRole("combobox", { name: "People & organisations" });
    const options = within(people).getAllByRole("option").slice(1) as HTMLOptionElement[];
    // people with no letters are greyed out; the rest count letters only
    expect(options.some((o) => o.disabled && / \(0\)$/.test(o.textContent ?? ""))).toBe(true);
    expect(options.filter((o) => !o.disabled).every((o) => / \([1-9]\d*\)$/.test(o.textContent ?? ""))).toBe(true);
  });

  it("builds the empty hint from the filters that are set", async () => {
    const client = await seededClient();
    renderWithProviders(<TimelineView />, { client, route: "/timeline?type=appointment&area=tax" });
    const list = screen.getByRole("region", { name: "Every date" });
    expect(within(list).getByRole("heading", { level: 3, name: "No dates match these filters" })).toBeInTheDocument();
    // "Show past" is on: no "or show past dates"
    expect(list).toHaveTextContent("Try another kind or area.");
    expect(list).not.toHaveTextContent(/show past dates/);
    // the lanes don't claim the dates are below
    expect(screen.getByRole("region", { name: "Your year ahead" })).toHaveTextContent("Nothing on the lanes for these filters");
  });

  it("hides past dates with the switch", async () => {
    const client = await seededClient();
    renderWithProviders(<TimelineView />, { client, route: "/timeline" });
    const list = screen.getByRole("region", { name: "Every date" });
    const before = within(list).getAllByRole("listitem").length;
    expect(within(list).getByRole("heading", { name: /August 2026/ })).toBeInTheDocument();
    fireEvent.click(within(list).getByRole("switch", { name: "Show past" }));
    const after = within(list).getAllByRole("listitem").length;
    expect(after).toBeLessThan(before);
    expect(within(list).queryByRole("heading", { name: /August 2026/ })).not.toBeInTheDocument();
  });

  it("jumps from a lane marker without a page of its own to its entry in the list", async () => {
    const client = await seededClient();
    const { container } = renderWithProviders(<TimelineView />, { client, route: "/timeline" });
    const lanesRegion = screen.getByRole("region", { name: "Your year ahead" });
    fireEvent.click(within(lanesRegion).getByRole("button", { name: /^Rent · Mon 5 Oct.*Shows it in the list below/ }));
    const row = container.querySelector("[data-date='2026-10-05'] > *");
    expect(row?.className).toMatch(/bg-marker/);
  });
});

describe("your own dates and repeating ones (audit item 26)", () => {
  const ownDate = (srv: MockServer) => {
    srv.db.addItem("itm_own_vat", { kind: "reminder", title: "UStVA", due_date: "2026-10-14", recurrence: { interval: 1, unit: "months", working_day: 3 } });
  };

  it("opens a date of your own without a letter from its row — a real button — and gives focus back to it", async () => {
    const client = await seededClient({ setup: ownDate });
    const user = userEvent.setup();
    renderWithProviders(<TimelineView />, { client, route: "/timeline" });
    const list = screen.getByRole("region", { name: "Every date" });
    const row = within(list).getByRole("button", { name: /UStVA/ });
    expect(row.tagName).toBe("BUTTON");
    expect(row).toHaveAttribute("type", "button");
    expect(row).toHaveAttribute("aria-haspopup", "dialog");
    // placed by its rule: the 3rd working day of October
    expect(row.closest("li")).toHaveAttribute("data-date", "2026-10-05");
    await user.click(row);
    const dialog = await screen.findByRole("dialog", { name: "Edit your date" });
    expect(dialog).toHaveAccessibleDescription("A date you added yourself.");
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(row).toHaveFocus());
  });

  it("says how each repeating date repeats; a date read from a letter still links to its page", async () => {
    const client = await seededClient({ setup: ownDate });
    renderWithProviders(<TimelineView />, { client, route: "/timeline" });
    const list = screen.getByRole("region", { name: "Every date" });
    expect(within(list).getByRole("button", { name: /UStVA/ })).toHaveTextContent("Repeats every month on the 3rd working day");
    const instalment = within(list).getAllByRole("link", { name: /Electricity instalment/ })[0]!;
    expect(instalment).toHaveTextContent("Repeats every month");
    // a to-do read from a letter is never edited here: no button for one without a page either
    const rent = within(list).getAllByText("Rent for October")[0]!.closest("li")!;
    expect(within(rent).queryByRole("button")).toBeNull();
    expect(rent).toHaveTextContent("Repeats every month");
  });

  it("puts how a date repeats on a line of its own that is never cut short (a phone has no hover for the rest)", async () => {
    const client = await seededClient({ setup: ownDate });
    renderWithProviders(<TimelineView />, { client, route: "/timeline" });
    const list = screen.getByRole("region", { name: "Every date" });
    const row = within(list).getByRole("button", { name: /UStVA/ });
    const line = within(row).getByText("Repeats every month on the 3rd working day");
    for (let el: HTMLElement | null = line; el && el !== row; el = el.parentElement) {
      expect(el.className).not.toMatch(/truncate|line-clamp/);
    }
  });
});

describe("phones", () => {
  beforeEach(() => viewport(390));

  it("starts the list at Today: earlier dates fold behind one button, the list is part of the page", async () => {
    const client = await seededClient();
    const { container } = renderWithProviders(<TimelineView />, { client, route: "/timeline" });
    const list = screen.getByRole("region", { name: "Every date" });
    expect(within(list).queryByRole("heading", { name: /August 2026/ })).not.toBeInTheDocument();
    const today = within(list).getByLabelText(/^Today, Monday, 28 September 2026/);
    expect(container.querySelector("[data-entry-id]")?.compareDocumentPosition(today)).toBe(Node.DOCUMENT_POSITION_PRECEDING);
    // no scroll box inside the scrolling page
    expect(container.querySelector(".overflow-y-auto")).toBeNull();
    // month headers stick under the top bar
    expect(within(list).getByRole("heading", { name: /October 2026/ }).className).toMatch(/\btop-14\b/);

    fireEvent.click(within(list).getByRole("button", { name: /^Show \d+ earlier dates$/ }));
    expect(within(list).getByRole("heading", { name: /August 2026/ })).toBeInTheDocument();
    expect(within(list).queryByRole("button", { name: /earlier dates/ })).toBeNull();
  });

  it("unfolds the earlier dates when a lane marker points to one of them", async () => {
    const client = await seededClient();
    const { from, to } = defaultLaneRange(TEST_TODAY);
    // "Rent for September" (3 Sep): before today, so folded away on a phone
    const earlier = (client.getQueryData<TimelineEntry[]>(qk.timeline(from, to)) ?? []).find((e) => e.date < TEST_TODAY && e.type === "payment")!;
    const lanes = client.getQueryData<Lane[]>(qk.lanes(from, to))!;
    client.setQueryData(
      qk.lanes(from, to),
      lanes.map((l) => (l.label === "Money" ? { ...l, markers: [{ date: earlier.date, label: earlier.title, kind: "other" as const }, ...l.markers] } : l)),
    );
    const { container } = renderWithProviders(<TimelineView />, { client, route: "/timeline" });
    expect(container.querySelector(`[data-entry-id="${earlier.id}"]`)).toBeNull();
    const lanesRegion = screen.getByRole("region", { name: "Your year ahead" });
    fireEvent.click(within(lanesRegion).getByRole("button", { name: new RegExp(`^${earlier.title.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}.*Shows it in the list below`) }));
    await waitFor(() => expect(container.querySelector(`[data-entry-id="${earlier.id}"] > *`)?.className).toMatch(/bg-marker/));
  });

  it("keeps a month header to one line: no '0 dates', and 'Nothing this month' for a month without dates", async () => {
    const client = await seededClient();
    renderWithProviders(<TimelineView />, { client, route: "/timeline?type=expiry" });
    const list = screen.getByRole("region", { name: "Every date" });
    const september = within(list).getByRole("heading", { name: /^September 2026/ });
    expect(september).toHaveTextContent(/^September 2026$/);
    expect(within(list).getByLabelText(/^Today, Monday, 28 September 2026 — nothing this month$/)).toHaveTextContent("Nothing this month");
    const november = within(list).getByRole("heading", { name: /^November 2026/ });
    expect(november).toHaveTextContent("1 date");
    // a fixed 44 px header whose counts shrink and truncate instead of wrapping below it
    expect(november.className).toMatch(/\bh-11\b/);
    expect(november.querySelector(".truncate")?.className).toMatch(/\bmin-w-0\b/);
    expect(november.querySelector(".display")?.className).toMatch(/\bwhitespace-nowrap\b/);
  });

  it("says 'Nothing else this month' when this month's dates all lie before today", async () => {
    const client = await seededClient();
    renderWithProviders(<TimelineView />, { client, route: "/timeline?type=draft" });
    const list = screen.getByRole("region", { name: "Every date" });
    expect(within(list).getByLabelText(/— nothing else this month$/)).toBeInTheDocument();
  });
});

describe("states", () => {
  it("on a load error shows only the error — no empty lanes, filters or export — and keeps it while retrying", async () => {
    let timelineCalls = 0;
    vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/timeline")) {
        timelineCalls += 1;
        if (timelineCalls > 1) return new Promise<Response>(() => {});
      }
      return json({ detail: "Internal error" }, 500);
    });
    const user = userEvent.setup();
    renderWithProviders(<TimelineView />, { route: "/timeline" });
    const alert = await screen.findByRole("alert");
    expect(within(alert).getByRole("heading", { level: 2, name: "Couldn't load your timeline" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Your year ahead" })).toBeNull();
    expect(screen.queryByRole("region", { name: "Every date" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Add your dates to your calendar" })).toBeNull();
    expect(screen.queryByText(/0 lanes|still empty|No dates yet/)).toBeNull();

    await user.click(within(alert).getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(within(alert).getByRole("button", { name: "Try again" })).toHaveAttribute("aria-busy", "true"));
    expect(screen.getByRole("alert")).toBe(alert);
  });

  it("while loading shows no counts and no export", () => {
    vi.stubGlobal("fetch", () => new Promise<Response>(() => {}));
    renderWithProviders(<TimelineView />, { route: "/timeline" });
    const lanesRegion = screen.getByRole("region", { name: "Your year ahead" });
    expect(lanesRegion).toHaveTextContent("June 2026 – September 2027");
    expect(lanesRegion).not.toHaveTextContent(/\d+ lanes?/);
    expect(screen.queryByRole("button", { name: "Add your dates to your calendar" })).toBeNull();
  });

  it("on a fresh install shows one empty state that asks for letters — no filters, counts or export", async () => {
    const client = await seededClient({ lanes: [], timeline: [] });
    renderWithProviders(
      <AddLettersProvider>
        <TimelineView />
      </AddLettersProvider>,
      { client, route: "/timeline" },
    );
    expect(screen.getByRole("heading", { level: 2, name: "Your year is still empty" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add letters" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Your year ahead" })).toBeNull();
    expect(screen.queryByRole("region", { name: "Every date" })).toBeNull();
    expect(screen.queryByRole("combobox")).toBeNull();
    expect(screen.queryByRole("button", { name: "Add your dates to your calendar" })).toBeNull();
    expect(screen.getAllByRole("heading", { level: 2 })).toHaveLength(1);
  });
});

describe("calendar export", () => {
  it("downloads on the first open only, then offers 'Download again'", async () => {
    const client = await seededClient();
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    renderWithProviders(<TimelineView />, { client, route: "/timeline" });
    fireEvent.click(screen.getByRole("button", { name: "Add your dates to your calendar" }));
    expect(click).toHaveBeenCalledTimes(1);
    let dialog = await screen.findByRole("dialog", { name: "Add your dates to your calendar" });
    expect(dialog).toHaveTextContent("is downloading");
    fireEvent.click(within(dialog).getByRole("button", { name: "Done" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());

    fireEvent.click(screen.getByRole("button", { name: "Add your dates to your calendar" }));
    dialog = await screen.findByRole("dialog", { name: "Add your dates to your calendar" });
    expect(click).toHaveBeenCalledTimes(1);
    expect(dialog).toHaveTextContent("is in your Downloads");
    fireEvent.click(within(dialog).getByRole("button", { name: "Download again" }));
    expect(click).toHaveBeenCalledTimes(2);
    click.mockRestore();
  });

  it("links the site and Settings, and numbers each way of importing on its own", async () => {
    const client = await seededClient();
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    renderWithProviders(<TimelineView />, { client, route: "/timeline" });
    fireEvent.click(screen.getByRole("button", { name: "Add your dates to your calendar" }));
    const dialog = await screen.findByRole("dialog", { name: "Add your dates to your calendar" });
    const google = within(dialog).getByRole("link", { name: /calendar\.google\.com/ });
    expect(google).toHaveAttribute("href", expect.stringMatching(/^https:\/\/calendar\.google\.com\//));
    expect(google).toHaveAttribute("target", "_blank");
    expect(within(dialog).getByRole("link", { name: "change them in Settings" })).toHaveAttribute("href", "/settings?section=reminders");
    expect(within(dialog).getByText(/Reminders: 14, 7, 3 and 1 days/)).toBeInTheDocument();

    fireEvent.click(within(dialog).getByRole("radio", { name: "Apple" }));
    expect(within(dialog).getByRole("heading", { name: "On a Mac" })).toBeInTheDocument();
    expect(within(dialog).getByRole("heading", { name: "On an iPhone or iPad" })).toBeInTheDocument();
    // two lists: 1–2 for the Mac, 1 for the iPhone
    expect(within(dialog).getAllByRole("list").filter((l) => l.tagName === "OL").map((l) => within(l).getAllByRole("listitem").length)).toEqual([2, 1]);
    fireEvent.click(within(dialog).getByRole("radio", { name: "Outlook" }));
    expect(within(dialog).getByText(/Upload from file/)).toBeInTheDocument();
    click.mockRestore();
  });

  it("isn't offered when there is no open date to add", async () => {
    const client = await seededClient();
    const { from, to } = defaultLaneRange(TEST_TODAY);
    const letters = (client.getQueryData<TimelineEntry[]>(qk.timeline(from, to)) ?? []).filter((e) => e.type === "document");
    client.setQueryData(qk.timeline(from, to), letters);
    renderWithProviders(<TimelineView />, { client, route: "/timeline" });
    expect(screen.getByRole("region", { name: "Every date" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add your dates to your calendar" })).toBeNull();
  });
});
