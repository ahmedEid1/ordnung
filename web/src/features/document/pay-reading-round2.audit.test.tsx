/**
 * UI audit round 2, bucket "document-pay-reading": the letter's Pay panel says a copy on its button (no toast
 * over its footer or behind a phone's sheet) and names, orders and checks the details as Today's does; after
 * "Mark as paid" focus goes on to the verdict; "Read the letter again" in the GiroCode block follows the
 * reading to its end; reading a letter again says so above the verdict (no second title) and a failed re-read
 * says the verdict is the earlier reading; a waiting letter's title keeps its dates and references whole, in
 * the detail-title size, where the verdict's and the "How it was read" tab's sit, and says "Claude".
 */
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { makeTestQueryClient, renderWithProviders } from "@/test/render";
import { useMockApi } from "@/test/mockFetch";
import { qk } from "@/api/hooks";
import { __resetEventsForTests, handleServerEvent, seedJob, useJobProgress } from "@/api/sse";
import type { DocumentDetail } from "@/api/types";
import { Toaster, __clearToasts } from "@/components/ui/Toast";
import { FileNameText } from "@/components/ui/FileNameText";
import { UploadCenter, setUploadToastHidden } from "@/components/shell/UploadCenter";
import { GIROCODES } from "@/mocks/data/girocodes";
import { GIROCODE_READ_AGAIN, GIROCODE_READING_AGAIN, GiroCodeSection } from "@/features/girocode/GiroCode";
import { MEANING_ICONS } from "@/lib/copy";
import { plainText } from "@/lib/glue";
import { DocumentView } from "./DocumentView";
import { HeldCard } from "./HeldCard";
import { PayPanel } from "./PayPanel";
import { ProcessingCard, wasReadBefore } from "./ProcessingCard";
import { TracePanel } from "./trace/TracePanel";
import { makeDetail, makeDoc, makeItem } from "./fixtures";

beforeEach(() => {
  vi.stubGlobal("scrollTo", () => {});
  __resetEventsForTests();
});
afterEach(() => {
  vi.unstubAllGlobals();
  act(() => __clearToasts());
});

async function detail(srv: ReturnType<typeof useMockApi>["srv"], id: string): Promise<DocumentDetail> {
  srv.openAllMail();
  return (await (await srv.handle("GET", `/documents/${id}`, new URLSearchParams(), undefined)).json()) as DocumentDetail;
}

function client() {
  const qc = makeTestQueryClient();
  qc.setQueryData(qk.rules, []);
  return qc;
}

