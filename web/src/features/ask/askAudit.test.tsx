/**
 * UI audit round 1 (Ask): the tool trace, the source list, the question bubble and linked text.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FileText } from "lucide-react";
import { makeTestQueryClient, renderWithProviders } from "@/test/render";
import { useMockApi } from "@/test/mockFetch";
import { qk } from "@/api/hooks";
import { CitationChip, CitationMarker } from "./CitationChip";
import { QuestionBubble } from "./AskTurnView";
import { RefText, splitLinks, trustedHost } from "./RefText";
import { ToolTrace } from "./ToolTrace";
import { fallbackToolLabel, toolLabel, traceSummary } from "./tools";
import type { ToolStep } from "./stream";
import type { RefInfo } from "./refs";

afterEach(() => vi.unstubAllGlobals());

const step = (name: string, label: string, result = "Done"): ToolStep => ({ name, input: {}, label, result, done: true });

describe("the tool trace", () => {
  it("shows a single step as it is, without a toggle that opens one line", () => {
    render(<ToolTrace steps={[step("list_contracts", "Looked at your contracts", "Found 9 contracts")]} live={false} />);
    expect(screen.queryByRole("button")).toBeNull();
    expect(within(screen.getByRole("list", { name: "What Ordnung looked at" })).getByText("Looked at your contracts")).toBeInTheDocument();
  });

  it("counts what it looked at in the records, not today's date, behind a toggle of at least 28 px", async () => {
    const user = userEvent.setup();
    render(<ToolTrace steps={[step("today", "Checked today's date"), step("list_items", "Checked your open deadlines")]} live={false} />);
    const toggle = screen.getByRole("button", { name: "Looked at 1 thing in your records" });
    expect(toggle.className).toContain("min-h-7");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await user.click(toggle);
    expect(within(screen.getByRole("list", { name: "What Ordnung looked at" })).getAllByRole("listitem")).toHaveLength(2);
    expect(traceSummary([step("today", "x")])).toBe("Checked today's date");
    expect(traceSummary([step("search", "x"), step("get_document", "y"), step("today", "z")])).toBe("Looked at 2 things in your records");
  });

  it("names the kind of to-dos a filtered call listed, so two calls read apart", () => {
    expect(fallbackToolLabel("list_items", { kind: "deadline", status: "open" })).toBe("Listed your open deadlines");
    expect(fallbackToolLabel("list_items", { kind: "payment", status: "all", to: "2026-10-31" })).toMatch(/^Listed your payments until /);
    expect(fallbackToolLabel("list_items", { kind: "nonsense" })).toBe("Listed your open to-dos & dates");
  });

  it("never splits a law reference in a step's result", () => {
    render(<ToolTrace steps={[step("explain_date", "Checked how the date was worked out", "Due 2026-10-15 — § 556 Abs. 3 BGB")]} live={false} />);
    expect(screen.getByTestId("tool-step-result").textContent).toMatch(/§\u00a0556 Abs\.\u00a03 BGB$/);
  });

  it("writes the backend's straight quotes as the app's curly ones", () => {
    expect(toolLabel({ name: "search", input: {}, label: 'Searched your letters for "Kündigung"' })).toBe("Searched your letters for “Kündigung”");
    expect(toolLabel({ name: "get_document", input: {}, label: 'Read "Tax assessment 2025"' })).toBe("Read “Tax assessment 2025”");
  });
});

const info = (title: string): RefInfo => ({ type: "document", id: "doc_x", title, kindLabel: "Letter", icon: FileText, href: "/documents/doc_x" });

describe("sources and markers", () => {
  const renderIn = (ui: React.ReactElement) => renderWithProviders(ui);

  it("a source's long title wraps instead of being cut to one line", () => {
    useMockApi();
    const title = "Operating and Heating Cost Statement 2025 (Betriebs- und Heizkostenabrechnung) – Wohnbau Musterstadt eG";
    renderIn(<CitationChip info={info(title)} n={11} />);
    const chip = screen.getByRole("link", { name: `Source 11: Letter “${title}”` });
    const text = within(chip).getByText(title);
    expect(text.className).toContain("line-clamp-3");
    expect(text.className).not.toContain("truncate");
    // the number keeps its width next to a long title (UI audit round 1: "11" squeezed to 12 px)
    expect(chip.querySelector("[aria-hidden]")?.className).toContain("shrink-0");
  });

  it("a marker reacts around its small box and its digits are 11 px", () => {
    useMockApi();
    renderIn(<CitationMarker info={info("Phone contract")} n={1} />);
    const marker = screen.getByRole("link", { name: "Source 1: Letter “Phone contract”" });
    expect(marker.className).toContain("after:-inset-1");
    expect(marker.className).toContain("text-[11px]");
  });
});

describe("the question bubble", () => {
  it("is a heading that wraps a long word or an IBAN inside the bubble", () => {
    render(<QuestionBubble text="Warum steht DE89370400440532013000 in der Immatrikulationsbescheinigungsverlängerung?" />);
    const heading = screen.getByRole("heading", { level: 2 });
    expect(heading).toHaveTextContent(/^You asked: Warum/);
    expect(heading.className).toContain("[overflow-wrap:anywhere]");
    expect(heading.className).toContain("min-w-0");
  });
});

describe("linked text (Ideas)", () => {
  it("links the sites Ordnung cites by their name, and leaves any other address as text", () => {
    expect(trustedHost("https://www.gesetze-im-internet.de/aufenthg_2004/__16b.html")).toBe("gesetze-im-internet.de");
    expect(trustedHost("https://service.justiz.de/x")).toBe("service.justiz.de");
    expect(trustedHost("http://www.gesetze-im-internet.de/")).toBeNull();
    expect(trustedHost("https://gesetze-im-internet.de.evil.example/")).toBeNull();
    expect(splitLinks("See https://dejure.org/gesetze/BGB/573c.html.").map((p) => p.kind)).toEqual(["text", "url", "text"]);
  });

  it("shows “Law: gesetze-im-internet.de ↗”, opening in a new tab, and wraps a long unknown address", () => {
    useMockApi();
    renderWithProviders(
      <p>
        <RefText text="Law: https://www.gesetze-im-internet.de/aufenthg_2004/__16b.html · Advice: https://www.studierendenwerke.de · Paid: https://pay-now.example/very/long/path/to/somewhere" />
      </p>,
    );
    // the site's name keeps its hyphens unbreakable (U+2011)
    const law = screen.getByRole("link", { name: /^gesetze‑im‑internet\.de ?\(opens in a new tab\)/ });
    expect(law).toHaveAttribute("href", "https://www.gesetze-im-internet.de/aufenthg_2004/__16b.html");
    expect(law).toHaveAttribute("target", "_blank");
    expect(law).toHaveAttribute("rel", "noreferrer noopener");
    expect(screen.getByRole("link", { name: /^studierendenwerke\.de ?\(opens in a new tab\)/ })).toBeInTheDocument();
    // an address Ordnung doesn't know may come from a letter: text, never a link, but it wraps
    expect(screen.queryByRole("link", { name: /pay-now/ })).toBeNull();
    expect(screen.getByText("https://pay-now.example/very/long/path/to/somewhere").className).toContain("[overflow-wrap:anywhere]");
  });

  it("shows a record's whole title (UI audit round 1: cut after 48 characters mid-word)", async () => {
    const { srv } = useMockApi();
    const client = makeTestQueryClient();
    // an id as the weekly review writes it (the mock data's short ids are no record ids to the text)
    const doc = { ...srv.db.state.documents[0]!, id: "doc_0b2t88kqsf2n" };
    const title = "Operating and Heating Cost Statement 2025 (Betriebs- und Heizkostenabrechnung)";
    client.setQueryData(qk.documents.list({}), [{ ...doc, title }]);
    renderWithProviders(<RefText text={`${doc.id} describes it.`} />, { client });
    expect(await screen.findByRole("link", { name: `“${title}”` })).toBeInTheDocument();
  });
});
