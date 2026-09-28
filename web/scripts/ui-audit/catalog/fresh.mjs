/**
 * A first run (`ordnung serve` on an empty data folder): the onboarding wizard at every step
 * (the finishing POST is answered by the audit; the real onboarding afterwards uses `skip_ai`), then
 * every page empty. Nothing here sends anything to Claude: no letters, no questions, no "Run check".
 */
import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { fakeApi, settle } from "../browser.mjs";
import { freshPdf } from "./folder.mjs";
import { commonSettingsSections } from "./shared.mjs";
import { numbersAndWeekEmptyStates } from "./numbers-week.mjs";

const G = "onboarding-and-empty";

/** Walk the wizard to `step` (0 welcome, 1 region, 2 name & address, 3 Claude check). */
async function wizardTo(c, step, { name = "", address = "" } = {}) {
  await c.goto("/welcome");
  if (step >= 1) await c.click(c.page.getByRole("button", { name: "Get started" }));
  if (step >= 2) {
    await chooseRegion(c);
    await c.click(c.page.getByRole("button", { name: "Continue" }));
  }
  if (step === 2 && name) await c.type(c.page.getByRole("textbox", { name: /Your name/ }), name);
  if (step === 2 && address) await c.type(c.page.getByRole("textbox", { name: /Postal address/ }), address);
  if (step >= 3) await c.click(c.page.getByRole("button", { name: "Skip for now" }));
  await c.page.evaluate(() => window.scrollTo(0, 0));
  await settle(c.page);
}

/** The longest state name, and "yes" for the residence-permit question. */
async function chooseRegion(c) {
  await c.click(c.page.locator("label").filter({ has: c.page.locator("input[name=region][value=MV]") }));
  await c.click(c.page.locator("label").filter({ has: c.page.locator('input[name=permit][value="yes"]') }));
}

/**
 * This machine's Claude status as the wizard/Settings would see it on another computer: the
 * health answer is passed through with its `claude` part replaced (nothing is sent to Claude).
 */
const CLAUDE = {
  missing: { installed: false, version: null, path: null, ok: null, detail: "The claude command was not found on this computer." },
  "signed-out": { installed: true, version: "2.1.283 (Claude Code)", path: "/usr/local/bin/claude", ok: false, detail: "Claude Code is installed but not signed in. Run `claude` once and sign in." },
};
async function fakeClaude(c, variant) {
  await fakeApi(c.page, "GET", /^\/api\/health$/, async (_req, original) => ({ json: { ...original, claude: CLAUDE[variant] } }), { passthrough: true });
}

