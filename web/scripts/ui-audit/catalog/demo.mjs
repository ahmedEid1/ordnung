/**
 * Every state of the demo (Sam Rivera's sample life) the audit captures. Built from the router
 * (`src/app/router.tsx`), the navigation (`components/shell/nav.ts`), the feature folders and the
 * demo API: every document, draft, party and New-mail letter the server returns gets its states.
 *
 * Phases:
 *  1. main       — read-only states on the untouched demo, run in parallel (tour hidden)
 *  2. tour       — the guided tour at every step (server-side tour state, so one at a time)
 *  3. mutations  — on a second, reset demo data folder: extra drafts, a sent letter
 *  4. mail       — the New-mail letters read the way the e2e helper `openMail` does it
 *  5. folder     — the watched folder on its own demo data folder (./folder.mjs)
 *  6. high-stakes — letters re-filed as high-stakes kinds on another demo data folder
 */
import { fakeApi, failApi, holdApi, pinToasts, settle } from "../browser.mjs";
import { inMain } from "../steps.mjs";
import { remindersBackupStates } from "./reminders-backup.mjs";
import { commonSettingsSections, loadingAndErrorStates, SETTINGS_SECTIONS } from "./shared.mjs";
import { numbersAndWeekDemoStates, numbersAndWeekMutationStates } from "./numbers-week.mjs";
import { folderPhase } from "./folder.mjs";

const slug = (s) =>
  s
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/ß/g, "ss")
    .replace(/\.[a-z0-9]+$/, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 48);

const docSlug = (d) => `doc-${slug(d.filename ?? d.id)}`;

/** Tour state (server-wide): hide it, or show step `i` (0-based). */
export const setTour = (api, step) => api.patch("/api/demo/tour", step === null ? { active: false, completed: true } : { active: true, step, completed: false });

// ------------------------------------------------------------------------------------------------

