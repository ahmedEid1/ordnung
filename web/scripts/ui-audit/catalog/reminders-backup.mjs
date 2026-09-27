/**
 * Reminders that reach you while Ordnung is closed and the encrypted backup: Settings → Reminders →
 * "Desktop notification each morning" (its modes, the preview, the test, start at login, no tool)
 * and Settings → Data → "Encrypted backup" (the passphrase dialog, its errors, a suggested
 * passphrase, the download). What depends on this computer (the notification tool, an autostart
 * entry) is answered by the audit, so every capture looks the same wherever it runs.
 */
import { failApi, fakeApi, pinToasts, settle } from "../browser.mjs";
import { inMain } from "../steps.mjs";

const REMINDERS = "/settings?section=reminders";
const DATA = "/settings?section=data";

const card = (c, name) => inMain(c.page).getByRole("region", { name });
const desktopCard = (c) => card(c, "Desktop notification each morning");
const SWITCH = /Notify me each morning on this computer/;
const backupCard = (c) => card(c, "Encrypted backup");

/** A long, realistic preview (a German title that doesn't break easily) and a Linux setup. */
function desktopStatus(overrides = {}) {
  return {
    system: "linux",
    tool: "notify-send",
    missing: null,
    preview: {
      discreet: { title: "Ordnung", body: "1 overdue · 4 due this week" },
      full: {
        title: "Ordnung · 1 overdue · 4 due this week",
        body:
          "Return overdue library items — overdue · Pay outstanding invoice plus reminder fee €94.99 by tomorrow · " +
          "Monatliche Abbuchung Deutschlandticket €63 by Wed · and 2 more",
      },
    },
    last_shown_on: null,
    autostart: {
      enabled: false,
      kind: "systemd user service",
      path: "/home/sam/.config/systemd/user/ordnung.service",
      points_here: false,
      command: "ordnung autostart enable",
    },
    ...overrides,
  };
}

async function openDesktop(c, status = desktopStatus(), mode = null) {
  await fakeApi(c.page, "GET", /^\/api\/reminders\/desktop$/, async () => ({ json: status }));
  await c.goto(REMINDERS);
  const box = await c.visible(desktopCard(c));
  // switched on it starts discreet; "With details" is a second choice
  if (mode) await c.click(box.getByRole("switch", { name: SWITCH }));
  if (mode && mode !== "Discreet") await c.click(box.getByRole("radio", { name: mode }));
  // the card is the section's last: at the page's end its save bar sits where it belongs, not over
  // the card (the pinned bar over half-scrolled content is the save bar's own, audited elsewhere)
  await c.page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
  await settle(c.page);
  return box;
}

async function openBackupDialog(c) {
  await c.goto(DATA);
  const box = await c.visible(backupCard(c));
  await c.click(box.getByRole("button", { name: "Download encrypted backup…" }));
  return c.visible(c.page.getByRole("dialog", { name: "Download an encrypted backup" }));
}

