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
import { staticRemindersBackupStates } from "./reminders-backup.mjs";

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
  add("settings-data", "/settings?section=data", "Static demo: Settings → Data (the guided tour's card: “Restart the demo tour”).");
  for (const [id, path, description, run] of numbersAndWeekStaticPaths()) add(id, path, description, run);
  staticRemindersBackupStates(add);
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
  // GiroCode (EPC-QR): a code, a photo that waits for the paper letter, the code after the check, Today's folded code
  const pay = async (c) => c.click(inMain(c.page).getByRole("article").first().getByRole("button", { name: /^Pay\b/ }));
  if (pick("doc_nebenkosten")) add("girocode-statement", "/documents/doc_nebenkosten", "Static demo: the utility statement's Pay panel with its GiroCode.", pay);
  if (pick("doc_parking")) {
    add("girocode-photo-check", "/documents/doc_parking", "Static demo: the photographed parking fine asks to compare with the paper letter first.", pay);
    add("girocode-photo-confirmed", "/documents/doc_parking", "Static demo: the parking fine's GiroCode after “These match the letter”.", async (c) => {
      await pay(c);
      await c.click(c.page.getByRole("button", { name: "These match the letter" }), { settleAfter: false });
      await c.page.getByRole("img", { name: /^GiroCode: transfer/ }).waitFor({ timeout: 30_000 });
      await settle(c.page);
    });
  }
  add("girocode-today", "/", "Static demo: Today's Pay panel with the GiroCode unfolded.", async (c) => {
    await c.click(inMain(c.page).getByRole("button", { name: /^Pay: / }).first());
    await c.click(c.page.getByRole("button", { name: "Show code" }));
  });
  if (pick("doc_parking")) {
    add("girocode-photo-mismatch", "/documents/doc_parking", "Static demo: the parking fine after “They don't match”.", async (c) => {
      await pay(c);
      await c.click(c.page.getByRole("button", { name: "They don't match" }));
    });
  }
  if (pick("doc_lease")) add("girocode-several", "/documents/doc_lease", "Static demo: the lease's Pay panel — several payments, so no code.", pay);
  if (pick("doc_tax")) add("doc-link-before-opening", "/documents/doc_tax", "Static demo: a link to a New-mail letter that hasn't been opened yet.");
  // "How this was read" (mock traces: src/mocks/data/traces.ts)
  const steps = (c) => inMain(c.page).getByRole("list", { name: "Steps of this reading" });
  if (pick("doc_parking")) {
    add("doc-parking--trace", "/documents/doc_parking?view=trace", "Static demo: How this was read — the parking fine's newest of two readings, with the reading picker.");
    add("doc-parking--trace-repair", "/documents/doc_parking?view=trace", "Static demo: the first reading, whose extraction needed a repair call (opened, linked to the call it retried).", async (c) => {
      await c.click(inMain(c.page).getByRole("radiogroup", { name: "Reading" }).getByRole("radio").first());
      await c.visible(steps(c).getByRole("button", { name: /^Claude, asked again/ }));
      await c.click(steps(c).getByRole("button", { name: /^Claude, asked again/ }));
    });
    add("doc-parking--trace-date", "/documents/doc_parking?view=trace", "Static demo: a date's step opened — the DateSpec, the dates, the rules and its “Why this date?” receipt.", async (c) => {
      await c.click(steps(c).getByRole("button", { name: /^Dates computed/ }));
      await c.click(inMain(c.page).getByRole("list", { name: /^Steps of “Dates computed”/ }).getByRole("button").first());
    });
    add("doc-parking--trace-compare", "/documents/doc_parking?view=trace", "Static demo: what the second reading decided differently from the first.", async (c) => {
      await c.click(inMain(c.page).getByRole("button", { name: /^Compare with reading/ }));
      await c.visible(inMain(c.page).getByRole("heading", { name: /decided differently/ }));
    });
  }
  if (pick("doc_passport")) {
    add("doc-passport--trace", "/documents/doc_passport?view=trace", "Static demo: How this was read for a phone photo (the page transcribed by Claude).");
    add("doc-passport--trace-quote", "/documents/doc_passport?view=trace", "Static demo: a photo's quote opened — its numbers found only in Claude's transcript.", async (c) => {
      await c.click(steps(c).getByRole("button", { name: /^Quotes checked on the page/ }));
      await c.click(inMain(c.page).getByRole("list", { name: /^Steps of “Quotes checked on the page”/ }).getByRole("button").first());
    });
  }
  if (pick("doc_nebenkosten")) {
    add("doc-nebenkosten--trace-open", "/documents/doc_nebenkosten?view=trace", "Static demo: a text PDF's steps with the quotes, the dates and the links opened.", async (c) => {
      for (const name of [/^Quotes checked on the page/, /^Dates computed/, /^Thread, contract & payment/]) await c.click(steps(c).getByRole("button", { name }).first());
    });
  }
  for (const id of draftIds.slice(0, 2)) add(id.replace(/_/g, "-"), `/letters/${id}`, `Static demo: draft ${id}.`);
  add("ask-answer", "/ask", "Static demo: a suggested question answered from the mock data.", async (c) => {
    await c.click(c.page.getByRole("list", { name: "Suggested questions" }).getByRole("button").first(), { settleAfter: false });
    await c.page.getByRole("main").getByRole("status").filter({ hasText: /Answer ready|could not be completed|No recorded answer|Stopped/ }).waitFor({ timeout: 60_000 });
    const trace = inMain(c.page).getByRole("button", { name: /^Looked at \d+ things?/ });
    if (await c.exists(trace)) await c.click(trace.last());
    await settle(c.page);
  });
  // the watched folder (SPEC § 8.1): Sam's ~/Scans brought in a scan and an e-mailed bill that wait
  add("settings-folder", "/settings?section=folder", "Static demo: Settings → Watched folder (watching, letters waiting, the last files).");
  add("settings-folder-auto-read", "/settings?section=folder", "Static demo: Watched folder with “Read new files straight away” switched on, unsaved.", (c) =>
    c.click(inMain(c.page).getByRole("switch", { name: /Read new files with Claude straight away/ })),
  );
  add("settings-folder-refused", "/settings?section=folder", "Static demo: a relative folder path refused, the reason under the field.", async (c) => {
    const field = inMain(c.page).getByLabel("Folder", { exact: true });
    await field.fill("");
    await c.type(field, "Scans");
    await c.click(inMain(c.page).getByRole("button", { name: "Save changes" }), { settleAfter: false });
    await c.wait(500);
    await settle(c.page);
  });
  for (const id of new Set(mockIds(webDir, "folder.ts", "doc").filter((x) => x.startsWith("doc_folder_")))) {
    add(id.replace(/_/g, "-"), `/documents/${id}`, `Static demo: the waiting letter ${id} (from the watched folder).`);
  }
  add("inbox-waiting-read", "/inbox", "Static demo: “Read these 3” → the online demo can't read new letters (toast).", async (c) => {
    await c.click(inMain(c.page).getByRole("button", { name: /^Read these \d+ with Claude/ }), { settleAfter: false });
    await c.wait(600);
    await settle(c.page, { idle: false });
  });
  add("inbox-waiting-kept-private", "/inbox", "Static demo: “Keep private” for the waiting letters (toast with Undo; the group is gone).", async (c) => {
    await c.click(inMain(c.page).getByRole("button", { name: "Keep private" }), { settleAfter: false });
    await c.wait(600);
    await settle(c.page, { idle: false });
  });
  add("doc-folder-scan-kept-private", "/documents/doc_folder_scan", "Static demo: “Keep private” on the waiting scan's page — the toast, focus on the verdict, “Not read” with Undo.", async (c) => {
    await c.click(inMain(c.page).getByRole("button", { name: "Keep private" }), { settleAfter: false });
    await c.wait(600);
    await settle(c.page, { idle: false });
  });
  add("doc-folder-scan-kept-undo", "/documents/doc_folder_scan", "Static demo: “Keep private”, then “Undo “Keep private”” on the letter's page — it waits again, focus on the waiting card's title.", async (c) => {
    await c.click(inMain(c.page).getByRole("button", { name: "Keep private" }), { settleAfter: false });
    await c.wait(600);
    await c.click(inMain(c.page).getByRole("button", { name: "Undo “Keep private”" }), { settleAfter: false });
    await c.wait(600);
    await settle(c.page, { idle: false });
  });
  add("inbox-waiting-one", "/documents/doc_folder_mail", "Static demo: one letter still waits (the e-mail was kept private with its bill): the Inbox's group speaks of one.", async (c) => {
    await c.click(inMain(c.page).getByRole("button", { name: "Keep private" }), { settleAfter: false });
    await c.wait(600);
    // in the page (the mock database lives there): a reload would start the demo over
    await c.click(c.page.getByRole("link", { name: /^Inbox/ }).first());
    await c.page.getByRole("region", { name: /From your folder/ }).waitFor({ timeout: 10_000 });
    await settle(c.page);
  });
  add("search-waiting", "/", "Static demo: the empty search sheet on phones — a waiting letter says it waits, with the day it came.", async (c) => {
    const open = c.page.getByRole("button", { name: "Search letters" });
    if (await c.exists(open)) await c.click(open.first());
    else await c.click(c.page.getByRole("combobox", { name: "Search your letters" }).first());
    await c.wait(400);
    await settle(c.page, { idle: false });
  });
  add("dev-ui", "/dev/ui", "Static demo: the design-system gallery with its mock examples.");
  add("dev-ui-popover", "/dev/ui", "Static demo: gallery receipt popover (“Why this date? (phone contract)”).", (c) =>
    c.click(inMain(c.page).getByRole("button", { name: /Why this date\? \(phone contract\)/ })),
  );
  add("add-letter-unavailable", "/inbox", "Static demo: adding a letter → “Install Ordnung to add your own letters”.", async (c) => {
    await c.addFiles([{ name: "Mietvertrag.pdf", mimeType: "application/pdf" }]);
    await c.page.getByRole("dialog", { name: "Install Ordnung to add your own letters" }).waitFor({ timeout: 10_000 });
    await settle(c.page, { idle: false });
  });
  // ---------------------------------------------------------------------------------------------
  // High-stakes letters (ADR 0010): the court order and the dismissal from the tray, other kinds
  // set with the kind picker, the arrival/delivery question, and the letters the composer offers
  // ---------------------------------------------------------------------------------------------
  const senders = new Map(trayDocs.map(([, id, sender]) => [id, sender]));
  const court = senders.get("mail_court");
  const dismissal = senders.get("mail_dismissal");
  /** Read a tray letter (the mock database lives in the page, so every capture reads it again). */
  const readTray = async (c, sender) => {
    await c.goto("/inbox");
    const env = c.page.getByRole("region", { name: /^New mail/ }).getByRole("listitem").filter({ hasText: sender }).first();
    await c.click(env.getByRole("button", { name: "Let Ordnung read it" }), { settleAfter: false });
    await c.page.waitForURL(/\/documents\//, { timeout: 60_000 });
    await settle(c.page);
  };
  /** Navigate inside the page (a hash change keeps the in-page mock database). */
  const hashTo = async (c, path) => {
    await c.page.evaluate((p) => (window.location.hash = `#${p}`), path);
    await c.wait(300);
    await settle(c.page);
  };
  const verdict = (c) => c.page.getByRole("article").first();
  const openKindPicker = (c) => c.click(inMain(c.page).getByRole("button", { name: "Change what kind of letter this is" }));
  const fileAs = async (c, kind) => {
    await openKindPicker(c);
    const form = c.page.getByRole("dialog", { name: "What kind of letter is this?" });
    await c.select(form.getByRole("combobox", { name: "Kind of letter" }), kind);
    await c.click(form.getByRole("button", { name: "Save", exact: true }), { settleAfter: false });
    await c.wait(500);
    await settle(c.page);
  };
  const hs = [];
  const addHs = (id, path, description, run, extra = {}) =>
    hs.push({ id: `static-${id}`, group: "high-stakes", route: `#${path}`, how: `open /#${path}, then as described`, description, run, ...extra });

  if (court) {
    addHs("mail-court--kind-picker", "/inbox", "Court payment order: the kind picker (“Change”) open.", async (c) => {
      await readTray(c, court);
      await openKindPicker(c);
    });
    addHs("mail-court--why-this-date", "/inbox", "Court payment order: “Why this date?” with the rules (delivery date unknown).", async (c) => {
      await readTray(c, court);
      await c.click(verdict(c).getByRole("button", { name: /Why this date\?/ }));
      if (await c.exists(c.page.getByRole("button", { name: "Show the rules" }))) await c.click(c.page.getByRole("button", { name: "Show the rules" }));
    });
    addHs("mail-court--delivery-saved", "/inbox", "Court payment order: the envelope date entered and saved (toast).", async (c) => {
      await readTray(c, court);
      await c.type(c.page.locator("#arrival-date"), "2026-09-25");
      await c.click(c.page.locator("#arrival-question").getByRole("button", { name: "Save" }), { settleAfter: false });
      await c.wait(600);
      await settle(c.page);
    }, { pinToasts: true });
    const docIdOf = (c) => new URL(c.page.url()).hash.match(/documents\/([^?]+)/)?.[1];
    addHs("mail-court--objection", "/inbox", "Composer: objection to the court payment order (the statutory note on partial objections).", async (c) => {
      await readTray(c, court);
      await hashTo(c, `/letters?kind=objection&doc=${docIdOf(c)}`);
      await c.visible(c.page.getByRole("dialog", { name: "New letter" }));
    });
    addHs("mail-court--objection-draft", "/inbox", "Court payment order → verdict “Draft objection” → the drafted letter (how to send it to a court).", async (c) => {
      await readTray(c, court);
      await c.click(verdict(c).getByRole("button", { name: /Draft objection/ }), { settleAfter: false });
      await c.page.waitForURL(/\/letters\/drf_/, { timeout: 30_000 });
      await settle(c.page);
    }, { pinToasts: true });
    addHs("mail-court--extension-refused", "/inbox", "Composer: “Ask for more time” against the court order (refusal callout).", async (c) => {
      await readTray(c, court);
      await hashTo(c, `/letters?kind=extension_request&doc=${docIdOf(c)}`);
      await c.visible(c.page.getByRole("dialog", { name: "New letter" }));
    });
    addHs("mail-court--as-enforcement-order", "/inbox", "The court letter re-filed as an enforcement order with the kind picker.", async (c) => {
      await readTray(c, court);
      await fileAs(c, "enforcement_order");
    }, { pinToasts: true });
    addHs("mail-court--enforcement-suspend", "/inbox", "Composer: objection to the letter re-filed as an enforcement order, “suspend enforcement” ticked.", async (c) => {
      await readTray(c, court);
      await fileAs(c, "enforcement_order");
      await hashTo(c, `/letters?kind=objection&doc=${docIdOf(c)}`);
      const dialog = await c.visible(c.page.getByRole("dialog", { name: "New letter" }));
      const box = dialog.getByRole("checkbox", { name: /suspend enforcement/ });
      if (await c.exists(box)) await c.click(box);
      else c.note("no suspend checkbox");
    });
  }
  if (dismissal) {
    addHs("mail-dismissal--why-this-date", "/inbox", "Dismissal: “Why this date?” for the three weeks (§ 4 KSchG).", async (c) => {
      await readTray(c, dismissal);
      await c.click(verdict(c).getByRole("button", { name: /Why this date\?/ }));
      if (await c.exists(c.page.getByRole("button", { name: "Show the rules" }))) await c.click(c.page.getByRole("button", { name: "Show the rules" }));
    });
    addHs("mail-dismissal--advice-card", "/inbox", "Dismissal: scrolled to the “get advice” card.", async (c) => {
      await readTray(c, dismissal);
      await c.scrollTo(inMain(c.page).locator("section[aria-labelledby^=advice-]"));
    });
    addHs("mail-dismissal--trace-law", "/inbox", "Dismissal: How this was read → To-dos filed → a deadline the law adds, opened (its law's citation).", async (c) => {
      await readTray(c, dismissal);
      await c.click(inMain(c.page).getByRole("tab", { name: "How this was read" }));
      await c.click(inMain(c.page).getByRole("list", { name: "Steps of this reading" }).getByRole("button", { name: /^To-dos filed/ }));
      await c.click(inMain(c.page).getByRole("list", { name: /^Steps of “To-dos filed”/ }).getByRole("button", { name: /Deadline the law adds/ }).first());
    });
  }
  for (const [kind, label] of [
    ["landlord_notice", "a landlord's notice"],
    ["rent_increase", "a rent increase"],
  ]) {
    if (!pick("doc_lease")) break;
    addHs(`doc-lease--as-${kind.replace(/_/g, "-")}`, "/documents/doc_lease", `The lease re-filed as ${label} (advice card, verdict).`, async (c) => {
      await c.goto("/documents/doc_lease");
      await fileAs(c, kind);
    });
  }
  if (pick("doc_nebenkosten")) {
    addHs("doc-nebenkosten--as-operating-costs", "/documents/doc_nebenkosten", "The utility statement re-filed as an operating-cost statement.", async (c) => {
      await c.goto("/documents/doc_nebenkosten");
      await fileAs(c, "operating_costs");
    });
  }
  // the template letters
  addHs("composer-chooser", "/letters?new=1", "Composer step 1: the three letters and the eight template letters.", async (c) => {
    await c.goto("/letters?new=1");
    await c.visible(c.page.getByRole("dialog", { name: "New letter" }));
  });
  const tmpl = (kind, query, description, then) =>
    addHs(`composer-${kind.replace(/_/g, "-")}`, `/letters?kind=${kind}${query}`, description, async (c) => {
      await c.goto(`/letters?kind=${kind}${query}`);
      const d = await c.visible(c.page.getByRole("dialog", { name: "New letter" }));
      if (then) await then(c, d);
      await settle(c.page);
    });
  tmpl("withdrawal", "", "Template: withdraw from a purchase (letter list, facts, checkbox).");
  tmpl("extension_request", pick("doc_tm_dunning") ? "&doc=doc_tm_dunning" : "", "Template: ask for more time, answering the dunning letter.");
  tmpl("payment_plan", pick("doc_tm_dunning") ? "&doc=doc_tm_dunning" : "", "Template: instalments for the dunning letter (amount hint).", async (c, d) => {
    const box = d.getByRole("textbox", { name: /Monthly instalment/ });
    if (await c.exists(box)) await c.type(box, "1.500");
  });
  tmpl("defect_notice", "", "Template: report a defect (landlord picker, long textarea).");
  tmpl("data_access", "", "Template: ask for your data, SCHUFA's address filled in.", async (c, d) => {
    const b = d.getByRole("button", { name: "Use SCHUFA's address" });
    if (await c.exists(b)) await c.click(b);
  });
  tmpl("receipts_inspection", pick("doc_nebenkosten") ? "&doc=doc_nebenkosten" : "", "Template: see the receipts behind the statement.");
  tmpl("deposit_return", "", "Template: get the deposit back (IBAN from the profile).", async (c, d) => {
    const sel = d.getByRole("combobox", { name: /Recipient/ });
    if (await c.exists(sel)) {
      const v = await sel.locator("option").nth(1).getAttribute("value");
      if (v) await c.select(sel, v);
    }
  });
  tmpl("address_change", "", "Template: share a new address (from the profile).");

  // ---------------------------------------------------------------------------------------------
  // Proof of sending, "Waiting for" and call notes: the FitWell cancellation sent by Einschreiben
  // (tracking number, a photo of the posting receipt), the deposit and the overdue phone promise
  // ---------------------------------------------------------------------------------------------
  const pf = [];
  const addPf = (id, path, description, run, extra = {}) =>
    pf.push({ id: `static-${id}`, group: "proof", route: `#${path}`, how: `open /#${path}${run ? ", then as described" : ""}`, description, run: async (c) => (await c.goto(path), run && run(c)), ...extra });
  const proofCard = (c) => inMain(c.page).getByRole("region", { name: "Proof of sending" });
  const callsOf = (c) => c.page.getByRole("dialog").getByRole("region", { name: /^Calls/ });
  if (draftIds.includes("drf_phone") && readFileSync(join(webDir, "src", "mocks", "data", "proof.ts"), "utf8").includes('id: "drf_gym"')) {
    addPf("letter-proof", "/letters/drf_gym", "Sent letter: “Proof of sending” (tracking number, posting receipt, what's missing, timeline, Nachweis).", (c) => c.scrollTo(proofCard(c)));
    addPf("letter-proof--add", "/letters/drf_gym", "Sent letter: the “Add proof” dialog (file, kind, day, note).", (c) => c.click(proofCard(c).getByRole("button", { name: "Add proof" })));
    addPf("letter-proof--tracking-wrong", "/letters/drf_gym", "Sent letter: changing the tracking number to one with a wrong check digit.", async (c) => {
      await c.click(proofCard(c).getByRole("button", { name: "Change" }));
      const field = proofCard(c).getByRole("textbox", { name: "Tracking number" });
      await field.fill("");
      await c.type(field, "RT 123 456 784 DE");
    });
    addPf("letter-proof--remove", "/letters/drf_gym", "Sent letter: “Remove the posting receipt?” names the file, offers to download it first.", async (c) => {
      await c.click(proofCard(c).getByRole("button", { name: /^Actions for / }).first());
      await c.click(c.page.getByRole("menuitem", { name: "Remove this proof" }));
    });
    addPf("letter-proof--row-menu", "/letters/drf_gym", "Sent letter: a proof's ⋯ menu (“Change kind or day” whole, never cut off).", async (c) => {
      await c.click(proofCard(c).getByRole("button", { name: /^Actions for / }).first());
    });
    addPf("letter-proof--conflict", "/letters/drf_gym", "Sent letter: the receipt's day changed to another day than the sending: “These days don't match”.", async (c) => {
      await c.click(proofCard(c).getByRole("button", { name: /^Actions for / }).first());
      await c.click(c.page.getByRole("menuitem", { name: "Change kind or day" }));
      const dialog = await c.visible(c.page.getByRole("dialog"));
      await dialog.getByLabel(/Posted on/).fill("2026-09-24");
      await c.click(dialog.getByRole("button", { name: /^Save/ }));
      await c.centre(await c.visible(proofCard(c).getByText("These days don't match")));
    });
    addPf("letter-proof--online-stamp", "/letters/drf_gym", "Sent letter: an Einschreiben bought online — the online stamp's 20-character number, and what to keep instead of a receipt.", async (c) => {
      await c.click(proofCard(c).getByRole("button", { name: "Change" }));
      const field = proofCard(c).getByRole("textbox", { name: "Tracking number" });
      await field.fill("");
      await c.type(field, "A0 0123 45D6 0000 123C EC");
      await c.click(proofCard(c).getByRole("button", { name: "Save number" }));
      await c.centre(await c.visible(proofCard(c).getByText(/online stamp/).first()));
    });
    addPf("mark-sent--tracking", "/letters/drf_phone", "Mark as sent by Einwurf-Einschreiben with a mistyped tracking number (the check digit error).", async (c) => {
      await c.click(c.page.getByRole("button", { name: "Mark as sent" }).first());
      const dialog = await c.visible(c.page.getByRole("dialog", { name: "Mark as sent" }));
      await c.click(dialog.getByText("Einwurf-Einschreiben", { exact: false }).first()); // the radio itself is visually hidden
      await c.type(dialog.getByRole("textbox", { name: /Tracking number/ }), "RT 123 456 784 DE");
    });
    addPf("mark-sent--tracking-ok", "/letters/drf_phone", "Mark as sent by Einwurf-Einschreiben with a correct tracking number.", async (c) => {
      await c.click(c.page.getByRole("button", { name: "Mark as sent" }).first());
      const dialog = await c.visible(c.page.getByRole("dialog", { name: "Mark as sent" }));
      await c.click(dialog.getByText("Einwurf-Einschreiben", { exact: false }).first()); // the radio itself is visually hidden
      await c.type(dialog.getByRole("textbox", { name: /Tracking number/ }), "RT 123 456 785 DE");
    });
    addPf("letter-proof--answered-another-way", "/letters/drf_gym", "Sent letter: “I got an answer — close this” (closed box, toast with Undo).", async (c) => {
      await c.click(proofCard(c).getByRole("button", { name: "I got an answer — close this" }), { settleAfter: false });
      await c.visible(c.page.getByText("Marked as answered"));
      await settle(c.page);
    }, { pinToasts: true });
    addPf("letter-proof--delete", "/letters/drf_gym", "Sent letter: “Delete this letter?” names its proof file and offers to keep it.", async (c) => {
      await c.click(inMain(c.page).getByRole("button", { name: "More actions" }));
      await c.click(c.page.getByRole("menuitem", { name: "Delete this letter" }));
    });
    addPf("proof-file", "/letters/drf_gym/proofs/doc_gym_receipt", "The posting receipt on its own page, under its letter.");
    addPf("waiting", "/letters/waiting", "Waiting for: the overdue phone promise, the letters' replies and the deposit.");
    addPf("waiting--arrived", "/letters/waiting", "Waiting for: the deposit marked as arrived (toast with Undo).", async (c) => {
      await c.click(inMain(c.page).getByRole("listitem").filter({ hasText: "Deposit back" }).getByRole("button", { name: "It arrived" }), { settleAfter: false });
      await c.visible(c.page.getByText("Marked as received"));
      await settle(c.page);
    }, { pinToasts: true });
    addPf("party-calls", "/letters?party=pty_fitwell", "FitWell's drawer: the “Calls” section with the noted call and its promise.", (c) => c.scrollTo(callsOf(c)));
    addPf("waiting--note-call", "/letters/waiting", "Waiting for: “Note a call” on the overdue promise opens FitWell's drawer with the form.", async (c) => {
      const row = inMain(c.page).getByRole("region", { name: /Overdue/ });
      await c.click(row.getByRole("button", { name: "Note a call" }).first());
      await c.visible(callsOf(c).getByRole("form", { name: "Note a call" }));
    });
    addPf("party-calls--form", "/letters?party=pty_fitwell", "FitWell's drawer: “Note a call” form, saved empty (what's missing).", async (c) => {
      await c.click(callsOf(c).getByRole("button", { name: "Note a call" }));
      const form = callsOf(c).getByRole("form", { name: "Note a call" });
      await c.type(form.getByRole("textbox", { name: /What they promised/ }), "Refund of the September fee");
      await c.click(form.getByRole("button", { name: "Save note" }));
    });
  }

  return {
    phases: [
      {
        name: "static",
        parallel: true,
        states: S.map((s) => ({ ...s, pinToasts: s.id.endsWith("unavailable") || s.id.startsWith("static-inbox-waiting-") || s.id.endsWith("-kept-private") })),
      },
      { name: "high-stakes", parallel: true, states: hs },
      { name: "proof", parallel: true, states: pf },
    ],
  };
}
