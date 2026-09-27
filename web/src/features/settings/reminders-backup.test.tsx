import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Toaster, __clearToasts } from "@/components/ui/Toast";
import SettingsPage from "@/pages/SettingsPage";
import { renderWithProviders } from "@/test/render";
import { useMockApi } from "@/test/mockFetch";
import type { DesktopReminders } from "@/api/types";
import { mockNotification } from "@/mocks/data/reminders";
import { createMockServer } from "@/mocks/server";
import { backupSummary, passphraseProblem, restoreCommand, suggestPassphrase } from "./backup";
import { autostartLabel, previewFor, testMode, testOutcome, timeError } from "./desktop";

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
    expect(testOutcome(true, null)).toMatchObject({ tone: "success", title: "Test notification sent" });
    expect(testOutcome(false, "notify-send failed (exit code 1).")).toEqual({ tone: "warn", title: "No notification appeared", description: "notify-send failed (exit code 1)." });
    expect(testOutcome(false, null).description).toMatch(/calendar alarms still work/);
  });

  it("names the start-at-login state", () => {
    const info = { enabled: true, points_here: true, kind: "LaunchAgent", path: "/p", command: "ordnung autostart enable" };
    expect(autostartLabel(undefined)).toEqual({ text: "Off", tone: "neutral" });
    expect(autostartLabel({ ...info, enabled: false })).toEqual({ text: "Off", tone: "neutral" });
    expect(autostartLabel({ ...info, points_here: false })).toEqual({ text: "Starts another folder", tone: "warn" });
    expect(autostartLabel(info)).toEqual({ text: "On", tone: "ok" });
  });
});

describe("backup helpers", () => {
  it("checks the passphrase policy and the repeat", () => {
    expect(passphraseProblem("short", "short")).toEqual({ field: "passphrase", message: "Use at least 12 characters — a short sentence works well." });
    expect(passphraseProblem("a".repeat(1025), "a".repeat(1025))?.field).toBe("passphrase");
    expect(passphraseProblem("a long enough one", "a long enough 0ne")).toEqual({ field: "repeat", message: "The two passphrases differ." });
    expect(passphraseProblem("a long enough one", "a long enough one")).toBeNull();
    expect(passphraseProblem("twenty chars exactly", "twenty chars exactly", 24)?.message).toMatch(/at least 24/);
  });

  it("suggests unambiguous random passphrases without modulo bias", () => {
    const value = suggestPassphrase();
    expect(value).toMatch(/^[a-hjkmnp-z2-9]{5}(-[a-hjkmnp-z2-9]{5}){3}$/);
    expect(suggestPassphrase()).not.toBe(value);
    // bytes ≥ 248 (the biased tail for 31 letters) are skipped, the rest map in order
    let calls = 0;
    const fixed = suggestPassphrase((bytes) => {
      calls += 1;
      bytes.fill(calls === 1 ? 255 : 0);
      return bytes;
    });
    expect(calls).toBe(2);
    expect(fixed).toBe("aaaaa-aaaaa-aaaaa-aaaaa");
  });

  it("summarises what a backup holds", () => {
    expect(backupSummary({ letters: 1, files: 1, bytes: 2_400_000 })).toBe("1 letter · 1 file · about 2.3 MB");
    expect(backupSummary({ letters: 22, files: 1071, bytes: 10_600_000 })).toBe("22 letters · 1,071 files · about 10 MB");
    expect(restoreCommand("ordnung-backup-2026-09-28.ordnung-backup")).toBe("ordnung restore ordnung-backup-2026-09-28.ordnung-backup");
  });
});

