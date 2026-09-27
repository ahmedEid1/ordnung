import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Toaster, __clearToasts } from "@/components/ui/Toast";
import SettingsPage from "@/pages/SettingsPage";
import { renderWithProviders } from "@/test/render";
import { useMockApi } from "@/test/mockFetch";
import { createMockServer } from "@/mocks/server";
import { mockCalendarPreview } from "@/mocks/data/calendarSync";
import { eventWhen, fieldFor, hostOf, lastSyncLine, preferredCalendar, syncFormProblem } from "./calendarSync";

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
    expect(new Set(discreet.map((e) => e.summary))).toEqual(new Set(discreet.map((e) => e.summary).filter((s) => /^Ordnung: (deadline|payment|appointment)$/.test(s))));
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
