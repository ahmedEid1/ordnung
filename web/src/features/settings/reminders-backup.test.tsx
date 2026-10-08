import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, beforeEach, describe, expect, it, onTestFinished, vi } from "vitest";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Toaster, __clearToasts } from "@/components/ui/Toast";
import SettingsPage from "@/pages/SettingsPage";
import { qk } from "@/api/hooks";
import { makeTestQueryClient, renderWithProviders, TEST_HEALTH } from "@/test/render";
import { useMockApi } from "@/test/mockFetch";
import type { DesktopReminders } from "@/api/types";
import { mockNotification } from "@/mocks/data/reminders";
import { createMockServer } from "@/mocks/server";
import { NB_HYPHEN } from "@/lib/glue";
import { backupStrengthLine, backupSummary, failureSentence, leftOutSentence, MIN_PASSPHRASE, passphraseProblem, restoreCommand, restoreCommandPieces, WEAK_PASSPHRASE_MESSAGE } from "./backup";
import { MIN_PASSPHRASE_BITS, passphraseBits } from "./passphrase";
import { deleteCalendarNote } from "./calendarSync";
import { autostartLabel, failureDetail, failureLine, previewFor, savedNote, testMode, testOutcome, timeError } from "./desktop";

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
  vi.unstubAllEnvs();
  act(() => __clearToasts());
});

// ------------------------------------------------------------------------------------------------
// pure helpers
// ------------------------------------------------------------------------------------------------

