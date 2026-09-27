/**
 * Reminders that reach you while Ordnung is closed and the encrypted backup: Settings → Reminders →
 * "Desktop notification each morning" (its modes, the preview, the test, start at login, no tool),
 * Settings → Calendar → "Sync with your own calendar" (CalDAV: the demo's refusal, the form, its
 * errors, the calendars found, connected, paused, no password store, disconnecting) and Settings →
 * Data → "Encrypted backup" (the passphrase dialog, its errors, a suggested passphrase, the
 * download). What depends on this computer (the notification tool, an autostart entry, the
 * password store, a calendar server) is answered by the audit, so every capture looks the same
 * wherever it runs.
 */
import { failApi, fakeApi, pinToasts, settle } from "../browser.mjs";
import { inMain } from "../steps.mjs";

const REMINDERS = "/settings?section=reminders";
const DATA = "/settings?section=data";
const CALENDAR = "/settings?section=calendar";

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

const syncCard = (c) => card(c, "Sync with your own calendar");
/** A long, iCloud-like calendar address (a host and ids that don't break easily). */
const ICLOUD = "https://p142-caldav.icloud.com:443/11837429562/calendars/9F3B6E1A-4C2D-4F7B-9A1E-6D2C8B5E7F10/";

function syncStatus(overrides = {}) {
  return {
    available: true,
    unavailable: null,
    install_command: null,
    connected: false,
    url: null,
    username: null,
    calendar_name: null,
    mode: "discreet",
    password_saved: false,
    paused: false,
    events: 23,
    synced: 0,
    last_sync: null,
    ...overrides,
  };
}

function connectedStatus(overrides = {}) {
  return syncStatus({
    connected: true,
    url: ICLOUD,
    username: "samantha.rivera-musterfrau@icloud.com",
    calendar_name: "Ordnung — Fristen und Termine",
    password_saved: true,
    synced: 23,
    last_sync: { at: new Date(Date.now() - 4 * 60_000).toISOString(), sent: 2, removed: 1, unchanged: 21, failed: 0, error: null, error_kind: null },
    ...overrides,
  });
}

async function openSync(c, status = syncStatus()) {
  await fakeApi(c.page, "GET", /^\/api\/calendar\/sync$/, async () => ({ json: status }));
  await c.goto(CALENDAR);
  const box = await c.visible(syncCard(c));
  await box.getByText("What your calendar gets").waitFor({ timeout: 10_000 });
  return syncCard(c);
}

