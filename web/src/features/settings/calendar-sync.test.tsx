import { afterEach, beforeEach, describe, expect, it, onTestFinished, vi } from "vitest";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Toaster, __clearToasts } from "@/components/ui/Toast";
import SettingsPage from "@/pages/SettingsPage";
import { renderWithProviders } from "@/test/render";
import { useMockApi } from "@/test/mockFetch";
import { createMockServer } from "@/mocks/server";
import { mockCalendarPreview } from "@/mocks/data/calendarSync";
import type { CalendarSyncStatus } from "@/api/types";
import { eventWhen, fieldFor, foundLine, hostOf, isPastEvent, lastSyncLine, preferredCalendar, previewOrder, syncFormProblem } from "./calendarSync";

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

const NEXTCLOUD = "https://cloud.example.org";
const CALENDAR = "https://cloud.example.org/remote.php/dav/calendars/sam/ordnung/";

// ------------------------------------------------------------------------------------------------
// pure helpers
// ------------------------------------------------------------------------------------------------

describe("calendar sync helpers", () => {
  it("checks the form before asking the server", () => {
    const ok = { url: NEXTCLOUD, username: "sam", password: "app-pass" };
    expect(syncFormProblem(ok)).toBeNull();
    expect(syncFormProblem({ ...ok, url: "cloud.example.org" })?.field).toBe("url");
    expect(syncFormProblem({ ...ok, url: "http://cloud.example.org" })?.message).toMatch(/unencrypted/);
    expect(syncFormProblem({ ...ok, url: "http://127.0.0.1:5232/sam/" })).toBeNull();
    expect(syncFormProblem({ ...ok, url: "https://sam:pw@cloud.example.org" })?.message).toMatch(/own fields/);
    expect(syncFormProblem({ ...ok, username: "  " })?.field).toBe("username");
    expect(syncFormProblem({ ...ok, password: "" })?.field).toBe("password");
    expect(syncFormProblem({ ...ok, password: "" }, false)).toBeNull();
  });

  it("puts a refusal next to its field", () => {
    expect(fieldFor("address")).toBe("url");
    expect(fieldFor("not_calendar")).toBe("url");
    expect(fieldFor("auth")).toBe("password");
    expect(fieldFor("network")).toBe("form");
    expect(fieldFor(null)).toBe("form");
  });

  it("prefers a calendar named Ordnung", () => {
    expect(preferredCalendar([{ url: "a", name: "Personal" }, { url: "b", name: " ordnung " }])).toBe("b");
    expect(preferredCalendar([{ url: "a", name: "Personal" }, { url: "b", name: null }])).toBe("a");
    expect(preferredCalendar([])).toBeNull();
  });

  it("names what was found", () => {
    expect(foundLine([{ url: "a", name: "Privat" }])).toBe("Found 1 calendar: Privat.");
    expect(foundLine([{ url: "a", name: null }])).toBe("Found 1 calendar (it has no name).");
    expect(foundLine([{ url: "a", name: "Privat" }, { url: "b", name: "Ordnung" }])).toBe("Found 2 calendars — choose one.");
  });

  it("previews what is still to come first, the dates that have passed last", () => {
    const events = [{ start: "2025-10-01" }, { start: "2026-09-28" }, { start: "2026-07-01T10:00:00+02:00" }, { start: "2026-10-14T10:00:00+02:00" }];
    expect(isPastEvent(events[0]!, "2026-09-28")).toBe(true);
    expect(isPastEvent(events[1]!, "2026-09-28")).toBe(false); // today's date is still to come
    expect(previewOrder(events, "2026-09-28")).toEqual({
      events: [{ start: "2026-09-28" }, { start: "2026-10-14T10:00:00+02:00" }, { start: "2025-10-01" }, { start: "2026-07-01T10:00:00+02:00" }],
      past: 2,
    });
  });

  it("words the event times and the last sync", () => {
    expect(eventWhen({ start: "2026-09-29", all_day: true }, "2026-09-28")).toBe("Tue 29 Sep");
    expect(eventWhen({ start: "2026-10-14T10:00:00+02:00", all_day: false }, "2026-09-28")).toBe("Wed 14 Oct, 10:00");
    const now = new Date("2026-09-28T10:00:00Z");
    const base = { at: "2026-09-28T09:58:00Z", sent: 0, removed: 0, unchanged: 12, failed: 0, error: null, error_kind: null };
    expect(lastSyncLine(null)).toEqual({ tone: "neutral", text: "Not synced yet." });
    expect(lastSyncLine(base, now).text).toBe("Up to date — checked 2 min ago, nothing had changed.");
    expect(lastSyncLine({ ...base, sent: 1, removed: 2 }, now).text).toBe("Synced 2 min ago: 1 event sent, 2 removed.");
    const failed = lastSyncLine({ ...base, error: "Couldn't reach cloud.example.org.", error_kind: "network" }, now);
    expect(failed).toEqual({ tone: "warn", text: "Last sync 2 min ago: Couldn't reach cloud.example.org." });
    expect(hostOf(CALENDAR)).toBe("cloud.example.org");
    expect(hostOf("not a url")).toBe("not a url");
  });
});