describe("the demo's notification preview", () => {
  it("counts what is overdue or due this week, and lists the first three in full", () => {
    const { db } = createMockServer({ staticDemo: true, latency: 0 });
    const discreet = mockNotification(db, "discreet");
    const full = mockNotification(db, "full");
    expect(discreet?.title).toBe("Ordnung");
    expect(discreet?.body).toMatch(/^(\d+ overdue · )?\d+ (things? )?due this week$|^\d+ things? overdue$/);
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
  it("is off until chosen; discreet shows a count, details show what is due; saving stores both", async () => {
    const { srv, calls } = useMockApi();
    const user = userEvent.setup();
    const card = await openDesktopCard();
    const modes = within(card).getByRole("radiogroup", { name: "What the desktop notification shows" });
    expect(within(modes).getByRole("radio", { name: "Off" })).toBeChecked();
    expect(within(card).queryByLabelText("Show it from")).not.toBeInTheDocument();

    await user.click(within(modes).getByRole("radio", { name: "Discreet" }));
    expect(within(card).getByText(/no names or amounts/)).toBeInTheDocument();
    const preview = await within(card).findByRole("figure");
    await waitFor(() => expect(preview).toHaveTextContent(/Ordnung.*due this week/));
    expect(preview).not.toHaveTextContent("€");
    expect(within(card).getByLabelText("Show it from")).toHaveValue("08:00");

    await user.click(within(modes).getByRole("radio", { name: "With details" }));
    await waitFor(() => expect(within(card).getByRole("figure")).toHaveTextContent(/Ordnung · .*due this week/));
    expect(within(card).getByText(/Anyone who can see your screen can read it/)).toBeInTheDocument();

    const time = within(card).getByLabelText("Show it from");
    await user.clear(time);
    await user.type(time, "07:30");
    await user.click(within(card).getByRole("button", { name: "Save changes" }));
    expect(await within(card).findByText("Saved.")).toBeInTheDocument();
    expect(calls.find((c) => c.method === "PUT" && c.path === "/settings")?.body).toEqual({ desktop_notifications: "full", desktop_notify_time: "07:30" });
    expect(srv.db.state.settings.desktop_notifications).toBe("full");
  });

  it("won't save an empty time", async () => {
    const { calls } = useMockApi();
    const user = userEvent.setup();
    const card = await openDesktopCard();
    await user.click(within(card).getByRole("radio", { name: "Discreet" }));
    await user.clear(within(card).getByLabelText("Show it from"));
    await user.click(within(card).getByRole("button", { name: "Save changes" }));
    expect(within(card).getByText("Choose a time, like 08:00")).toBeInTheDocument();
    expect(calls.some((c) => c.method === "PUT")).toBe(false);
  });

  it("shows a test notification in the chosen mode and says so", async () => {
    const { calls } = useMockApi();
    const user = userEvent.setup();
    const card = await openDesktopCard();
    await user.click(within(card).getByRole("radio", { name: "With details" }));
    await user.click(await within(card).findByRole("button", { name: "Show a test notification" }));
    expect(await screen.findByText("Test notification sent")).toBeInTheDocument();
    expect(calls.find((c) => c.path === "/reminders/desktop/test")?.body).toEqual({ mode: "full" });
    expect(within(card).getByText("Shown with notify-send")).toBeInTheDocument();
  });

  it("explains how to start Ordnung at login", async () => {
    useMockApi();
    const card = await openDesktopCard();
    expect(within(card).getByRole("heading", { name: "Start Ordnung when you log in" })).toBeInTheDocument();
    expect(await within(card).findByText("Off")).toBeInTheDocument();
    expect(within(card).getByRole("button", { name: "Copy command to start Ordnung when you log in: ordnung autostart enable" })).toBeInTheDocument();
  });

  const useAutostartApi = (pointsHere: boolean) => {
    const { srv } = useMockApi();
    const handle = srv.handle.bind(srv);
    const autostart = { enabled: true, kind: "systemd user service", path: "/home/sam/.config/systemd/user/ordnung.service", points_here: pointsHere, command: "ordnung autostart enable" };
    srv.handle = async (method, path, query, body, signal) => {
      const res = await handle(method, path, query, body, signal);
      if (method !== "GET" || path !== "/reminders/desktop") return res;
      const json = (await res.json()) as DesktopReminders;
      return new Response(JSON.stringify({ ...json, autostart }), { status: 200, headers: { "Content-Type": "application/json" } });
    };
  };

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
    expect(first).toHaveAccessibleDescription(/Use at least 12 characters/);
    await user.type(first, "a long enough one");
    await user.type(within(dialog).getByLabelText("Repeat the passphrase"), "a long enough 0ne");
    await user.click(within(dialog).getByRole("button", { name: "Download backup" }));
    expect(within(dialog).getByLabelText("Repeat the passphrase")).toHaveAccessibleDescription("The two passphrases differ.");
    expect(calls.some((c) => c.path === "/backup" && c.method === "POST")).toBe(false);

    await user.click(within(dialog).getByRole("button", { name: "Suggest a strong one" }));
    expect(first).toHaveAttribute("type", "text");
    const suggested = (first as HTMLInputElement).value;
    expect(suggested).toMatch(/^[a-z2-9]{5}(-[a-z2-9]{5}){3}$/);
    expect(within(dialog).getByLabelText("Repeat the passphrase")).toHaveValue(suggested);
    expect(first).toHaveAccessibleDescription(/Save this passphrase in your password manager/);

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
    await user.type(within(dialog).getByLabelText("Passphrase"), "a long enough one");
    await user.type(within(dialog).getByLabelText("Repeat the passphrase"), "a long enough one");
    // (Enter submits too — the footer button belongs to the form; user-event can't see that, e2e does)
    await user.click(within(dialog).getByRole("button", { name: "Download backup" }));
    await waitFor(() => expect(within(dialog).getByLabelText("Passphrase")).toHaveAccessibleDescription("Use a passphrase of at most 1024 characters."));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("in the online demo it explains that there is nothing to back up", async () => {
    vi.stubEnv("VITE_STATIC_DEMO", "1");
    useMockApi({ staticDemo: true });
    const card = await openBackupCard();
    expect(within(card).getByRole("note")).toHaveTextContent("Not available in the online demo");
    expect(within(card).getByRole("button", { name: "Download encrypted backup…" })).toBeDisabled();
  });
});