/** Server-backed targets (demo, fresh): the states of both cards. */
export function remindersBackupStates({ group = "settings", prefix = "settings" } = {}) {
  const S = [];
  const add = (s) => S.push({ group, ...s, id: `${prefix}-${s.id}` });

  add({
    id: "reminders-desktop-off",
    route: REMINDERS,
    how: "open Settings → Reminders, scroll to “Desktop notification each morning” (off; GET /api/reminders/desktop answered by the audit)",
    description: "Desktop notification switched off: the switch, nothing else to choose, start at login.",
    run: (c) => openDesktop(c),
  });
  add({
    id: "reminders-desktop-discreet",
    route: REMINDERS,
    how: "open Settings → Reminders, switch the morning notification on (discreet; unsaved)",
    description: "Discreet mode: the time, the preview with a count only, the test button, the save bar.",
    run: (c) => openDesktop(c, desktopStatus(), "Discreet"),
  });
  add({
    id: "reminders-desktop-full",
    route: REMINDERS,
    how: "open Settings → Reminders, switch it on, choose “With details” (unsaved; a long preview)",
    description: "Details mode: a long preview with titles, amounts and days, the warning about screens.",
    run: (c) => openDesktop(c, desktopStatus(), "With details"),
  });
  add({
    id: "reminders-desktop-nothing-due",
    route: REMINDERS,
    how: "open Settings → Reminders, switch it on (discreet), with nothing due this week (answered by the audit)",
    description: "Discreet mode when nothing is due: the preview says there is no notification today.",
    run: (c) => openDesktop(c, desktopStatus({ preview: { discreet: null, full: null } }), "Discreet"),
  });
  add({
    id: "reminders-desktop-no-tool",
    route: REMINDERS,
    how: "open Settings → Reminders on a computer without notify-send (answered by the audit)",
    description: "No notification tool: the warning with what to install, shown before it is switched on (no test button).",
    run: (c) =>
      openDesktop(c, desktopStatus({ tool: null, missing: "No notification tool was found: install notify-send (the libnotify-bin or libnotify package)." })),
  });
  add({
    id: "reminders-desktop-autostart-on",
    route: REMINDERS,
    how: "open Settings → Reminders with start at login set up for this folder (a long macOS path, answered by the audit)",
    description: "Start at login is on: the badge and where the entry is (a long path wraps).",
    run: (c) =>
      openDesktop(
        c,
        desktopStatus({
          system: "macos",
          tool: "osascript",
          autostart: {
            enabled: true,
            kind: "LaunchAgent",
            path: "/Users/samantha-rivera-musterfrau/Library/LaunchAgents/local.ordnung.serve.plist",
            points_here: true,
            command: "ordnung autostart enable",
          },
        }),
        "Discreet",
      ),
  });
  add({
    id: "reminders-desktop-autostart-other",
    route: REMINDERS,
    how: "open Settings → Reminders with start at login set up for another data folder (answered by the audit)",
    description: "Start at login starts another folder: the warning badge and what to do.",
    run: (c) => openDesktop(c, desktopStatus({ autostart: { ...desktopStatus().autostart, enabled: true, points_here: false } })),
  });
  add({
    id: "reminders-desktop-test-toast",
    route: REMINDERS,
    how: "switch it on, choose “With details”, “Show a test notification” (answered by the audit: shown)",
    description: "The toast after a test notification was shown.",
    pinToasts: true,
    run: async (c) => {
      await fakeApi(c.page, "POST", /^\/api\/reminders\/desktop\/test$/, async () => ({
        json: { shown: true, tool: "notify-send", notification: desktopStatus().preview.full, detail: null },
      }));
      const box = await openDesktop(c, desktopStatus(), "With details");
      await c.click(box.getByRole("button", { name: "Show a test notification" }));
      await pinToasts(c.page);
    },
  });

  add({
    id: "data-backup",
    route: DATA,
    how: "open Settings → Data, scroll to “Encrypted backup”",
    description: "The encrypted backup card: what it holds now, the download, how to restore.",
    run: async (c) => {
      await c.goto(DATA);
      await c.centre(await c.visible(backupCard(c)));
    },
  });
  add({
    id: "data-backup-dialog",
    route: DATA,
    how: "open Settings → Data, “Download encrypted backup…”",
    description: "The passphrase dialog, empty.",
    run: (c) => openBackupDialog(c),
  });
  add({
    id: "data-backup-dialog-errors",
    route: DATA,
    how: "in the backup dialog type a short passphrase, Download",
    description: "The passphrase dialog with the “at least 12 characters” error.",
    run: async (c) => {
      const dialog = await openBackupDialog(c);
      await c.type(dialog.getByLabel("Passphrase", { exact: true }), "too short");
      await c.click(dialog.getByRole("button", { name: "Download backup" }));
    },
  });
  add({
    id: "data-backup-dialog-mismatch",
    route: DATA,
    how: "in the backup dialog type two different long passphrases, Download",
    description: "The passphrase dialog with “The two passphrases differ.”",
    run: async (c) => {
      const dialog = await openBackupDialog(c);
      await c.type(dialog.getByLabel("Passphrase", { exact: true }), "Straßenbahn fährt um sieben");
      await c.type(dialog.getByLabel("Repeat the passphrase"), "Strassenbahn faehrt um sieben");
      await c.click(dialog.getByRole("button", { name: "Download backup" }));
    },
  });
  add({
    id: "data-backup-dialog-suggested",
    route: DATA,
    how: "in the backup dialog, “Suggest a strong one”",
    description: "A suggested passphrase, shown, with the reminder to save it.",
    run: async (c) => {
      const dialog = await openBackupDialog(c);
      await c.click(dialog.getByRole("button", { name: "Suggest a strong one" }));
    },
  });
  add({
    id: "data-backup-server-error",
    route: DATA,
    how: "in the backup dialog, a suggested passphrase, Download (POST /api/backup answered with HTTP 500 by the audit)",
    description: "The dialog's own error when the backup couldn't be made.",
    run: async (c) => {
      await failApi(c.page, { status: 500, only: ["/api/backup"], method: "POST", except: [] });
      const dialog = await openBackupDialog(c);
      await c.click(dialog.getByRole("button", { name: "Suggest a strong one" }));
      await c.click(dialog.getByRole("button", { name: "Download backup" }));
    },
  });
  add({
    id: "data-backup-downloaded",
    route: DATA,
    how: "in the backup dialog, a suggested passphrase, Download (POST /api/backup answered with a small file by the audit)",
    description: "The card confirms the download in its footer (file name and size), focus back on its button.",
    run: async (c) => {
      await c.page.route(
        (url) => new URL(url.href).pathname === "/api/backup",
        (route) =>
          route.request().method() === "POST"
            ? route.fulfill({ status: 200, contentType: "application/octet-stream", body: Buffer.concat([Buffer.from("ORDNUNG-BACKUP\n"), Buffer.alloc(40_000)]) })
            : route.fallback(),
      );
      const dialog = await openBackupDialog(c);
      await c.click(dialog.getByRole("button", { name: "Suggest a strong one" }));
      await c.click(dialog.getByRole("button", { name: "Download backup" }));
      const status = backupCard(c).getByRole("status");
      await status.getByText(/^Downloaded/).waitFor({ timeout: 10_000 }).catch(() => c.note("no download confirmation"));
      await c.centre(status);
    },
  });
  return S;
}

/** The static demo: both cards explain that the online demo can't do this. */
export function staticRemindersBackupStates(add) {
  add("settings-reminders-desktop", "/settings?section=reminders", "Static demo: the desktop notification card (it can't notify from the online demo).", async (c) => {
    const box = await c.visible(desktopCard(c));
    await c.click(box.getByRole("switch", { name: SWITCH }));
    await c.centre(box);
  });
  add("settings-data-backup", "/settings?section=data", "Static demo: the encrypted backup card (nothing to back up in the online demo).", async (c) => {
    await c.centre(await c.visible(backupCard(c)));
  });
}