describe("the letter's Pay panel (R2-document-pay-reading-1, -2, -4)", () => {
  it("says a copy on its button — no toast over its footer or behind the sheet — with Today's names and order", async () => {
    const { srv } = useMockApi();
    const user = userEvent.setup();
    const d = await detail(srv, "doc_nebenkosten");
    renderWithProviders(
      <>
        <DocumentView detail={d} />
        <Toaster />
      </>,
      { client: client() },
    );
    await user.click(screen.getByRole("button", { name: /^Pay €184\.30/ }));
    const panel = await screen.findByRole("dialog", { name: "Pay" });
    // the bank form's order, under the names Today's panel uses
    expect(within(panel).getAllByRole("term").map((t) => t.textContent)).toEqual(["Recipient", "IBAN", "Amount", "Reference"]);
    await user.click(within(panel).getByRole("button", { name: "Copy IBAN" }));
    expect(await navigator.clipboard.readText()).toBe(d.document.payment!.iban!.replace(/\s+/g, ""));
    const copied = within(panel).getByRole("button", { name: "IBAN copied" });
    expect(copied).toHaveTextContent("Copied");
    expect(within(panel).getByText("IBAN copied")).toHaveAttribute("aria-live", "polite");
    expect(document.querySelector("[data-toast]")).toBeNull();
    // the footer: the letter's own "Close" (a sheet has its own) and "Mark as paid", as on Today
    expect(within(panel).queryByRole("button", { name: "I've paid it" })).toBeNull();
    expect(within(panel).getByRole("button", { name: "Mark as paid" })).toHaveClass("ml-auto");
  });

  it("says in the panel when the clipboard is blocked", async () => {
    const user = userEvent.setup();
    vi.spyOn(navigator.clipboard, "writeText").mockRejectedValue(new Error("blocked"));
    Object.defineProperty(document, "execCommand", { value: () => false, configurable: true });
    const doc = makeDoc({ payment: { iban: "DE70123478000048213000", payee: "TechMarkt Online GmbH", iban_valid: true, reference: "TM-2026-0048213" } });
    const item = makeItem({ kind: "payment", direction: "out", amount: 94.99, currency: "EUR" });
    renderWithProviders(
      <>
        <PayPanel item={item} doc={doc} onPaid={() => {}} />
        <Toaster />
      </>,
      { client: client() },
    );
    await user.click(screen.getByRole("button", { name: "Copy reference" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't copy — your browser blocked the clipboard. Select the text and copy it by hand.");
    expect(screen.getByRole("button", { name: "Copy reference" })).toBeInTheDocument();
    expect(document.querySelector("[data-toast]")).toBeNull();
  });

  it("shows the IBAN's valid check digits, as Today does, and keeps a reference whole", () => {
    const doc = makeDoc({ payment: { iban: "DE70123478000048213000", payee: "TechMarkt Online GmbH", iban_valid: true, reference: "TM-2026-0048213" } });
    renderWithProviders(<PayPanel item={makeItem({ kind: "payment", direction: "out", amount: 94.99 })} doc={doc} onPaid={() => {}} />, { client: client() });
    expect(screen.getByText("The IBAN's check digits are valid — that only rules out typos, not fraud.")).toBeInTheDocument();
    const reference = screen.getByText((_, el) => el?.tagName === "DD" && plainText(el.textContent ?? "") === "TM-2026-0048213");
    expect(reference.textContent).toBe("TM‑2026‑0048213");
  });

  it("after “Mark as paid”, keyboard focus goes on to the verdict's heading — never <body>", async () => {
    const { srv, calls } = useMockApi();
    const user = userEvent.setup();
    renderWithProviders(<DocumentView detail={await detail(srv, "doc_nebenkosten")} />, { client: client() });
    await user.click(screen.getByRole("button", { name: /^Pay €184\.30/ }));
    const panel = await screen.findByRole("dialog", { name: "Pay" });
    await user.click(within(panel).getByRole("button", { name: "Mark as paid" }));
    await waitFor(() => expect(document.activeElement).toBe(document.getElementById("verdict-title")));
    expect(document.activeElement?.tagName).toBe("H1");
    await waitFor(() => expect(calls.some((c) => c.method === "PATCH" && c.path.startsWith("/items/") && (c.body as { status?: string }).status === "done")).toBe(true));
  });
});

describe("“Read the letter again” in the GiroCode block (R2-document-pay-reading-3)", () => {
  /** The reading's progress as the page has it (the job asked for). */
  function Job() {
    const job = useJobProgress("doc_parking");
    return <span data-testid="job">{job?.job_id ?? ""}</span>;
  }

  /** The block in a panel that can be closed, beside the app's progress cards. */
  function Panel() {
    const [open, setOpen] = useState(true);
    return (
      <>
        <button type="button" onClick={() => setOpen(false)}>
          Close the panel
        </button>
        {open ? <GiroCodeSection code={GIROCODES.itm_parking} docId="doc_parking" canReadAgain /> : null}
        <Job />
        <UploadCenter />
      </>
    );
  }
  const cards = () => screen.getByRole("list", { name: "Letters being read" }).querySelectorAll("[data-upload-row]");

  /** (Under `useMockApi()`.) */
  async function askToReadAgain() {
    const user = userEvent.setup();
    renderWithProviders(<Panel />, { client: client() });
    await user.click(screen.getByRole("button", { name: "They don't match" }));
    const button = screen.getByRole("button", { name: "Read the letter again" });
    await user.click(button);
    expect(await screen.findByText(GIROCODE_READING_AGAIN)).toBeInTheDocument();
    await waitFor(() => expect(button).toHaveAttribute("aria-disabled", "true"));
    await waitFor(() => expect(screen.getByTestId("job")).not.toHaveTextContent(/^$/));
    const jobId = screen.getByTestId("job").textContent!;
    const end = (status: "done" | "failed", error?: string) =>
      act(() => handleServerEvent(makeTestQueryClient(), { type: "job.progress", data: { job_id: jobId, doc_id: "doc_parking", stage: "done", progress: 1, status, error } }));
    return { user, button, end };
  }

  it("says when the reading is done and offers it again — also once the page drops the finished job", async () => {
    const { calls } = useMockApi();
    const { user, button, end } = await askToReadAgain();
    end("done");
    expect(screen.getByText(GIROCODE_READ_AGAIN)).toHaveAttribute("role", "status");
    expect(screen.queryByText(GIROCODE_READING_AGAIN)).toBeNull();
    expect(button).not.toHaveAttribute("aria-disabled");
    expect(button).toHaveFocus();
    // the letter's page drops a finished job from the progress list: the answer stays
    act(() => __resetEventsForTests());
    expect(screen.getByText(GIROCODE_READ_AGAIN)).toBeInTheDocument();
    // and it can be asked again
    await user.click(button);
    await waitFor(() => expect(calls.filter((c) => c.path === "/documents/doc_parking/reprocess")).toHaveLength(2));
    expect(await screen.findByText(GIROCODE_READING_AGAIN)).toBeInTheDocument();
  });

  it("while it follows the reading, no progress card covers the panel; said done, none comes once it closes", async () => {
    useMockApi();
    const { user, end } = await askToReadAgain();
    expect(cards()).toHaveLength(0);
    end("done");
    expect(cards()).toHaveLength(0);
    await user.click(screen.getByRole("button", { name: "Close the panel" }));
    expect(cards()).toHaveLength(0);
    expect(screen.getByTestId("job")).toHaveTextContent(/^$/);
  });

  it("a progress card stays hidden while any place still shows the progress (the letter's card and the block)", () => {
    renderWithProviders(<UploadCenter />, { client: client() });
    act(() => {
      setUploadToastHidden("doc_parking", true);
      setUploadToastHidden("doc_parking", true);
      seedJob({ job_id: "job_1", doc_id: "doc_parking", stage: "extract", progress: 0.3, status: "running" });
    });
    act(() => setUploadToastHidden("doc_parking", false));
    expect(cards()).toHaveLength(0);
    act(() => setUploadToastHidden("doc_parking", false));
    expect(cards()).toHaveLength(1);
  });

  it("closed while the letter is read, the progress card shows it instead", async () => {
    useMockApi();
    const { user } = await askToReadAgain();
    expect(cards()).toHaveLength(0);
    await user.click(screen.getByRole("button", { name: "Close the panel" }));
    expect(cards()).toHaveLength(1);
  });

  it("says why a reading failed, in the block", async () => {
    useMockApi();
    const { button, end } = await askToReadAgain();
    end("failed", "Claude couldn't read this photo — it is too blurry.");
    expect(screen.getByRole("alert")).toHaveTextContent("Couldn't read the letter again: Claude couldn't read this photo — it is too blurry.");
    expect(screen.queryByText(GIROCODE_READING_AGAIN)).toBeNull();
    expect(button).not.toHaveAttribute("aria-disabled");
  });
});

describe("reading a letter again (R2-document-pay-reading-5, -7)", () => {
  const appointment = { title: "Dental appointment reminder", kind: "appointment" as const };
  const blurry = "Claude couldn't read this photo — it is too blurry.";

  it("a failed re-read says so — and that what's below is the earlier reading — with no heading before the verdict's", () => {
    renderWithProviders(<ProcessingCard doc={makeDoc({ ...appointment, status: "failed", error: blurry })} />, { client: client() });
    const card = screen.getByRole("alert");
    expect(within(card).getByText("Couldn't read it again")).toBeInTheDocument();
    expect(card).toHaveTextContent(`What's shown below is from the earlier reading. ${blurry} Your file is safe.`);
    expect(within(card).queryByRole("heading")).toBeNull();
    expect(within(card).queryByText(/Ordnung couldn't read this letter/)).toBeNull();
    expect(within(card).getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("a failed first reading is the page's heading (no verdict shows)", () => {
    renderWithProviders(<ProcessingCard doc={makeDoc({ title: null, kind: null, status: "failed", error: blurry })} />, { client: client() });
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Ordnung couldn't read this letter");
    expect(screen.queryByText(/earlier reading/)).toBeNull();
  });

  it("reading it again: a line above the verdict — its title isn't said twice", () => {
    renderWithProviders(<ProcessingCard doc={makeDoc({ ...appointment, status: "processing" })} />, { client: client() });
    expect(screen.getByText("Reading it again")).toBeInTheDocument();
    expect(screen.queryByRole("heading")).toBeNull();
    expect(screen.queryByText("Dental appointment reminder")).toBeNull();
  });

  it("a first reading titles the page with the file's name, broken after its underscores", () => {
    renderWithProviders(<ProcessingCard doc={makeDoc({ title: null, kind: null, filename: "Scan_2026-09-28_0914.pdf", status: "processing" })} />, { client: client() });
    expect(screen.getByText("Reading your letter")).toBeInTheDocument();
    const h1 = screen.getByRole("heading", { level: 1 });
    expect(plainText(h1.textContent ?? "")).toBe("Scan_2026-09-28_0914.pdf");
    expect(h1.querySelectorAll("wbr")).toHaveLength(2);
  });

  it("counts a letter as read before when the page shows its verdict", () => {
    expect(wasReadBefore({ title: "Invoice", kind: null })).toBe(true);
    expect(wasReadBefore({ title: null, kind: "invoice" })).toBe(true);
    expect(wasReadBefore({ title: null, kind: null })).toBe(false);
  });
});

describe("a waiting letter's title (R2-document-pay-reading-8, -9)", () => {
  it("keeps a file name's date and a reference whole: it breaks only after an underscore", () => {
    const { container } = renderWithProviders(
      <>
        <p data-testid="a">
          <FileNameText name="Rechnung_2026-09_FunkNetz.pdf" />
        </p>
        <p data-testid="b">
          <FileNameText name="Rechnung_FN-5521904-2026.pdf" />
        </p>
      </>,
    );
    const a = screen.getByTestId("a");
    expect(a.textContent).toBe("Rechnung_2026‑09_FunkNetz.pdf");
    expect(a.querySelectorAll("wbr")).toHaveLength(2);
    expect(screen.getByTestId("b").textContent).toBe("Rechnung_FN‑5521904‑2026.pdf");
    expect(plainText(container.textContent ?? "")).toBe("Rechnung_2026-09_FunkNetz.pdfRechnung_FN-5521904-2026.pdf");
  });

  it("an e-mail's subject keeps its reference whole, its file name under it; named as written", () => {
    const doc = makeDoc({ status: "held", source: "folder", title: "Ihre Rechnung FN-5521904-2026 · FunkNetz", filename: "Rechnung_2026-09_FunkNetz.eml" });
    renderWithProviders(<HeldCard detail={makeDetail({ document: doc })} />, { client: client() });
    const card = screen.getByRole("article", { name: "Ihre Rechnung FN-5521904-2026 · FunkNetz" });
    const h1 = within(card).getByRole("heading", { level: 1 });
    expect(h1.textContent).toBe("Ihre Rechnung FN‑5521904‑2026 · FunkNetz");
    expect(h1.className).toMatch(/\btext-detail\b/);
    expect(within(card).getByText((_, el) => el?.tagName === "P" && el.textContent === "Rechnung_2026‑09_FunkNetz.eml")).toBeInTheDocument();
  });

  it("uses the Inbox's “not read yet” icon, not the deadline's hourglass, in a row as tall as the verdict's badges", () => {
    const doc = makeDoc({ status: "held", source: "folder", title: null, filename: "Scan_2026-09-28_0914.pdf" });
    renderWithProviders(<HeldCard detail={makeDetail({ document: doc })} />, { client: client() });
    const eyebrow = screen.getByText("Not read yet");
    expect(eyebrow).toHaveClass("min-h-7");
    const { container: inbox } = renderWithProviders(<MEANING_ICONS.notReadYet />);
    const icon = eyebrow.querySelector("svg")!;
    expect(icon.getAttribute("class")).toContain(inbox.querySelector("svg")!.getAttribute("class")!.split(" ")[1]!);
    expect(icon.getAttribute("class")).not.toMatch(/hourglass/);
    // the title where the verdict's sits: under a 28 px row, 12 px down
    expect(screen.getByRole("heading", { level: 1 })).toHaveClass("mt-3");
  });
});

describe("the “How it was read” tab's heading (R2-document-pay-reading-9)", () => {
  it("sits in a card like the verdict's, under a badge row, in the detail-title size", async () => {
    const { srv } = useMockApi();
    renderWithProviders(<TracePanel detail={await detail(srv, "doc_nebenkosten")} />, { client: client() });
    const h1 = screen.getByRole("heading", { level: 1, name: "Utility cost statement 2025" });
    expect(h1.className).toMatch(/\btext-detail(-long)?\b/);
    expect(h1).toHaveClass("mt-3");
    const header = h1.closest("header")!;
    expect(header).toHaveClass("card", "px-5", "pt-5", "sm:px-6", "sm:pt-6");
    expect(header.firstElementChild).toHaveClass("min-h-7");
    await screen.findByRole("heading", { level: 2, name: /^Read on/ });
  });

  it("a waiting letter's tab says “Not read yet” over its title, as its card does", async () => {
    const { srv } = useMockApi();
    const d = await detail(srv, "doc_folder_scan");
    renderWithProviders(<TracePanel detail={d} />, { client: client() });
    const header = screen.getByRole("heading", { level: 1 }).closest("header")!;
    expect(within(header).getByText("Not read yet")).toBeInTheDocument();
  });
});