export async function demoCatalog({ api, server }) {
  const [docs, drafts, parties, contracts, mail, questions] = await Promise.all([
    api.get("/api/documents"),
    api.get("/api/drafts"),
    api.get("/api/parties"),
    api.get("/api/contracts"),
    api.get("/api/demo/mail"),
    api.get("/api/demo/questions"),
  ]);
  await setTour(api, null);

  const byTitle = (re) => docs.find((d) => d.title && re.test(d.title));
  const payDoc = byTitle(/Payment Reminder|Mahnung/) ?? docs.find((d) => d.payment);
  const reviewDoc = docs.find((d) => d.status === "needs_review");
  const photoDoc = docs.find((d) => d.text_mode === "vision") ?? docs[0];
  const multiDoc = docs.find((d) => (d.pages ?? 1) > 1) ?? docs[0];
  const objectionDoc = docs.find((d) => d.remedy?.type === "widerspruch" || d.remedy?.type === "einspruch");
  const noRemedyDoc = docs.find((d) => d.remedy?.type === "none" && d.area !== "other") ?? docs.find((d) => d.remedy?.type === "none");
  const replyDoc = byTitle(/Heizkosten|Operating/) ?? docs[0];
  const glossaryDoc = objectionDoc ?? docs[0];
  const phoneContract = contracts.find((c) => /FunkNetz/.test(c.name)) ?? contracts[0];
  const employment = contracts.find((c) => c.category === "employment");
  const draft = drafts[0];
  const bigParty = [...parties].sort((a, b) => (b.name?.length ?? 0) - (a.name?.length ?? 0))[0];

  // real page images for the "one letter?" dialog thumbnails
  const photoPages = [];
  for (const d of docs.filter((x) => x.text_mode === "vision").slice(0, 3)) {
    try {
      photoPages.push({ name: `IMG_20260928_${photoPages.length + 1}.jpg`, mimeType: "image/jpeg", buffer: await api.raw(`/api/documents/${d.id}/pages/1.jpg`) });
    } catch {
      /* skip */
    }
  }

  const S = [];
  const add = (s) => S.push(s);
  const main = inMain;

  // ---------------------------------------------------------------------------------------------
  // Today
  // ---------------------------------------------------------------------------------------------
  add({ id: "today", group: "today", route: "/", how: "open /", description: "Today: greeting, secretary's note, Top 3, Coming up, Ideas, life at a glance, recent letters.", run: (c) => c.goto("/") });
  add({
    id: "today-expanded",
    group: "today",
    route: "/",
    how: "open /, then open every fold on the page (Recent letters, more Ideas, Read more)",
    description: "Today with all collapsible parts expanded.",
    run: async (c) => {
      await c.goto("/");
      const m = main(c.page);
      for (const name of [/^Show \d+ more Ideas?/, /^Read more$/]) if (await c.exists(m.getByRole("button", { name }))) await c.click(m.getByRole("button", { name }));
      if (await c.exists(m.getByRole("button", { name: /Recent letters/ }))) await c.click(m.getByRole("button", { name: /Recent letters/ }));
      await c.page.evaluate(() => window.scrollTo(0, 0));
    },
  });
  add({
    id: "today-pay-panel",
    group: "today",
    route: "/",
    how: "open /, click the first Top-3 “Pay” button",
    description: "Today's Pay panel (transfer details with copy buttons, Mark as paid).",
    run: async (c) => {
      await c.goto("/");
      await c.click(main(c.page).getByRole("button", { name: /^Pay: / }));
    },
  });
  add({
    id: "today-pay-girocode",
    group: "today",
    route: "/",
    how: "open /, click the first Top-3 “Pay” button, then “Show code”",
    description: "Today's Pay panel with its GiroCode (EPC-QR) unfolded: dark on white with its quiet zone in both themes.",
    run: async (c) => {
      await c.goto("/");
      await c.click(main(c.page).getByRole("button", { name: /^Pay: / }));
      const show = c.page.getByRole("button", { name: "Show code" });
      if (await c.exists(show)) await c.click(show);
      else c.note("no “Show code”: this payment has no GiroCode");
    },
  });
  const payFine = async (c) => {
    await c.goto("/");
    const pay = main(c.page).getByRole("button", { name: /^Pay: .*(Verwarnungsgeld|traffic fine|parking)/i }).first();
    if (await c.exists(pay)) await c.click(pay);
    else c.note("no Top-3 “Pay” for the photographed fine");
  };
  add({
    id: "today-pay-girocode-check",
    group: "today",
    route: "/",
    how: "open /, click the Top-3 “Pay: …Verwarnungsgeld…” button",
    description: "Today's Pay panel of a letter read from a photo: compare the details with the paper letter first (a phone says to scan on a computer or copy the details).",
    run: payFine,
  });
  add({
    id: "today-pay-girocode-mismatch",
    group: "today",
    route: "/",
    how: "open /, click the Top-3 “Pay: …Verwarnungsgeld…” button, then “They don't match”",
    description: "Today's Pay panel after “They don't match”: type the details as the letter shows them, or read the letter again.",
    run: async (c) => {
      await payFine(c);
      const mismatch = c.page.getByRole("button", { name: "They don't match" });
      if (await c.exists(mismatch)) await c.click(mismatch);
      else c.note("no “They don't match”: already compared");
    },
  });
  // refusals in the panel (the server's answer forced): the reason shows in the panel, clear of its
  // sticky footer — no toast, which would wait behind a phone's sheet or cover a popover's footer
  const refuseConfirm = (c) =>
    fakeApi(c.page, "POST", /^\/api\/items\/[^/]+\/girocode\/confirm$/, async () => ({
      status: 409,
      json: { detail: "The payment details changed since you looked at them. Please compare them again." },
    }));
  const failReadAgain = (c) =>
    fakeApi(c.page, "POST", /^\/api\/documents\/[^/]+\/reprocess$/, async () => ({ status: 429, json: { detail: "Claude needs a short break. Try again at 15:30." } }));
  const refusedMatch = async (c) => {
    const match = c.page.getByRole("button", { name: "These match the letter" });
    if (!(await c.exists(match))) return c.note("no “These match the letter”: already compared");
    await c.click(match, { settleAfter: false });
    await c.page.getByRole("alert").filter({ hasText: /^Not confirmed/ }).waitFor({ timeout: 15_000 });
    await settle(c.page);
  };
  const failedReadAgain = async (c) => {
    const mismatch = c.page.getByRole("button", { name: "They don't match" });
    if (!(await c.exists(mismatch))) return c.note("no “They don't match”: already compared");
    await c.click(mismatch);
    const again = c.page.getByRole("button", { name: "Read the letter again" });
    if (!(await c.exists(again))) return c.note("no “Read the letter again” (a private letter, or one being read)");
    await c.click(again, { settleAfter: false });
    await c.page.getByRole("alert").filter({ hasText: /^Couldn't read the letter again/ }).waitFor({ timeout: 15_000 });
    await settle(c.page);
  };
  add({
    id: "today-pay-girocode-refused",
    group: "today",
    route: "/",
    how: "open /, click the Top-3 “Pay: …Verwarnungsgeld…” button, then “These match the letter” (the server's refusal forced: 409)",
    description: "Today's Pay panel after a refused “These match the letter”: the reason under the buttons, scrolled clear of the sticky footer, focus back on the button.",
    run: async (c) => {
      await refuseConfirm(c);
      await payFine(c);
      await refusedMatch(c);
    },
  });
  add({
    id: "today-pay-girocode-read-again-failed",
    group: "today",
    route: "/",
    how: "open /, click the Top-3 “Pay: …Verwarnungsgeld…” button, “They don't match”, then “Read the letter again” (a 429 forced)",
    description: "Today's Pay panel after “Read the letter again” failed: why, under the button, clear of the sticky footer, focus kept on the button.",
    run: async (c) => {
      await failReadAgain(c);
      await payFine(c);
      await failedReadAgain(c);
    },
  });
  // a code that carries no reference (the letter's reference taken out of the answer): it says so
  const withoutReference = (c) =>
    fakeApi(
      c.page,
      "GET",
      /^\/api\/documents\/[^/]+$/,
      async (_req, detail) => {
        if (detail?.document?.payment) detail.document.payment.reference = null;
        for (const code of detail?.girocodes ?? []) if (code.status === "ready") code.payload = code.payload.split("\n").slice(0, 8).join("\n");
        return { json: detail };
      },
      { passthrough: true },
    );
  add({
    id: "today-pay-girocode-no-reference",
    group: "today",
    route: "/",
    how: "open /, click the first Top-3 “Pay” button, then “Show code” (the letter's reference taken out of the answer)",
    description: "Today's Pay panel with a GiroCode that carries no reference: the line saying to add the letter's reference, if it names one, in the banking app.",
    run: async (c) => {
      await withoutReference(c);
      await c.goto("/");
      await c.click(main(c.page).getByRole("button", { name: /^Pay: / }));
      const show = c.page.getByRole("button", { name: "Show code" });
      if (await c.exists(show)) await c.click(show);
      else c.note("no “Show code”: this payment has no GiroCode");
    },
  });
  add({
    id: "today-why-this-date",
    group: "today",
    route: "/",
    how: "open /, click the first “Why this date?” in Top 3",
    description: "The date receipt popover (sheet on phones).",
    run: async (c) => {
      await c.goto("/");
      await c.click(main(c.page).getByRole("button", { name: /^Why this date\?/ }));
    },
  });
  add({
    id: "today-why-this-date-rules",
    group: "today",
    route: "/",
    how: "open /, “Why this date?”, then “Show the rules”",
    description: "The date receipt with every rule step and citation.",
    run: async (c) => {
      await c.goto("/");
      await c.click(main(c.page).getByRole("button", { name: /^Why this date\?/ }));
      await c.click(c.page.getByRole("button", { name: "Show the rules" }));
    },
  });
  add({
    id: "today-marked-paid-toast",
    group: "today",
    route: "/",
    how: "open /, Pay → “Mark as paid” (the PATCH is answered by the audit, nothing changes on the server)",
    description: "The success toast with Undo after marking a payment as paid.",
    pinToasts: true,
    run: async (c) => {
      await fakeApi(c.page, "PATCH", /^\/api\/items\/[^/]+$/, async (req) => {
        const id = new URL(req.url()).pathname.split("/").pop();
        const item = await c.api.get(`/api/items/${id}`);
        return { json: { ...item, ...(req.postDataJSON() ?? {}) } };
      });
      await c.goto("/");
      await c.click(main(c.page).getByRole("button", { name: /^Pay: / }));
      await c.click(c.page.getByRole("button", { name: "Mark as paid" }));
      await pinToasts(c.page);
    },
  });
  add({
    id: "today-calendar-toast",
    group: "today",
    route: "/",
    how: "open /, click the calendar card's button (download answered locally, “exported” POST faked)",
    description: "Calendar card after adding the dates: download toast.",
    pinToasts: true,
    run: async (c) => {
      await fakeApi(c.page, "POST", /^\/api\/calendar\/exported$/, async () => ({ json: { ok: true } }));
      await c.goto("/");
      const btn = c.page.getByRole("region", { name: /calendar/i }).getByRole("button");
      const card = (await c.exists(btn)) ? btn : main(c.page).getByRole("button", { name: /calendar/i });
      await c.click(card);
      await pinToasts(c.page);
    },
  });

  // ---------------------------------------------------------------------------------------------
  // Inbox
  // ---------------------------------------------------------------------------------------------
  add({ id: "inbox", group: "inbox", route: "/inbox", how: "open /inbox", description: "Inbox: New-mail tray (3 envelopes), filters, every letter grouped by month.", run: (c) => c.goto("/inbox") });
  add({ id: "inbox-filter-check", group: "inbox", route: "/inbox?filter=check", how: "open /inbox?filter=check", description: "Inbox filtered to “Please check”.", run: (c) => c.goto("/inbox?filter=check") });
  add({ id: "inbox-filter-private", group: "inbox", route: "/inbox?filter=private", how: "open /inbox?filter=private", description: "Inbox filtered to “Private” (none in the demo → empty state).", run: (c) => c.goto("/inbox?filter=private") });
  add({
    id: "inbox-filter-kind",
    group: "inbox",
    route: "/inbox?kind=…",
    how: "open /inbox, choose the first kind in the “kind” select",
    description: "Inbox filtered by letter kind.",
    run: async (c) => {
      await c.goto("/inbox");
      const sel = c.page.locator("#inbox-kind");
      const value = await sel.locator("option").nth(1).getAttribute("value");
      await c.select(sel, value);
    },
  });
  add({
    id: "inbox-search-results",
    group: "inbox",
    route: "/inbox",
    how: "open /inbox, type “Muster” in the inbox search",
    description: "Inbox search with results.",
    run: async (c) => {
      await c.goto("/inbox");
      await c.type(c.page.locator("#inbox-search"), "Muster");
      await c.wait(400);
      await settle(c.page);
    },
  });
  add({
    id: "inbox-search-none",
    group: "inbox",
    route: "/inbox",
    how: "open /inbox, type “Quittung 1999” in the inbox search",
    description: "Inbox search without results (empty state with Clear filters).",
    run: async (c) => {
      await c.goto("/inbox");
      await c.type(c.page.locator("#inbox-search"), "Quittung 1999");
      await c.wait(400);
      await settle(c.page);
    },
  });
  const fakeOpenMail = async (c, docId) => {
    const { document: doc } = await c.api.get(`/api/documents/${docId}`);
    const job = { id: "job_ui_audit", doc_id: doc.id, stage: "intake", status: "running", progress: 0, error: null };
    await fakeApi(c.page, "POST", /^\/api\/demo\/mail$/, async () => ({ json: { document: doc, job } }));
  };
  add({
    id: "inbox-new-mail-reading",
    group: "inbox",
    route: "/inbox",
    how: "open /inbox with /api/events and the open-mail POST answered by the audit; “Let Ordnung read it” on the first envelope, then a “Checking” progress event",
    description: "A New-mail envelope while it is being read (live stepper).",
    run: async (c) => {
      const ev = await c.events();
      await fakeOpenMail(c, photoDoc.id);
      await c.goto("/inbox");
      await c.click(c.page.getByRole("button", { name: "Let Ordnung read it" }), { settleAfter: false });
      await ev.waitConnected();
      await ev.deliver([{ type: "job.progress", data: { job_id: "job_ui_audit", doc_id: photoDoc.id, stage: "verify", progress: 0.6, status: "running", error: null } }]);
      await settle(c.page);
    },
  });
  add({
    id: "inbox-new-mail-failed",
    group: "inbox",
    route: "/inbox",
    how: "as inbox-new-mail-reading, then a “failed” progress event",
    description: "A New-mail envelope whose reading failed, with the error toast.",
    pinToasts: true,
    run: async (c) => {
      const ev = await c.events();
      await fakeOpenMail(c, photoDoc.id);
      await c.goto("/inbox");
      await c.click(c.page.getByRole("button", { name: "Let Ordnung read it" }), { settleAfter: false });
      await ev.waitConnected();
      await ev.deliver([
        { type: "job.progress", data: { job_id: "job_ui_audit", doc_id: photoDoc.id, stage: "extract", progress: 0.3, status: "running", error: null } },
        { type: "job.progress", data: { job_id: "job_ui_audit", doc_id: photoDoc.id, stage: "extract", progress: 0.3, status: "failed", error: "Claude couldn't read this photo — it is too blurry. Try a sharper photo in daylight." } },
      ]);
      await settle(c.page);
      await pinToasts(c.page);
    },
  });
  add({
    id: "inbox-batch-recap",
    group: "inbox",
    route: "/inbox",
    how: "open /inbox with /api/events answered by the audit: three letters report running, then done",
    description: "The batch recap dialog after several letters were read at once.",
    run: async (c) => {
      const ev = await c.events();
      await c.goto("/inbox");
      await ev.waitConnected();
      const ids = docs.slice(0, 3).map((d) => d.id);
      await ev.deliver([
        ...ids.map((id, i) => ({ type: "job.progress", data: { job_id: `job_${i}`, doc_id: id, stage: "extract", progress: 0.4, status: "running", error: null } })),
        ...ids.map((id, i) => ({ type: "job.progress", data: { job_id: `job_${i}`, doc_id: id, stage: "done", progress: 1, status: "done", error: null } })),
      ]);
      await c.visible(c.page.getByRole("dialog"));
      await settle(c.page);
    },
  });

  // ---------------------------------------------------------------------------------------------
  // Documents: every letter, then the interactive parts on representative ones
  // ---------------------------------------------------------------------------------------------
  for (const d of docs) {
    const tags = [d.text_mode === "vision" ? "phone photo" : "text PDF", `${d.pages ?? 1} page(s)`, d.status, d.warnings?.length ? `${d.warnings.length} warning(s)` : null].filter(Boolean).join(", ");
    add({ id: docSlug(d), group: "document", route: `/documents/${d.id}`, how: `open /documents/${d.id}`, description: `Letter viewer: “${d.title}” (${tags}).`, run: (c) => c.goto(`/documents/${d.id}`) });
  }
  const docState = (doc, suffix, how, description, run, extra = {}) =>
    doc && add({ id: `${docSlug(doc)}--${suffix}`, group: "document", route: `/documents/${doc.id}`, how: `open /documents/${doc.id}, ${how}`, description, run: async (c) => (await c.goto(`/documents/${doc.id}`), run(c)), ...extra });
  docState(payDoc, "pay", "click the verdict card's “Pay …” button", "The Pay popover (IBAN, reference, amount, copy buttons).", (c) => c.click(c.page.getByRole("article").first().getByRole("button", { name: /^Pay\b/ })));
  docState(payDoc, "why-this-date", "click “Why this date?”, then “Show the rules”", "The “Why this date?” receipt with the rule steps.", async (c) => {
    await c.click(c.page.getByRole("article").first().getByRole("button", { name: /Why this date\?/ }));
    if (await c.exists(c.page.getByRole("button", { name: "Show the rules" }))) await c.click(c.page.getByRole("button", { name: "Show the rules" }));
  });
  docState(payDoc, "item-menu", "open the first to-do's “More actions” menu", "A to-do's action menu (calendar, change date, done, not a real to-do).", (c) => c.click(c.page.getByRole("button", { name: /^More actions for / })));
  docState(payDoc, "item-change-date", "“More actions” → “Change date”", "Inline date editor of a to-do.", async (c) => {
    await c.click(c.page.getByRole("button", { name: /^More actions for / }));
    await c.click(c.page.getByRole("menuitem", { name: /Change date|Set a date/ }));
  });
  docState(payDoc, "evidence", "click the first “show … on the page” evidence button", "The evidence highlight and quote on the page image.", (c) => c.click(c.page.getByRole("button", { name: /show “.*” on the page/ })));
  docState(payDoc, "evidence-tooltip", "hover the first evidence chip", "Tooltip of an evidence chip.", (c) => c.hover(c.page.getByRole("button", { name: /show “.*” on the page/ })));
  docState(payDoc, "delete-dialog", "click “Delete”", "The delete-letter confirmation.", (c) => c.click(main(c.page).getByRole("button", { name: /^Delete$/ })));
  const statementDoc = docs.find((d) => /nebenkosten/i.test(d.filename ?? ""));
  const photoFineDoc = docs.find((d) => d.text_mode === "vision" && d.payment?.iban);
  const openPay = async (c) => {
    const pay = c.page.getByRole("article").first().getByRole("button", { name: /^Pay\b/ });
    if (await c.exists(pay)) await c.click(pay);
    else c.note("no “Pay” button on the verdict card");
  };
  docState(statementDoc, "girocode", "click the verdict card's “Pay …” button", "The Pay popover with the letter's GiroCode (EPC-QR) and how to use it.", openPay);
  docState(photoFineDoc, "girocode-check", "click the verdict card's “Pay …” button", "The Pay popover of a letter read from a photo: compare the details with the paper letter first (“These match the letter”).", openPay);
  docState(photoFineDoc, "girocode-mismatch", "click the verdict card's “Pay …” button, then “They don't match”", "The Pay popover of a photographed letter after “They don't match”.", async (c) => {
    await openPay(c);
    const mismatch = c.page.getByRole("button", { name: "They don't match" });
    if (await c.exists(mismatch)) await c.click(mismatch);
    else c.note("no “They don't match”: already compared");
  });
  // no code for a reason the person can't resolve here (a reminder took over), and a lease's deposit
  const replacedInvoiceDoc = docs.find((d) => d.kind === "invoice" && /techmarkt/i.test(`${d.filename} ${d.title}`));
  const leaseDoc = docs.find((d) => /mietvertrag|lease/i.test(`${d.filename} ${d.title}`));
  docState(replacedInvoiceDoc, "girocode-replaced", "click the verdict card's “Pay …” button", "The Pay popover of an invoice a payment reminder took over: why there is no code.", openPay);
  docState(leaseDoc, "girocode-lease", "click the verdict card's “Pay …” button", "The Pay popover of the lease's deposit: its sentence doesn't state the amount, so compare with the paper letter first (the monthly rent next to it gets no code: several payments).", openPay);
  docState(photoFineDoc, "girocode-refused", "click the verdict card's “Pay …” button, then “These match the letter” (the server's refusal forced: 409)", "The Pay popover after a refused “These match the letter”: the reason in the block, clear of the footer.", async (c) => {
    await refuseConfirm(c);
    await openPay(c);
    await refusedMatch(c);
  });
  docState(photoFineDoc, "girocode-read-again-failed", "click the verdict card's “Pay …” button, “They don't match”, then “Read the letter again” (a 429 forced)", "The Pay popover after “Read the letter again” failed: why, in the block.", async (c) => {
    await failReadAgain(c);
    await openPay(c);
    await failedReadAgain(c);
  });
  if (statementDoc) {
    add({
      id: `${docSlug(statementDoc)}--girocode-no-reference`,
      group: "document",
      route: `/documents/${statementDoc.id}`,
      how: `open /documents/${statementDoc.id} (the letter's reference taken out of the answer), click the verdict card's “Pay …” button, “Show code” on phones`,
      description: "The Pay popover with a GiroCode that carries no reference: the line saying to add the letter's reference in the banking app.",
      run: async (c) => {
        await withoutReference(c);
        await c.goto(`/documents/${statementDoc.id}`);
        await openPay(c);
        const show = c.page.getByRole("button", { name: "Show code" });
        if (await c.exists(show)) await c.click(show);
      },
    });
  }
  docState(multiDoc, "zoom-150", "switch the page viewer zoom to 150 %", "Page viewer at 150 % (horizontal scrolling inside the viewer).", (c) => c.click(c.page.getByRole("radiogroup", { name: "Zoom" }).getByRole("radio", { name: /150/ })));
  docState(multiDoc, "page-2", "click the page-2 thumbnail", "Page viewer scrolled to page 2.", (c) => c.click(c.page.getByRole("button", { name: /^Go to page 2/ })));
  docState(photoDoc, "zoom-150", "switch the page viewer zoom to 150 %", "Phone photo at 150 %.", (c) => c.click(c.page.getByRole("radiogroup", { name: "Zoom" }).getByRole("radio", { name: /150/ })));
  docState(reviewDoc, "change-date", "click “Change date” in the Please-check warning", "Please-check warning with the date editor open.", (c) => c.click(main(c.page).getByRole("button", { name: "Change date" })));
  docState(glossaryDoc, "glossary-tooltip", "hover the first German term with a dotted underline", "Glossary tooltip (German term explained).", (c) => c.hover(main(c.page).locator("span.cursor-help")));

  // ---------------------------------------------------------------------------------------------
  // Timeline
  // ---------------------------------------------------------------------------------------------
  add({ id: "timeline", group: "timeline", route: "/timeline", how: "open /timeline", description: "Timeline: life lanes (year ahead) and the month-by-month list.", run: (c) => c.goto("/timeline") });
  const tlSelect = (id, sel, n, desc) =>
    add({
      id: `timeline-filter-${id}`,
      group: "timeline",
      route: "/timeline",
      how: `open /timeline, choose option ${n} in the ${sel} select`,
      description: desc,
      run: async (c) => {
        await c.goto("/timeline");
        const s = c.page.locator(sel);
        await c.select(s, await s.locator("option").nth(n).getAttribute("value"));
      },
    });
  tlSelect("kind", "#tl-type", 1, "Timeline filtered by kind.");
  tlSelect("area", "#tl-area", 1, "Timeline filtered by life area (lanes show the area chip).");
  tlSelect("party", "#tl-party", 1, "Timeline filtered by person/organisation.");
  add({
    id: "timeline-show-past",
    group: "timeline",
    route: "/timeline",
    how: "open /timeline, switch on “Show past”",
    description: "Timeline including past dates.",
    run: async (c) => {
      await c.goto("/timeline");
      await c.click(c.page.getByRole("switch", { name: /Show past/ }));
    },
  });
  add({
    id: "timeline-filter-empty",
    group: "timeline",
    route: "/timeline",
    // the menus grey out choices that would show nothing, so: letters received, then hide the past
    how: "open /timeline, pick “Letters received” as the kind and switch off “Show past” (no dates match)",
    description: "Timeline filters that match nothing (empty state).",
    run: async (c) => {
      await c.goto("/timeline");
      await c.select(c.page.locator("#tl-type"), "document");
      await c.click(c.page.getByRole("switch", { name: /Show past/ }));
    },
  });
  add({
    id: "timeline-lanes-zoom",
    group: "timeline",
    route: "/timeline",
    how: "open /timeline, lanes zoom “Zoom in”",
    description: "Life lanes zoomed in (scrollable chart).",
    run: async (c) => {
      await c.goto("/timeline");
      await c.click(c.page.getByRole("radiogroup", { name: "Zoom" }).getByRole("radio", { name: /Zoom in/ }));
    },
  });
  add({
    id: "timeline-lane-tooltip",
    group: "timeline",
    route: "/timeline",
    how: "open /timeline, hover the first bar/marker in the lanes",
    description: "Tooltip of a lane bar.",
    run: async (c) => {
      await c.goto("/timeline");
      await c.hover(c.page.getByRole("region", { name: "Your year ahead" }).getByRole("list", { name: "Lanes" }).getByRole("button"));
    },
  });
  add({
    id: "timeline-calendar-export",
    group: "timeline",
    route: "/timeline",
    how: "open /timeline, “Add to my calendar” (the download happens; the “exported” POST is faked)",
    description: "Calendar export dialog with the per-app guide.",
    run: async (c) => {
      await fakeApi(c.page, "POST", /^\/api\/calendar\/exported$/, async () => ({ json: { ok: true } }));
      await c.goto("/timeline");
      await c.click(main(c.page).getByRole("button", { name: "Add to my calendar" }));
      await c.visible(c.page.getByRole("dialog"));
    },
  });
  add({
    id: "timeline-calendar-export-app",
    group: "timeline",
    route: "/timeline",
    how: "as timeline-calendar-export, then pick the last calendar app",
    description: "Calendar export dialog, another calendar app's steps.",
    run: async (c) => {
      await fakeApi(c.page, "POST", /^\/api\/calendar\/exported$/, async () => ({ json: { ok: true } }));
      await c.goto("/timeline");
      await c.click(main(c.page).getByRole("button", { name: "Add to my calendar" }));
      const radios = c.page.getByRole("dialog").getByRole("radiogroup").getByRole("radio");
      await c.click(radios.last());
    },
  });

  // ---------------------------------------------------------------------------------------------
  // Contracts
  // ---------------------------------------------------------------------------------------------
  add({ id: "contracts", group: "contracts", route: "/contracts", how: "open /contracts", description: "Contracts: cost summary, Decide by, lanes chart, every contract card.", run: (c) => c.goto("/contracts") });
  for (const tab of ["Cancelled", "Ended", "All"]) {
    add({
      id: `contracts-tab-${tab.toLowerCase()}`,
      group: "contracts",
      route: "/contracts",
      how: `open /contracts, tab “${tab}” (or /contracts?status=${tab.toLowerCase()}: a status without contracts has no tab)`,
      description: `Contracts filtered to “${tab}”.`,
      run: async (c) => {
        await c.goto("/contracts");
        const tabEl = c.page.getByRole("tablist", { name: "Show contracts" }).getByRole("tab", { name: new RegExp(`^${tab}`) });
        if (await c.exists(tabEl)) await c.click(tabEl);
        else await c.goto(`/contracts?status=${tab.toLowerCase()}`);
      },
    });
  }
  add({
    id: "contracts-why",
    group: "contracts",
    route: "/contracts",
    how: "open /contracts, first “Why these dates?”, then “Show the rules”",
    description: "A contract's “why these dates” popover with the rule steps.",
    run: async (c) => {
      await c.goto("/contracts");
      await c.click(main(c.page).getByRole("button", { name: /^Why these dates\?/ }));
      if (await c.exists(c.page.getByRole("button", { name: "Show the rules" }))) await c.click(c.page.getByRole("button", { name: "Show the rules" }));
    },
  });
  add({
    id: "contracts-lane-tooltip",
    group: "contracts",
    route: "/contracts",
    how: "open /contracts, hover the first bar in the contracts lanes",
    description: "Tooltip of a contract lane bar (send-by marker).",
    run: async (c) => {
      await c.goto("/contracts");
      await c.hover(main(c.page).getByRole("list", { name: "Lanes" }).getByRole("button"));
    },
  });
  const noticeForm = async (c) => {
    await c.goto("/contracts");
    const add = main(c.page).getByRole("button", { name: /^(Add|Change) notice period/ });
    if (!(await c.exists(add))) c.notApplicable("no contract with terms it couldn't work out");
    await c.click(add);
    return main(c.page).getByRole("form", { name: /^Notice period for / });
  };
  add({
    id: "contracts-notice-form",
    group: "contracts",
    route: "/contracts",
    how: "open /contracts, “Add notice period” on a contract whose terms are unclear",
    description: "The notice period entered by hand on a contract card (terms it couldn't work out).",
    run: noticeForm,
  });
  add({
    id: "contracts-notice-errors",
    group: "contracts",
    route: "/contracts",
    how: "open /contracts, “Add notice period”, then “Save notice period” with nothing entered",
    description: "The notice-period form's validation errors.",
    run: async (c) => {
      const form = await noticeForm(c);
      await c.click(form.getByRole("button", { name: "Save notice period" }));
    },
  });

  // My numbers and the weekly session
  for (const s of numbersAndWeekDemoStates()) add(s);

  // ---------------------------------------------------------------------------------------------
  // Letters (drafts) and the composer
  // ---------------------------------------------------------------------------------------------
  add({ id: "letters", group: "letters", route: "/letters", how: "open /letters", description: "Letters: drafts in progress / sent and “How letters work”.", run: (c) => c.goto("/letters") });
  const composer = (id, query, description, then) =>
    add({
      id: `composer-${id}`,
      group: "letters",
      route: `/letters?${query}`,
      how: `open /letters?${query}${then ? ", then choose as described" : ""}`,
      description,
      run: async (c) => {
        await c.goto(`/letters?${query}`);
        await c.visible(c.page.getByRole("dialog", { name: "New letter" }));
        if (then) await then(c);
        await settle(c.page);
      },
    });
  composer("new", "new=1", "The New-letter composer, nothing chosen yet.");
  composer("cancellation", "kind=cancellation", "Composer: “Cancel a contract” with the contract list.");
  if (phoneContract) composer("cancellation-chosen", `kind=cancellation&contract=${phoneContract.id}`, `Composer: cancelling “${phoneContract.name}” (recipient, send-by date, instructions).`);
  if (employment) composer("cancellation-employment", `kind=cancellation&contract=${employment.id}`, "Composer: ending an employment contract (resignation wording and hints).");
  composer("objection", "kind=objection", "Composer: “Object to a decision” with the eligible letters.");
  if (objectionDoc) composer("objection-chosen", `kind=objection&doc=${objectionDoc.id}`, `Composer: objection against “${objectionDoc.title}”.`);
  if (noRemedyDoc) composer("objection-not-possible", `kind=objection&doc=${noRemedyDoc.id}`, `Composer: objection chosen for a letter without a remedy (“${noRemedyDoc.title}”) — explanation and advice.`);
  composer("reply", "kind=general_reply", "Composer: “Reply to a letter” with the searchable letter list.");
  composer("reply-chosen", `kind=general_reply&doc=${replyDoc.id}`, `Composer: reply to “${replyDoc.title}” with instructions.`, async (c) => {
    const box = c.page.getByRole("dialog").getByRole("textbox").last();
    if (await c.exists(box)) await c.type(box, "Bitte schicken Sie mir die Belege zur Heizkostenabrechnung. Ich möchte in zwei Raten zahlen.");
  });
  if (phoneContract && draft) {
    add({
      id: "composer-written-toast",
      group: "letters",
      route: `/letters?kind=cancellation&contract=${phoneContract.id}`,
      how: "composer for the phone contract → “Write the letter” (the POST is answered with the existing draft, so nothing is created)",
      description: "Arriving on the drafted letter with the “Your letter is ready to check” toast.",
      pinToasts: true,
      run: async (c) => {
        const existing = await c.api.get(`/api/drafts/${draft.id}`);
        await fakeApi(c.page, "POST", /^\/api\/drafts$/, async () => ({ status: 201, json: existing }));
        await c.goto(`/letters?kind=cancellation&contract=${phoneContract.id}`);
        await c.click(c.page.getByRole("dialog", { name: "New letter" }).getByRole("button", { name: /Write the letter/ }));
        await c.page.waitForURL(/\/letters\/drf_/);
        await settle(c.page);
        await pinToasts(c.page);
      },
    });
  }
  if (draft) {
    const lp = `/letters/${draft.id}`;
    const letterState = (suffix, how, description, run, extra = {}) =>
      add({ id: `letter-${slug(draft.kind)}${suffix ? `--${suffix}` : ""}`, group: "letters", route: lp, how: `open ${lp}${how ? `, ${how}` : ""}`, description, run: async (c) => (await c.goto(lp), run && run(c)), ...extra });
    letterState("", "", `Letter draft “${draft.subject}”: editor, translation, checks, how to send it, PDF preview.`);
    letterState("english", "switch the editor to “In English” (phones/tablets) or scroll to the translation", "The English translation pane.", async (c) => {
      const radio = c.page.getByRole("radiogroup", { name: "Show the letter or its translation" }).getByRole("radio", { name: /In English/ });
      if (await c.exists(radio)) await c.click(radio);
      else c.notApplicable("the translation is shown side by side at this width");
    });
    letterState("menu", "open “More actions”", "The letter's More-actions menu.", (c) => c.click(main(c.page).getByRole("button", { name: "More actions" })));
    letterState("mark-sent", "click “Mark as sent”", "The Mark-as-sent dialog (channel and date).", (c) => c.click(main(c.page).getByRole("button", { name: "Mark as sent" })));
    letterState("mark-sent-other", "“Mark as sent”, choose the second way of sending", "The Mark-as-sent dialog with another channel than the recommended one.", async (c) => {
      await c.click(main(c.page).getByRole("button", { name: "Mark as sent" }));
      const d = c.page.getByRole("dialog");
      await c.visible(d);
      await d.locator("label").filter({ has: c.page.locator("input[type=radio]") }).nth(1).click();
      await settle(c.page);
    });
    letterState("delete-dialog", "More actions → “Delete this letter”", "The delete-draft confirmation.", async (c) => {
      await c.click(main(c.page).getByRole("button", { name: "More actions" }));
      await c.click(c.page.getByRole("menuitem", { name: "Delete this letter" }));
    });
    letterState("unsaved", "type a sentence at the end of the German text (not saved)", "Editor with unsaved changes (Save enabled).", async (c) => {
      const box = await c.visible(c.page.getByRole("textbox", { name: "Letter text (German)" }));
      await box.click();
      await c.page.keyboard.press("ControlOrMeta+End");
      await c.page.keyboard.type(" Mit freundlichen Grüßen, Sam.");
      await settle(c.page);
    });
    letterState("leave-dialog", "edit the text, then click Today in the navigation", "“Leave without saving?” dialog.", async (c) => {
      const box = await c.visible(c.page.getByRole("textbox", { name: "Letter text (German)" }));
      await box.click();
      await c.page.keyboard.press("ControlOrMeta+End");
      await c.page.keyboard.type(" Danke.");
      await c.click(c.page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: /^Today/ }));
    });
  }

  // ---------------------------------------------------------------------------------------------
  // Ask
  // ---------------------------------------------------------------------------------------------
  add({ id: "ask", group: "ask", route: "/ask", how: "open /ask", description: "Ask with an empty thread: suggested questions and the composer.", run: (c) => c.goto("/ask") });
  add({
    id: "ask-typed",
    group: "ask",
    route: "/ask",
    how: "open /ask, type a long question (not sent)",
    description: "Ask composer with a long question typed.",
    run: async (c) => {
      await c.goto("/ask");
      await c.type(main(c.page).getByRole("textbox"), "Muss ich meine Betriebs- und Heizkostenabrechnung 2025 von der Wohnbau Musterstadt eG wirklich bis Ende Oktober bezahlen, und kann ich Einspruch einlegen?", { settleAfter: false });
      await settle(c.page, { idle: false });
    },
  });
  questions.forEach((q, i) => {
    add({
      id: `ask-answer-${i + 1}`,
      group: "ask",
      route: "/ask",
      how: `open /ask, click the suggested question “${q}”, wait for “Answer ready.”, expand “Looked at … things”`,
      description: `Streamed (replayed) answer to “${q}” with the tool trace expanded.`,
      run: async (c) => {
        await c.goto("/ask");
        await c.click(c.page.getByRole("list", { name: "Suggested questions" }).getByRole("button", { name: q }), { settleAfter: false });
        await c.page.getByRole("main").getByRole("status").filter({ hasText: /Answer ready|could not be completed|No recorded answer|Stopped/ }).waitFor({ timeout: 60_000 });
        const trace = main(c.page).getByRole("button", { name: /^Looked at \d+ things?/ });
        if (await c.exists(trace)) await c.click(trace.last());
        await settle(c.page);
      },
    });
  });
  add({
    id: "ask-citation-tooltip",
    group: "ask",
    route: "/ask",
    how: "answer the first suggested question, hover its first source chip",
    description: "Tooltip on a citation chip in an answer.",
    run: async (c) => {
      await c.goto("/ask");
      await c.click(c.page.getByRole("list", { name: "Suggested questions" }).getByRole("button").first(), { settleAfter: false });
      await c.page.getByRole("main").getByRole("status").filter({ hasText: /Answer ready|could not be completed|No recorded answer/ }).waitFor({ timeout: 60_000 });
      await settle(c.page);
      await c.hover(main(c.page).getByRole("article").locator('a[aria-label^="Source"], button[aria-label^="Source"]'));
    },
  });
  add({
    id: "ask-unrecorded",
    group: "ask",
    route: "/ask",
    how: "open /ask, send a question the demo has no recording for",
    description: "What the demo answers to a question without a recording (no Claude call in replay mode).",
    run: async (c) => {
      await c.goto("/ask");
      await c.type(main(c.page).getByRole("textbox"), "Which of my letters mention a Kaution?", { settleAfter: false });
      await c.page.keyboard.press("Enter");
      await c.page.getByRole("main").getByRole("status").filter({ hasText: /Answer ready|could not be completed|No recorded answer|Stopped/ }).waitFor({ timeout: 60_000 });
      await settle(c.page);
    },
  });

  // Ask: what the answer check shows (ADR 0008) — the answer stream is answered in the page, so any
  // state can be shown without a recording: a note under the answer, values left out, a check that
  // failed, the "writing" line, and a stream that ends without its checked answer
  {
    const noteDoc = replyDoc;
    const noteItems = noteDoc ? await api.get(`/api/items?doc_id=${noteDoc.id}`).catch(() => []) : [];
    const noteItem = noteItems.find((i) => i.due_date) ?? noteItems[0];
    const trace = [
      { type: "tool_use", name: "list_items", input: { from: "2026-09-28", to: "2026-10-31", status: "open" }, text: "Listed your open to-dos & dates from 2026-09-28 to 2026-10-31" },
      { type: "tool_result", name: "list_items", text: `${noteItems.length || 12} to-dos, the earliest due 2026-10-01` },
      noteDoc ? { type: "tool_use", name: "get_document", input: { doc_id: noteDoc.id }, text: `Opened “${noteDoc.title}”` } : null,
      noteDoc ? { type: "tool_result", name: "get_document", text: "Ordnung's record and the letter's text (2 pages)" } : null,
      { type: "tool_use", name: "explain_date", input: { item_or_contract_id: noteItem?.id ?? "itm_x" }, text: `Checked how “${noteItem?.title ?? "a date"}” was worked out` },
      { type: "tool_result", name: "explain_date", text: "Due 2026-10-15 — § 556 Abs. 3 BGB" },
      { type: "text" },
    ].filter(Boolean);
    const cite = noteDoc ? `[doc:${noteDoc.id}]` : "";
    const citeItem = noteItem ? `[item:${noteItem.id}]` : "";
    const citations = [noteDoc ? { type: "document", id: noteDoc.id, label: noteDoc.title } : null, noteItem ? { type: "item", id: noteItem.id, label: noteItem.title } : null].filter(Boolean);
    const done = (text, note, label) => ({ type: "done", text, note, note_label: label, citations, message_id: "msg_ui_audit", thread_id: "thr_ui_audit" });
    /** Answer `POST /api/ask` in the page with `events`; `open` keeps the stream open after them. */
    const answerAsk = (c, events, { open = false } = {}) =>
      c.page.addInitScript(
        ({ events, open }) => {
          const real = window.fetch.bind(window);
          window.fetch = (input, init) => {
            const url = typeof input === "string" ? input : input.url;
            if (!/\/api\/ask(\?|$)/.test(new URL(url, location.href).pathname) || (init?.method ?? "GET").toUpperCase() !== "POST") return real(input, init);
            const enc = new TextEncoder();
            const body = new ReadableStream({
              start(ctrl) {
                for (const e of events) ctrl.enqueue(enc.encode(`data: ${JSON.stringify(e)}\n\n`));
                if (!open) ctrl.close();
              },
            });
            return Promise.resolve(new Response(body, { status: 200, headers: { "content-type": "text/event-stream" } }));
          };
        },
        { events, open },
      );
    const askState = (id, question, events, description, { open = false, expand = true } = {}) =>
      add({
        id: `ask-${id}`,
        group: "ask",
        route: "/ask",
        how: `open /ask with POST /api/ask answered in the page, send “${question}”${expand ? ", expand the trace" : ""}`,
        description,
        run: async (c) => {
          await answerAsk(c, events, { open });
          await c.goto("/ask");
          await c.type(main(c.page).getByRole("textbox"), question, { settleAfter: false });
          await c.page.keyboard.press("Enter");
          if (open) await c.page.getByText(/Writing the answer/).first().waitFor({ timeout: 10_000 }).catch(() => c.note("no “writing” line"));
          else await c.page.getByRole("main").getByRole("status").filter({ hasText: /Answer ready|could not be completed|Couldn't|Stopped|interrupted/ }).waitFor({ timeout: 15_000 }).catch(() => c.note("no final status"));
          const t = main(c.page).getByRole("button", { name: /^Looked at \d+ things?/ });
          if (expand && (await c.exists(t))) await c.click(t.last());
          await settle(c.page, { idle: !open });
        },
      });
    askState(
      "check-note",
      "Was muss ich im Oktober für die Nebenkosten bezahlen, und bis wann?",
      [
        ...trace,
        done(
          `The operating-cost statement asks for a back-payment of [amount only in the letter] ${cite}. The to-do “${noteItem?.title ?? "Pay"}” is due 2026-10-15 ${citeItem}. Your landlord also wrote that the new prepayment starts [date left out].\n\nYou can ask to see the receipts before you pay.`,
          "1 date, time or amount is marked “left out”: it isn't among the dates and amounts Ordnung saved for the linked letter, to-do or contract. 1 date, time or amount is marked “only in the letter”: a letter's text has it, but it isn't among the dates and amounts Ordnung saved for the linked letter, to-do or contract — open the letter to read it.",
          "Checked by Ordnung:",
        ),
      ],
      "Checked answer with left-out and only-in-the-letter values, the check's note and the tool trace expanded.",
    );
    askState(
      "check-note-de",
      "Bis wann muss ich die Nebenkosten zahlen?",
      [
        ...trace,
        done(
          `Die Nachzahlung aus der Betriebskostenabrechnung ist bis 2026-10-15 fällig ${citeItem}. Der Vermieter nennt außerdem „[Betrag nur im Brief]“ als neue Vorauszahlung ${cite}.`,
          "1 Angabe ist als „nur im Brief“ markiert: Sie steht im Text eines Briefs, gehört aber nicht zu den Daten und Beträgen, die Ordnung zum verknüpften Brief, zur Aufgabe oder zum Vertrag gespeichert hat – öffnen Sie den Brief, um sie zu lesen. 1 Quelle ergänzt: Ein Satz nannte ein Datum, eine Uhrzeit oder einen Betrag ohne Quelle.",
          "Von Ordnung geprüft:",
        ),
      ],
      "A German checked answer with the German note label.",
    );
    askState(
      "checked-no-note",
      "When is the operating-cost payment due?",
      [...trace, done(`The back-payment is due 2026-10-15 ${citeItem}.`, null, "Checked by Ordnung:")],
      "A checked answer the check did not change (“Dates and amounts checked against your records.”).",
    );
    askState(
      "check-failed",
      "When is the operating-cost payment due?",
      [...trace, { type: "error", error: "Ordnung couldn't check this answer against your records, so it isn't shown. Please ask again." }],
      "The answer check failed (fails closed): the error callout with Try again.",
    );
    askState("writing", "When is the operating-cost payment due?", trace, "The model is writing: the trace and the “Writing the answer — it appears once Ordnung has checked it” line.", { open: true, expand: false });
    askState(
      "stream-cut",
      "When is the operating-cost payment due?",
      trace,
      "The stream ends after “writing” without a checked answer (a dropped connection or a server restart).",
    );
    askState(
      "check-note-payment",
      "Do I have to pay the new rent from November?",
      [
        ...trace,
        done(
          `The new rent of 712.40 € is due from 2026-11-01 ${citeItem}. Your landlord asks you to agree by 2026-11-30 ${cite}.`,
          "Added 1 source to a sentence that gave a date, time or amount without one. For the records concerned, Ordnung has on file: the to-do “Neue monatliche Miete (Vorauszahlungen)”, due Sun 1 Nov 2026, 712.40 €; the letter “Mieterhöhungsverlangen nach § 558 BGB”, dated Fri 18 Sep 2026. The new rent is only owed once you agree to the increase, and paying it can count as agreeing (§ 558b Abs. 1 BGB) — decide before you pay.",
          "Checked by Ordnung:",
        ),
      ],
      "A checked answer about a rent increase: the check's note repeats the app's payment note (§ 558b Abs. 1 BGB, decide before you pay).",
    );
    askState(
      "check-note-scam",
      "Should I pay the Rundfunk letter?",
      [
        ...trace,
        done(
          `The letter asks for 254.35 € by 2026-09-30 ${cite}.`,
          "A letter this answer refers to shows signs of a scam: don't pay its demand before you have checked with the sender, using contact details you already know (not the ones in the letter). Added 1 source to a sentence that gave a date, time or amount without one.",
          "Checked by Ordnung:",
        ),
      ],
      "A checked answer about a letter with scam signs: the warning comes first, in the warning tone, the check's bookkeeping below it.",
    );
  }

  // the kind picker ("What kind of letter is this?") on a real letter, not saved
  if (replyDoc) {
    docState(replyDoc, "kind-picker", "click “Change” next to the letter's kind", "The kind picker: “What kind of letter is this?” with the high-stakes kinds first.", (c) =>
      c.click(main(c.page).getByRole("button", { name: "Change what kind of letter this is" })),
    );
  }

  // the template letters on the real server (the profile has no IBAN: the deposit letter says where to add it)
  const landlord = parties.find((p) => p.kind === "landlord");
  composer("templates-deposit", `kind=deposit_return${landlord ? `&to=${landlord.id}` : ""}`, "Composer: “Get your deposit back” for the landlord, no IBAN in the profile.");
  composer("templates-withdrawal", "kind=withdrawal", "Composer: “Withdraw from a purchase” with the letter list and facts.");
  if (payDoc) composer("templates-payment-plan", `kind=payment_plan&doc=${payDoc.id}`, "Composer: “Pay in instalments” for the payment reminder (amount default hint).");
  if (payDoc) composer("templates-extension", `kind=extension_request&doc=${payDoc.id}`, "Composer: “Ask for more time” for the payment reminder (the letter's deadline as the default).");
  composer("templates-defect", `kind=defect_notice${landlord ? `&to=${landlord.id}` : ""}`, "Composer: “Report a defect” for the landlord (long description field and dates).");
  composer("templates-data-access", "kind=data_access", "Composer: “Ask for your data” with SCHUFA's address filled in.", async (c) => {
    const b = c.page.getByRole("dialog").getByRole("button", { name: "Use SCHUFA's address" });
    if (await c.exists(b)) await c.click(b);
    else c.note("no SCHUFA button");
  });
  if (replyDoc) composer("templates-receipts", `kind=receipts_inspection&doc=${replyDoc.id}`, "Composer: “See the receipts” for the operating-cost statement.");
  composer("templates-address-change", "kind=address_change", "Composer: “Share a new address” with the profile's address.");
  if (objectionDoc) {
    composer("objection-suspend", `kind=objection&doc=${objectionDoc.id}`, "Composer: objection to an authority's decision with “Also ask to suspend enforcement” ticked.", async (c) => {
      const box = c.page.getByRole("dialog").getByRole("checkbox", { name: /suspend enforcement/ });
      if (await c.exists(box)) await c.click(box);
      else c.note("no suspend checkbox");
    });
  }

  // ---------------------------------------------------------------------------------------------
  // Settings
  // ---------------------------------------------------------------------------------------------
  for (const s of commonSettingsSections("settings")) add(s);
  add({
    id: "settings-profile-iban-invalid",
    group: "settings",
    route: "/settings?section=profile",
    how: "open /settings?section=profile, type an IBAN with a wrong check digit, leave the field",
    description: "Profile: the refund IBAN with its validation error.",
    run: async (c) => {
      await c.goto("/settings?section=profile");
      const box = await c.type(main(c.page).getByRole("textbox", { name: /IBAN for refunds/ }), "DE89 3704 0044 0532 0130 01");
      await box.press("Tab");
      await settle(c.page);
      await c.centre(box);
    },
  });
  add({
    id: "settings-profile-iban-valid",
    group: "settings",
    route: "/settings?section=profile",
    how: "open /settings?section=profile, type a valid IBAN without spaces, leave the field (unsaved)",
    description: "Profile: a valid refund IBAN shown in blocks of four, the save bar.",
    run: async (c) => {
      await c.goto("/settings?section=profile");
      const box = await c.type(main(c.page).getByRole("textbox", { name: /IBAN for refunds/ }), "DE89370400440532013000");
      await box.press("Tab");
      await settle(c.page);
      await c.centre(box);
    },
  });
  add({
    id: "settings-profile-unsaved",
    group: "settings",
    route: "/settings?section=profile",
    how: "open Settings → Profile, change the name (not saved)",
    description: "Profile form with unsaved changes (save bar).",
    run: async (c) => {
      await c.goto("/settings?section=profile");
      await c.type(c.page.getByRole("textbox", { name: /Full name/ }), "Sam Alexandra Rivera-Schneidermann");
    },
  });
  add({
    id: "settings-profile-invalid",
    group: "settings",
    route: "/settings?section=profile",
    how: "open Settings → Profile, type an invalid e-mail address",
    description: "Profile form with a validation error.",
    run: async (c) => {
      await c.goto("/settings?section=profile");
      await c.type(c.page.getByRole("textbox", { name: /Email/ }), "sam.rivera@");
      await c.page.getByRole("textbox", { name: /Phone/ }).click();
      await settle(c.page);
    },
  });
  add({
    id: "settings-discard-dialog",
    group: "settings",
    route: "/settings?section=profile",
    how: "change the name, then click another settings section",
    description: "“Save your changes?” dialog (Discard · Keep editing · Save and go).",
    run: async (c) => {
      await c.goto("/settings?section=profile");
      await c.type(c.page.getByRole("textbox", { name: /Full name/ }), "Sam R.");
      await c.click(c.page.getByRole("navigation", { name: "Settings sections" }).getByRole("link", { name: SETTINGS_SECTIONS.region }));
    },
  });
  add({
    id: "settings-reminders-unsaved",
    group: "settings",
    route: "/settings?section=reminders",
    how: "open Settings → Reminders, change the postal buffer (not saved)",
    description: "Reminders with unsaved changes.",
    run: async (c) => {
      await c.goto("/settings?section=reminders");
      const sel = c.page.locator("#postal-buffer");
      const vals = await sel.locator("option").evaluateAll((os) => os.map((o) => o.value));
      const cur = await sel.inputValue();
      await c.select(sel, vals.find((v) => v !== cur) ?? vals[0]);
    },
  });
  add({
    id: "settings-profile-saved-toast",
    group: "shell-and-overlays",
    route: "/settings?section=profile",
    how: "change the name, Save (the PUT is answered by the audit with the unchanged profile)",
    description: "Profile saved: the save bar confirms in place (“Saved. New letters use…”), pinned in view for a moment — no toast over it.",
    pinToasts: true,
    run: async (c) => {
      const profile = await c.api.get("/api/profile");
      await fakeApi(c.page, "PUT", /^\/api\/profile$/, async () => ({ json: profile }));
      await c.goto("/settings?section=profile");
      await c.type(c.page.getByRole("textbox", { name: /Full name/ }), "Sam Rivera ");
      await c.click(main(c.page).getByRole("button", { name: /^Save/ }));
      await pinToasts(c.page);
    },
  });
  add({
    id: "settings-save-error-toast",
    group: "shell-and-overlays",
    route: "/settings?section=profile",
    how: "change the name, Save (the PUT fails with HTTP 500, answered by the audit)",
    description: "Error toast (“That didn't work”) after a failed save.",
    pinToasts: true,
    run: async (c) => {
      await failApi(c.page, { status: 500, only: ["/api/profile"], method: "PUT", except: [] });
      await c.goto("/settings?section=profile");
      await c.type(c.page.getByRole("textbox", { name: /Full name/ }), "Sam Rivera ");
      await c.click(main(c.page).getByRole("button", { name: /^Save/ }));
      await pinToasts(c.page);
    },
  });
  add({
    id: "settings-data-delete-dialog",
    group: "settings",
    route: "/settings?section=data",
    how: "open Settings → Data, “Delete everything…”",
    description: "The typed-confirmation “Delete everything?” dialog.",
    run: async (c) => {
      await c.goto("/settings?section=data");
      const btn = main(c.page).getByRole("button", { name: /Delete everything/ });
      if (!(await c.exists(btn))) c.notApplicable("the demo offers “reset the demo” instead of deleting");
      await c.click(btn);
    },
  });
  for (const s of remindersBackupStates()) add(s);

  // ---------------------------------------------------------------------------------------------
  // Shell & overlays
  // ---------------------------------------------------------------------------------------------
  const SH = "shell-and-overlays";
  add({ id: "not-found", group: SH, route: "/this-page-does-not-exist", how: "open an unknown route", description: "404 inside the shell.", run: (c) => c.goto("/this-page-does-not-exist") });
  add({ id: "dev-ui", group: SH, route: "/dev/ui", how: "open /dev/ui", description: "Design-system gallery.", run: (c) => c.goto("/dev/ui") });
  const gallery = (id, how, description, run, extra = {}) =>
    add({ id: `dev-ui-${id}`, group: SH, route: "/dev/ui", how: `open /dev/ui, ${how}`, description, run: async (c) => (await c.goto("/dev/ui"), run(c)), ...extra });
  gallery("dialog", "“Open dialog”", "Gallery: example dialog.", (c) => c.click(main(c.page).getByRole("button", { name: "Open dialog" })));
  gallery("drawer", "“Open drawer”", "Gallery: example drawer.", (c) => c.click(main(c.page).getByRole("button", { name: "Open drawer" })));
  gallery("menu", "“Open menu”", "Gallery: example menu (danger item).", (c) => c.click(main(c.page).getByRole("button", { name: "Open menu" })));
  gallery("popover", "“Why this date? (phone contract)”", "Gallery: receipt popover (its example data exists in the static demo's mocks only).", async (c) => {
    const b = main(c.page).getByRole("button", { name: /Why this date\? \(phone contract\)/ });
    if (!(await c.exists(b, { timeout: 3000 }))) c.notApplicable("the gallery's receipt example needs the mock item itm_phone_cancel (static demo only) — here it stays a skeleton");
    await c.click(b);
  });
  gallery("tooltip", "hover “Hover or focus me”", "Gallery: tooltip.", (c) => c.hover(main(c.page).getByRole("button", { name: "Hover or focus me" })));
  gallery(
    "toasts",
    "click the success, error and action toast buttons",
    "Gallery: three stacked toasts (success with Undo, error, with action).",
    async (c) => {
      for (const name of [/Success toast|Undo toast|Marked as done/i, "Error toast", "Toast with action"]) {
        const b = main(c.page).getByRole("button", { name });
        if (await c.exists(b)) await c.click(b, { settleAfter: false });
      }
      // the first button's label: whatever triggers the undo toast
      const undo = main(c.page).locator("button").filter({ hasText: /toast/i }).first();
      if (!(await c.page.getByText("Marked as done").count())) await undo.click().catch(() => {});
      await settle(c.page, { idle: false });
      await pinToasts(c.page);
    },
    { pinToasts: true },
  );
  add({ id: "sidebar-collapsed", group: SH, route: "/", how: "open / with localStorage ordnung.sidebar.collapsed=true", description: "Collapsed sidebar (icon rail) on laptops.", storage: { "ordnung.sidebar.collapsed": "true" }, run: (c) => c.goto("/") });
  add({
    id: "sidebar-rail-tooltip",
    group: SH,
    route: "/",
    how: "collapsed sidebar, hover the “Expand sidebar” button under the logo",
    description: "Tooltip of the rail's Expand button (the rail's sections are labelled, so they have none).",
    storage: { "ordnung.sidebar.collapsed": "true" },
    run: async (c) => {
      if (!c.desktop) c.notApplicable("the sidebar can be collapsed on laptops only (tablets always show the labelled rail)");
      await c.goto("/");
      await c.hover(c.page.getByRole("complementary", { name: "Sidebar" }).getByRole("button", { name: "Expand sidebar" }));
    },
  });
  add({
    id: "demo-badge-about",
    group: SH,
    route: "/",
    how: "open /, click the “Demo · 28 Sep 2026” badge (the flask in the phone top bar)",
    description: "“About the demo” popover (a bottom sheet on phones): Sam Rivera's sample life, the simulated date.",
    run: async (c) => {
      if (c.width < 360) c.notApplicable("below 360 px the top bar has no room for the demo badge");
      await c.goto("/");
      await c.click(c.page.getByRole("button", { name: /about the demo$/ }));
      await c.page.getByRole("dialog", { name: "About the demo" }).waitFor();
      await settle(c.page, { idle: false });
    },
  });
  add({
    id: "theme-toggle-tooltip",
    group: SH,
    route: "/",
    how: "open /, hover the theme button in the sidebar",
    description: "Theme toggle tooltip.",
    run: async (c) => {
      if (c.phone) c.notApplicable("the theme button lives in the sidebar (Settings on phones)");
      await c.goto("/");
      await c.hover(c.page.getByRole("button", { name: /^Theme: / }));
    },
  });
  add({
    id: "skip-link",
    group: SH,
    route: "/",
    how: "open /, press Tab once",
    description: "The “Skip to content” link on first Tab.",
    run: async (c) => {
      await c.goto("/");
      await c.page.keyboard.press("Tab");
      await settle(c.page, { idle: false });
    },
  });
  const search = (id, text, description) =>
    add({
      id: `search-${id}`,
      group: SH,
      route: "/",
      how: `open /, open the letter search (top bar; the search sheet on phones), type “${text}”`,
      description,
      run: async (c) => {
        await c.goto("/");
        if (c.phone) await c.click(c.page.getByRole("button", { name: "Search letters" }));
        const box = c.page.getByRole("combobox", { name: "Search your letters" });
        await c.type(box, text, { settleAfter: false });
        await c.wait(500);
        await settle(c.page);
      },
    });
  search("hint", "M", "Search with one character: “keep typing” hint.");
  search("results", "Muster", "Search results (keyboard-navigable list).");
  search("none", "Quittung 1999", "Search without results.");
  add({
    id: "search-sheet",
    group: SH,
    route: "/",
    how: "open /, tap the search icon (phones)",
    description: "The empty search sheet on phones.",
    run: async (c) => {
      if (!c.phone) c.notApplicable("the search is inline in the top bar from 768 px");
      await c.goto("/");
      await c.click(c.page.getByRole("button", { name: "Search letters" }));
    },
  });
  add({
    id: "add-letters-dialog",
    group: SH,
    route: "/inbox",
    how: "open /inbox, put one PDF with a long file name on the Add-letters file input",
    description: "“Add this letter?” with “Keep private — no AI”.",
    run: async (c) => {
      await c.goto("/inbox");
      await c.addFiles([{ name: "Einkommensteuerbescheid_2025_Finanzamt_Musterstadt_Steuernummer_123-456-78901_Seite1.pdf", mimeType: "application/pdf" }]);
      await c.visible(c.page.getByRole("dialog"));
    },
  });
  add({
    id: "add-letters-many-private",
    group: SH,
    route: "/inbox",
    how: "open /inbox, add 10 PDFs, switch on “Keep private — no AI”",
    description: "Adding many letters privately (list shortened, “Store privately”).",
    run: async (c) => {
      await c.goto("/inbox");
      const names = ["Mietvertrag", "Nebenkostenabrechnung_2025", "Kündigungsbestätigung", "Beitragsbescheid", "Rundfunkbeitrag", "Stromrechnung", "Lohnsteuerbescheinigung", "Versicherungsschein", "Immatrikulation", "Aufenthaltstitel"];
      await c.addFiles(names.map((n) => ({ name: `${n}.pdf`, mimeType: "application/pdf" })));
      await c.click(c.page.getByRole("dialog").getByRole("switch", { name: /Keep private/ }));
    },
  });
  if (photoPages.length >= 2) {
    add({
      id: "add-letters-combine",
      group: SH,
      route: "/inbox",
      how: "open /inbox, add three phone photos",
      description: "“Are these pages of one letter?” with thumbnails.",
      run: async (c) => {
        await c.goto("/inbox");
        await c.addFiles(photoPages);
        await c.visible(c.page.getByRole("dialog"));
        await c.wait(300);
        await settle(c.page, { idle: false });
      },
    });
  }
  add({
    id: "files-skipped-toast",
    group: SH,
    route: "/inbox",
    how: "open /inbox, add a .txt file",
    description: "Warning toast: file type not supported.",
    pinToasts: true,
    run: async (c) => {
      await c.goto("/inbox");
      await c.addFiles([{ name: "notizen.txt", mimeType: "text/plain" }]);
      await pinToasts(c.page);
    },
  });
  add({
    id: "drop-zone",
    group: SH,
    route: "/",
    how: "open /, drag a file over the window",
    description: "The global drop overlay.",
    run: async (c) => {
      await c.goto("/");
      await c.dragFilesOver();
    },
  });
  add({
    id: "upload-center",
    group: SH,
    route: "/",
    how: "open / with /api/events answered by the audit: one letter being read, one done, one failed",
    description: "Upload progress cards (stepper, done with “Open letter”, failed).",
    run: async (c) => {
      const ev = await c.events();
      await c.goto("/");
      await ev.waitConnected();
      const [a, b, d] = [docs[9] ?? docs[0], docs[15] ?? docs[1], docs[3] ?? docs[2]];
      await ev.deliver([
        { type: "job.progress", data: { job_id: "job_a", doc_id: a.id, stage: "verify", progress: 0.55, status: "running", error: null } },
        { type: "job.progress", data: { job_id: "job_b", doc_id: b.id, stage: "extract", progress: 0.3, status: "running", error: null } },
        { type: "job.progress", data: { job_id: "job_c", doc_id: d.id, stage: "transcribe", progress: 0.1, status: "running", error: null } },
        { type: "job.progress", data: { job_id: "job_b", doc_id: b.id, stage: "done", progress: 1, status: "done", error: null } },
        { type: "job.progress", data: { job_id: "job_c", doc_id: d.id, stage: "transcribe", progress: 0.1, status: "failed", error: "Couldn't read this letter — the file is damaged." } },
      ]);
      await settle(c.page);
    },
  });
  add({
    id: "paused-banner",
    group: SH,
    route: "/",
    how: "open / with /api/events answered by the audit: “llm.paused” until Mon 15:30",
    description: "“Claude is taking a break” banner.",
    run: async (c) => {
      const ev = await c.events();
      await c.goto("/");
      await ev.waitConnected();
      await ev.deliver([{ type: "llm.paused", data: { until: "2099-01-05T15:30:00+01:00", reason: "Your Claude plan's usage limit was reached." } }]);
      await settle(c.page);
    },
  });
  for (const p of parties) {
    add({
      id: `party-${slug(p.name)}`,
      group: SH,
      route: `/?party=${p.id}`,
      how: `open /?party=${p.id}`,
      description: `People & organisations drawer: ${p.name}${p === bigParty ? " (longest name)" : ""}.`,
      run: async (c) => {
        await c.goto(`/?party=${p.id}`);
        await c.visible(c.page.getByRole("dialog"));
        await settle(c.page);
      },
    });
  }
  for (const s of loadingAndErrorStates({ docId: payDoc?.id ?? docs[0].id, draftId: draft?.id })) add(s);

  // ---------------------------------------------------------------------------------------------
  // Phase 2: the guided tour (server-side state → one capture at a time)
  // ---------------------------------------------------------------------------------------------
  const tour = [];
  const tourState = (id, step, path, description, run, extra = {}) =>
    tour.push({
      id: `tour-${id}`,
      group: "tour",
      route: path,
      how: `PATCH /api/demo/tour {active: true, step: ${step}}, open ${path}${run ? ", then as described" : ""}`,
      description,
      run: async (c) => {
        await setTour(c.api, step);
        await c.goto(path);
        await c.visible(c.page.getByRole("region", { name: "Demo tour" }).or(c.page.getByRole("button", { name: /^Demo tour · \d of \d — resume/ }))).catch(() => c.note("tour card not visible"));
        if (run) await run(c);
        await settle(c.page);
      },
      ...extra,
    });
  tourState("step-1", 0, "/inbox", "Tour step 1 “You have new mail” on the Inbox (spotlight on the New-mail tray).");
  tourState("step-1-elsewhere", 0, "/contracts", "Tour step 1 while on another page (“Show me the mail”).");
  tourState("step-2", 1, "/", "Tour step 2 “An idea just arrived” on Today (spotlight on Ideas).");
  tourState("step-3", 2, "/ask", "Tour step 3 “Ask anything” (spotlight on the suggested questions).");
  tourState("step-4", 3, "/timeline", "Tour step 4 “Your year ahead” (spotlight on the lanes).");
  tourState("minimised", 1, "/", "The minimised tour pill.", null, { storage: { "ordnung.tour.minimised": "true" } });
  tourState("settings-card", 1, "/settings?section=data", "Settings → Data while the tour is showing: the Guided tour card says where it is (“Restart the demo tour”).");
  const openBar = async (c) => {
    const bar = c.page.getByRole("button", { name: /^Demo tour · \d of \d: .* — show the whole step$/ });
    if (await c.exists(bar)) await c.click(bar);
    return c.page.getByRole("region", { name: "Demo tour" });
  };
  tourState("phone-open", 1, "/", "Phones, tablets and short screens: the slim tour bar opened into the whole step card.", async (c) => {
    const bar = c.page.getByRole("button", { name: /^Demo tour · \d of \d: .* — show the whole step$/ });
    if (!(await c.exists(bar))) c.notApplicable("the slim tour bar shows on phones, tablets and short screens only");
    await c.click(bar);
  });
  tourState("finished-toast", 3, "/timeline", "After “Finish”: the “That's the tour” toast (with “Restart the tour”).", async (c) => {
    const tourCard = await openBar(c);
    await c.click(tourCard.getByRole("button", { name: /^Finish/ }));
    await pinToasts(c.page);
  }, { pinToasts: true });
  tourState("ended-toast", 2, "/ask", "After “End the tour” (×): the “Tour hidden” toast with Undo and where to restart it.", async (c) => {
    const tourCard = await openBar(c);
    await c.click(tourCard.getByRole("button", { name: "End the tour" }));
    await pinToasts(c.page);
  }, { pinToasts: true });

  // ---------------------------------------------------------------------------------------------
  // Proof of sending, "Waiting for" and call notes on the untouched demo (nothing sent yet)
  // ---------------------------------------------------------------------------------------------
  add({ id: "proof-waiting-empty", group: "proof", route: "/letters/waiting", how: "open /letters/waiting", description: "Waiting for on the untouched demo: nothing to wait for.", run: (c) => c.goto("/letters/waiting") });
  if (bigParty) {
    const calls = (c) => c.page.getByRole("dialog").getByRole("region", { name: /^Calls/ });
    add({
      id: "proof-party-calls-empty",
      group: "proof",
      route: `/?party=${bigParty.id}`,
      how: "open the drawer of the party with the longest name, scroll to Calls",
      description: "People drawer: no calls noted yet.",
      run: async (c) => {
        await c.goto(`/?party=${bigParty.id}`);
        await c.centre(await c.visible(calls(c)));
      },
    });
    add({
      id: "proof-party-calls-form-long",
      group: "proof",
      route: `/?party=${bigParty.id}`,
      how: "open the drawer, Note a call, type long values and a German amount, Save with “What was said” empty",
      description: "Note a call: long German values, “1.234,56” read back, the first missing field focused.",
      run: async (c) => {
        await c.goto(`/?party=${bigParty.id}`);
        await c.click(calls(c).getByRole("button", { name: "Note a call" }));
        const form = calls(c).getByRole("form", { name: "Note a call" });
        await form.getByRole("textbox", { name: /Who you spoke to/ }).fill("Frau Dr. Wilhelmine Sachbearbeiterin-Kundenbetreuungsabteilungsleiterin, Forderungsmanagement");
        await form.getByRole("textbox", { name: /What they promised/ }).fill("Rückerstattungsbestätigungsschreiben über die Überzahlung aus der Nebenkostenabrechnung 2025");
        await form.getByRole("textbox", { name: /Amount/ }).fill("1.234,56");
        await c.click(form.getByRole("button", { name: "Save note" }));
      },
    });
  }

  // ---------------------------------------------------------------------------------------------
  // Phase 3: states that change data — on a second demo data folder
  // ---------------------------------------------------------------------------------------------
  const mutations = [];
  const extra = {};
  const letterPage = (id, pick, description, run) =>
    mutations.push({
      id,
      group: "letters",
      route: "/letters/…",
      how: "created by the audit on the second demo folder (POST /api/drafts, POST …/sent), then opened",
      description,
      run: async (c) => {
        const d = extra[pick];
        if (!d) throw new Error(`draft “${pick}” was not created`);
        await c.goto(`/letters/${d.id}`);
        if (run) await run(c);
      },
    });
  letterPage("letter-objection", "objection", "An objection (Widerspruch) draft against the health-insurance contribution notice.");
  letterPage("letter-reply", "reply", "A reply draft to the operating-costs statement, with instructions.");
  letterPage("letter-sent", "sent", "A letter marked as sent (read-only, follow-up reminder).");
  letterPage("letter-sent--menu", "sent", "The More-actions menu of a sent letter.", (c) => c.click(main(c.page).getByRole("button", { name: "More actions" })));
  mutations.push(...numbersAndWeekMutationStates());
  mutations.push({ id: "letters-with-sent", group: "letters", route: "/letters", how: "open /letters after the audit drafted three letters and marked one as sent", description: "Letters list with in-progress and sent letters.", run: (c) => c.goto("/letters") });
  // proof of sending on the sent letters (the FitWell Einschreiben without proof; the FunkNetz one with a
  // lot of it: a posting receipt photo with a long name and note, a text delivery record, an undated scan)
  const proofRegion = (c) => main(c.page).getByRole("region", { name: "Proof of sending" });
  const proofState = (id, pick, description, run) =>
    letterPage(id, pick, description, async (c) => {
      if (run) await run(c);
      else await c.centre(await c.visible(proofRegion(c)));
    });
  proofState("proof-sent--card", "sent", "Proof card on a real sent Einschreiben with nothing added yet (what to start with, the answer button).");
  proofState("proof-sent--add", "sent", "Add proof: the posting receipt starts on the sending day.", (c) => c.click(proofRegion(c).getByRole("button", { name: "Add proof" })));
  proofState("proof-sent--add-no-file", "sent", "Add proof, pressed without a file: the file field says what's missing (focused).", async (c) => {
    await c.click(proofRegion(c).getByRole("button", { name: "Add proof" }));
    const dialog = await c.visible(c.page.getByRole("dialog", { name: "Add proof" }));
    await c.click(dialog.getByRole("button", { name: "Add proof" }));
  });
  proofState("proof-sent--tracking-typing", "sent", "Tracking number partly typed, then Save: the mistake is said.", async (c) => {
    const field = proofRegion(c).getByRole("textbox", { name: "Tracking number" });
    await c.type(field, "RT 123 45");
    await c.click(proofRegion(c).getByRole("button", { name: "Save number" }));
  });
  proofState("proof-sent--change-sending", "sent", "“Change how or when you sent it” (from More actions), pre-filled.", async (c) => {
    await c.click(main(c.page).getByRole("button", { name: "More actions" }));
    await c.click(c.page.getByRole("menuitem", { name: "Change how or when you sent it" }));
  });
  proofState("proof-sent--delete", "sent2", "“Delete this letter?” on a sent letter with proof files: named, with “Keep the proof files”.", async (c) => {
    await c.click(main(c.page).getByRole("button", { name: "More actions" }));
    await c.click(c.page.getByRole("menuitem", { name: "Delete this letter" }));
  });
  const answeredWaiting = (w, docId) => ({
    ...w,
    status: "answered",
    answered_by: { type: "document", id: docId },
    answered_on: "2026-09-27",
    note: "Their letter “Bestätigung Ihrer Kündigung zum 31.10.2026 — Vertragskontonummer 4711-0815-2342” of Sun 27 Sep is in the same thread. Check that it answers yours, then close this.",
  });
  proofState("proof-sent--answered", "sent", "A letter in the thread may have answered (faked): check it, “It's the answer — close this”.", async (c) => {
    const docs = await c.api.get("/api/documents");
    await fakeApi(c.page, "GET", /\/api\/drafts\/[^/]+\/proof$/, (_r, o) => ({ json: { ...o, waiting: o.waiting ? answeredWaiting(o.waiting, docs[0].id) : o.waiting } }), { passthrough: true });
    await c.goto(`/letters/${extra.sent.id}`);
    await c.centre(await c.visible(proofRegion(c)));
  });
  proofState("proof-sent--overdue", "sent", "Nothing came by the follow-up day (faked): “Still waiting for …” in red, “Write a reminder” and “Note a call”.", async (c) => {
    await fakeApi(
      c.page,
      "GET",
      /\/api\/drafts\/[^/]+\/proof$/,
      (_r, o) => ({
        json: {
          ...o,
          waiting: o.waiting
            ? { ...o.waiting, status: "overdue", note: `${o.waiting.note.split(".")[0]}; nothing linked to it has arrived since. Send a short reminder or call them — and note what they say.` }
            : o.waiting,
        },
      }),
      { passthrough: true },
    );
    await c.goto(`/letters/${extra.sent.id}`);
    await c.centre(await c.visible(proofRegion(c)));
  });
  proofState("proof-sent--conflict", "sent2", "A receipt's day and the sending day disagree (faked): “These days don't match”.", async (c) => {
    await fakeApi(
      c.page,
      "GET",
      /\/api\/drafts\/[^/]+\/proof$/,
      (_r, o) => ({ json: { ...o, conflicts: ["Your posting receipt says Sat 12 Sep 2026, but the letter is marked as sent on Thu 10 Sep 2026 — correct one of them, so your records agree."] } }),
      { passthrough: true },
    );
    await c.goto(`/letters/${extra.sent2.id}`);
    await c.centre(await c.visible(proofRegion(c)));
  });
  proofState("proof-sent--error", "sent", "The proof overview fails to load.", async (c) => {
    await failApi(c.page, { status: 500, only: [`/api/drafts/${extra.sent.id}/proof`] });
    await c.goto(`/letters/${extra.sent.id}`);
    await c.wait(4000);
    await c.centre(await c.visible(proofRegion(c)));
  });
  proofState("proof-sent2--card", "sent2", "Proof card with a lot on it: domestic tracking number, photo with a long name and note, a text delivery record, an undated scan.");
  proofState("proof-sent2--top", "sent2", "The top of a sent letter: the banner (no second reminder) above the proof card.", async (c) => c.wait(200));
  proofState("proof-sent2--edit", "sent2", "“Change this proof” dialog.", async (c) => {
    await c.click(proofRegion(c).getByRole("button", { name: /^Actions for / }).first());
    await c.click(c.page.getByRole("menuitem", { name: "Change kind or day" }));
  });
  mutations.push({
    id: "proof-file-page",
    group: "proof",
    route: "/letters/…/proofs/…",
    how: "open the posting receipt of the FunkNetz letter from its proof card",
    description: "A proof file on its own page: under its letter (Letters in the nav), “Remove this proof”.",
    run: async (c) => {
      const o = await c.api.get(`/api/drafts/${extra.sent2.id}/proof`);
      const receipt = o.proofs.find((p) => p.proof.kind === "posting_receipt") ?? o.proofs[0];
      await c.goto(`/letters/${extra.sent2.id}/proofs/${receipt.document.id}`);
    },
  });
  mutations.push({ id: "proof-waiting-with-sent", group: "proof", route: "/letters/waiting", how: "after the audit sent letters and noted calls", description: "Waiting for with sent letters and calls: every letter can be closed.", run: (c) => c.goto("/letters/waiting") });
  mutations.push({
    id: "proof-waiting--answered",
    group: "proof",
    route: "/letters/waiting",
    how: "fake one letter as answered",
    description: "Waiting for: “A letter may have answered” group.",
    run: async (c) => {
      const docs = await c.api.get("/api/documents");
      await fakeApi(c.page, "GET", /^\/api\/waiting$/, (_r, o) => ({ json: o.map((w, i) => (w.source === "letter" && i === o.findIndex((x) => x.source === "letter") ? answeredWaiting(w, docs[0].id) : w)) }), { passthrough: true });
      await c.goto("/letters/waiting");
    },
  });
  mutations.push({
    id: "proof-waiting--error",
    group: "proof",
    route: "/letters/waiting",
    how: "fail GET /api/waiting",
    description: "Waiting for: could not load.",
    run: async (c) => {
      await failApi(c.page, { status: 500, only: ["/api/waiting"] });
      await c.goto("/letters/waiting", { heading: false, idle: false });
      await c.wait(4000);
      await settle(c.page);
    },
  });
  mutations.push({
    id: "proof-waiting--loading",
    group: "proof",
    route: "/letters/waiting",
    how: "hold GET /api/waiting",
    description: "Waiting for: loading.",
    idle: false,
    run: async (c) => {
      await holdApi(c.page, { only: ["/api/waiting"], except: [] });
      await c.goto("/letters/waiting", { idle: false });
      await c.wait(600);
      await settle(c.page, { idle: false });
    },
  });
  mutations.push({ id: "proof-letters-with-waiting", group: "proof", route: "/letters", how: "after the audit sent letters", description: "Letters with the Waiting-for count (overdue in red).", run: (c) => c.goto("/letters") });
  mutations.push({
    id: "proof-party-calls-long",
    group: "proof",
    route: "/letters?party=…",
    how: "open the FunkNetz drawer after the audit noted two calls",
    description: "People drawer: Calls with long notes, a promise with an amount, a kept one.",
    run: async (c) => {
      await c.goto(`/letters?party=${extra.sent2.party_id}`);
      await c.centre(await c.visible(c.page.getByRole("dialog").getByRole("region", { name: /^Calls/ })));
    },
  });
  if (objectionDoc) {
    mutations.push({
      id: `${docSlug(objectionDoc)}--with-draft`,
      group: "document",
      route: `/documents/${objectionDoc.id}`,
      how: "open the objected letter after its objection was drafted",
      description: "Letter viewer listing “Your letters about this”.",
      run: (c) => c.goto(`/documents/${objectionDoc.id}`),
    });
  }

  mutations.push({
    id: "today-pay-girocode-confirmed",
    group: "today",
    route: "/",
    how: "open /, click the Top-3 “Pay: …Verwarnungsgeld…” button, then “These match the letter” (later captures find it done and unfold the code)",
    description: "Today's Pay panel right after “These match the letter”: the code and its confirmation line scrolled clear of the sticky footer.",
    run: async (c) => {
      await payFine(c);
      const match = c.page.getByRole("button", { name: "These match the letter" });
      const show = c.page.getByRole("button", { name: "Show code" });
      if (await c.exists(match)) await c.click(match, { settleAfter: false });
      else if (await c.exists(show)) await c.click(show);
      await c.page.getByRole("img", { name: /^GiroCode: transfer/ }).waitFor({ timeout: 30_000 });
      await settle(c.page);
    },
  });
  if (photoFineDoc) {
    mutations.push({
      id: `${docSlug(photoFineDoc)}--girocode-confirmed`,
      group: "document",
      route: `/documents/${photoFineDoc.id}`,
      how: `open /documents/${photoFineDoc.id}, “Pay …”, “These match the letter” (recorded on the mutations copy; later captures find it done)`,
      description: "The photographed letter's GiroCode after the person compared the details with the paper letter.",
      run: async (c) => {
        await c.goto(`/documents/${photoFineDoc.id}`);
        await c.click(c.page.getByRole("article").first().getByRole("button", { name: /^Pay\b/ }));
        const match = c.page.getByRole("button", { name: "These match the letter" });
        const show = c.page.getByRole("button", { name: "Show code" });
        if (await c.exists(match)) await c.click(match, { settleAfter: false });
        // later captures: already compared — on a phone the code waits behind "Show code"
        else if (await c.exists(show)) await c.click(show);
        await c.page.getByRole("img", { name: /^GiroCode: transfer/ }).waitFor({ timeout: 30_000 });
        await settle(c.page);
      },
    });
  }

  // ---------------------------------------------------------------------------------------------
  // Phase 4: the New-mail letters, read like the e2e helper openMail does
  // ---------------------------------------------------------------------------------------------
  const mailStates = [];
  for (const t of mail) {
    mailStates.push({
      id: `doc-mail-${slug(t.filename ?? t.id)}`,
      group: "document",
      route: "/documents/… (New mail)",
      how: `Inbox → “Let Ordnung read it” on ${t.sender} (first capture; later captures open the letter it became)`,
      description: `New-mail letter from ${t.sender}: “${t.subject}” (${t.photo ? "phone photo" : "PDF"}${/rundfunk/i.test(t.sender) ? ", the scam letter" : ""}).`,
      run: (c) => openMail(c, t.sender),
    });
  }
  const scam = mail.find((t) => /Rundfunk/i.test(t.sender));
  if (scam) {
    mailStates.push({
      id: `doc-mail-${slug(scam.filename ?? scam.id)}--signs`,
      group: "document",
      route: "/documents/… (New mail)",
      how: "open the scam letter, “Show all … signs”",
      description: "The scam warning with every sign listed.",
      run: async (c) => {
        await openMail(c, scam.sender);
        const b = main(c.page).getByRole("button", { name: /^Show all \d+ signs/ });
        if (await c.exists(b)) await c.click(b);
        else c.note("no “Show all signs” button");
      },
    });
  }
  mailStates.push({ id: "inbox-after-mail", group: "inbox", route: "/inbox", how: "open /inbox after all New-mail letters were read", description: "Inbox without the tray, the new letters on top.", run: (c) => c.goto("/inbox") });
  mailStates.push({ id: "today-after-mail", group: "today", route: "/", how: "open / after all New-mail letters were read", description: "Today after the new letters (new Ideas, scam warning idea).", run: (c) => c.goto("/") });

  // ---------------------------------------------------------------------------------------------
  // Phase 5: high-stakes letters (ADR 0010) on a third demo folder — real letters re-filed with the
  // kind picker's PATCH, so the server works out their law-set dates and "get advice" cards
  // ---------------------------------------------------------------------------------------------
  const HS_KINDS = [
    [/^03_mietvertrag/, "landlord_notice"],
    [/^13_nebenkostenabrechnung/, "operating_costs"],
    [/^15_mahnung_techmarkt/, "court_payment_order"],
    [/^07_arbeitsvertrag/, "dismissal"],
    [/^20_stadtbibliothek/, "enforcement_order"],
    [/^19_bank_preisaenderung/, "rent_increase"],
  ];
  const hsDocs = {};
  /** The court objection's draft of each set-up letter, created by its first capture (reset with the setup). */
  const hsObjectionDrafts = new Map();
  const hsStates = [];
  for (const [re, kind] of HS_KINDS) {
    const d = docs.find((x) => re.test(x.filename ?? ""));
    if (!d) continue;
    const at = (suffix, how, description, run) =>
      hsStates.push({
        id: `hs-${kind.replace(/_/g, "-")}${suffix ? `--${suffix}` : ""}`,
        group: "high-stakes",
        route: "/documents/…",
        how: `“${d.filename}” re-filed as ${kind} (PATCH kind), open it${how ? `, ${how}` : ""}`,
        description,
        run: async (c) => {
          const id = hsDocs[kind];
          if (!id) throw new Error(`${kind} was not set up`);
          await c.goto(`/documents/${id}`);
          if (run) await run(c, id);
        },
      });
    at("", "", `“${d.filename}” as ${kind}: verdict, advice card, arrival question.`);
    at("why-this-date", "“Why this date?” → “Show the rules”", `${kind}: the date receipt with the law's steps.`, async (c) => {
      const b = c.page.getByRole("article").first().getByRole("button", { name: /Why this date\?/ });
      if (!(await c.exists(b))) c.notApplicable("no “Why this date?” on the verdict");
      await c.click(b);
      if (await c.exists(c.page.getByRole("button", { name: "Show the rules" }))) await c.click(c.page.getByRole("button", { name: "Show the rules" }));
    });
    if (kind === "landlord_notice" || kind === "court_payment_order" || kind === "enforcement_order") {
      at("objection", "open the composer's objection for it", `${kind}: the composer's objection with the statutory note.`, async (c, id) => {
        await c.goto(`/letters?kind=objection&doc=${id}`);
        await c.visible(c.page.getByRole("dialog", { name: "New letter" }));
        await settle(c.page);
      });
    }
    if (kind === "court_payment_order" || kind === "dismissal") {
      at("extension-refused", "open “Ask for more time” for it", `${kind}: “Ask for more time” refused (a deadline set by law).`, async (c, id) => {
        await c.goto(`/letters?kind=extension_request&doc=${id}`);
        await c.visible(c.page.getByRole("dialog", { name: "New letter" }));
        await settle(c.page);
      });
    }
    if (kind === "court_payment_order") {
      // the re-filed reminder's sender is the claimant, not a court: the objection goes to the court typed in
      // (review round 3 of phase 2 — it went to the claimant)
      const court = "Amtsgericht Hünfeld\nZentrales Mahngericht\n36088 Hünfeld";
      at("objection-letter", "create its objection to the court typed in (POST /api/drafts, once per setup) and open the letter", `${kind}: the objection to the court and how to send it (e-mail isn't valid at a court).`, async (c, id) => {
        // one draft for all of this state's captures (review round 4 of phase 2: each of its 10 captures, 3 at a
        // time, made another, and the Letters list behind the composer showed 10 identical drafts)
        let pending = hsObjectionDrafts.get(id);
        if (!pending) {
          pending = c.api.post("/api/drafts", { kind: "objection", doc_id: id, language: "en", details: { recipient: court } });
          hsObjectionDrafts.set(id, pending);
        }
        const draft = await pending;
        await c.goto(`/letters/${draft.id}`);
      });
      at("objection-court-typed", "open the composer's objection for it and type the court", `${kind}: the objection asks for the court (its sender, as filed, is the claimant) — typed in.`, async (c, id) => {
        await c.goto(`/letters?kind=objection&doc=${id}`);
        const d = await c.visible(c.page.getByRole("dialog", { name: "New letter" }));
        const box = d.getByLabel("The court that sent the order");
        if (!(await c.exists(box))) c.notApplicable("no court field (the letter's sender is a court)");
        await box.fill(court);
        await settle(c.page);
      });
      at("objection-court-wrong", "open the composer's objection for it and type the claimant as the court", `${kind}: a typed name that is no court is refused before anything is written.`, async (c, id) => {
        await c.goto(`/letters?kind=objection&doc=${id}`);
        const d = await c.visible(c.page.getByRole("dialog", { name: "New letter" }));
        const box = d.getByLabel("The court that sent the order");
        if (!(await c.exists(box))) c.notApplicable("no court field (the letter's sender is a court)");
        await box.fill("TechMarkt Online GmbH");
        await box.focus();
        await settle(c.page);
      });
    }
    if (kind === "landlord_notice") {
      at("all-steps", "click “Show all … steps” on the advice card", `${kind}: the advice card unfolded to all its steps.`, async (c) => {
        const b = main(c.page).getByRole("button", { name: /^Show all \d+ steps$/ });
        if (!(await c.exists(b))) c.notApplicable("the card has no folded steps");
        await c.click(b);
      });
    }
    if (kind === "court_payment_order") {
      at("payment-plan", "open “Pay in instalments” for it", `${kind}: “Pay in instalments” refused for the court (offer them to the claimant).`, async (c, id) => {
        await c.goto(`/letters?kind=payment_plan&doc=${id}`);
        await c.visible(c.page.getByRole("dialog", { name: "New letter" }));
        await settle(c.page);
      });
      at("payment-plan-claimant", "open “Pay in instalments” for it, then “Write to the claimant instead”", `${kind}: instalments to the claimant — the typed claimant field.`, async (c, id) => {
        await c.goto(`/letters?kind=payment_plan&doc=${id}`);
        const d = await c.visible(c.page.getByRole("dialog", { name: "New letter" }));
        const b = d.getByRole("button", { name: "Write to the claimant instead" });
        if (!(await c.exists(b))) c.notApplicable("no “Write to the claimant instead”");
        await c.click(b);
      });
    }
  }
  /** A fresh demo folder with the HS_KINDS letters re-filed by the kind picker's PATCH. */
  const setUpHighStakes = async (restart) => {
    await restart("high-stakes");
    hsObjectionDrafts.clear();
    await setTour(api, null);
    const docs3 = await api.get("/api/documents");
    for (const [re, kind] of HS_KINDS) {
      const d = docs3.find((x) => re.test(x.filename ?? ""));
      if (d) {
        await api.patch(`/api/documents/${d.id}`, { kind });
        hsDocs[kind] = d.id;
      }
    }
  };
  // "I've dealt with this" changes the letter: one capture at a time, each starting from the untouched card
  const hsDealt = [];
  const landlordRe = HS_KINDS.find(([, k]) => k === "landlord_notice")?.[0];
  if (landlordRe && docs.some((x) => landlordRe.test(x.filename ?? ""))) {
    hsDealt.push({
      id: "hs-landlord-notice--dealt-with",
      group: "high-stakes",
      route: "/documents/…",
      how: "the lease re-filed as landlord_notice, its tags cleared, open it, click “I've dealt with this”",
      description: "landlord_notice: marked as dealt with (the handled card, “Not dealt with yet”, the toast).",
      pinToasts: true,
      run: async (c) => {
        const id = hsDocs.landlord_notice;
        if (!id) throw new Error("landlord_notice was not set up");
        await c.api.patch(`/api/documents/${id}`, { tags: [] });
        await c.goto(`/documents/${id}`);
        const b = main(c.page).getByRole("button", { name: "I've dealt with this" });
        if (!(await c.exists(b))) c.notApplicable("the card can't be closed by the person (its objection to-do closes it: hs-landlord-notice--handled)");
        await c.click(b, { settleAfter: false });
        await c.page.getByText("You marked this letter as dealt with").first().waitFor({ timeout: 10_000 });
        await settle(c.page);
        await pinToasts(c.page);
      },
    });
    hsDealt.push({
      id: "hs-landlord-notice--handled",
      group: "high-stakes",
      route: "/documents/…",
      how: "the lease re-filed as landlord_notice, its law to-dos marked done (PATCH status), open it",
      description: "landlord_notice: every to-do with the law's deadline done — the card is no longer urgent and its title says so.",
      run: async (c) => {
        const id = hsDocs.landlord_notice;
        if (!id) throw new Error("landlord_notice was not set up");
        const items = await c.api.get(`/api/items?doc_id=${id}`);
        const law = items.filter((i) => i.origin === "rule" && i.status === "open");
        if (!law.length && !items.some((i) => i.origin === "rule")) c.notApplicable("the letter has no to-do with the law's deadline");
        for (const i of law) await c.api.patch(`/api/items/${i.id}`, { status: "done" });
        await c.goto(`/documents/${id}`);
      },
    });
  }
  // the arrival question: the letter's arrival day is cleared (the demo's letters have one), then a day before
  // the letter's own date is entered — the field says why it can't be saved (WCAG 3.3.1)
  const dismissalRe = HS_KINDS.find(([, k]) => k === "dismissal")?.[0];
  if (dismissalRe && docs.some((x) => dismissalRe.test(x.filename ?? ""))) {
    hsDealt.push({
      id: "hs-dismissal--arrival-before-letter",
      group: "high-stakes",
      route: "/documents/…",
      how: "the work contract re-filed as dismissal, its arrival day cleared (PATCH received_date), open it, enter a day three days before the letter's date",
      description: "dismissal: nothing filled in, the Zugang wording, and the message for a day before the letter's own date.",
      run: async (c) => {
        const id = hsDocs.dismissal;
        if (!id) throw new Error("dismissal was not set up");
        await c.api.patch(`/api/documents/${id}`, { received_date: null });
        await c.goto(`/documents/${id}`);
        const input = c.page.locator("#arrival-date");
        if (!(await c.exists(input))) c.notApplicable("no arrival question");
        const min = await input.getAttribute("min");
        if (!min) c.notApplicable("the letter has no date");
        const day = new Date(`${min}T12:00:00Z`);
        day.setUTCDate(day.getUTCDate() - 3);
        await input.fill(day.toISOString().slice(0, 10));
        await c.centre(input);
        await settle(c.page);
      },
    });
  }

  return {
    phases: [
      { name: "main", parallel: true, states: S },
      { name: "tour", parallel: false, states: tour, after: async () => setTour(api, null) },
      {
        name: "mutations",
        parallel: false,
        states: mutations,
        before: async ({ restart }) => {
          await restart("mutations");
          await setTour(api, null);
          const docs2 = await api.get("/api/documents");
          const contracts2 = await api.get("/api/contracts");
          const find = (d) => docs2.find((x) => x.filename === d?.filename);
          const od = find(objectionDoc);
          const rd = find(replyDoc);
          if (od) extra.objection = await api.post("/api/drafts", { kind: "objection", doc_id: od.id, party_id: od.party_id, language: "en" });
          if (rd)
            extra.reply = await api.post("/api/drafts", {
              kind: "general_reply",
              doc_id: rd.id,
              party_id: rd.party_id,
              instructions: "Please send me the receipts for the operating-costs statement and let me pay in two instalments.",
              language: "en",
            });
          const gym = contracts2.find((c) => /FitWell/.test(c.name)) ?? contracts2.find((c) => c.id !== phoneContract?.id);
          if (gym) {
            const d = await api.post("/api/drafts", { kind: "cancellation", contract_id: gym.id, doc_id: gym.source_doc_id ?? null, party_id: gym.party_id ?? null, language: "en" });
            await api.post(`/api/drafts/${d.id}/sent`, { channel: "registered_letter", date: "2026-09-26" });
            extra.sent = d;
          }
          const phone = contracts2.find((c) => /FunkNetz/.test(c.name));
          if (phone) {
            const d2 = await api.post("/api/drafts", { kind: "cancellation", contract_id: phone.id, doc_id: phone.source_doc_id ?? null, party_id: phone.party_id ?? null, language: "en" });
            await api.post(`/api/drafts/${d2.id}/sent`, { channel: "registered_letter", date: "2026-09-10", tracking_number: "1234 5678 9012" });
            extra.sent2 = d2;
            const upload = async (name, mimeType, buffer, kind, onDate, note) => {
              const fd = new FormData();
              fd.append("file", new Blob([buffer], { type: mimeType }), name);
              fd.append("kind", kind);
              if (onDate) fd.append("on_date", onDate);
              if (note) fd.append("note", note);
              const r = await fetch(`${server.base}/api/drafts/${d2.id}/proofs`, { method: "POST", headers: { Authorization: `Bearer ${server.token()}`, "X-Ordnung-Client": "web" }, body: fd });
              if (!r.ok) throw new Error(`proof upload failed: ${r.status} ${await r.text()}`);
            };
            if (photoPages[0])
              await upload(
                "IMG_20260910_Einlieferungsbeleg_Einwurf-Einschreiben_FunkNetz_Kundenkuendigung_Vertragsnummer_998877665544.jpg",
                "image/jpeg",
                photoPages[0].buffer,
                "posting_receipt",
                "2026-09-10",
                "Postfiliale im Hauptbahnhof, Schalter 3 — die Mitarbeiterin hat den Umschlag vor meinen Augen gewogen und abgestempelt; Zeugin: meine Nachbarin Frau Kowalczyk-Hernández.",
              );
            await upload("Sendungsverfolgung.txt", "text/plain", Buffer.from("Sendung zugestellt am 12.09.2026"), "delivery_record", "2026-09-12", null);
            await upload("scan.pdf", "application/pdf", await api.raw(`/api/documents/${docs2[0].id}/file`), "other", null, "Kopie des Briefes mit Unterschrift, eingescannt, bevor er in den Umschlag kam");
            if (phone.party_id) {
              await api.post("/api/calls", {
                party_id: phone.party_id,
                called_on: "2026-09-02",
                contact: "Herr Maximilian Kundenservicemitarbeiter-Oberreiter (Kündigungsabteilung, Durchwahl 0800-123456789)",
                summary: "Rang wegen der Kündigung an. Er sagte, die Kündigung sei eingegangen, aber die Bestätigung komme erst nach Prüfung der Mindestvertragslaufzeit.\nEr wollte zurückrufen.",
                promise: "Schriftliche Kündigungsbestätigung mit Beendigungsdatum und Erstattung des zu viel gezahlten Grundpreises",
                promise_due: "2026-09-09",
                promise_amount: 1234.56,
              });
              await api.post("/api/calls", { party_id: phone.party_id, called_on: "2026-09-20", summary: "Kurz nachgefragt.", promise: "Rückruf", promise_due: "2026-10-30" });
            }
          }
        },
      },
      { name: "mail", parallel: false, states: mailStates },
      folderPhase({ api, server }),
      {
        name: "high-stakes",
        parallel: true,
        states: hsStates,
        before: async ({ restart }) => setUpHighStakes(restart),
      },
      {
        name: "high-stakes-dealt-with",
        parallel: false,
        states: hsDealt,
        // run on its own (--only), the high-stakes phase's setup was skipped
        before: async ({ restart }) => (Object.keys(hsDocs).length ? undefined : setUpHighStakes(restart)),
      },
    ],
  };
}

/** Read a New-mail letter the way the e2e helper does, or open the letter it already became. */
async function openMail(c, sender) {
  const tray = await c.api.get("/api/demo/mail");
  const item = tray.find((t) => t.sender.startsWith(sender));
  if (!item) throw new Error(`no New-mail letter from ${sender}`);
  if (item.opened && item.doc_id) {
    await c.goto(`/documents/${item.doc_id}`);
    return;
  }
  await c.goto("/inbox");
  const env = c.page.getByRole("region", { name: /^New mail/ }).getByRole("listitem").filter({ hasText: sender }).first();
  await c.click(env.getByRole("button", { name: "Let Ordnung read it" }), { settleAfter: false });
  await c.page.waitForURL(/\/documents\/doc_/, { timeout: 60_000 });
  await settle(c.page);
}