export async function freshCatalog({ api, server }) {
  const wizard = [];
  const w = (id, how, description, run, extra = {}) => wizard.push({ id: `welcome-${id}`, group: G, route: "/welcome", how, description, run, ...extra });
  w("1-welcome", "open / (redirects to /welcome)", "Onboarding step 1: welcome and privacy.", async (c) => {
    await c.goto("/");
    await c.page.waitForURL(/\/welcome/).catch(() => c.note("no redirect to /welcome"));
    await settle(c.page);
  });
  w("2-region", "“Get started”", "Onboarding step 2: where you live (nothing chosen, Continue disabled).", (c) => wizardTo(c, 1));
  w("2-region-chosen", "“Get started”, choose Mecklenburg-Vorpommern and “yes” for the permit", "Onboarding step 2 with the longest state name chosen.", async (c) => {
    await wizardTo(c, 1);
    await chooseRegion(c);
  });
  w("3-address", "… “Continue”", "Onboarding step 3: name and address (empty) with the letterhead preview.", (c) => wizardTo(c, 2));
  w(
    "3-address-filled",
    "… type a long name and a three-line address",
    "Onboarding step 3 filled in (long German street name).",
    (c) => wizardTo(c, 2, { name: "Alexandra Maria Rivera-Schneidermann", address: "Hauptbahnhofsvorplatzstraße 123a, Hinterhaus 4. OG links\n12345 Musterstadt-Mitte\nDeutschland" }),
  );
  w("4-claude", "… “Skip for now”", "Onboarding step 4: the Claude check as this computer reports it (health runs `claude --version` / `auth status` only — no tokens).", (c) => wizardTo(c, 3));
  for (const variant of Object.keys(CLAUDE)) {
    w(`4-claude-${variant}`, `… “Skip for now”, with the health check reporting Claude as ${variant} (faked)`, `Onboarding step 4 when Claude is ${variant === "missing" ? "not installed" : "installed but not signed in"}: copyable fixes, “Continue without AI”.`, async (c) => {
      await fakeClaude(c, variant);
      await wizardTo(c, 3);
    });
  }
  w(
    "5-done-without-ai",
    "… Claude missing (faked), “Continue without AI” (the POST /api/onboarding is answered by the audit)",
    "Onboarding done after skipping AI.",
    async (c) => {
      const profile = await c.api.get("/api/profile");
      await fakeClaude(c, "missing");
      await fakeApi(c.page, "POST", /^\/api\/onboarding$/, async (req) => ({ json: { ...profile, ...(req.postDataJSON()?.profile ?? {}), onboarded: true } }));
      await wizardTo(c, 3);
      await c.click(c.page.getByRole("button", { name: "Continue without AI" }));
      await settle(c.page);
    },
  );
  w(
    "5-done",
    "… “Finish setup” (or “Continue without AI”); the POST /api/onboarding is answered by the audit, so the server stays un-onboarded",
    "Onboarding done: add your first letters or explore the demo.",
    async (c) => {
      const profile = await c.api.get("/api/profile");
      await fakeApi(c.page, "POST", /^\/api\/onboarding$/, async (req) => ({ json: { ...profile, ...(req.postDataJSON()?.profile ?? {}), onboarded: true } }));
      await wizardTo(c, 3);
      const skip = c.page.getByRole("button", { name: "Continue without AI" });
      const finish = c.page.getByRole("button", { name: "Finish setup" });
      await c.click((await c.exists(skip)) ? skip : finish);
      await c.page.getByRole("heading", { level: 1 }).first().waitFor();
      await settle(c.page);
    },
  );

  const empty = [];
  const e = (id, path, description, run) => empty.push({ id, group: G, route: path, how: run ? `open ${path}, then as described` : `open ${path} after onboarding (no letters)`, description, run: async (c) => (await c.goto(path), run && run(c)) });
  e("empty-today", "/", "Today with no letters.");
  e("empty-inbox", "/inbox", "Inbox with no letters (empty state, Add letters).");
  e("empty-timeline", "/timeline", "Timeline with no dates.");
  e("empty-contracts", "/contracts", "Contracts with none known.");
  e("empty-letters", "/letters", "Letters with no drafts.");
  e("empty-waiting", "/letters/waiting", "Waiting for with nothing yet (no letter sent, no call noted).");
  e("empty-composer", "/letters?new=1", "The composer with nothing to cancel, object to or reply to.", async (c) => {
    await c.visible(c.page.getByRole("dialog"));
  });
  e("empty-composer-cancellation", "/letters?kind=cancellation", "Composer → Cancel a contract, with no contracts.", async (c) => {
    await c.visible(c.page.getByRole("dialog"));
  });
  e("empty-ask", "/ask", "Ask with no letters.");
  e("empty-search", "/", "Letter search with nothing to find.", async (c) => {
    if (c.phone) await c.click(c.page.getByRole("button", { name: "Search letters" }));
    await c.type(c.page.getByRole("combobox", { name: "Search your letters" }), "Miete", { settleAfter: false });
    await c.wait(500);
    await settle(c.page);
  });
  e("empty-not-found", "/documents/doc_does_not_exist", "A letter link that doesn't exist (deleted letter).");
  e("empty-letter-not-found", "/letters/drf_does_not_exist", "A draft link that doesn't exist.");
  for (const s of numbersAndWeekEmptyStates(G)) empty.push(s);
  for (const s of commonSettingsSections(G, "empty-settings")) empty.push(s);
  for (const variant of Object.keys(CLAUDE)) {
    empty.push({
      id: `empty-settings-claude-${variant}`,
      group: G,
      route: "/settings?section=claude",
      how: `open Settings → Claude connection with the health check reporting Claude as ${variant} (faked)`,
      description: `Settings → Claude connection when Claude is ${variant === "missing" ? "not installed" : "not signed in"}.`,
      run: async (c) => {
        await fakeClaude(c, variant);
        await c.goto("/settings?section=claude");
      },
    });
  }
  empty.push({
    id: "empty-welcome-again",
    group: G,
    route: "/welcome",
    how: "open /welcome after onboarding",
    description: "The wizard opened again by an onboarded person (values pre-filled).",
    run: (c) => c.goto("/welcome"),
  });
  empty.push({
    id: "empty-add-dialog",
    group: G,
    route: "/inbox",
    how: "open /inbox, choose one PDF (not added)",
    description: "First “Add this letter?” on an empty inbox.",
    run: async (c) => {
      await c.goto("/inbox");
      await c.addFiles([{ name: "Mietvertrag.pdf", mimeType: "application/pdf" }]);
      await c.visible(c.page.getByRole("dialog"));
    },
  });

  const onboard = () =>
    api.post("/api/onboarding", {
      profile: { region: "BE", language: "en", country: "DE", is_student_visa: false, name: "Alex Beispiel", address: "Musterstraße 1\n10115 Berlin" },
      skip_ai: true,
    });

  // last: a watched folder brings the first letters in, and they wait (nothing is sent to Claude)
  const waiting = [
    {
      id: "fresh-today-waiting",
      group: G,
      route: "/",
      how: "set a watched folder holding two scans (PUT /api/settings), wait until both wait, open /",
      description: "A first run whose folder brought two scans: Ordnung's own note says nothing is due from what was read — never “all clear” — and the waiting card.",
      run: (c) => c.goto("/"),
    },
  ];

  return {
    phases: [
      { name: "wizard", parallel: true, states: wizard },
      {
        name: "empty",
        parallel: true,
        states: empty,
        before: onboard,
      },
      {
        name: "waiting",
        parallel: true,
        states: waiting,
        before: async () => {
          await onboard(); // also when only this phase runs (`--only fresh-today-waiting`)
          const folder = `${server.dataDir}-scans`;
          rmSync(folder, { recursive: true, force: true });
          mkdirSync(folder, { recursive: true });
          writeFileSync(join(folder, "Scan_2026-09-28_0914.pdf"), freshPdf(server.webDir, "17_auslaenderbehoerde_termin.pdf", "fresh-1"));
          writeFileSync(join(folder, "Scan_2026-09-28_0915.pdf"), freshPdf(server.webDir, "08_rechnung_techmarkt.pdf", "fresh-2"));
          await api.put("/api/settings", { inbox_dir: folder });
          for (let i = 0; i < 240; i += 1) {
            if ((await api.get("/api/folder")).waiting >= 2) break;
            await new Promise((r) => setTimeout(r, 250));
          }
        },
      },
    ],
  };
}