async function fillAccount(c, box, { url = "https://caldav.icloud.com", password = "abcd-efgh-ijkl-mnop" } = {}) {
  await c.type(box.getByLabel("Calendar or server address"), url);
  await c.type(box.getByLabel("User name"), "samantha.rivera-musterfrau@icloud.com");
  await c.type(box.getByLabel("App password"), password);
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
    id: "calendar-sync-demo",
    route: CALENDAR,
    how: "open Settings → Calendar, scroll to “Sync with your own calendar” (the demo's own answer)",
    description: "Calendar sync in the demo: why it can't connect, and the discreet preview of what would be sent.",
    run: async (c) => {
      await c.goto(CALENDAR);
      await c.centre(await c.visible(syncCard(c)));
    },
  });
  add({
    id: "calendar-sync-form",
    route: CALENDAR,
    how: "open Settings → Calendar with calendar sync available (GET /api/calendar/sync answered by the audit)",
    description: "Not connected: the address, user name and app password, where to find them (open), the preview.",
    run: async (c) => {
      const box = await openSync(c);
      await c.click(box.getByText("Where do I find these?"));
      await c.centre(box.getByLabel("Calendar or server address"));
    },
  });
  add({
    id: "calendar-sync-form-errors",
    route: CALENDAR,
    how: "calendar sync available, an http:// address, “Find my calendars”",
    description: "The form's own check: an unencrypted address is refused next to the field.",
    run: async (c) => {
      const box = await openSync(c);
      await fillAccount(c, box, { url: "http://nextcloud.example.org" });
      await c.click(box.getByRole("button", { name: "Find my calendars" }));
    },
  });
  add({
    id: "calendar-sync-refused",
    route: CALENDAR,
    how: "calendar sync available, “Find my calendars” (POST /api/calendar/sync/discover answered 422 auth by the audit)",
    description: "The server refused the app password: said under the password field.",
    run: async (c) => {
      await fakeApi(c.page, "POST", /^\/api\/calendar\/sync\/discover$/, async () => ({
        status: 422,
        json: { detail: "The calendar server refused the user name or app password.", code: "auth" },
      }));
      const box = await openSync(c);
      await fillAccount(c, box);
      await c.click(box.getByRole("button", { name: "Find my calendars" }));
    },
  });
  add({
    id: "calendar-sync-choose",
    route: CALENDAR,
    how: "calendar sync available, “Find my calendars” (three calendars found, answered by the audit)",
    description: "The calendars found: long names and iCloud addresses wrap; Ordnung's preselected; Connect and sync.",
    run: async (c) => {
      await fakeApi(c.page, "POST", /^\/api\/calendar\/sync\/discover$/, async () => ({
        json: {
          calendars: [
            { url: ICLOUD.replace("9F3B6E1A", "0A1B2C3D"), name: "Privat — Familie, Arzttermine und Geburtstage" },
            { url: ICLOUD, name: "Ordnung" },
            { url: ICLOUD.replace("9F3B6E1A", "77E5D4C3"), name: null },
          ],
        },
      }));
      const box = await openSync(c);
      await fillAccount(c, box);
      await c.click(box.getByRole("button", { name: "Find my calendars" }));
      await c.centre(box.getByRole("group", { name: "Which calendar should Ordnung write into?" }));
    },
  });
  add({
    id: "calendar-sync-network-error",
    route: CALENDAR,
    how: "calendar sync available, “Find my calendars” (answered 502 network by the audit)",
    description: "The calendar server couldn't be reached: the form's own error.",
    run: async (c) => {
      await fakeApi(c.page, "POST", /^\/api\/calendar\/sync\/discover$/, async () => ({
        status: 502,
        json: { detail: "Couldn't reach caldav.icloud.com. Ordnung tries again later.", code: "network" },
      }));
      const box = await openSync(c);
      await fillAccount(c, box);
      await c.click(box.getByRole("button", { name: "Find my calendars" }));
    },
  });
  add({
    id: "calendar-sync-full-preview",
    route: CALENDAR,
    how: "calendar sync available, “With details”, “Show all … events”",
    description: "Every event as it would be sent with details: titles, what to do, amounts, alarms.",
    run: async (c) => {
      const box = await openSync(c);
      await c.click(box.getByRole("radio", { name: "With details" }));
      await c.click(box.getByRole("button", { name: /^Show all \d+ events$/ }));
      await c.centre(box.getByRole("list", { name: "Events, with details" }));
    },
  });
  add({
    id: "calendar-sync-no-keyring",
    route: CALENDAR,
    how: "open Settings → Calendar without the keyring package (answered by the audit)",
    description: "No password store: what to install, as a command to copy.",
    run: async (c) => {
      const box = await openSync(
        c,
        syncStatus({
          available: false,
          unavailable: "Calendar sync keeps your app password in this computer's password store, and Ordnung needs an extra package for that.",
          install_command: "pip install 'ordnung[caldav]'",
        }),
      );
      await c.centre(box);
    },
  });
  add({
    id: "calendar-sync-connected",
    route: CALENDAR,
    how: "open Settings → Calendar, connected to an iCloud calendar (answered by the audit)",
    description: "Connected: a long calendar name and address wrap, the last sync, Sync now, Disconnect.",
    run: async (c) => {
      const box = await openSync(c, connectedStatus());
      await c.centre(box.getByRole("button", { name: "Sync now" }));
    },
  });
  add({
    id: "calendar-sync-paused",
    route: CALENDAR,
    how: "open Settings → Calendar, connected, paused after a refused password (answered by the audit)",
    description: "Paused after the server refused the password: the reason and a field for the app password.",
    run: async (c) => {
      const box = await openSync(
        c,
        connectedStatus({
          paused: true,
          last_sync: { at: new Date(Date.now() - 50 * 60_000).toISOString(), sent: 0, removed: 0, unchanged: 0, failed: 3, error: "The calendar server refused the user name or app password.", error_kind: "auth" },
        }),
      );
      await c.centre(box.getByLabel("App password"));
    },
  });
  add({
    id: "calendar-sync-mode-unsaved",
    route: CALENDAR,
    how: "connected, choose “With details” (unsaved)",
    description: "Changing what the calendar gets: the save bar.",
    run: async (c) => {
      const box = await openSync(c, connectedStatus());
      await c.click(box.getByRole("radio", { name: "With details" }));
    },
  });
  add({
    id: "calendar-sync-disconnect",
    route: CALENDAR,
    how: "connected, “Disconnect…”",
    description: "The disconnect dialog: remove Ordnung's events too (ticked).",
    run: async (c) => {
      const box = await openSync(c, connectedStatus());
      await c.click(box.getByRole("button", { name: "Disconnect…" }));
      await c.visible(c.page.getByRole("dialog"));
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
  add("settings-calendar-sync", "/settings?section=calendar", "Static demo: calendar sync (it can't reach a calendar; the preview shows what would be sent).", async (c) => {
    await c.centre(await c.visible(syncCard(c)));
  });
  add("settings-data-backup", "/settings?section=data", "Static demo: the encrypted backup card (nothing to back up in the online demo).", async (c) => {
    await c.centre(await c.visible(backupCard(c)));
  });
}
