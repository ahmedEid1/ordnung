/**
 * Reminders that reach you while Ordnung is closed and the encrypted backup: Settings → Reminders →
 * "Desktop notification each morning" (its modes, the preview, the test, start at login, the app-menu
 * shortcut, no tool),
 * Settings → Calendar → "Sync with your own calendar" (CalDAV: the demo's refusal, the form, its
 * errors, the calendars found, connected, paused, no password store, disconnecting) and Settings →
 * Data → "Encrypted backup" (the passphrase dialog, its errors, a suggested passphrase, the
 * download). What depends on this computer (the notification tool, an autostart entry, the app-menu
 * shortcut, the password store, a calendar server) is answered by the audit, so every capture looks the same
 * wherever it runs. Loading, error and busy states are captured too (an error waits for its text:
 * a 5xx answer is retried twice first).
 */
import { failApi, fakeApi, holdApi, pinToasts, settle } from "../browser.mjs";
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
      discreet: { title: "Ordnung", body: "1 due today · 1 overdue · 3 more this week" },
      full: {
        title: "Ordnung · 1 due today · 1 overdue · 3 more this week",
        body:
          "Object to contribution notice (Widerspruch) today · Return overdue library items — overdue · " +
          "Monatliche Abbuchung Deutschlandticket €63 by Wed · and 2 more",
      },
    },
    last_shown_on: null,
    last_failure: null,
    last_failure_on: null,
    demo: false,
    autostart: {
      enabled: false,
      kind: "systemd user service",
      path: "/home/sam/.config/systemd/user/ordnung.service",
      points_here: false,
      command: "ordnung autostart enable --data-dir /home/samantha-rivera-musterfrau/Dokumente/Ordnung-Unterlagen",
    },
    shortcut: {
      added: false,
      kind: "app menu entry",
      path: "/home/sam/.local/share/applications/ordnung.desktop",
      points_here: false,
      current: false,
      foreign: false,
      command: "ordnung shortcut --data-dir /home/samantha-rivera-musterfrau/Dokumente/Ordnung-Unterlagen",
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
    last_sync: { at: new Date(Date.now() - 4 * 60_000).toISOString(), sent: 2, removed: 1, unchanged: 21, failed: 0, missing: 0, error: null, error_kind: null },
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
    id: "reminders-desktop-shortcut-added",
    route: REMINDERS,
    how: "open Settings → Reminders with Ordnung in the Start menu for this folder (a long Windows path, answered by the audit)",
    description: "Open Ordnung from your Start menu: the Added badge and where the shortcut is (a long path wraps).",
    run: (c) =>
      openDesktop(
        c,
        desktopStatus({
          system: "windows",
          tool: "powershell",
          shortcut: {
            added: true,
            kind: "Start menu shortcut",
            path: "C:\\Users\\samantha-rivera-musterfrau\\AppData\\Roaming\\Microsoft\\Windows\\Start Menu\\Programs\\Ordnung.lnk",
            points_here: true,
            current: true,
            foreign: false,
            command: "ordnung shortcut",
          },
        }),
      ),
  });
  add({
    id: "reminders-desktop-shortcut-other",
    route: REMINDERS,
    how: "open Settings → Reminders with the app-menu shortcut set up for another data folder (answered by the audit)",
    description: "The app-menu shortcut opens another folder: the warning badge, what to do and the command.",
    run: (c) => openDesktop(c, desktopStatus({ shortcut: { ...desktopStatus().shortcut, added: true, points_here: false } })),
  });
  add({
    id: "reminders-desktop-shortcut-stale",
    route: REMINDERS,
    how: "open Settings → Reminders with the app-menu shortcut running another installation of Ordnung (answered by the audit)",
    description: "The app-menu shortcut needs updating: the warning badge, what to do and the command.",
    run: (c) => openDesktop(c, desktopStatus({ shortcut: { ...desktopStatus().shortcut, added: true, points_here: true, current: false } })),
  });
  add({
    id: "reminders-desktop-shortcut-foreign",
    route: REMINDERS,
    how: "open Settings → Reminders with an app-menu entry in place that `ordnung shortcut` didn't write (answered by the audit)",
    description: "A launcher Ordnung didn't write is in the way: the warning, its path (it wraps) and the command for afterwards.",
    run: (c) => openDesktop(c, desktopStatus({ shortcut: { ...desktopStatus().shortcut, foreign: true } })),
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
        json: { detail: "Couldn't reach caldav.icloud.com.", code: "network" },
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
      // "Show all 31 events (3 overdue)": the count of overdue ones may follow
      await c.click(box.getByRole("button", { name: /^Show all \d+ events/ }));
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
          unavailable:
            "Calendar sync keeps your app password in this computer's password store, and this installation of Ordnung is missing the package for that.",
          install_command: "pipx inject ordnung keyring",
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
    id: "calendar-sync-missing-put-back",
    route: CALENDAR,
    how: "open Settings → Calendar, connected; the last sync put back events deleted from the calendar (answered by the audit)",
    description: "The last sync sent back events that had gone missing from the calendar (deleted there, or by another Ordnung).",
    run: async (c) => {
      const at = new Date(Date.now() - 60_000).toISOString();
      const box = await openSync(c, connectedStatus({ last_sync: { at, sent: 12, removed: 0, unchanged: 11, failed: 0, missing: 12, error: null, error_kind: null } }));
      await c.centre(box.getByRole("button", { name: "Sync now" }));
    },
  });
  add({
    id: "calendar-sync-restored",
    route: CALENDAR,
    how: "open Settings → Calendar in a copy restored from a backup: connected, no password here yet, waiting (answered by the audit)",
    description: "A restored copy's calendar sync waits for the app password: nothing sent, the field to enter it.",
    run: async (c) => {
      const box = await openSync(c, connectedStatus({ password_saved: false, paused: true, synced: 0, last_sync: null }));
      await c.centre(box.getByLabel("App password"));
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
    id: "data-backup-dialog-left-out",
    route: DATA,
    how: "open the backup dialog while the originals' folder is a link to another drive (GET /api/backup answered by the audit)",
    description: "The backup dialog names what it leaves out: links are never followed.",
    run: async (c) => {
      await fakeApi(c.page, "GET", /^\/api\/backup$/, async () => ({
        json: {
          letters: 22,
          files: 0,
          bytes: 2_400_000,
          file_name: "ordnung-backup-2026-09-28.ordnung-backup",
          left_out: ["files", "drafts/Briefe-an-die-Krankenversicherung-Widerspruchsverfahren-2026"],
          min_passphrase: 12,
          format_version: 1,
        },
      }));
      await openBackupDialog(c);
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
      const confirmation = backupCard(c).getByText(/^Downloaded/).first();
      await confirmation.waitFor({ timeout: 10_000 }).catch(() => c.note("no download confirmation"));
      await c.centre(confirmation);
    },
  });

  // ---- loading, error and busy states, and what the round-1 review asked to see ----
  add({
    id: "reminders-desktop-loading",
    route: REMINDERS,
    how: "switch the morning notification on while GET /api/reminders/desktop is held by the audit",
    description: "The preview while today's notification loads (skeleton).",
    run: async (c) => {
      await holdApi(c.page, { only: ["/api/reminders/desktop"], except: [] });
      await c.goto(REMINDERS, { idle: false });
      const box = await c.visible(desktopCard(c));
      await box.getByRole("switch", { name: SWITCH }).click();
      await settle(c.page, { idle: false });
      await c.centre(box.getByText("Today it would say"));
    },
  });
  add({
    id: "reminders-desktop-error",
    route: REMINDERS,
    how: "switch the morning notification on (GET /api/reminders/desktop answered 500 by the audit)",
    description: "Today's notification couldn't be loaded: the shared load error in the preview's place.",
    run: async (c) => {
      await failApi(c.page, { status: 500, only: ["/api/reminders/desktop"], except: [] });
      await c.goto(REMINDERS);
      const box = await c.visible(desktopCard(c));
      await c.click(box.getByRole("switch", { name: SWITCH }));
      const error = box.getByText("Couldn't load today's notification");
      await error.waitFor({ timeout: 20_000 }).catch(() => c.note("no load error"));
      await c.centre(error);
    },
  });
  add({
    id: "reminders-desktop-last-failure",
    route: REMINDERS,
    how: "switch it on; the last notification couldn't be shown (answered by the audit)",
    description: "Why the last notification wasn't shown, under the test button.",
    run: (c) =>
      openDesktop(
        c,
        desktopStatus({ last_failure: "notify-send failed (exit code 1): GDBus.Error:org.freedesktop.DBus.Error.ServiceUnknown", last_failure_on: "2026-09-28" }),
        "Discreet",
      ),
  });
  add({
    id: "reminders-desktop-demo",
    route: REMINDERS,
    how: "open Settings → Reminders in the demo, switch it on (the demo's own answer)",
    description: "The demo: it doesn't notify on its own (the test or the preview shows what it would say) and offers no start-at-login command.",
    run: async (c) => {
      await c.goto(REMINDERS);
      const box = await c.visible(desktopCard(c));
      await c.click(box.getByRole("switch", { name: SWITCH }));
      await c.page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
      await settle(c.page);
    },
  });
  add({
    id: "reminders-desktop-demo-saved",
    route: REMINDERS,
    how: "in the demo, switch it on and Save (PUT /api/settings answered by the audit)",
    description: "The save note in the demo: saved, but the demo doesn't notify on its own.",
    run: async (c) => {
      const current = await c.api.get("/api/settings");
      await fakeApi(c.page, "PUT", /^\/api\/settings$/, async (req) => ({ json: { ...current, ...(req.postDataJSON() ?? {}) } }));
      await c.goto(REMINDERS);
      const box = await c.visible(desktopCard(c));
      await c.click(box.getByRole("switch", { name: SWITCH }));
      await c.click(box.getByRole("button", { name: /^Save/ }));
      await box.getByText(/doesn't notify on its own — the preview/).first().waitFor({ timeout: 5_000 }).catch(() => c.note("no save note"));
      await c.page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
      await settle(c.page);
    },
  });
  add({
    id: "calendar-sync-loading",
    route: CALENDAR,
    how: "open Settings → Calendar while GET /api/calendar/sync is held by the audit",
    description: "Calendar sync while its status loads (skeleton).",
    run: async (c) => {
      await holdApi(c.page, { only: ["/api/calendar/sync"], except: [] });
      await c.goto(CALENDAR, { idle: false });
      await c.centre(await c.visible(syncCard(c)));
    },
  });
  add({
    id: "calendar-sync-error",
    route: CALENDAR,
    how: "open Settings → Calendar (GET /api/calendar/sync answered 500 by the audit)",
    description: "Calendar sync couldn't be loaded: the shared load error.",
    run: async (c) => {
      await failApi(c.page, { status: 500, only: ["/api/calendar/sync"], except: [] });
      await c.goto(CALENDAR);
      const error = syncCard(c).getByText("Couldn't load calendar sync");
      await error.waitFor({ timeout: 20_000 }).catch(() => c.note("no load error"));
      await c.centre(await c.visible(syncCard(c)));
    },
  });
  add({
    id: "calendar-sync-preview-error",
    route: CALENDAR,
    how: "calendar sync available (GET /api/calendar/sync/preview answered 500 by the audit)",
    description: "The preview couldn't be loaded: the shared load error under “What your calendar gets”.",
    run: async (c) => {
      await failApi(c.page, { status: 500, only: ["/api/calendar/sync/preview"], except: [] });
      const box = await openSync(c);
      const error = box.getByText("Couldn't load the preview");
      await error.waitFor({ timeout: 20_000 }).catch(() => c.note("no load error"));
      await c.centre(error);
    },
  });
  add({
    id: "calendar-sync-discovering",
    route: CALENDAR,
    how: "“Find my calendars” while POST /api/calendar/sync/discover is held by the audit",
    description: "Finding calendars: the fields read-only (focus kept), the button busy.",
    run: async (c) => {
      await holdApi(c.page, { only: ["/api/calendar/sync/discover"], except: [] });
      const box = await openSync(c);
      await fillAccount(c, box);
      await box.getByRole("button", { name: "Find my calendars" }).click();
      await settle(c.page, { idle: false });
      await c.centre(box.getByRole("button", { name: "Find my calendars" }));
    },
  });
  add({
    id: "calendar-sync-one-found",
    route: CALENDAR,
    how: "“Find my calendars” (one calendar, not named Ordnung, answered by the audit)",
    description: "One calendar found: the footer names it, focus on its choice, the tip about a calendar of its own.",
    run: async (c) => {
      await fakeApi(c.page, "POST", /^\/api\/calendar\/sync\/discover$/, async () => ({ json: { calendars: [{ url: ICLOUD, name: "Privat — Familie und Arzttermine" }] } }));
      const box = await openSync(c);
      await fillAccount(c, box);
      await c.click(box.getByRole("button", { name: "Find my calendars" }));
      await c.centre(box.getByRole("button", { name: "Connect and sync" }));
    },
  });
  add({
    id: "calendar-sync-connected-toast",
    route: CALENDAR,
    how: "“Find my calendars”, then “Connect and sync” (answered by the audit)",
    description: "Just connected: the toast, and focus on the “Connected to …” line.",
    pinToasts: true,
    run: async (c) => {
      let connected = false;
      const done = () => connectedStatus({ calendar_name: "Ordnung", last_sync: { at: new Date().toISOString(), sent: 23, removed: 0, unchanged: 0, failed: 0, error: null, error_kind: null } });
      await fakeApi(c.page, "POST", /^\/api\/calendar\/sync\/discover$/, async () => ({ json: { calendars: [{ url: ICLOUD, name: "Ordnung" }] } }));
      await fakeApi(c.page, "PUT", /^\/api\/calendar\/sync$/, async () => {
        connected = true;
        return { json: done() };
      });
      await fakeApi(c.page, "GET", /^\/api\/calendar\/sync$/, async () => ({ json: connected ? done() : syncStatus() }));
      await c.goto(CALENDAR);
      const box = await c.visible(syncCard(c));
      await fillAccount(c, box);
      await c.click(box.getByRole("button", { name: "Find my calendars" }));
      await c.click(box.getByRole("button", { name: "Connect and sync" }));
      await syncCard(c).getByText("Connected to Ordnung").waitFor({ timeout: 10_000 }).catch(() => c.note("not connected"));
      await pinToasts(c.page);
    },
  });
  add({
    id: "calendar-sync-no-password",
    route: CALENDAR,
    how: "open Settings → Calendar, connected, the app password not on this computer (answered by the audit)",
    description: "Connected but the password isn't saved here: its field; “Sync now” off.",
    run: async (c) => {
      const box = await openSync(c, connectedStatus({ password_saved: false }));
      await c.centre(box.getByLabel("App password"));
    },
  });
  add({
    id: "calendar-sync-last-error",
    route: CALENDAR,
    how: "open Settings → Calendar, connected, the last sync couldn't reach the server (answered by the audit)",
    description: "The last sync's error (the tick tries again), not paused.",
    run: async (c) => {
      const box = await openSync(
        c,
        connectedStatus({
          last_sync: { at: new Date(Date.now() - 2 * 3600_000).toISOString(), sent: 3, removed: 0, unchanged: 18, failed: 2, error: "Couldn't reach p142-caldav.icloud.com. Ordnung tries again later.", error_kind: "network" },
        }),
      );
      await c.centre(box.getByRole("button", { name: "Sync now" }));
    },
  });
  add({
    id: "calendar-sync-now-toast",
    route: CALENDAR,
    how: "connected, “Sync now” (answered by the audit)",
    description: "The toast after “Sync now”.",
    pinToasts: true,
    run: async (c) => {
      await fakeApi(c.page, "POST", /^\/api\/calendar\/sync\/run$/, async () => ({
        json: connectedStatus({ last_sync: { at: new Date().toISOString(), sent: 0, removed: 0, unchanged: 23, failed: 0, error: null, error_kind: null } }),
      }));
      const box = await openSync(c, connectedStatus());
      await c.click(box.getByRole("button", { name: "Sync now" }));
      await pinToasts(c.page);
    },
  });
  add({
    id: "calendar-sync-disconnect-error",
    route: CALENDAR,
    how: "connected, “Disconnect…”, Disconnect (POST /api/calendar/sync/disconnect answered 502 by the audit)",
    description: "The disconnect dialog's error: the events couldn't be removed (no promise to retry).",
    run: async (c) => {
      await fakeApi(c.page, "POST", /^\/api\/calendar\/sync\/disconnect$/, async () => ({
        status: 502,
        json: { detail: "Couldn't reach p142-caldav.icloud.com.", code: "network" },
      }));
      const box = await openSync(c, connectedStatus());
      await c.click(box.getByRole("button", { name: "Disconnect…" }));
      const dialog = await c.visible(c.page.getByRole("dialog"));
      await c.click(dialog.getByRole("button", { name: "Disconnect" }));
      await dialog.getByText("The events couldn't be removed").waitFor({ timeout: 10_000 }).catch(() => c.note("no error"));
    },
  });
  add({
    id: "calendar-sync-unavailable",
    route: CALENDAR,
    how: "open Settings → Calendar on a computer without a password store (answered by the audit)",
    description: "No usable password store (and nothing to install): why calendar sync can't be used.",
    run: async (c) => {
      const box = await openSync(
        c,
        syncStatus({ available: false, unavailable: "This computer has no password store Ordnung can use (on Linux: GNOME Keyring or KWallet, unlocked), so it can't keep the app password safely." }),
      );
      await c.centre(box);
    },
  });
  add({
    id: "calendar-file-synced",
    route: CALENDAR,
    how: "open Settings → Calendar, connected (answered by the audit)",
    description: "The calendar file's card says the dates already go to the connected calendar.",
    run: async (c) => {
      await openSync(c, connectedStatus());
      await c.page.evaluate(() => window.scrollTo(0, 0));
      await c.centre(inMain(c.page).getByText(/Your dates already go to/));
    },
  });
  add({
    id: "calendar-sync-show-fewer",
    route: CALENDAR,
    how: "calendar sync available, “Show all … events”, then “Show fewer”",
    description: "After collapsing the preview: its toggle (focused) back in view, clear of the top bar.",
    run: async (c) => {
      const box = await openSync(c);
      await c.click(box.getByRole("button", { name: /^Show all \d+ events/ }));
      await c.click(box.getByRole("button", { name: "Show fewer" }));
      await settle(c.page);
    },
  });
  add({
    id: "data-backup-loading",
    route: DATA,
    how: "open Settings → Data while GET /api/backup is held by the audit",
    description: "The backup card while what it would hold loads.",
    run: async (c) => {
      await holdApi(c.page, { only: ["/api/backup"], except: [] });
      await c.goto(DATA, { idle: false });
      await c.centre(await c.visible(backupCard(c)));
    },
  });
  add({
    id: "data-backup-info-error",
    route: DATA,
    how: "open Settings → Data (GET /api/backup answered 500 by the audit)",
    description: "What the backup would hold couldn't be loaded: the shared load error (the download still offered).",
    run: async (c) => {
      await failApi(c.page, { status: 500, only: ["/api/backup"], method: "GET", except: [] });
      await c.goto(DATA);
      const error = backupCard(c).getByText("Couldn't load what the backup would hold");
      await error.waitFor({ timeout: 20_000 }).catch(() => c.note("no load error"));
      await c.centre(await c.visible(backupCard(c)));
    },
  });
  add({
    id: "data-backup-busy",
    route: DATA,
    how: "backup dialog, a suggested passphrase, Download (POST /api/backup held by the audit)",
    description: "The backup dialog while it encrypts: “Stop” has the focus, the fields read-only.",
    run: async (c) => {
      await c.page.route(
        (url) => new URL(url.href).pathname === "/api/backup",
        async (route) => {
          if (route.request().method() !== "POST") return route.fallback();
          await new Promise(() => {});
        },
      );
      const dialog = await openBackupDialog(c);
      await c.click(dialog.getByRole("button", { name: "Suggest a strong one" }));
      await dialog.getByRole("button", { name: "Download backup" }).click();
      await settle(c.page, { idle: false });
    },
  });
  add({
    id: "data-backup-dialog-copied",
    route: DATA,
    how: "backup dialog, “Suggest a strong one”, “Copy passphrase”",
    description: "A suggested passphrase copied (a password manager won't offer to save a shown one).",
    run: async (c) => {
      const dialog = await openBackupDialog(c);
      await c.click(dialog.getByRole("button", { name: "Suggest a strong one" }));
      await c.click(dialog.getByRole("button", { name: "Copy passphrase" }));
    },
  });
  add({
    id: "data-backup-dialog-long",
    route: DATA,
    how: "backup dialog, a long passphrase typed twice, shown",
    description: "A long shown passphrase wraps in its field's width.",
    run: async (c) => {
      const dialog = await openBackupDialog(c);
      const long = "Donaudampfschifffahrtsgesellschaftskapitänsmützenabzeichen-und-Straßenbahnhaltestelle-2026";
      await c.type(dialog.getByLabel("Passphrase", { exact: true }), long);
      await c.type(dialog.getByLabel("Repeat the passphrase"), long);
      await c.click(dialog.getByRole("button", { name: "Show passphrase" }));
    },
  });
  return S;
}

/**
 * The fresh target (your own Ordnung, not the demo): "Delete everything" with a calendar connected
 * and the backup it offers first.
 */
export function freshRemindersBackupStates({ group = "settings", prefix = "fresh-settings" } = {}) {
  const S = [];
  const add = (s) => S.push({ group, ...s, id: `${prefix}-${s.id}` });
  const openDelete = async (c) => {
    await c.goto(DATA);
    await c.click(inMain(c.page).getByRole("button", { name: "Delete everything…" }));
    return c.visible(c.page.getByRole("dialog", { name: "Delete everything?" }));
  };
  add({
    id: "data-delete-calendar",
    route: DATA,
    how: "open Settings → Data, “Delete everything…”, with a calendar connected (GET /api/calendar/sync answered by the audit)",
    description: "The delete dialog: an encrypted backup first, and the connected calendar's events removed first.",
    run: async (c) => {
      await fakeApi(c.page, "GET", /^\/api\/calendar\/sync$/, async () => ({ json: connectedStatus() }));
      await openDelete(c);
    },
  });
  add({
    id: "data-delete-calendar-refused",
    route: DATA,
    how: "“Delete everything…” with a calendar connected, DELETE typed (DELETE /api/data answered 409 by the audit)",
    description: "The calendar's events couldn't be removed, so nothing was deleted: what to do instead.",
    run: async (c) => {
      await fakeApi(c.page, "GET", /^\/api\/calendar\/sync$/, async () => ({ json: connectedStatus() }));
      await fakeApi(c.page, "DELETE", /^\/api\/data$/, async () => ({
        status: 409,
        json: {
          detail:
            "Ordnung's events in your calendar “Ordnung — Fristen und Termine” couldn't be removed, so nothing was deleted: Couldn't reach p142-caldav.icloud.com. Try again — or disconnect the calendar in Settings → Calendar first (you can leave its events there), then delete everything.",
        },
      }));
      const dialog = await openDelete(c);
      await c.type(dialog.getByLabel(/to confirm/), "DELETE");
      await c.click(dialog.getByRole("button", { name: "Delete everything" }));
      await dialog.getByText(/nothing was deleted/).waitFor({ timeout: 10_000 }).catch(() => c.note("no refusal"));
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
  add("settings-sync", "/settings?section=computers", "Static demo: hand-off sync (Your computers: the online demo keeps nothing on your computer, so there's nothing to hand over).", async (c) => {
    await c.centre(await c.visible(card(c, "Use Ordnung on more than one computer")));
  });
}
