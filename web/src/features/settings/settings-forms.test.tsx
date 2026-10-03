/**
 * Settings forms (UI audit round 1, settings-b): the save bar that stays in view, profile
 * validation, the Reminders chips and their focus, "Save and go", the AI jobs that are switched
 * off, the Region and Calendar copy and the Claude connection's states.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { qk } from "@/api/hooks";
import type { Health } from "@/api/types";
import { __clearToasts } from "@/components/ui/Toast";
import {
  makeTestQueryClient,
  renderWithProviders,
  TEST_HEALTH,
} from "@/test/render";
import { useMockApi } from "@/test/mockFetch";
import SettingsPage from "@/pages/SettingsPage";
import { LLM_PURPOSE_LABELS } from "@/lib/copy";
import { CALENDAR_FILE_KEY, calendarFileSummary } from "./CalendarSection";
import { bareVersion } from "./ClaudeSection";
import { leadDaysError, leadLabel, leadSpan } from "./logic";
import { cleanProfile, profileErrors } from "./ProfileSection";
import { SAVED_PIN_MS } from "./SettingsCard";
import { edgeFade } from "./SettingsNav";

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

const pinnedBar = () => document.querySelector<HTMLElement>("[data-pinned]");

describe("settings helpers", () => {
  it("lead times read like the chips; a lead time that can't be added says why", () => {
    expect([1, 3, 7, 14, 30].map(leadSpan)).toEqual([
      "1 day",
      "3 days",
      "1 week",
      "2 weeks",
      "30 days",
    ]);
    expect(leadLabel(21)).toBe("3 weeks before");
    expect(leadDaysError("5", [14, 7])).toBeNull();
    expect(leadDaysError(" 7 ", [14, 7])).toBe(
      "Already in the list (1 week before)",
    );
    expect(leadDaysError("400", [])).toBe("Up to 365 days");
    expect(leadDaysError("", [])).toMatch(/Enter a number/);
    expect(leadDaysError("5.5", [])).toMatch(/Enter a number/);
  });

  it("a profile is saved without stray spaces, and needs a name, a real e-mail address and a valid IBAN", () => {
    expect(
      cleanProfile({
        name: "  Sam   Rivera ",
        address: " Weg 1 \n 12345 Stadt ",
        email: " sam@example.de ",
        phone: " 0170 ",
        iban: " de89 3704 0044 0532 0130 00 ",
      }),
    ).toEqual({
      name: "Sam Rivera",
      address: "Weg 1\n12345 Stadt",
      email: "sam@example.de",
      phone: "0170",
      iban: "DE89370400440532013000",
    });
    expect(
      profileErrors({
        name: "   ",
        address: "",
        email: "sam.rivera@",
        phone: "",
        iban: "DE89 3704 0044 0532 0130 01",
      }),
    ).toEqual({
      name: expect.stringMatching(/Enter your name/),
      email: expect.stringMatching(/doesn't look like an email address/),
      iban: expect.stringMatching(/That IBAN isn't valid/),
    });
    expect(
      profileErrors({
        name: "Sam",
        address: "",
        email: "",
        phone: "",
        iban: "",
      }),
    ).toEqual({});
  });

  it("names the Claude Code version once; says what the calendar file will hold", () => {
    expect(bareVersion("2.1.283 (Claude Code)")).toBe("2.1.283");
    expect(bareVersion(null)).toBeNull();
    expect(calendarFileSummary(0)).toMatch(/^No dates yet — add letters first/);
    // the file's events, never "dates": Today's Idea counts the dates to act on, and a contract's
    // decision is two events (post by, arrive by) — two counts of "dates" for one file (round 2)
    expect(calendarFileSummary(1)).toBe(
      "1 calendar event in one file: every open date and send-by day.",
    );
    expect(calendarFileSummary(12)).toBe(
      "12 calendar events in one file: every open date and send-by day.",
    );
    for (const n of [1, 12])
      expect(calendarFileSummary(n)).not.toMatch(/\bdates? in\b/);
  });

  it("the section pills fade out only at an edge with more behind it", () => {
    expect(edgeFade(false, false)).toBeUndefined();
    expect(edgeFade(false, true)?.maskImage).toMatch(
      /^linear-gradient\(to right, #000, .* transparent\)$/,
    );
    expect(edgeFade(true, true)?.WebkitMaskImage).toMatch(
      /^linear-gradient\(to right, transparent, .* transparent\)$/,
    );
  });
});

describe("the save bar", () => {
  it("is only a status while nothing changed, stays in view while there are edits and confirms a save in place", async () => {
    useMockApi();
    const user = userEvent.setup();
    renderWithProviders(<SettingsPage />, {
      route: "/settings?section=profile",
    });
    const phone = await screen.findByLabelText(/^Phone/);
    const status = screen.getByText("All changes saved").closest("p")!;
    // the status on the left; a footer's lone action (Data → "Download JSON") stays on the right
    expect(status.className).toMatch(/\bmr-auto\b/);
    expect(status.parentElement!.className).toMatch(/\bjustify-end\b/);
    // no disabled "Saved" button next to it
    expect(
      screen.queryByRole("button", { name: /Save/ }),
    ).not.toBeInTheDocument();
    expect(pinnedBar()).toBeNull();

    await user.type(phone, "1");
    expect(screen.getByText("Unsaved changes")).toBeInTheDocument();
    const bar = pinnedBar()!;
    expect(bar).not.toBeNull();
    expect(bar.className).toMatch(/\bsticky\b/);
    // the card clips its corners without becoming the sticky footer's scroll box
    expect(bar.closest(".card")!.className).toMatch(/\boverflow-clip\b/);
    expect(
      within(bar)
        .getAllByRole("button")
        .map((b) => b.textContent),
    ).toEqual(["Discard", "Save changes"]);

    await user.click(within(bar).getByRole("button", { name: "Save changes" }));
    expect(
      await screen.findByText("New letters use this name and address."),
    ).toBeInTheDocument();
    // readable in place a moment, then the bar goes back to the end of its card
    expect(pinnedBar()).not.toBeNull();
    await waitFor(() => expect(pinnedBar()).toBeNull(), {
      timeout: SAVED_PIN_MS + 2000,
    });
    expect(screen.getByText("Saved.")).toBeInTheDocument();
  });

  it("keeps keyboard focus in the card after Save and after Discard — on the status, never <body>", async () => {
    useMockApi();
    const user = userEvent.setup();
    renderWithProviders(<SettingsPage />, {
      route: "/settings?section=profile",
    });
    const phone = await screen.findByLabelText(/^Phone/);
    const status = screen.getByText("All changes saved").closest("p")!;
    // reachable from script only: no extra Tab stop in every card
    expect(status).toHaveAttribute("tabindex", "-1");

    // Save with the keyboard: Tab from the field to the pinned bar's buttons, Enter
    await user.type(phone, "1");
    const bar = pinnedBar()!;
    within(bar).getByRole("button", { name: "Save changes" }).focus();
    await user.keyboard("{Enter}");
    expect(
      await screen.findByText("New letters use this name and address."),
    ).toBeInTheDocument();
    await waitFor(() => expect(status).toHaveFocus());
    expect(within(bar).queryByRole("button")).toBeNull();

    // Discard: the buttons go at once, focus stays on what the bar now says
    await user.type(phone, "2");
    within(pinnedBar()!).getByRole("button", { name: "Discard" }).focus();
    await user.keyboard("{Enter}");
    expect(screen.queryByText("Unsaved changes")).toBeNull();
    expect(status).toHaveFocus();
    expect(document.activeElement).not.toBe(document.body);
  });

  it("leaves focus alone when it moved on while the save was running", async () => {
    const { srv } = useMockApi();
    const handle = srv.handle.bind(srv);
    let answer = () => {};
    const held = new Promise<void>((resolve) => (answer = resolve));
    srv.handle = async (method, path, query, body, signal) => {
      if (method === "PUT" && path === "/profile") await held;
      return handle(method, path, query, body, signal);
    };
    const user = userEvent.setup();
    renderWithProviders(<SettingsPage />, {
      route: "/settings?section=profile",
    });
    const phone = await screen.findByLabelText(/^Phone/);
    await user.type(phone, "3");
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    // the person clicked into another field before the answer came
    const email = screen.getByLabelText(/^Email/);
    await user.click(email);
    act(() => answer());
    expect(
      await screen.findByText("New letters use this name and address."),
    ).toBeInTheDocument();
    expect(email).toHaveFocus();
  });
});

describe("a load error", () => {
  it("is the shared error card: a primary “Try again” that spins while it asks again, and the technical details", async () => {
    const { srv } = useMockApi();
    const handle = srv.handle.bind(srv);
    let failing = true;
    let answer = () => {};
    srv.handle = async (method, path, query, body, signal) => {
      if (method === "GET" && path === "/profile" && failing)
        return new Response(JSON.stringify({ detail: "database is locked" }), {
          status: 500,
        });
      if (method === "GET" && path === "/profile")
        await new Promise<void>((resolve) => (answer = resolve));
      return handle(method, path, query, body, signal);
    };
    const user = userEvent.setup();
    renderWithProviders(<SettingsPage />, {
      route: "/settings?section=profile",
    });
    const alert = await screen.findByRole("alert");
    expect(
      within(alert).getByRole("heading", {
        level: 2,
        name: "Couldn't load your settings",
      }),
    ).toBeInTheDocument();
    expect(alert).toHaveTextContent(
      "Your letters are safe — Ordnung didn't answer. Is it still running?",
    );
    expect(within(alert).getByText("Technical details")).toBeInTheDocument();
    expect(alert).toHaveTextContent("HTTP 500 · database is locked");
    const retry = within(alert).getByRole("button", { name: "Try again" });
    expect(retry.className).toMatch(/\bbg-accent\b/); // primary, as on every other page

    failing = false;
    await user.click(retry);
    // asking again: the card stays (not announced twice) and the button says it is busy
    await waitFor(() =>
      expect(
        within(screen.getByRole("alert")).getByRole("button", {
          name: "Try again",
        }),
      ).toHaveAttribute("aria-busy", "true"),
    );
    act(() => answer());
    expect(await screen.findByLabelText("Full name")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("Profile", () => {
  it("shows a mistake once you leave the field, and Save points to it instead of saving", async () => {
    const { calls } = useMockApi();
    const user = userEvent.setup();
    renderWithProviders(<SettingsPage />, {
      route: "/settings?section=profile",
    });
    const email = await screen.findByLabelText(/^Email/);
    await user.clear(email);
    await user.type(email, "sam.rivera@");
    // not while typing
    expect(email).not.toHaveAttribute("aria-invalid");
    await user.tab();
    expect(email).toHaveAttribute("aria-invalid", "true");
    expect(email).toHaveAccessibleDescription(
      /doesn't look like an email address/,
    );

    const name = screen.getByLabelText("Full name");
    await user.clear(name);
    await user.type(name, "   ");
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    expect(
      screen.getByText("Fix the highlighted field to save"),
    ).toBeInTheDocument();
    expect(name).toHaveAccessibleDescription(/Enter your name/);
    await waitFor(() => expect(name).toHaveFocus());
    expect(calls.some((c) => c.method === "PUT")).toBe(false);

    await user.clear(name);
    await user.type(name, "  Sam  Rivera ");
    await user.clear(email);
    await user.type(email, " sam@example.de ");
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "PUT")?.body).toMatchObject({
        name: "Sam Rivera",
        email: "sam@example.de",
      }),
    );
    expect(await screen.findByText("Saved.")).toBeInTheDocument();
  });

  it("“Save and go” saves, then opens the other section", async () => {
    const { calls } = useMockApi();
    const user = userEvent.setup();
    const { router } = renderWithProviders(<SettingsPage />, {
      route: "/settings?section=profile",
    });
    await user.type(await screen.findByLabelText(/^Phone/), "9");
    await user.click(
      within(
        screen.getByRole("navigation", { name: "Settings sections" }),
      ).getByRole("link", { name: "Reminders" }),
    );
    const dialog = await screen.findByRole("dialog", {
      name: "Save your changes?",
    });
    expect(
      within(dialog)
        .getAllByRole("button")
        .map((b) => b.textContent),
    ).toEqual(
      expect.arrayContaining([
        "Discard changes",
        "Keep editing",
        "Save and go",
      ]),
    );
    await user.click(
      within(dialog).getByRole("button", { name: "Save and go" }),
    );
    await waitFor(() =>
      expect(router.state.location.search).toBe("?section=reminders"),
    );
    expect(
      (calls.find((c) => c.method === "PUT")?.body as { phone: string }).phone,
    ).toMatch(/9$/);
    expect(
      await screen.findByRole(
        "heading",
        { level: 2, name: "Reminders" },
        { timeout: 5_000 },
      ),
    ).toBeInTheDocument();
  });

  it("“Save and go” with a mistake stays and shows it", async () => {
    const { calls } = useMockApi();
    const user = userEvent.setup();
    const { router } = renderWithProviders(<SettingsPage />, {
      route: "/settings?section=profile",
    });
    const email = await screen.findByLabelText(/^Email/);
    await user.clear(email);
    await user.type(email, "sam@");
    await user.click(
      within(
        screen.getByRole("navigation", { name: "Settings sections" }),
      ).getByRole("link", { name: "Data" }),
    );
    await user.click(
      within(
        await screen.findByRole("dialog", { name: "Save your changes?" }),
      ).getByRole("button", { name: "Save and go" }),
    );
    await waitFor(
      () => expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
      { timeout: 3000 },
    );
    expect(router.state.location.search).toBe("?section=profile");
    expect(calls.some((c) => c.method === "PUT")).toBe(false);
    expect(email).toHaveAttribute("aria-invalid", "true");
    await waitFor(() => expect(email).toHaveFocus());
  });
});

describe("Reminders", () => {
  it("the chips are the list and “+ Add” follows it; Enter and Escape hand focus back to “+ Add”", async () => {
    useMockApi();
    const user = userEvent.setup();
    renderWithProviders(<SettingsPage />, {
      route: "/settings?section=reminders",
    });
    const deadlines = await screen.findByRole("list", {
      name: "Reminders for deadlines",
    });
    for (const child of Array.from(deadlines.children))
      expect(child.tagName).toBe("LI");
    expect(
      within(deadlines).queryByRole("button", { name: /^Add a reminder/ }),
    ).not.toBeInTheDocument();
    // 24 px remove buttons
    expect(
      within(deadlines).getByRole("button", {
        name: "Remove reminder 1 day before for deadlines",
      }).className,
    ).toMatch(/\bsize-6\b/);

    await user.click(
      screen.getByRole("button", { name: "Add a reminder for deadlines" }),
    );
    await user.keyboard("{Escape}");
    expect(
      screen.getByRole("button", { name: "Add a reminder for deadlines" }),
    ).toHaveFocus();

    await user.click(
      screen.getByRole("button", { name: "Add a reminder for deadlines" }),
    );
    const field = screen.getByLabelText("Days before, for deadlines");
    expect(field).toHaveAttribute("type", "text");
    expect(field).toHaveAttribute("inputmode", "numeric");
    // a duplicate or too many days: the field stays open and says why
    await user.type(field, "7{Enter}");
    expect(field).toHaveAttribute("aria-invalid", "true");
    expect(field).toHaveAccessibleDescription(
      "Already in the list (1 week before)",
    );
    await user.clear(field);
    await user.type(field, "400{Enter}");
    expect(screen.getByRole("alert")).toHaveTextContent("Up to 365 days");
    await user.clear(field);
    await user.type(field, "5{Enter}");
    expect(
      within(deadlines)
        .getAllByRole("listitem")
        .map((li) => li.textContent),
    ).toEqual([
      "2 weeks before",
      "1 week before",
      "5 days before",
      "3 days before",
      "1 day before",
    ]);
    expect(
      screen.getByRole("button", { name: "Add a reminder for deadlines" }),
    ).toHaveFocus();
    expect(
      screen.getByText("Added: 5 days before, for deadlines"),
    ).toBeInTheDocument();
  });

  it("removing a chip moves focus to the next one (the last: to the one before, none left: to “+ Add”)", async () => {
    useMockApi();
    const user = userEvent.setup();
    renderWithProviders(<SettingsPage />, {
      route: "/settings?section=reminders",
    });
    const deadlines = await screen.findByRole("list", {
      name: "Reminders for deadlines",
    });
    await user.click(
      within(deadlines).getByRole("button", {
        name: "Remove reminder 3 days before for deadlines",
      }),
    );
    expect(
      within(deadlines).getByRole("button", {
        name: "Remove reminder 1 day before for deadlines",
      }),
    ).toHaveFocus();
    expect(
      screen.getByText("Removed: 3 days before, for deadlines"),
    ).toBeInTheDocument();
    await user.click(
      within(deadlines).getByRole("button", {
        name: "Remove reminder 1 day before for deadlines",
      }),
    );
    expect(
      within(deadlines).getByRole("button", {
        name: "Remove reminder 1 week before for deadlines",
      }),
    ).toHaveFocus();

    const todos = screen.getByRole("list", { name: "Reminders for to-dos" });
    await user.click(
      within(todos).getByRole("button", {
        name: "Remove reminder 3 days before for to-dos",
      }),
    );
    expect(
      screen.getByRole("button", { name: "Add a reminder for to-dos" }),
    ).toHaveFocus();
  });

  it("the head start for letters by post is a labelled field", async () => {
    useMockApi();
    renderWithProviders(<SettingsPage />, {
      route: "/settings?section=reminders",
    });
    const buffer = await screen.findByLabelText("Time to allow for the post");
    expect(buffer.tagName).toBe("SELECT");
    expect(buffer).toHaveAttribute("id", "postal-buffer");
    expect(buffer).toHaveAccessibleDescription(
      /Recommended: 4 working days\. .* within 3 working days/,
    );
  });
});

describe("AI & models", () => {
  it("offers no model per job — one model does everything, chosen under Claude connection — and “Weekly review” names only the session", async () => {
    useMockApi();
    renderWithProviders(<SettingsPage />, { route: "/settings?section=ai" });
    expect(
      await screen.findByRole("heading", { level: 2, name: "AI & models" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        /One model does every job — Sonnet 5 unless you choose another under Claude connection → Model\./,
      ),
    ).toBeInTheDocument();
    expect(screen.queryByRole("radiogroup")).toBeNull();
    expect(screen.queryByText(/which model does which job/)).toBeNull();
    const model = screen.getByRole("link", { name: /^Model/ });
    expect(model).toHaveAttribute("href", "/settings?section=claude");
    expect(model).toHaveTextContent(
      "claude-sonnet-5 — change it in Claude connection",
    );
    expect(
      screen.getByRole("link", { name: /Language for explanations/ }),
    ).toHaveAttribute("href", "/settings?section=region");
    expect(screen.queryByText(/weekly review/i)).toBeNull();
    expect(LLM_PURPOSE_LABELS.review).toBe("Weekly Ideas");
  });

  it("switching the daily note off is saved with the other choices, for the next note", async () => {
    const { srv, calls } = useMockApi();
    const user = userEvent.setup();
    renderWithProviders(<SettingsPage />, { route: "/settings?section=ai" });
    const brief = await screen.findByRole("switch", {
      name: /Let Claude write the daily note/,
    });
    expect(brief).toBeChecked();
    await user.click(brief);
    expect(screen.getByText("Unsaved changes")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    expect(
      await screen.findByText(/They apply to the next letter or question\./),
    ).toBeInTheDocument();
    expect(
      calls.find((c) => c.method === "PUT" && c.path === "/settings")?.body,
    ).toEqual({ concurrency: 2, llm_brief: false, llm_review: true });
    expect(srv.db.state.settings.llm_brief).toBe(false);
    expect(screen.queryByText("Unsaved changes")).toBeNull();
  });
});

describe("Region & language", () => {
  it("lists the states by their German names (the English one is in the hint)", async () => {
    useMockApi();
    renderWithProviders(<SettingsPage />, {
      route: "/settings?section=region",
    });
    const state = await screen.findByLabelText(
      "Your federal state (Bundesland)",
    );
    expect(
      within(state).getByRole("option", { name: "Nordrhein-Westfalen" }),
    ).toBeInTheDocument();
    expect(
      within(state).queryByRole("option", { name: /North Rhine/ }),
    ).not.toBeInTheDocument();
    expect(state).toHaveAccessibleDescription(
      /Payments you make count the holidays of Nordrhein-Westfalen \(North Rhine-Westphalia\)\./,
    );
    // a letter's deadlines follow its sender's state, which only the person sets (nationwide until then)
    expect(
      screen.getByText(/Letters from authorities use their own state's holidays, or nationwide ones until you set the sender's state/),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Language for explanations").tagName).toBe(
      "SELECT",
    );
  });
});

describe("Calendar", () => {
  it("with no dates the download waits; the alarms use the chips' words and link to Reminders", async () => {
    useMockApi();
    const client = makeTestQueryClient();
    client.setQueryData(CALENDAR_FILE_KEY, 0);
    renderWithProviders(<SettingsPage />, {
      route: "/settings?section=calendar",
      client,
    });
    expect(
      await screen.findByText(/^No dates yet — add letters first/),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Download .ics" }),
    ).toBeDisabled();
    expect(
      screen.getByText(
        /Alarms: 2 weeks, 1 week, 3 days and 1 day before each deadline/,
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "change them in Reminders" }),
    ).toHaveAttribute("href", "/settings?section=reminders");
    expect(
      screen.queryByText(/change them in Settings/),
    ).not.toBeInTheDocument();
  });

  it("counts the dates in the file itself", async () => {
    useMockApi();
    const apiFetch = globalThis.fetch;
    const ics =
      "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nEND:VEVENT\r\nBEGIN:VEVENT\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n";
    vi.stubGlobal("fetch", (input: RequestInfo | URL, init?: RequestInit) =>
      String(input).includes("calendar.ics")
        ? Promise.resolve(new Response(ics))
        : apiFetch(input, init),
    );
    renderWithProviders(<SettingsPage />, {
      route: "/settings?section=calendar",
    });
    expect(
      await screen.findByText(
        "2 calendar events in one file: every open date and send-by day.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download .ics" })).toBeEnabled();
    // the action in one voice with Today's Idea and the Timeline's dialog
    expect(
      screen.getByText("Add your dates to your calendar"),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Add my dates/)).toBeNull();
  });
});

describe("Claude connection", () => {
  const withHealth = (health: Partial<Health>) => {
    const client = makeTestQueryClient();
    client.setQueryData(qk.health, { ...TEST_HEALTH, ...health });
    return client;
  };

  it("the demo has nothing to check: no “Run check”, and the steps behind a disclosure", async () => {
    useMockApi();
    const client = withHealth({
      backend: "replay",
      claude: {
        installed: false,
        version: null,
        path: null,
        ok: null,
        detail: null,
      },
    });
    renderWithProviders(<SettingsPage />, {
      route: "/settings?section=claude",
      client,
    });
    expect(
      await screen.findByText("The demo runs without Claude"),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Run check" }),
    ).not.toBeInTheDocument();
    // not installed: whether you're signed in isn't a question yet
    expect(screen.queryByText("Signed in")).not.toBeInTheDocument();
    expect(
      screen
        .getByText("Connect Claude for your own letters")
        .closest("summary"),
    ).not.toBeNull();
  });

  it("signed out: its own words with the command as code, never literal backticks", async () => {
    useMockApi();
    const client = withHealth({
      backend: "claude_cli",
      claude: {
        installed: true,
        version: "2.1.283 (Claude Code)",
        path: "/usr/local/bin/claude",
        ok: false,
        detail:
          "Claude Code is installed but not signed in. Run `claude` once and sign in.",
      },
    });
    renderWithProviders(<SettingsPage />, {
      route: "/settings?section=claude",
      client,
    });
    const status = await screen.findByText(
      "Claude is installed, but not signed in",
    );
    const box = status.closest("[role=status]") as HTMLElement;
    expect(box.textContent).not.toMatch(/`/);
    expect(within(box).getByText("claude").tagName).toBe("CODE");
    expect(screen.getByText("2.1.283")).toBeInTheDocument();
    expect(screen.getByText("No")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run check" })).toBeEnabled();
    expect(screen.getByText("ordnung doctor --probe").className).toMatch(
      /whitespace-nowrap/,
    );
  });

  it("names the program as the setup wizard does — Claude Code, never “the Claude app” — and its version once", async () => {
    useMockApi();
    const client = withHealth({
      backend: "claude_cli",
      claude: {
        installed: true,
        version: "2.1.4 (Claude Code)",
        path: "/usr/local/bin/claude",
        ok: true,
        detail: null,
      },
    });
    renderWithProviders(<SettingsPage />, {
      route: "/settings?section=claude",
      client,
    });
    const section = (
      await screen.findByRole("heading", {
        level: 2,
        name: "Claude connection",
      })
    ).closest("section") as HTMLElement;
    expect(section).toHaveTextContent(
      "Ordnung reads letters with Claude Code, the Claude program on this computer, signed in with your own Claude account.",
    );
    expect(section.textContent).not.toMatch(/Claude app|claude CLI/i);
    const version = within(section).getByText("2.1.4");
    expect(version.previousElementSibling).toHaveTextContent("Claude Code");
  });

  it("not installed: “Run check” stays (it finds a fresh install) and says so", async () => {
    useMockApi();
    const client = withHealth({
      backend: "claude_cli",
      claude: {
        installed: false,
        version: null,
        path: null,
        ok: null,
        detail: null,
      },
    });
    renderWithProviders(<SettingsPage />, {
      route: "/settings?section=claude",
      client,
    });
    expect(
      await screen.findByText("Claude isn't installed"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run check" })).toBeEnabled();
    expect(
      screen.getByText(/^Installed it\? The check finds it/),
    ).toBeInTheDocument();
    expect(screen.queryByText("Signed in")).not.toBeInTheDocument();
  });
});

describe("switching sections", () => {
  it("moves focus to the new section's heading, without a focus box around it", async () => {
    useMockApi();
    const user = userEvent.setup();
    renderWithProviders(<SettingsPage />, {
      route: "/settings?section=profile",
    });
    const nav = await screen.findByRole("navigation", {
      name: "Settings sections",
    });
    await user.click(within(nav).getByRole("link", { name: "Calendar" }));
    const heading = await screen.findByRole("heading", {
      level: 2,
      name: "Calendar",
    });
    await waitFor(() => expect(heading).toHaveFocus());
    expect(heading).toHaveAttribute("tabindex", "-1");
    expect(heading.className).toMatch(/\boutline-none\b/);
  });
});