describe("the demo's calendar preview", () => {
  it("is discreet by default and shows the calendar file's words with details", () => {
    const { db } = createMockServer({ staticDemo: true, latency: 0 });
    const discreet = mockCalendarPreview(db, "discreet");
    const full = mockCalendarPreview(db, "full");
    expect(discreet.length).toBeGreaterThan(3);
    expect(discreet.map((e) => e.uid)).toEqual(full.map((e) => e.uid));
    // "money in" for money coming in, "— check the date" for a date that couldn't be confirmed
    const plain = /^Ordnung: (deadline|payment|appointment|money in)( — check the date)?$/;
    expect(new Set(discreet.map((e) => e.summary))).toEqual(new Set(discreet.map((e) => e.summary).filter((s) => plain.test(s))));
    const titles = db.state.items.map((i) => i.title);
    for (const e of discreet) expect(titles.some((t) => `${e.summary} ${e.description}`.includes(t))).toBe(false);
    expect(full.some((e) => e.description.includes("With: "))).toBe(true);
  });
});

// ------------------------------------------------------------------------------------------------
// Settings → Calendar → sync
// ------------------------------------------------------------------------------------------------

async function openCard() {
  renderWithProviders(
    <>
      <SettingsPage />
      <Toaster />
    </>,
    { route: "/settings?section=calendar" },
  );
  // loaded (the preview's heading is there in every state): the card that replaced the skeleton
  await screen.findByText("What your calendar gets", {}, { timeout: 3000 });
  return screen.getByRole("region", { name: "Sync with your own calendar" });
}

