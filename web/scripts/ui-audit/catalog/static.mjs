/**
 * The zero-install static demo (`VITE_STATIC_DEMO=1`, mock data, hash routes such as `#/timeline`):
 * the main routes, a few letters and drafts, an answered question, and what the online demo says
 * when something needs the real app. The ids come from the mock data in `src/mocks/data`.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { settle } from "../browser.mjs";
import { inMain } from "../steps.mjs";

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
    addPf("letter-proof--remove", "/letters/drf_gym", "Sent letter: “Remove this proof?” confirmation.", async (c) => {
      await c.click(proofCard(c).getByRole("button", { name: /^Actions for / }).first());
      await c.click(c.page.getByRole("menuitem", { name: "Remove this proof" }));
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
    addPf("party-calls--form", "/letters?party=pty_fitwell", "FitWell's drawer: “Note a call” form, saved empty (what's missing).", async (c) => {
      await c.click(callsOf(c).getByRole("button", { name: "Note a call" }));
      const form = callsOf(c).getByRole("form", { name: "Note a call" });
      await c.type(form.getByRole("textbox", { name: /What they promised/ }), "Refund of the September fee");
      await c.click(form.getByRole("button", { name: "Save note" }));
    });
  }

  return {
    phases: [
      { name: "static", parallel: true, states: S.map((s) => ({ ...s, pinToasts: s.id.endsWith("unavailable") })) },
      { name: "high-stakes", parallel: true, states: hs },
      { name: "proof", parallel: true, states: pf },
    ],
  };
}
