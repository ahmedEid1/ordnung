/**
 * The zero-install static demo (`VITE_STATIC_DEMO=1`, mock data, hash routes such as `#/timeline`):
 * the main routes, a few letters and drafts, an answered question, and what the online demo says
 * when something needs the real app. The ids come from the mock data in `src/mocks/data`.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { settle } from "../browser.mjs";
import { inMain } from "../steps.mjs";
import { numbersAndWeekStaticPaths } from "./numbers-week.mjs";

const G = "static-demo";

function mockIds(webDir, file, prefix) {
  const src = readFileSync(join(webDir, "src", "mocks", "data", file), "utf8");
  return [...src.matchAll(new RegExp(`id: "(${prefix}_[a-z0-9_]+)"`, "g"))].map((m) => m[1]);
}

export async function staticCatalog({ webDir }) {
  const docIds = mockIds(webDir, "documents.ts", "doc");
  const draftIds = mockIds(webDir, "drafts.ts", "drf");
  const pick = (id) => docIds.includes(id);
  const S = [];
  const add = (id, path, description, run) =>
    S.push({ id: `static-${id}`, group: G, route: `#${path}`, how: `open /#${path}${run ? ", then as described" : ""}`, description, run: async (c) => (await c.goto(path), run && run(c)) });

  add("today", "/", "Static demo: Today (the tour card as a visitor sees it).");
  add("inbox", "/inbox", "Static demo: Inbox.");
  add("timeline", "/timeline", "Static demo: Timeline.");
  add("contracts", "/contracts", "Static demo: Contracts.");
  add("letters", "/letters", "Static demo: Letters.");
  add("ask", "/ask", "Static demo: Ask.");
  add("settings", "/settings", "Static demo: Settings → Profile.");
  add("settings-privacy", "/settings?section=privacy", "Static demo: Settings → Privacy & AI usage.");
  for (const [id, path, description] of numbersAndWeekStaticPaths()) add(id, path, description);
  add("not-found", "/no-such-page", "Static demo: unknown route.");
  add("welcome", "/welcome", "Static demo: the onboarding wizard.");
  for (const id of ["doc_lease", "doc_nebenkosten", "doc_passport", "doc_tm_dunning"].filter(pick)) {
    add(id.replace(/_/g, "-"), `/documents/${id}`, `Static demo: letter ${id}.`);
  }
  // New-mail letters only exist once opened from the tray (the mock database lives in the page)
  const trayDocs = [...readFileSync(join(webDir, "src", "mocks", "data", "system.ts"), "utf8").matchAll(/id: "(mail_[a-z_]+)", filename: "[^"]*", sender: "([^"]+)"/g)];
  for (const [, id, sender] of trayDocs) {
    add(`mail-${id.replace(/^mail_/, "")}`, "/inbox", `Static demo: the New-mail letter from ${sender}, read from the tray.`, async (c) => {
      const env = c.page.getByRole("region", { name: /^New mail/ }).getByRole("listitem").filter({ hasText: sender }).first();
      await c.click(env.getByRole("button", { name: "Let Ordnung read it" }), { settleAfter: false });
      await c.page.waitForURL(/\/documents\//, { timeout: 60_000 });
      await settle(c.page);
    });
  }
  if (pick("doc_tax")) add("doc-link-before-opening", "/documents/doc_tax", "Static demo: a link to a New-mail letter that hasn't been opened yet.");
  for (const id of draftIds.slice(0, 2)) add(id.replace(/_/g, "-"), `/letters/${id}`, `Static demo: draft ${id}.`);
  add("ask-answer", "/ask", "Static demo: a suggested question answered from the mock data.", async (c) => {
    await c.click(c.page.getByRole("list", { name: "Suggested questions" }).getByRole("button").first(), { settleAfter: false });
    await c.page.getByRole("main").getByRole("status").filter({ hasText: /Answer ready|could not be completed|Stopped/ }).waitFor({ timeout: 60_000 });
    const trace = inMain(c.page).getByRole("button", { name: /^Looked at \d+ things?/ });
    if (await c.exists(trace)) await c.click(trace.last());
    await settle(c.page);
  });
  add("dev-ui", "/dev/ui", "Static demo: the design-system gallery with its mock examples.");
  add("dev-ui-popover", "/dev/ui", "Static demo: gallery receipt popover (“Why this date? (phone contract)”).", (c) =>
    c.click(inMain(c.page).getByRole("button", { name: /Why this date\? \(phone contract\)/ })),
  );
  add("add-letter-unavailable", "/inbox", "Static demo: adding a letter → “Not available in the online demo”.", async (c) => {
    await c.addFiles([{ name: "Mietvertrag.pdf", mimeType: "application/pdf" }]);
    const dialog = c.page.getByRole("dialog");
    await c.click(dialog.getByRole("button", { name: /^Add letter|^Store privately/ }));
    await c.wait(600);
    await settle(c.page, { idle: false });
  });
  return { phases: [{ name: "static", parallel: true, states: S.map((s) => ({ ...s, pinToasts: s.id.endsWith("unavailable") })) }] };
}