describe("desktop notification helpers", () => {
  it("accepts only HH:MM times", () => {
    expect(timeError("08:00")).toBeNull();
    expect(timeError("23:59")).toBeNull();
    for (const bad of ["", "8:00", "24:00", "07:60", "07:00:00"]) expect(timeError(bad)).toMatch(/Choose a time/);
  });

  it("tests in the chosen mode, discreetly while it is off", () => {
    expect(testMode("off")).toBe("discreet");
    expect(testMode("discreet")).toBe("discreet");
    expect(testMode("full")).toBe("full");
  });

  it("previews the chosen mode only", () => {
    const status = { preview: { discreet: { title: "Ordnung", body: "2 things due this week" }, full: null } } as unknown as DesktopReminders;
    expect(previewFor(status, "discreet")).toEqual({ title: "Ordnung", body: "2 things due this week" });
    expect(previewFor(status, "full")).toBeNull();
    expect(previewFor(status, "off")).toBeNull();
    expect(previewFor(undefined, "discreet")).toBeNull();
  });

  it("says what happened after a test", () => {
    const morning = { system: "macos", saved: "discreet", dirty: false, time: "08:00" } as const;
    const sent = testOutcome(true, null, morning);
    // the tool took it: whether macOS shows it is its call, so the toast says where to look
    expect(sent).toMatchObject({ tone: "success", title: "Test notification sent to your system" });
    expect(sent.description).toMatch(/^Nothing appeared\? Open System Settings → Notifications and allow notifications for Script Editor/);
    expect(sent.description).toMatch(/The morning one comes at 08:00\.$/);
    expect(testOutcome(true, null, { ...morning, system: "windows" }).description).toMatch(/Windows PowerShell, and Do not disturb off/);
    // switched on but not saved: no morning notification comes until it is
    expect(testOutcome(true, null, { ...morning, saved: "off", dirty: true, time: "07:30" }).description).toMatch(/Save to get it each morning at 07:30\.$/);
    expect(testOutcome(true, null, { ...morning, saved: "off" }).description).not.toMatch(/morning one/);
    expect(testOutcome(false, "notify-send failed (exit code 1).", morning)).toEqual({ tone: "warn", title: "No notification appeared", description: "notify-send failed (exit code 1)." });
    expect(testOutcome(false, null, morning).description).toMatch(/calendar alarms still work/);
  });

  it("words the save note for each place it runs", () => {
    expect(savedNote("discreet", "07:30", null)).toBe("Once a day at 07:30, while Ordnung runs.");
    expect(savedNote("off", "07:30", null)).toBe("No desktop notification from now on.");
    // the demos never notify on their own: the note doesn't promise it
    // after the save bar's own "Saved." (never "Saved. Saved.")
    expect(savedNote("full", "07:30", "demo")).toBe("The demo doesn't notify on its own — the preview shows what it would say.");
    expect(savedNote("discreet", "07:30", "static")).toMatch(/online demo can't show notifications/);
  });

  it("says why the last notification wasn't shown, while that is the latest news", () => {
    const failed = { last_failure: "notify-send failed (exit code 1).", last_failure_on: "2026-09-28", last_shown_on: null };
    // a sentence for people, the tool's own words folded away beside it
    expect(failureLine(failed)).toBe(
      "The last notification (Mon 28 Sep) couldn't be shown on this computer. Check that your desktop shows notifications, then send a test notification.",
    );
    expect(failureDetail(failed)).toBe("notify-send failed (exit code 1).");
    // given up on after its tries: the day is used up, the failure is still the news
    expect(failureLine({ ...failed, last_shown_on: "2026-09-28" })).not.toBeNull();
    expect(failureLine({ ...failed, last_shown_on: "2026-09-29" })).toBeNull();
    expect(failureLine({ ...failed, last_failure: null })).toBeNull();
    expect(failureLine(undefined)).toBeNull();
  });

  it("names the start-at-login state", () => {
    const info = { enabled: true, points_here: true, kind: "LaunchAgent", path: "/p", command: "ordnung autostart enable" };
    expect(autostartLabel(undefined)).toEqual({ text: "Off", tone: "neutral" });
    expect(autostartLabel({ ...info, enabled: false })).toEqual({ text: "Off", tone: "neutral" });
    expect(autostartLabel({ ...info, points_here: false })).toEqual({ text: "Starts another folder", tone: "warn" });
    expect(autostartLabel(info)).toEqual({ text: "On", tone: "ok" });
  });
});

/** The backup policy as the server has it (`ordnung.backup`): the web app says the same before asking it. */
const BACKUP_POLICY = readFileSync(resolve(__dirname, "../../../../src/ordnung/backup/__init__.py"), "utf8");
const STRONG = "orbit velvet canyon maple thunder";

describe("backup helpers", () => {
  it("checks the passphrase policy — a new sync folder's strength — and the repeat", () => {
    expect(passphraseProblem("short", "short")).toEqual({ field: "passphrase", message: "Use a passphrase of at least 12 characters — five or more words that don't belong together work well." });
    expect(passphraseProblem("a".repeat(1025), "a".repeat(1025))?.field).toBe("passphrase");
    // long enough, but too easy to guess: a short sentence of common words, four words, one word again and again
    for (const guessable of ["a long enough one", "the cat sat on the mat today", "correct horse battery staple", "canyon ".repeat(6)]) {
      expect(passphraseProblem(guessable, guessable)).toEqual({ field: "passphrase", message: WEAK_PASSPHRASE_MESSAGE });
      expect(passphraseBits(guessable)).toBeLessThan(MIN_PASSPHRASE_BITS);
    }
    expect(passphraseProblem(STRONG, `${STRONG}s`)).toEqual({ field: "repeat", message: "The two passphrases differ." });
    expect(passphraseProblem(STRONG, STRONG)).toBeNull();
    expect(passphraseProblem(STRONG)).toBeNull();
    expect(passphraseProblem("twenty chars exactly", "twenty chars exactly", 24)?.message).toMatch(/at least 24/);
  });

  it("still takes a passphrase Ordnung 0.1.0 suggested, but not a pattern in its shape", () => {
    // four random groups of five letters and digits: the estimator counts one with few digits as four words
    for (const earlier of ["fsumn-hqfzc-jgtck-crjwz", "jnkhc-pnbkc-nevya-ngcmd", "k7qmx-3vxdp-9tawr-2emnb"]) {
      expect(passphraseProblem(earlier, earlier)).toBeNull();
      expect(backupStrengthLine(earlier)?.tone).toBe("ok");
    }
    for (const pattern of ["water-water-water-water", "abcde-fghjk-mnpqr-stuvw", "after-these-three-seven", "Fsumn-hqfzc-jgtck-crjwz"]) {
      expect(passphraseProblem(pattern, pattern)).toEqual({ field: "passphrase", message: WEAK_PASSPHRASE_MESSAGE });
    }
    // the server's shape, character for character
    expect(/^EARLIER_SUGGESTION = re\.compile\(r"(.+)"\)$/m.exec(BACKUP_POLICY)?.[1]).toBe("[a-hjkmnp-z2-9]{5}(?:-[a-hjkmnp-z2-9]{5}){3}");
  });

  it("refuses in the server's words", () => {
    const weak = /^WEAK_PASSPHRASE_MESSAGE = \(\s*((?:"[^"]*"\s*)+)\)/m.exec(BACKUP_POLICY)?.[1] ?? "";
    expect([...weak.matchAll(/"([^"]*)"/g)].map((m) => m[1]).join("")).toBe(WEAK_PASSPHRASE_MESSAGE);
    const short = /def length_problem[\s\S]*?return \(\s*((?:f?"[^"]*"\s*)+)\)/.exec(BACKUP_POLICY)?.[1] ?? "";
    const min = Number(/^MIN_PASSPHRASE_CHARS = (\d+)$/m.exec(BACKUP_POLICY)?.[1]);
    expect(min).toBe(MIN_PASSPHRASE);
    expect([...short.matchAll(/"([^"]*)"/g)].map((m) => m[1]).join("").replace("{MIN_PASSPHRASE_CHARS}", String(min))).toBe(passphraseProblem("short")?.message);
  });

  it("says how strong a new passphrase is while it is typed", () => {
    expect(backupStrengthLine("")).toBeNull();
    expect(backupStrengthLine("correct horse battery staple")).toEqual({ tone: "warn", text: expect.stringContaining("add one more word") });
    expect(backupStrengthLine("cat dog")?.text).toContain("add 3 more words");
    expect(backupStrengthLine(STRONG)).toEqual({ tone: "ok", text: "Strong enough for a backup kept on another drive or in the cloud." });
  });

  it("the mock server refuses what the real one refuses", async () => {
    const srv = createMockServer({ staticDemo: false, latency: 0 });
    const post = (passphrase: string) => srv.handle("POST", "/backup", new URLSearchParams(), { passphrase });
    const weak = await post("a long enough passphrase");
    expect(weak.status).toBe(422);
    expect(((await weak.json()) as { detail: string }).detail).toBe(WEAK_PASSPHRASE_MESSAGE);
    expect((await post("short")).status).toBe(422);
    expect((await post(STRONG)).status).toBe(200);
  });

  it("summarises what a backup holds", () => {
    expect(backupSummary({ letters: 1, files: 1, bytes: 2_400_000 })).toBe("1 letter · 1 file · about 2.3 MB");
    expect(backupSummary({ letters: 22, files: 1071, bytes: 10_600_000 })).toBe("22 letters · 1,071 files · about 10 MB");
    expect(restoreCommand("ordnung-backup-2026-09-28.ordnung-backup")).toBe("ordnung restore ordnung-backup-2026-09-28.ordnung-backup");
  });

  it("shows the restore command in pieces that never split the date", () => {
    const nb = (s: string) => s.replaceAll("-", NB_HYPHEN);
    expect(restoreCommandPieces("ordnung-backup-2026-09-28.ordnung-backup")).toEqual(["ordnung restore ", "ordnung-backup-", nb("2026-09-28"), ".ordnung-backup"]);
    expect(restoreCommandPieces("mine.ordnung-backup")).toEqual(["ordnung restore ", "mine", ".ordnung-backup"]);
    // shown glued, copied plain: the pieces are the command
    expect(restoreCommandPieces("ordnung-backup-2026-09-28.ordnung-backup").join("").replaceAll(NB_HYPHEN, "-")).toBe(restoreCommand("ordnung-backup-2026-09-28.ordnung-backup"));
  });

  it("turns a failure into a sentence the dialog can continue", () => {
    expect(failureSentence(new Error("Something went wrong"))).toBe("Something went wrong.");
    expect(failureSentence(new Error("There is no Ordnung database in /x."))).toBe("There is no Ordnung database in /x.");
    expect(failureSentence(new Error("  "))).toBe("Ordnung didn't answer. Is it still running?");
    expect(failureSentence("not an error")).toBe("Ordnung didn't answer. Is it still running?");
  });
});

describe("the demo's notification preview", () => {
  it("counts what is overdue or due this week, and lists the first three in full", () => {
    const { db } = createMockServer({ staticDemo: true, latency: 0 });
    const discreet = mockNotification(db, "discreet");
    const full = mockNotification(db, "full");
    expect(discreet?.title).toBe("Ordnung");
    expect(discreet?.body).toMatch(/^(\d+ due today · )?(\d+ overdue · )?\d+ (things? )?(due|more) this week$|^\d+ things? (overdue|due today)$|^\d+ due today · \d+ overdue$/);
    expect(full?.title).toBe(`Ordnung · ${discreet?.body}`);
    expect(full?.body.split(" · ").length).toBeLessThanOrEqual(4);
    // ticking everything off leaves nothing to say
    for (const item of db.state.items) item.status = "done";
    expect(mockNotification(db, "discreet")).toBeNull();
  });
});

// ------------------------------------------------------------------------------------------------
// Settings → Reminders → desktop notification
// ------------------------------------------------------------------------------------------------

async function openDesktopCard() {
  renderWithProviders(
    <>
      <SettingsPage />
      <Toaster />
    </>,
    { route: "/settings?section=reminders" },
  );
  return screen.findByRole("region", { name: "Desktop notification each morning" });
}

describe("desktop notification card", () => {
  const switchOn = async (user: ReturnType<typeof userEvent.setup>, card: HTMLElement) => {
    await user.click(within(card).getByRole("switch", { name: /Notify me each morning on this computer/ }));
    return within(card).getByRole("radiogroup", { name: "What the desktop notification shows" });
  };

  it("is off until switched on, which starts discreet; details show what is due; saving stores both", async () => {
    const { srv, calls } = useMockApi();
    const user = userEvent.setup();
    const card = await openDesktopCard();
    expect(within(card).getByRole("switch", { name: /Notify me each morning/ })).toHaveAttribute("aria-checked", "false");
    expect(within(card).queryByRole("radiogroup")).not.toBeInTheDocument();
    expect(within(card).queryByLabelText("Show it at")).not.toBeInTheDocument();
    expect(within(card).queryByRole("button", { name: "Show a test notification" })).not.toBeInTheDocument();

    const modes = await switchOn(user, card);
    expect(within(modes).getByRole("radio", { name: "Discreet" })).toBeChecked();
    expect(within(card).getByText(/no names or amounts/)).toBeInTheDocument();
    const preview = await within(card).findByRole("figure");
    await waitFor(() => expect(preview).toHaveTextContent(/Ordnung.*due this week/));
    expect(preview).not.toHaveTextContent("€");
    expect(within(card).getByLabelText("Show it at")).toHaveValue("08:00");

    await user.click(within(modes).getByRole("radio", { name: "With details" }));
    await waitFor(() => expect(within(card).getByRole("figure")).toHaveTextContent(/Ordnung · .*due this week/));
    expect(within(card).getByText(/Anyone who can see your screen can read it/)).toBeInTheDocument();

    const time = within(card).getByLabelText("Show it at");
    await user.clear(time);
    await user.type(time, "07:30");
    await user.click(within(card).getByRole("button", { name: "Save changes" }));
    expect(await within(card).findByText("Saved.")).toBeInTheDocument();
    expect(calls.find((c) => c.method === "PUT" && c.path === "/settings")?.body).toEqual({ desktop_notifications: "full", desktop_notify_time: "07:30" });
    expect(srv.db.state.settings.desktop_notifications).toBe("full");

    // switched off again, it saves only the mode (the time is kept for next time)
    await user.click(within(card).getByRole("switch", { name: /Notify me each morning/ }));
    await user.click(within(card).getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(srv.db.state.settings.desktop_notifications).toBe("off"));
    expect(srv.db.state.settings.desktop_notify_time).toBe("07:30");
  });

  it("won't save an empty time", async () => {
    const { calls } = useMockApi();
    const user = userEvent.setup();
    const card = await openDesktopCard();
    await switchOn(user, card);
    await user.clear(within(card).getByLabelText("Show it at"));
    await user.click(within(card).getByRole("button", { name: "Save changes" }));
    expect(within(card).getByText("Choose a time, like 08:00")).toBeInTheDocument();
    expect(calls.some((c) => c.method === "PUT")).toBe(false);
  });

  it("shows a test notification in the chosen mode and says so", async () => {
    const { calls } = useMockApi();
    const user = userEvent.setup();
    const card = await openDesktopCard();
    await user.click(within(await switchOn(user, card)).getByRole("radio", { name: "With details" }));
    await user.click(await within(card).findByRole("button", { name: "Show a test notification" }));
    expect(await screen.findByText("Test notification sent to your system")).toBeInTheDocument();
    // switched on but not saved yet: the toast doesn't promise the morning one
    expect(screen.getByText(/Save to get it each morning at 08:00\./)).toBeInTheDocument();
    expect(calls.find((c) => c.path === "/reminders/desktop/test")?.body).toEqual({ mode: "full" });
    expect(within(card).getByText("Shown with notify-send")).toBeInTheDocument();
  });

  it("after a test, the card keeps saying where to look if nothing appeared", async () => {
    useDesktopApi(() => ({ system: "macos" as const, tool: "osascript" }));
    const user = userEvent.setup();
    const card = await openDesktopCard();
    await switchOn(user, card);
    expect(within(card).queryByText(/Nothing appeared\?/)).not.toBeInTheDocument();
    await user.click(await within(card).findByRole("button", { name: "Show a test notification" }));
    expect(await within(card).findByText(/Nothing appeared\? Open System Settings → Notifications/)).toBeInTheDocument();
  });

  /** Your own Ordnung (not the demo): the status as the API gives it there, changed by `patch`. */
  const useDesktopApi = (patch: (status: DesktopReminders) => Partial<DesktopReminders>) => {
    const mocked = useMockApi();
    const { srv } = mocked;
    const handle = srv.handle.bind(srv);
    srv.handle = async (method, path, query, body, signal) => {
      const res = await handle(method, path, query, body, signal);
      if (method !== "GET" || path !== "/reminders/desktop") return res;
      const json = (await res.json()) as DesktopReminders;
      const own = { ...json, demo: false, autostart: { ...json.autostart, command: "ordnung autostart enable --data-dir /home/sam/Ordnung" } };
      return new Response(JSON.stringify({ ...own, ...patch(own) }), { status: 200, headers: { "Content-Type": "application/json" } });
    };
    return mocked;
  };

  it("explains how to start this data folder at login", async () => {
    useDesktopApi(() => ({}));
    const card = await openDesktopCard();
    expect(within(card).getByRole("heading", { name: "Start Ordnung when you log in" })).toBeInTheDocument();
    expect(await within(card).findByText("Off")).toBeInTheDocument();
    // the command sets up *this* folder (the API adds --data-dir when it isn't the default one)
    expect(
      await within(card).findByRole("button", { name: "Copy command to start Ordnung when you log in: ordnung autostart enable --data-dir /home/sam/Ordnung" }),
    ).toBeInTheDocument();
  });

  it("in the demo it offers no start-at-login command, and says it doesn't notify on its own", async () => {
    useMockApi();
    const user = userEvent.setup();
    const card = await openDesktopCard();
    expect(await within(card).findByText(/The demo doesn't start at login/)).toBeInTheDocument();
    expect(within(card).queryByRole("button", { name: /Copy command to start Ordnung/ })).not.toBeInTheDocument();
    await switchOn(user, card);
    expect(within(card).getByRole("note")).toHaveTextContent("The demo doesn't notify on its own");
    await user.click(within(card).getByRole("button", { name: "Save changes" }));
    expect(await within(card).findByText("Saved.")).toBeInTheDocument();
    expect(within(card).getByText(/^The demo doesn't notify on its own — the preview shows what it would say\.$/)).toBeInTheDocument();
  });

  it("says why the last notification couldn't be shown", async () => {
    useDesktopApi(() => ({ last_failure: "notify-send failed (exit code 1).", last_failure_on: "2026-09-28" }));
    const user = userEvent.setup();
    const card = await openDesktopCard();
    await switchOn(user, card);
    expect(await within(card).findByText(/^The last notification \(Mon 28 Sep\) couldn't be shown on this computer\. Check that/)).toBeInTheDocument();
    // the tool's own words are there for whoever wants them, folded away
    const raw = within(card).getByText("notify-send failed (exit code 1).");
    expect(raw).not.toBeVisible();
    await user.click(within(card).getByText("What the system said"));
    expect(raw).toBeVisible();
  });

  it("shows the shared load error when today's notification can't be loaded", async () => {
    const { srv } = useMockApi();
    const handle = srv.handle.bind(srv);
    srv.handle = async (method, path, query, body, signal) =>
      method === "GET" && path === "/reminders/desktop"
        ? new Response(JSON.stringify({ detail: "boom" }), { status: 400, headers: { "Content-Type": "application/json" } })
        : handle(method, path, query, body, signal);
    const user = userEvent.setup();
    const card = await openDesktopCard();
    await switchOn(user, card);
    const alert = await within(card).findByRole("alert", {}, { timeout: 5000 });
    expect(within(alert).getByRole("heading", { level: 4, name: "Couldn't load today's notification" })).toBeInTheDocument();
    expect(within(alert).getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  const useAutostartApi = (pointsHere: boolean) =>
    useDesktopApi((own) => ({ autostart: { ...own.autostart, enabled: true, kind: "systemd user service", path: "/home/sam/.config/systemd/user/ordnung.service", points_here: pointsHere } }));

  it("says where start at login is set up (no command to run then)", async () => {
    useAutostartApi(true);
    const card = await openDesktopCard();
    expect(await within(card).findByText("On")).toBeInTheDocument();
    expect(within(card).getByText(/Set up as a systemd user service/)).toHaveTextContent("/home/sam/.config/systemd/user/ordnung.service");
    expect(within(card).getByText(/Set up as a systemd user service/)).toHaveTextContent("ordnung autostart disable undoes it.");
    expect(within(card).queryByRole("button", { name: /Copy command to start Ordnung/ })).not.toBeInTheDocument();
  });

  it("warns when start at login opens another data folder", async () => {
    useAutostartApi(false);
    const card = await openDesktopCard();
    expect(await within(card).findByText("Starts another folder")).toBeInTheDocument();
    expect(within(card).getByText(/set up for another data folder/)).toBeInTheDocument();
    expect(within(card).getByRole("button", { name: /Copy command to start Ordnung when you log in/ })).toBeInTheDocument();
  });

  it("in the online demo it explains that it can't notify", async () => {
    vi.stubEnv("VITE_STATIC_DEMO", "1");
    useMockApi({ staticDemo: true });
    const card = await openDesktopCard();
    expect(within(card).getByRole("note")).toHaveTextContent("Not available in the online demo");
    expect(within(card).queryByRole("button", { name: "Show a test notification" })).not.toBeInTheDocument();
  });
});

// ------------------------------------------------------------------------------------------------
// Settings → Data → encrypted backup
// ------------------------------------------------------------------------------------------------

async function openBackupCard() {
  renderWithProviders(
    <>
      <SettingsPage />
      <Toaster />
    </>,
    { route: "/settings?section=data" },
  );
  return screen.findByRole("region", { name: "Encrypted backup" });
}

describe("encrypted backup card", () => {
  it("says what a backup holds and how to restore it", async () => {
    useMockApi();
    const card = await openBackupCard();
    await waitFor(() => expect(card).toHaveTextContent(/Now: \d+ letters · \d+ files · about [\d.]+ MB/));
    expect(within(card).getByRole("button", { name: /Copy command to restore the backup: ordnung restore ordnung-backup-\d{4}-\d{2}-\d{2}\.ordnung-backup/ })).toBeInTheDocument();
  });

  it("asks for a passphrase twice, refuses a short or different one, then downloads", async () => {
    const { calls } = useMockApi();
    const created: Blob[] = [];
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: (b: Blob) => (created.push(b), "blob:backup"), revokeObjectURL: () => {} }));
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    const user = userEvent.setup();
    const card = await openBackupCard();
    await user.click(within(card).getByRole("button", { name: "Download encrypted backup…" }));
    const dialog = await screen.findByRole("dialog", { name: "Download an encrypted backup" });
    const first = within(dialog).getByLabelText("Passphrase");
    await waitFor(() => expect(first).toHaveFocus());
    expect(first).toHaveAttribute("type", "password");
    expect(first).toHaveAttribute("autocomplete", "new-password");

    await user.click(within(dialog).getByRole("button", { name: "Download backup" }));
    expect(first).toHaveAccessibleDescription(/Use a passphrase of at least 12 characters/);
    // long enough, but too easy to guess: said while typing, and refused before the server is asked
    await user.type(first, "a long enough one");
    expect(within(dialog).getByText(/^Too easy to guess yet: add 3 more words/)).toBeInTheDocument();
    await user.type(within(dialog).getByLabelText("Repeat the passphrase"), "a long enough one");
    await user.click(within(dialog).getByRole("button", { name: "Download backup" }));
    expect(first).toHaveAccessibleDescription(WEAK_PASSPHRASE_MESSAGE);
    await user.clear(first);
    await user.type(first, STRONG);
    expect(within(dialog).getByText("Strong enough for a backup kept on another drive or in the cloud.")).toBeInTheDocument();
    await user.clear(within(dialog).getByLabelText("Repeat the passphrase"));
    await user.type(within(dialog).getByLabelText("Repeat the passphrase"), `${STRONG}s`);
    await user.click(within(dialog).getByRole("button", { name: "Download backup" }));
    expect(within(dialog).getByLabelText("Repeat the passphrase")).toHaveAccessibleDescription("The two passphrases differ.");
    expect(calls.some((c) => c.path === "/backup" && c.method === "POST")).toBe(false);

    await user.click(within(dialog).getByRole("button", { name: "Suggest a strong one" }));
    expect(first).toHaveAttribute("type", "text");
    const suggested = (first as HTMLInputElement).value;
    // five made-up words, as hand-off sync suggests: always strong enough
    expect(suggested).toMatch(/^[bdfgjklmnprstvz][aeiou][bdfgjklmnprstvz][aeiou][bdfgjklmnprstvz](-[bdfgjklmnprstvz][aeiou][bdfgjklmnprstvz][aeiou][bdfgjklmnprstvz]){4}$/);
    expect(passphraseProblem(suggested, suggested)).toBeNull();
    expect(within(dialog).getByLabelText("Repeat the passphrase")).toHaveValue(suggested);
    expect(first).toHaveAccessibleDescription(/Save this passphrase in your password manager/);

    // shown as text, a password manager won't offer to save it: it can be copied instead
    // (user-event puts a clipboard of its own on navigator)
    await user.click(within(dialog).getByRole("button", { name: "Copy passphrase" }));
    expect(await navigator.clipboard.readText()).toBe(suggested);
    expect(await within(dialog).findByRole("button", { name: "Copied" })).toBeInTheDocument();

    await user.click(within(dialog).getByRole("button", { name: "Download backup" }));
    await waitFor(() => expect(within(card).getByRole("status")).toHaveTextContent(/^Downloaded ordnung-backup-\d{4}-\d{2}-\d{2}\.ordnung-backup \([\d.]+ KB\)\. Keep the passphrase safe/));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument(), { timeout: 3000 });
    const post = calls.find((c) => c.path === "/backup" && c.method === "POST");
    expect(post?.body).toEqual({ passphrase: suggested });
    // the passphrase never travels in a URL
    expect(calls.every((c) => !c.path.includes(suggested))).toBe(true);
    expect(created).toHaveLength(1);
    expect(click).toHaveBeenCalled();
    click.mockRestore();

    // opened again, the dialog starts empty
    await user.click(within(card).getByRole("button", { name: "Download encrypted backup…" }));
    expect(within(await screen.findByRole("dialog")).getByLabelText("Passphrase")).toHaveValue("");
  });

  it("shows the server's refusal next to the passphrase", async () => {
    const { srv } = useMockApi();
    const handle = srv.handle.bind(srv);
    srv.handle = async (method, path, query, body, signal) =>
      method === "POST" && path === "/backup"
        ? new Response(JSON.stringify({ detail: "Use a passphrase of at most 1024 characters." }), { status: 422, headers: { "Content-Type": "application/json" } })
        : handle(method, path, query, body, signal);
    const user = userEvent.setup();
    const card = await openBackupCard();
    await user.click(within(card).getByRole("button", { name: "Download encrypted backup…" }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText("Passphrase"), STRONG);
    await user.type(within(dialog).getByLabelText("Repeat the passphrase"), STRONG);
    // (Enter submits too — the footer button belongs to the form; user-event can't see that, e2e does)
    await user.click(within(dialog).getByRole("button", { name: "Download backup" }));
    await waitFor(() => expect(within(dialog).getByLabelText("Passphrase")).toHaveAccessibleDescription("Use a passphrase of at most 1024 characters."));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("a failed backup brings its reason into view and focus", async () => {
    const { srv } = useMockApi();
    const handle = srv.handle.bind(srv);
    srv.handle = async (method, path, query, body, signal) =>
      method === "POST" && path === "/backup"
        ? new Response(JSON.stringify({ detail: "There is no space left on the drive" }), { status: 500, headers: { "Content-Type": "application/json" } })
        : handle(method, path, query, body, signal);
    const user = userEvent.setup();
    const card = await openBackupCard();
    await user.click(within(card).getByRole("button", { name: "Download encrypted backup…" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Suggest a strong one" }));
    await user.click(within(dialog).getByRole("button", { name: "Download backup" }));
    const reason = await within(dialog).findByRole("alert");
    expect(reason).toHaveTextContent("There is no space left on the drive. Nothing was saved.");
    await waitFor(() => expect(document.getElementById("backup-error")).toHaveFocus());
  });

  it("names what a backup leaves out (links are never followed)", async () => {
    const { srv } = useMockApi();
    const handle = srv.handle.bind(srv);
    srv.handle = async (method, path, query, body, signal) => {
      const res = await handle(method, path, query, body, signal);
      if (method !== "GET" || path !== "/backup") return res;
      const info = (await res.json()) as Record<string, unknown>;
      return new Response(JSON.stringify({ ...info, left_out: ["files"] }), { status: 200, headers: { "Content-Type": "application/json" } });
    };
    const user = userEvent.setup();
    const card = await openBackupCard();
    await user.click(within(card).getByRole("button", { name: "Download encrypted backup…" }));
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByText(/^“files” is a link to somewhere outside the data folder, and a backup never follows links\./)).toBeInTheDocument();
    // the summary above it doesn't promise "every letter" when a linked folder is left out
    expect(within(dialog).getByText(/everything inside the data folder — not the linked folders named below/)).toBeInTheDocument();
    expect(within(dialog).queryByText(/every letter as you added it/)).toBeNull();
    expect(leftOutSentence(["files/ab", "files/cd"])).toMatch(/^“files\/ab” and “files\/cd” are links .* Back those up separately, or move them into the data folder\.$/);
    expect(leftOutSentence(["a", "b", "c", "d", "e"])).toMatch(/^“a”, “b”, “c” and 2 more are links/);
  });

  it("in the online demo it explains that there is nothing to back up — and counts nothing", async () => {
    vi.stubEnv("VITE_STATIC_DEMO", "1");
    useMockApi({ staticDemo: true });
    const card = await openBackupCard();
    expect(within(card).getByRole("note")).toHaveTextContent("Not available in the online demo");
    expect(within(card).getByRole("button", { name: "Download encrypted backup…" })).toBeDisabled();
    // no "Now: 22 letters" next to "it keeps nothing", no command for a file that can't be downloaded
    await new Promise((r) => setTimeout(r, 50));
    expect(card).not.toHaveTextContent(/Now:/);
    expect(within(card).queryByRole("button", { name: /Copy command to restore/ })).not.toBeInTheDocument();
  });

  it("keeps focus in the dialog while it encrypts", async () => {
    const { srv } = useMockApi();
    const handle = srv.handle.bind(srv);
    srv.handle = async (method, path, query, body, signal) =>
      method === "POST" && path === "/backup" ? new Promise<Response>(() => {}) : handle(method, path, query, body, signal);
    const user = userEvent.setup();
    const card = await openBackupCard();
    await user.click(within(card).getByRole("button", { name: "Download encrypted backup…" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Suggest a strong one" }));
    await user.click(within(dialog).getByRole("button", { name: "Download backup" }));
    await waitFor(() => expect(within(dialog).getByRole("button", { name: "Stop" })).toHaveFocus());
    // the fields stay focusable (read-only, not disabled) while the backup is made
    expect(within(dialog).getByLabelText("Passphrase")).toHaveAttribute("readonly");
    expect(within(dialog).getByLabelText("Passphrase")).not.toBeDisabled();
  });

  it("says so when what the backup would hold can't be loaded", async () => {
    const { srv } = useMockApi();
    const handle = srv.handle.bind(srv);
    srv.handle = async (method, path, query, body, signal) =>
      method === "GET" && path === "/backup"
        ? new Response(JSON.stringify({ detail: "boom" }), { status: 400, headers: { "Content-Type": "application/json" } })
        : handle(method, path, query, body, signal);
    const card = await openBackupCard();
    const alert = await within(card).findByRole("alert", {}, { timeout: 5000 });
    expect(within(alert).getByRole("heading", { level: 4, name: "Couldn't load what the backup would hold" })).toBeInTheDocument();
    expect(within(card).getByRole("button", { name: "Download encrypted backup…" })).toBeEnabled();
  });
});

// ------------------------------------------------------------------------------------------------
// Settings → Data → Delete everything (with a backup and a connected calendar)
// ------------------------------------------------------------------------------------------------

describe("delete everything", () => {
  /** Your own Ordnung (the demo can't be deleted), connected to a calendar when asked. */
  const useOwnApi = () => {
    const mocked = useMockApi();
    mocked.srv.db.state.health.demo = false;
    return mocked;
  };
  const connectCalendar = (srv: ReturnType<typeof useMockApi>["srv"]) =>
    srv.handle(
      "PUT",
      "/calendar/sync",
      new URLSearchParams(),
      { url: "https://cloud.example.org/remote.php/dav/calendars/sam/ordnung/", username: "sam", password: "abcd-efgh-ijkl-mnop", mode: "discreet" },
      null,
    );

  const openDeleteDialog = async (user: ReturnType<typeof userEvent.setup>) => {
    const client = makeTestQueryClient();
    client.setQueryData(qk.health, { ...TEST_HEALTH, demo: false });
    renderWithProviders(
      <>
        <SettingsPage />
        <Toaster />
      </>,
      { route: "/settings?section=data", client },
    );
    await user.click(await screen.findByRole("button", { name: "Delete everything…" }));
    return screen.findByRole("dialog", { name: "Delete everything?" });
  };

  it("offers an encrypted backup first, opening its dialog in place of this one", async () => {
    useOwnApi();
    const user = userEvent.setup();
    const dialog = await openDeleteDialog(user);
    expect(dialog).toHaveTextContent("Backups you made before stay where you saved them.");
    await user.type(within(dialog).getByLabelText(/to confirm/), "DELETE");
    await user.click(within(dialog).getByRole("button", { name: "Download an encrypted backup first" }));
    const backup = await screen.findByRole("dialog", { name: "Download an encrypted backup" });
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Delete everything?" })).not.toBeInTheDocument());
    // closed, the backup's dialog hands focus back to "Delete everything…", not to the page
    await user.click(within(backup).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Delete everything…" })).toHaveFocus());
    // and "Delete everything" starts over: the typed word doesn't carry over to the next opening
    await user.click(screen.getByRole("button", { name: "Delete everything…" }));
    const again = await screen.findByRole("dialog", { name: "Delete everything?" });
    expect(within(again).getByLabelText(/to confirm/)).toHaveValue("");
    expect(within(again).getByRole("button", { name: "Delete everything" })).toBeDisabled();
  });

  it("when the calendar can't be cleared, the dialog says why — never the correctly typed word's field", async () => {
    const { srv } = useOwnApi();
    await connectCalendar(srv);
    const handle = srv.handle.bind(srv);
    const reason = "Ordnung's events in your calendar “Ordnung” couldn't be removed, so nothing was deleted: Couldn't reach cloud.example.org.";
    srv.handle = async (method, path, query, body, signal) =>
      method === "DELETE" && path === "/data"
        ? new Response(JSON.stringify({ detail: reason }), { status: 409, headers: { "Content-Type": "application/json" } })
        : handle(method, path, query, body, signal);
    const user = userEvent.setup();
    const dialog = await openDeleteDialog(user);
    const field = within(dialog).getByLabelText(/to confirm/);
    await user.type(field, "DELETE");
    const scrolled: [string, ScrollLogicalPosition | undefined][] = [];
    const original = Object.getOwnPropertyDescriptor(Element.prototype, "scrollIntoView");
    Element.prototype.scrollIntoView = function (this: HTMLElement, arg?: boolean | ScrollIntoViewOptions) {
      scrolled.push([this.id, typeof arg === "object" ? arg.block : undefined]);
    };
    onTestFinished(() => {
      if (original) Object.defineProperty(Element.prototype, "scrollIntoView", original);
      else delete (Element.prototype as { scrollIntoView?: unknown }).scrollIntoView;
    });
    await user.click(within(dialog).getByRole("button", { name: "Delete everything" }));
    const alert = await within(dialog).findByRole("alert");
    expect(alert).toHaveTextContent("Nothing was deleted");
    expect(alert).toHaveTextContent(reason);
    // focus goes to the reason (as a failed backup's does), scrolled to its top: on a 320×640 phone it is
    // taller than the room under the header, and bringing in the field below cut off its heading (round 2)
    const reasonBox = alert.closest<HTMLElement>("#delete-everything-error")!;
    await waitFor(() => expect(reasonBox).toHaveFocus());
    expect(scrolled.at(-1)).toEqual(["delete-everything-error", "start"]);
    // the typed word, still right, is the next Tab stop after it (jsdom's Tab doesn't start from a tabindex=-1 box)
    const stops = [...dialog.querySelectorAll<HTMLElement>("a[href], button:not([disabled]), input")];
    expect(stops.find((el) => reasonBox.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING)).toBe(field);
    // "DELETE" was typed right: the field is not marked invalid, nor described by the server's reason
    expect(field).not.toHaveAttribute("aria-invalid", "true");
    expect(field).not.toHaveAccessibleDescription(reason);
    expect(document.activeElement).not.toBe(document.body);
  });

  it("words the calendar's part for one event and for none", () => {
    expect(deleteCalendarNote("Ordnung", 1)).toMatch(/^Your calendar “Ordnung” is connected: Ordnung's event there is removed first/);
    expect(deleteCalendarNote("Ordnung", 3)).toMatch(/Ordnung's 3 events there are removed first/);
    expect(deleteCalendarNote("Ordnung", 0)).toBe(
      "Your calendar “Ordnung” is connected: it holds none of Ordnung's events, and its app password is removed from this computer's password store.",
    );
  });

  it("says a connected calendar loses Ordnung's events first, and reports it", async () => {
    const { calls, srv } = useOwnApi();
    await connectCalendar(srv);
    const user = userEvent.setup();
    const dialog = await openDeleteDialog(user);
    expect(await within(dialog).findByText(/Your calendar “Ordnung” is connected: Ordnung's \d+ events there are removed first/)).toBeInTheDocument();
    await user.type(within(dialog).getByLabelText(/to confirm/), "DELETE");
    await user.click(within(dialog).getByRole("button", { name: "Delete everything" }));
    expect(await screen.findByText(/Ordnung's \d+ events were removed from your calendar, and its app password from this computer\./)).toBeInTheDocument();
    expect(calls.some((c) => c.method === "DELETE" && c.path === "/data")).toBe(true);
  });
});
