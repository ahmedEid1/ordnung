/**
 * UI audit round 2, the letter page's verdict, its to-do list and the sections around them: a to-do the
 * server set aside is said once and quietly, a rolling contract has no "decide by … today", references and
 * amounts stay whole, "Why this date?" has no twin tiles, and the loading page has the tabs' row.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { renderWithProviders, makeTestQueryClient } from "@/test/render";
import { qk } from "@/api/hooks";
import type { Contract, DocumentDetail, ItemAside } from "@/api/types";
import { plainText } from "@/lib/glue";
import { VerdictCard } from "./VerdictCard";
import { ItemsList } from "./ItemsList";
import { ContractsSection, ThreadSection } from "./Related";
import { DocumentWarnings } from "./Warnings";
import { DocumentSkeleton } from "./DocumentView";
import { receiptDates } from "./WhyThisDate";
import { selectPrimaryItem } from "./verdict";
import { makeDetail, makeDoc, makeItem, makeReceipt } from "./fixtures";

function client() {
  const qc = makeTestQueryClient();
  qc.setQueryData(qk.rules, []);
  return qc;
}

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify({}), { status: 200, headers: { "Content-Type": "application/json" } })),
  );
});
afterEach(() => vi.unstubAllGlobals());

function renderVerdict(detail: DocumentDetail) {
  renderWithProviders(<VerdictCard detail={detail} primary={selectPrimaryItem(detail.items, detail.set_aside)} />, { client: client() });
  return screen.getByRole("article");
}

const history = (id: string): ItemAside => ({ item_id: id, reason: "history", replaced_by: null });

describe("the verdict says a set-aside to-do once (R2-document-verdict-1)", () => {
  it("lists a dismissal's past law deadlines under 'Probably dealt with' only, never also as 'Also: … overdue'", () => {
    const certificate = makeItem({ id: "cert", kind: "task", title: "Submit enrollment certificate each semester", due_date: "2026-10-15" });
    const court = makeItem({ id: "court", kind: "deadline", origin: "rule", priority: "critical", title: "Get advice now: court action against the dismissal", due_date: "2026-04-10" });
    const register = makeItem({ id: "register", kind: "deadline", origin: "rule", priority: "high", title: "Register as job-seeking", due_date: "2026-03-23" });
    const card = renderVerdict(
      makeDetail({ document: makeDoc({ kind: "dismissal" }), items: [certificate, court, register], set_aside: [history("court"), history("register")] }),
    );
    expect(within(card).queryByRole("list", { name: "Also due by law" })).toBeNull();
    expect(within(card).queryByText(/overdue/)).toBeNull();
    const dealt = within(card).getByRole("list", { name: "Probably dealt with" });
    expect(within(dealt).getAllByRole("listitem")).toHaveLength(2);
    expect(within(dealt).getByText(/Register as job-seeking/)).toBeInTheDocument();
  });

  it("still lists a law deadline that is not set aside, with its countdown", () => {
    const certificate = makeItem({ id: "cert", kind: "task", priority: "critical", title: "Submit enrollment certificate each semester", due_date: "2026-10-15" });
    const register = makeItem({ id: "register", kind: "deadline", origin: "rule", priority: "high", title: "Register as job-seeking", due_date: "2026-10-01" });
    const card = renderVerdict(makeDetail({ document: makeDoc({ kind: "dismissal" }), items: [certificate, register] }));
    const also = within(card).getByRole("list", { name: "Also due by law" });
    expect(within(also).getByText(/Register as job-seeking/)).toBeInTheDocument();
  });
});

describe("the headline and its badge (R2-document-verdict-5, -9)", () => {
  it("keeps an amount with its € sign and uses the detail-title size", () => {
    renderVerdict(makeDetail({ document: makeDoc({ title: "Traffic fine warning (Verwarnung) – 30 € Verwarnungsgeld for parking violation" }) }));
    const h1 = screen.getByRole("heading", { level: 1 });
    expect(h1.textContent).toContain("30 €");
    expect(plainText(h1.textContent ?? "")).toBe("Traffic fine warning (Verwarnung) – 30 € Verwarnungsgeld for parking violation");
    expect(h1).toHaveClass("text-detail");
    // the size comes from the token alone: no fixed sizes or line heights beside it
    expect(h1.className).not.toMatch(/text-\[\d|leading-\[|sm:text-/);
  });

  it("names Claude in the privacy badge", () => {
    renderVerdict(makeDetail({ document: makeDoc({ ai_private: true, ai_processed_at: null }) }));
    expect(screen.getByText("Private — not read by Claude")).toBeInTheDocument();
    expect(screen.queryByText(/not read by AI/)).toBeNull();
  });

  it.each([
    ["untitled", null],
    // a private letter is titled by its file name
    ["kept private", "Scan_2026-09-28_0914.pdf"],
  ])("breaks a file name after its underscores, never inside its date (%s)", (_what, title) => {
    renderVerdict(makeDetail({ document: makeDoc({ title, filename: "Scan_2026-09-28_0914.pdf", ai_private: true, ai_processed_at: null }) }));
    const h1 = screen.getByRole("heading", { level: 1 });
    expect(h1.textContent).toBe("Scan_2026‑09‑28_0914.pdf");
    expect(h1.querySelectorAll("wbr")).toHaveLength(2);
    expect(plainText(h1.textContent ?? "")).toBe("Scan_2026-09-28_0914.pdf");
  });
});

describe("To-dos & dates: a to-do set aside (R2-document-verdict-2)", () => {
  const invoice = makeItem({ id: "inv", kind: "payment", direction: "out", title: "Pay TechMarkt Online invoice", amount: 89.99, due_date: "2026-09-03", send_by: "2026-09-02" });
  const deposit = makeItem({ id: "dep", kind: "payment", direction: "out", title: "Security deposit (Kaution)", amount: 1560, due_date: "2025-10-01" });
  const rent = makeItem({ id: "rent", kind: "payment", direction: "out", title: "Monthly rent", amount: 640, due_date: "2026-10-03", recurrence: { interval: 1, unit: "months", working_day: null, day_of_month: null } });

  it("says an invoice its reminder replaced for what it is: no countdown, not counted, a link to the reminder", () => {
    const reminder = makeDoc({ id: "doc_rem", doc_date: "2026-09-10" });
    renderWithProviders(
      <ItemsList items={[invoice]} docId="doc_1" setAside={[{ item_id: "inv", reason: "replaced", replaced_by: "doc_rem" }]} documents={[reminder]} />,
      { client: client() },
    );
    const todos = screen.getByRole("region", { name: /To-dos & dates/ });
    const heading = within(todos).getByRole("heading", { level: 2 });
    expect(heading).toHaveTextContent("· 0");
    expect(heading).toHaveTextContent("0 open");
    expect(within(todos).queryByText(/overdue/)).toBeNull();
    expect(todos.querySelector("time[data-urgency]")).toBeNull();
    expect(within(todos).queryByText(/transfer by/)).toBeNull();
    const note = within(todos).getByText(/Replaced by the payment reminder of/);
    expect(plainText(note.textContent ?? "")).toMatch(/^Replaced by the payment reminder of Thu 10 Sep — pay that one, not both\./);
    // its date stays on one line
    expect(note.textContent).toContain("Thu 10 Sep");
    expect(within(todos).getByRole("link", { name: /Open the reminder/ })).toHaveAttribute("href", "/documents/doc_rem");
    expect(within(todos).getByText(/was due/)).toHaveTextContent("was due 3 Sep");
    // it can still be ticked off
    expect(within(todos).getByRole("button", { name: "Mark “Pay TechMarkt Online invoice” as done" })).toBeEnabled();
  });

  it("asks about a date long past when the letter was added, after the to-dos to act on", () => {
    renderWithProviders(<ItemsList items={[deposit, rent]} docId="doc_1" setAside={[history("dep")]} />, { client: client() });
    const todos = screen.getByRole("region", { name: /To-dos & dates/ });
    expect(within(todos).getByRole("heading", { level: 2 })).toHaveTextContent("· 1");
    const rows = within(todos).getAllByRole("listitem");
    expect(rows[0]).toHaveTextContent("Monthly rent");
    expect(rows[1]).toHaveTextContent("Security deposit");
    expect(rows[1]).toHaveTextContent("was due 1 Oct 2025");
    expect(rows[1]).toHaveTextContent("Already past when the letter was added — still open?");
    expect(rows[1]).not.toHaveTextContent(/overdue/);
    expect(rows[1]!.querySelector("time[data-urgency]")).toBeNull();
  });

  it("counts down as ever when nothing is set aside", () => {
    renderWithProviders(<ItemsList items={[deposit]} docId="doc_1" />, { client: client() });
    expect(screen.getByText(/days overdue/)).toBeInTheDocument();
  });
});

describe("the contract card (R2-document-verdict-3)", () => {
  const base = { cost_amount: 640, cost_currency: "EUR", cost_interval: "monthly", status: "active" } as const;

  it("says 'Cancel any time' for a rolling contract — no red 'decide by … tomorrow'", () => {
    const lease = {
      ...base,
      id: "ctr_lease",
      name: "Mietvertrag Wohnung 05-2-03, Beispielweg 5",
      category: "rent",
      computed: { send_by: "2026-09-29", cancel_by: "2026-10-05", next_renewal: null, current_term_end: null, summary: "To leave on Thu 31 Dec 2026, your notice must arrive by Mon 5 Oct 2026." },
    } as unknown as Contract;
    renderWithProviders(<ContractsSection contracts={[lease]} />, { client: client() });
    const card = screen.getByRole("region", { name: "Contract" });
    expect(within(card).getByText("Cancel any time")).toBeInTheDocument();
    expect(card.querySelector("time")).toBeNull();
    expect(within(card).queryByText(/decide by/i)).toBeNull();
    // the flat number never breaks at its hyphens, nor a date in the summary after its weekday
    expect(card.textContent).toContain("05‑2‑03");
    expect(card.textContent).toContain("Mon 5 Oct 2026");
  });

  it("keeps the countdown for a real lock-in decision, 'Decide by' at the start of its phrase", () => {
    const gym = {
      ...base,
      id: "ctr_gym",
      name: "Gym membership",
      category: "fitness",
      computed: { send_by: "2026-10-02", cancel_by: "2026-10-05", next_renewal: "2027-01-01", current_term_end: "2026-12-31", summary: null },
    } as unknown as Contract;
    renderWithProviders(<ContractsSection contracts={[gym]} />, { client: client() });
    const time = screen.getByRole("region", { name: "Contract" }).querySelector("time")!;
    expect(time).toHaveTextContent(/^Decide by Fri 2 Oct/);
    expect(time).toHaveAttribute("data-urgency");
  });
});

describe("references stay whole (R2-document-verdict-6)", () => {
  it("in the 'Please check' card", () => {
    const doc = makeDoc({ warnings: ["Please check: This is a payment reminder about “TechMarkt Online invoice TM-2026-0048213 – 89.99 EUR”, which is still open."] });
    renderWithProviders(<DocumentWarnings detail={makeDetail({ document: doc })} />, { client: client() });
    const text = screen.getByText(/This is a payment reminder about/);
    expect(text.textContent).toContain("TM‑2026‑0048213");
    expect(text.textContent).toContain("89.99 EUR");
  });

  it("in the Thread list, the tooltip keeping the plain words", () => {
    const title = "TechMarkt Online invoice TM-2026-0048213 – 89.99 EUR";
    const detail = makeDetail({ document: makeDoc({ id: "doc_1", title: "1st Payment Reminder" }), related: [makeDoc({ id: "doc_2", title, doc_date: "2026-08-20" })] });
    renderWithProviders(<ThreadSection detail={detail} />, { client: client() });
    const link = screen.getByRole("link", { name: (name) => plainText(name) === title });
    expect(link.textContent).toContain("TM‑2026‑0048213");
    expect(link).toHaveAttribute("title", title);
  });
});

describe("'Why this date?' (R2-document-verdict-8)", () => {
  it("shows one tile when the send-by day is the due date itself", () => {
    const receipt = makeReceipt({ due_date: "2026-09-28", send_by: "2026-09-28" });
    expect(receiptDates(receipt, makeItem({ kind: "deadline" }), { nature: "objection" })).toEqual([{ label: "Must arrive by", date: "2026-09-28" }]);
    // two different days stay two tiles
    const earlier = makeReceipt({ due_date: "2026-09-30", send_by: "2026-09-28" });
    expect(receiptDates(earlier, makeItem({ kind: "deadline" }), { nature: "objection" }).map((d) => d.label)).toEqual(["Send by", "Must arrive by"]);
  });
});

describe("the loading page (R2-document-verdict-4)", () => {
  it("starts with a placeholder as tall as the view tabs, so the verdict doesn't move when it loads", () => {
    const { container } = render(<DocumentSkeleton />);
    const column = container.firstElementChild!.firstElementChild!;
    const tabs = column.firstElementChild!;
    expect(tabs).toHaveClass("h-10");
    expect(tabs).toHaveAttribute("aria-hidden", "true");
    expect(tabs.querySelectorAll(".animate-pulse")).toHaveLength(2);
    expect(column).toHaveClass("space-y-4", "xl:col-start-2");
  });
});
