/**
 * The watched folder on the live demo (SPEC § 8.1): a phase on its own demo data folder with a real
 * folder next to it — a scan and an e-mail with a PDF attached, copied from the demo's samples (with
 * a comment appended, so they are new to Ordnung). The demo only replays recorded answers, so the
 * watcher holds every file: the Inbox's "From your folder — waiting for you", the waiting letters, an
 * e-mail's attachments, and Settings → Watched folder (watching, a refused path, a missing folder).
 */
import { copyFileSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { pinToasts, settle } from "../browser.mjs";
import { inMain } from "../steps.mjs";

const SAMPLES = (webDir) => join(webDir, "..", "src", "ordnung", "demo", "samples");

/** A sample PDF made new to Ordnung: a comment after `%%EOF` changes its hash, not what it shows. */
function freshPdf(webDir, sample, tag) {
  return Buffer.concat([readFileSync(join(SAMPLES(webDir), sample)), Buffer.from(`\n% ui-audit copy: ${tag}\n`)]);
}

/** An e-mail (RFC 822) with one PDF attached, as a mail client saves it. */
function emailWithPdf(pdf, filename) {
  const boundary = "ordnung-audit-boundary";
  const body = pdf.toString("base64").replace(/.{76}/g, "$&\r\n");
  return [
    "From: FunkNetz Kundenservice <rechnung@funknetz.example>",
    "To: Sam Rivera <sam.rivera@example.org>",
    "Subject: Ihre Rechnung September 2026",
    "Date: Sun, 27 Sep 2026 18:02:00 +0200",
    "MIME-Version: 1.0",
    `Content-Type: multipart/mixed; boundary="${boundary}"`,
    "",
    `--${boundary}`,
    "Content-Type: text/plain; charset=utf-8",
    "",
    "Guten Tag Sam Rivera,",
    "",
    "Ihre Rechnung für September 2026 finden Sie im Anhang. SPECIMEN",
    "",
    `--${boundary}`,
    `Content-Type: application/pdf; name="${filename}"`,
    `Content-Disposition: attachment; filename="${filename}"`,
    "Content-Transfer-Encoding: base64",
    "",
    body,
    `--${boundary}--`,
    "",
  ].join("\r\n");
}

export function folderPhase({ api, server }) {
  const docs = {};
  const S = [];
  const add = (id, route, how, description, run, extra = {}) => S.push({ id, group: "folder", route, how, description, run, ...extra });
  const openDoc = (key) => async (c) => {
    if (!docs[key]) throw new Error(`the ${key} letter was not picked up`);
    await c.goto(`/documents/${docs[key]}`);
  };

  add("folder-inbox-waiting", "/inbox", "open /inbox with three files from the watched folder waiting", "Inbox: “From your folder — waiting for you” with a scan, an e-mail and its attachment.", (c) =>
    c.goto("/inbox"),
  );
  add(
    "folder-inbox-read-demo",
    "/inbox",
    "open /inbox, click “Read these 3” (the demo can't read new letters)",
    "The replay-only demo refuses “Read these” with its explanation.",
    async (c) => {
      await c.goto("/inbox");
      await c.click(inMain(c.page).getByRole("button", { name: /^Read these \d+ with Claude/ }), { settleAfter: false });
      await c.wait(600);
      await pinToasts(c.page);
      await settle(c.page, { idle: false });
    },
    { pinToasts: true },
  );
  add("folder-settings-watching", "/settings?section=folder", "open /settings?section=folder", "Settings → Watched folder: watching, three letters waiting, the last files.", (c) =>
    c.goto("/settings?section=folder"),
  );
  add("folder-doc-held", "/documents/…", "open the waiting scan", "A waiting letter: “Read it with Claude” / “Keep private”, its page image.", openDoc("scan"));
  add("folder-doc-held-email", "/documents/…", "open the waiting e-mail", "A waiting e-mail and what became of its attachment.", openDoc("mail"));
  add("folder-doc-held-attachment", "/documents/…", "open the e-mail's waiting PDF", "A waiting attachment: “Came with an e-mail”.", openDoc("attachment"));
  add("folder-today-waiting", "/", "open / (Today) while three letters from the folder wait", "Today says letters wait (its card above Top 3) instead of “all clear”; the Inbox's count includes them.", (c) =>
    c.goto("/"),
  );
  add(
    "folder-settings-refused",
    "/settings?section=folder",
    "open /settings?section=folder, type the relative path “Scans” and save",
    "The server's reason under the folder field; the save bar says what to fix.",
    async (c) => {
      await c.goto("/settings?section=folder");
      const field = inMain(c.page).getByLabel("Folder", { exact: true });
      await field.fill("");
      await c.type(field, "Scans");
      await c.click(inMain(c.page).getByRole("button", { name: "Save changes" }), { settleAfter: false });
      await c.page.getByText(/full folder path/).first().waitFor({ timeout: 10_000 }).catch(() => c.note("no reason under the field"));
      await settle(c.page);
    },
  );
  add(
    "folder-settings-problem",
    "/settings?section=folder",
    "set the folder to one that doesn't exist (PUT /api/settings), open /settings?section=folder",
    "A folder Ordnung can't find: “Not watching right now” with what to do.",
    async (c) => {
      await api.put("/api/settings", { inbox_dir: `${server.dataDir}-scans-missing` });
      await c.goto("/settings?section=folder");
      await c.page.getByText(/can't find this folder/).first().waitFor({ timeout: 15_000 }).catch(() => c.note("no problem shown"));
      await settle(c.page);
    },
  );

  // last: it answers for the scan (and makes it wait again first, for every viewport and theme)
  add(
    "folder-doc-kept-private",
    "/documents/…",
    "open the waiting scan, click “Keep private”",
    "The toast with Undo; the verdict says the letter wasn't read and offers “Undo “Keep private””; focus on its title.",
    async (c) => {
      await api.post("/api/documents/held/wait", { doc_ids: [docs.scan] });
      await openDoc("scan")(c);
      await c.click(inMain(c.page).getByRole("button", { name: "Keep private" }), { settleAfter: false });
      await c.wait(800);
      await pinToasts(c.page);
      await settle(c.page, { idle: false });
    },
    { pinToasts: true },
  );

  return {
    name: "folder",
    parallel: false,
    states: S,
    before: async ({ restart }) => {
      await restart("folder");
      await api.patch("/api/demo/tour", { active: false, completed: true });
      const folder = `${server.dataDir}-scans`;
      rmSync(folder, { recursive: true, force: true });
      mkdirSync(folder, { recursive: true });
      writeFileSync(join(folder, "Scan_2026-09-28_0914.pdf"), freshPdf(server.webDir, "17_auslaenderbehoerde_termin.pdf", "scan"));
      writeFileSync(join(folder, "Ihre Rechnung September 2026.eml"), emailWithPdf(freshPdf(server.webDir, "08_rechnung_techmarkt.pdf", "mail"), "Rechnung_2026-09.pdf"));
      copyFileSync(join(SAMPLES(server.webDir), "manifest.json"), join(folder, ".not-a-letter.json")); // a dotfile: ignored
      await api.put("/api/settings", { inbox_dir: folder });
      for (let i = 0; i < 240; i += 1) {
        const status = await api.get("/api/folder");
        if (status.waiting >= 3) break;
        await new Promise((r) => setTimeout(r, 250));
      }
      const waiting = await api.get("/api/documents?status=held");
      docs.scan = waiting.find((d) => d.filename.startsWith("Scan_"))?.id;
      docs.mail = waiting.find((d) => d.filename.endsWith(".eml"))?.id;
      docs.attachment = waiting.find((d) => d.source.startsWith("email:"))?.id;
    },
  };
}