describe("calendar sync card", () => {
  it("previews every event, discreet by default, before anything is sent", async () => {
    const { calls } = useMockApi();
    const user = userEvent.setup();
    const card = await openCard();
    const modes = await within(card).findByRole("radiogroup", { name: "What the calendar events show" });
    expect(within(modes).getByRole("radio", { name: "Discreet" })).toBeChecked();
    const list = await within(card).findByRole("list", { name: "Events, discreet" });
    expect(within(list).getAllByText(/^Ordnung: (deadline|payment|appointment)$/).length).toBeGreaterThan(0);
    expect(within(list).getAllByRole("listitem")).toHaveLength(4);
    await user.click(within(card).getByRole("button", { name: /Show all \d+ events/ }));
    expect(within(list).getAllByRole("listitem").length).toBeGreaterThan(4);
    await user.click(within(modes).getByRole("radio", { name: "With details" }));
    const detailed = await within(card).findByRole("list", { name: "Events, with details" });
    await waitFor(() => expect(detailed).toHaveTextContent("With: "));
    expect(calls.some((c) => c.method !== "GET")).toBe(false);
  });

  it("finds the calendars of an account, then connects the chosen one", async () => {
    const { calls } = useMockApi();
    const user = userEvent.setup();
    const card = await openCard();
    const find = await within(card).findByRole("button", { name: "Find my calendars" });

    await user.click(find);
    const address = within(card).getByLabelText("Calendar or server address");
    expect(address).toHaveAccessibleDescription("Enter the calendar's address, starting with https://.");
    expect(address).toHaveFocus();
    await user.type(address, "http://cloud.example.org");
    await user.type(within(card).getByLabelText("User name"), "sam");
    const password = within(card).getByLabelText("App password");
    expect(password).toHaveAttribute("type", "password");
    await user.type(password, "wrong");
    await user.click(find);
    expect(address).toHaveAccessibleDescription(/unencrypted/);
    expect(calls.some((c) => c.path === "/calendar/sync/discover")).toBe(false);

    await user.clear(address);
    await user.type(address, NEXTCLOUD);
    await user.click(find);
    // the server refuses the password: said next to it
    await waitFor(() => expect(password).toHaveAccessibleDescription("The calendar server refused the user name or app password."));
    await user.clear(password);
    await user.type(password, "abcd-efgh-ijkl-mnop");
    await user.click(within(card).getByRole("button", { name: "Find my calendars" }));

    const choices = await within(card).findByRole("group", { name: "Which calendar should Ordnung write into?" });
    expect(within(choices).getByRole("radio", { name: /^Ordnung/ })).toBeChecked();
    // the next step is the choice: focus moves there (and it scrolls into view), not left on <body>
    await waitFor(() => expect(within(choices).getByRole("radio", { name: /^Ordnung/ })).toHaveFocus());
    expect(within(card).getByRole("status")).toHaveTextContent("Found 2 calendars — choose one.");
    await user.click(within(card).getByRole("button", { name: "Connect and sync" }));

    // the card turns into the connected view, and a toast says so
    const connected = await waitFor(() => {
      const region = screen.getByRole("region", { name: "Sync with your own calendar" });
      within(region).getByText(/^Connected to Ordnung$/);
      return region;
    });
    expect(screen.getAllByText("Connected to Ordnung")).toHaveLength(2);
    const put = calls.find((c) => c.method === "PUT" && c.path === "/calendar/sync");
    expect(put?.body).toEqual({ url: CALENDAR, username: "sam", password: "abcd-efgh-ijkl-mnop", mode: "discreet" });
    expect(within(connected).getByText(/^Synced just now: \d+ events sent\. \d+ of \d+ events are in the calendar\.$/)).toHaveAttribute("role", "status");
    expect(within(connected).queryByLabelText("App password")).not.toBeInTheDocument();
    // the button that had focus is gone: the "Connected to …" line has it
    await waitFor(() => expect(within(connected).getByText(/^Connected to Ordnung$/).closest("p")).toHaveFocus());
  });

  it("shows the form's own error next to the button, and moves focus to it", async () => {
    const { srv } = useMockApi();
    const handle = srv.handle.bind(srv);
    srv.handle = async (method, path, query, body, signal) =>
      method === "POST" && path === "/calendar/sync/discover"
        ? new Response(JSON.stringify({ detail: "Couldn't reach caldav.icloud.com.", code: "network" }), { status: 502, headers: { "Content-Type": "application/json" } })
        : handle(method, path, query, body, signal);
    const user = userEvent.setup();
    const card = await openCard();
    await user.type(within(card).getByLabelText("Calendar or server address"), "https://caldav.icloud.com");
    await user.type(within(card).getByLabelText("User name"), "sam@icloud.com");
    await user.type(within(card).getByLabelText("App password"), "abcd-efgh-ijkl-mnop");
    const find = within(card).getByRole("button", { name: "Find my calendars" });
    await user.click(find);
    const error = await within(card).findByRole("alert", {}, { timeout: 5000 });
    expect(error).toHaveTextContent("Couldn't reach caldav.icloud.com.");
    expect(error).not.toHaveTextContent("tries again"); // nothing retries finding calendars
    // in the footer with the button (the fields and the preview are far above on a phone)
    expect(error.parentElement).toBe(find.parentElement);
    await waitFor(() => expect(error).toHaveFocus());
    // the fields stayed focusable while asking (read-only, not disabled)
    expect(within(card).getByLabelText("App password")).not.toBeDisabled();
  });

  it("lists the dates still to come first, marks the past ones, and brings the toggle back after “Show fewer”", async () => {
    const { srv } = useMockApi();
    const user = userEvent.setup();
    const scrolled = vi.fn();
    Element.prototype.scrollIntoView = scrolled; // jsdom has none
    onTestFinished(() => void delete (Element.prototype as { scrollIntoView?: unknown }).scrollIntoView);
    // two dates that have passed (one a year ago), sent first by date — as the live demo has them
    const dated = srv.db.openItems().find((i) => i.due_date && !i.due_time)!;
    srv.db.state.items.push({ ...dated, id: "past-a", due_date: "2025-10-01" }, { ...dated, id: "past-b", due_date: "2025-10-05" });
    const card = await openCard();
    const list = await within(card).findByRole("list", { name: "Events, discreet" });
    const today = srv.db.today;
    const past = srv.db.openItems().filter((i) => i.due_date && i.due_date < today).length;
    expect(past).toBeGreaterThanOrEqual(2);
    // the first four are dates still to come: their alarms will ring
    for (const item of within(list).getAllByRole("listitem")) expect(item).not.toHaveTextContent("Overdue");
    const toggle = within(card).getByRole("button", { name: new RegExp(`^Show all \\d+ events \\(${past} overdue\\)$`) });
    await user.click(toggle);
    const all = within(list).getAllByRole("listitem");
    expect(all.slice(-past).every((li) => /Overdue/.test(li.textContent ?? "") && !/Alarms:/.test(li.textContent ?? ""))).toBe(true);
    await user.click(within(card).getByRole("button", { name: "Show fewer" }));
    await waitFor(() => expect(scrolled).toHaveBeenCalledWith({ block: "nearest" }));
    expect(within(card).getByRole("button", { name: /^Show all/ })).toHaveFocus();
  });

  it("while paused, only “Save and sync” retries — “Sync now” would send the refused password again", async () => {
    const { srv } = useMockApi();
    await srv.handle("PUT", "/calendar/sync", new URLSearchParams(), { url: CALENDAR, username: "sam", password: "abcd-efgh-ijkl-mnop", mode: "discreet" }, null);
    const handle = srv.handle.bind(srv);
    srv.handle = async (method, path, query, body, signal) => {
      const res = await handle(method, path, query, body, signal);
      if (method !== "GET" || path !== "/calendar/sync") return res;
      const status = (await res.json()) as CalendarSyncStatus;
      return new Response(JSON.stringify({ ...status, paused: true }), { status: 200, headers: { "Content-Type": "application/json" } });
    };
    const card = await openCard();
    expect(await within(card).findByText("Paused: the server refused the app password")).toBeInTheDocument();
    expect(within(card).getByRole("button", { name: "Save and sync" })).toBeEnabled();
    expect(within(card).getByRole("button", { name: "Sync now" })).toBeDisabled();
  });

  it("shows the shared load error when calendar sync can't be loaded", async () => {
    const { srv } = useMockApi();
    const handle = srv.handle.bind(srv);
    srv.handle = async (method, path, query, body, signal) =>
      method === "GET" && path === "/calendar/sync"
        ? new Response(JSON.stringify({ detail: "boom" }), { status: 400, headers: { "Content-Type": "application/json" } })
        : handle(method, path, query, body, signal);
    renderWithProviders(<SettingsPage />, { route: "/settings?section=calendar" });
    const card = await screen.findByRole("region", { name: "Sync with your own calendar" });
    const alert = await within(card).findByRole("alert", {}, { timeout: 5000 });
    expect(within(alert).getByRole("heading", { level: 4, name: "Couldn't load calendar sync" })).toBeInTheDocument();
    expect(within(alert).getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("changes what the calendar gets, syncs now and disconnects", async () => {
    const { calls, srv } = useMockApi();
    // connected before the page opens
    await srv.handle("PUT", "/calendar/sync", new URLSearchParams(), { url: CALENDAR, username: "sam", password: "abcd-efgh-ijkl-mnop", mode: "discreet" }, null);
    const user = userEvent.setup();
    const card = await openCard();
    await within(card).findByText(/^Connected to Ordnung$/);

    await user.click(within(card).getByRole("radio", { name: "With details" }));
    await user.click(within(card).getByRole("button", { name: "Save changes" }));
    expect(await within(card).findByText("Saved.")).toBeInTheDocument();
    expect(calls.find((c) => c.method === "PUT")?.body).toEqual({ url: CALENDAR, username: "sam", password: null, mode: "full" });

    await user.click(within(card).getByRole("button", { name: "Sync now" }));
    expect(await screen.findByText("Calendar synced")).toBeInTheDocument();

    await user.click(within(card).getByRole("button", { name: "Disconnect…" }));
    const dialog = await screen.findByRole("dialog", { name: "Disconnect Ordnung?" });
    expect(within(dialog).getByRole("checkbox", { name: /Also remove Ordnung's \d+ events from the calendar/ })).toBeChecked();
    await user.click(within(dialog).getByRole("button", { name: "Disconnect" }));
    expect(await screen.findByText("Disconnected Ordnung")).toBeInTheDocument();
    expect(calls.find((c) => c.path === "/calendar/sync/disconnect")?.body).toEqual({ remove_events: true });
    expect(await screen.findByRole("button", { name: "Find my calendars" })).toBeInTheDocument();
    // "Disconnect…" is gone: the card's heading has the focus
    await waitFor(() => expect(screen.getByRole("heading", { name: "Sync with your own calendar" })).toHaveFocus());
  });

  it("keeps the calendar file next to its guide, calendar sync after them", async () => {
    useMockApi();
    renderWithProviders(<SettingsPage />, { route: "/settings?section=calendar" });
    await screen.findByText("What your calendar gets", {}, { timeout: 3000 });
    const file = screen.getByText("Add my dates to my calendar");
    const guide = screen.getByRole("region", { name: "How to import it" });
    const sync = screen.getByRole("region", { name: "Sync with your own calendar" });
    expect(file.compareDocumentPosition(guide) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(guide.compareDocumentPosition(sync) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByText(/It's a snapshot/)).toBeInTheDocument();
  });

  it("says the dates already go to a connected calendar (importing the file there too would double them)", async () => {
    const { srv } = useMockApi();
    srv.db.state.suggestions.push({ ...srv.db.state.suggestions[0]!, id: "cal-idea", rule_id: "calendar_outdated", status: "new" });
    await srv.handle("PUT", "/calendar/sync", new URLSearchParams(), { url: CALENDAR, username: "sam", password: "abcd-efgh-ijkl-mnop", mode: "discreet" }, null);
    // connecting took the "import the calendar file" Idea away, as the API's triggers do
    expect(srv.db.state.suggestions.filter((x) => x.rule_id === "calendar_outdated" && x.status === "new")).toHaveLength(0);
    renderWithProviders(<SettingsPage />, { route: "/settings?section=calendar" });
    expect(await screen.findByText(/Your dates already go to “Ordnung” by calendar sync/, {}, { timeout: 3000 })).toHaveTextContent("every date would be there twice");
    expect(screen.queryByText(/It's a snapshot/)).not.toBeInTheDocument();
  });

  it("explains that the online demo can't sync, and still shows what would be sent", async () => {
    useMockApi({ staticDemo: true });
    const card = await openCard();
    expect(await within(card).findByRole("note")).toHaveTextContent("The online demo can't reach your calendar");
    expect(within(card).queryByLabelText("App password")).not.toBeInTheDocument();
    expect(within(card).queryByRole("button", { name: "Find my calendars" })).not.toBeInTheDocument();
    expect(await within(card).findByRole("list", { name: "Events, discreet" })).toBeInTheDocument();
  });
});
