import { describe, expect, it, vi } from "vitest";
import { fireEvent, screen, within } from "@testing-library/react";
import type { Lane } from "@/api/types";
import { assertNoRawEnumsInElement } from "@/lib/copy";
import { renderWithProviders } from "@/test/render";
import { LanesChart, labelColumnWidth } from "./LanesChart";

const TODAY = "2026-09-28";
const RANGE = { from: "2026-06-01", to: "2027-09-30" };

const LANES: Lane[] = [
  {
    id: "residence",
    label: "Residence",
    area: "residence",
    bars: [
      {
        id: "bar_permit",
        label: "Residence permit",
        start: "2024-12-01",
        end: "2026-11-30",
        kind: "validity",
        status: "attention",
        markers: [{ date: "2026-11-30", label: "Permit expires", kind: "expiry" }],
        ref: { type: "document", id: "doc_abh" },
      },
    ],
    markers: [],
  },
  {
    id: "phone",
    label: "Phone · FunkNetz",
    area: "home",
    bars: [
      { id: "term", label: "Minimum term", start: "2024-11-15", end: "2026-11-14", kind: "contract", status: "ok", markers: [], ref: { type: "contract", id: "ctr_phone" } },
      {
        id: "notice",
        label: "Time to cancel",
        start: "2026-09-08",
        end: "2026-10-14",
        kind: "notice_window",
        status: "urgent",
        markers: [
          { date: "2026-10-08", label: "Send by", kind: "send_by" },
          { date: "2026-10-14", label: "Must arrive by", kind: "cancel_by" },
        ],
        ref: { type: "contract", id: "ctr_phone" },
      },
    ],
    markers: [],
  },
  { id: "money", label: "Money", area: "money", bars: [], markers: [{ date: "2026-10-05", label: "Rent", kind: "payment" }] },
];

function renderChart(props: Partial<Parameters<typeof LanesChart>[0]> = {}) {
  return renderWithProviders(<LanesChart lanes={LANES} from={RANGE.from} to={RANGE.to} today={TODAY} ariaLabel="Your year ahead" title="Your year ahead" {...props} />);
}

describe("LanesChart", () => {
  it("renders lanes, month axis, today line and legend without raw enum values", () => {
    const { container } = renderChart();
    const chart = screen.getByRole("group", { name: "Your year ahead" });
    const lanes = within(chart).getAllByRole("listitem");
    expect(lanes.map((l) => l.getAttribute("aria-label"))).toEqual(["Residence", "Phone · FunkNetz", "Money"]);
    expect(within(chart).getAllByText("Today").length).toBeGreaterThan(0);
    expect(within(chart).getByText("Oct")).toBeInTheDocument();
    expect(within(chart).getByText("2027")).toBeInTheDocument();
    // direct label for the upcoming send-by date
    expect(within(chart).getByText("Send by 8 Oct")).toBeInTheDocument();
    // label column: next date on the lane; the label may truncate, the date never does
    const next = within(lanes[1]!).getByTitle("Send by 8 Oct");
    expect(next).toHaveTextContent("Send by 8 Oct");
    expect(within(next).getByText("Send by")).toHaveClass("truncate");
    expect(within(next).getByText(/8 Oct/)).toHaveClass("shrink-0");
    // within a week it also says how soon, coloured by the app's urgency scale (payments never red)
    expect(within(lanes[2]!).getByTitle("Rent · 5 Oct · in 7 days")).toHaveClass("text-warn-ink");
    // legend lists what is on the chart, Today first (it never wraps onto a line of its own)
    const legend = screen.getByRole("list", { name: "Legend" });
    const items = within(legend).getAllByRole("listitem").map((li) => li.textContent);
    expect(items[0]).toBe("Today");
    for (const label of ["Valid", "Contract term", "Time to cancel — act now", "Ends soon", "Send by", "Must arrive by", "Payment", "Expires"]) {
      expect(items).toContain(label);
    }
    assertNoRawEnumsInElement(container);
  });

  it("gives every bar and marker a descriptive accessible name", () => {
    renderChart();
    expect(screen.getByRole("button", { name: /^Residence permit\. Valid, 1 Dec 2024 – 30 Nov 2026\. Ends soon\. Opens the letter\.$/ })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /^Time to cancel\. Time to cancel, 8 Sep – 14 Oct\. Act now — send by 8 Oct\. Opens the contract\.$/ }),
    ).toBeInTheDocument();
    // send-by and must-arrive-by sit 6 days apart: one mark that names both dates
    expect(
      screen.getByRole("button", {
        name: /^Send by · Thu 8 Oct, in 10 days; Must arrive by · Wed 14 Oct, in 16 days\. Phone · FunkNetz · Time to cancel\. Opens the contract\./,
      }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Rent · Mon 5 Oct, in 7 days\. Money\./ })).toBeInTheDocument();
  });

  it("is one tab stop with arrow-key navigation along and across lanes", () => {
    renderChart();
    const chart = screen.getByRole("group", { name: "Your year ahead" });
    const marks = Array.from(chart.querySelectorAll<HTMLElement>("[data-mark-key]"));
    expect(marks.filter((m) => m.tabIndex === 0)).toHaveLength(1);
    const first = marks.find((m) => m.tabIndex === 0)!;
    expect(first.getAttribute("data-mark-row")).toBe("0");

    // the default stop is the first upcoming mark: the permit's expiry marker
    expect(first.getAttribute("aria-label")).toMatch(/^Permit expires/);
    first.focus();
    fireEvent.keyDown(first, { key: "ArrowLeft" });
    const bar = document.activeElement as HTMLElement;
    expect(bar.getAttribute("aria-label")).toMatch(/^Residence permit\./);
    expect(bar.tabIndex).toBe(0);
    expect(first.tabIndex).toBe(-1);
    fireEvent.keyDown(bar, { key: "ArrowRight" });
    expect(document.activeElement).toBe(first);

    fireEvent.keyDown(first, { key: "ArrowDown" });
    expect((document.activeElement as HTMLElement).getAttribute("data-mark-row")).toBe("1");
    fireEvent.keyDown(document.activeElement!, { key: "ArrowDown" });
    expect((document.activeElement as HTMLElement).getAttribute("aria-label")).toMatch(/^Rent/);
    fireEvent.keyDown(document.activeElement!, { key: "ArrowUp" });
    fireEvent.keyDown(document.activeElement!, { key: "Home" });
    expect((document.activeElement as HTMLElement).getAttribute("aria-label")).toMatch(/^Minimum term\./);
  });

  it("opens the referenced letter or contract on click", () => {
    const { router } = renderChart();
    fireEvent.click(screen.getByRole("button", { name: /^Residence permit\./ }));
    expect(router.state.location.pathname).toBe("/documents/doc_abh");
  });

  it("hands clicks to onSelect with the lane, bar, marker and date", () => {
    const onSelect = vi.fn();
    renderChart({ onSelect });
    fireEvent.click(screen.getByRole("button", { name: /Send by · Thu 8 Oct/ }));
    expect(onSelect).toHaveBeenCalledWith(
      expect.objectContaining({
        date: "2026-10-08",
        ref: { type: "contract", id: "ctr_phone" },
        marker: expect.objectContaining({ kind: "send_by" }),
        bar: expect.objectContaining({ id: "notice" }),
        lane: expect.objectContaining({ id: "phone" }),
      }),
    );
  });

  it("fits every month by default (nothing to scroll, no jump button) and only scrolls when zoomed in", () => {
    renderChart();
    const zoom = screen.getByRole("radiogroup", { name: "Zoom" });
    expect(within(zoom).getByRole("radio", { name: /Fit all/ })).toHaveAttribute("aria-checked", "true");
    const group = screen.getByRole("group", { name: "Your year ahead" });
    // jsdom's chart is 1024 px wide: label column + plot = exactly that
    expect(group.style.width).toBe("1024px");
    expect(screen.queryByRole("button", { name: "Jump to today" })).not.toBeInTheDocument();
    expect(screen.queryByTestId("lanes-fade-right")).not.toBeInTheDocument();

    fireEvent.click(within(zoom).getByRole("radio", { name: /Zoom in/ }));
    expect(within(zoom).getByRole("radio", { name: /Zoom in/ })).toHaveAttribute("aria-checked", "true");
    expect(parseInt(group.style.width)).toBeGreaterThan(1024);
    expect(screen.getByRole("button", { name: "Jump to today" })).toBeInTheDocument();
    expect(screen.getByTestId("lanes-fade-right")).toBeInTheDocument();
  });

  it("sizes the label column to about a quarter of the chart, 200–320 px", () => {
    expect(labelColumnWidth(955)).toBe(229); // a 1280 px window with the sidebar
    expect(labelColumnWidth(640)).toBe(200);
    expect(labelColumnWidth(1500)).toBe(320); // wide screens: long contract names get room
  });

  it("reaches every row of a lane with ↑/↓ — one row per contract on the Contracts page", () => {
    const ref = (id: string) => ({ type: "contract", id });
    const lanes: Lane[] = [
      {
        id: "contracts",
        label: "Contracts",
        area: "other",
        bars: ["a", "b", "c"].map((id) => ({
          id,
          label: `Contract ${id}`,
          start: "2025-01-01",
          end: "2027-09-30",
          kind: "contract" as const,
          status: "ok" as const,
          markers: [],
          ref: ref(id),
        })),
        markers: [],
      },
    ];
    renderChart({ lanes });
    const rows = Array.from(document.querySelectorAll<HTMLElement>("[data-mark-key]"));
    expect(rows.map((m) => m.getAttribute("data-mark-row"))).toEqual(["0", "1", "2"]);
    const first = rows.find((m) => m.tabIndex === 0)!;
    first.focus();
    fireEvent.keyDown(first, { key: "ArrowDown" });
    expect(document.activeElement?.getAttribute("aria-label")).toMatch(/^Contract b\./);
    fireEvent.keyDown(document.activeElement!, { key: "ArrowDown" });
    expect(document.activeElement?.getAttribute("aria-label")).toMatch(/^Contract c\./);
  });

  it("never gives an open-ended bar an end date", () => {
    const lanes: Lane[] = [
      {
        id: "rent",
        label: "Lease",
        area: "home",
        bars: [
          { id: "open", label: "Open-ended", start: "2025-10-01", end: "2027-10-01", open_end: true, kind: "contract", status: "ok", markers: [], ref: null },
        ],
        markers: [],
      },
    ];
    renderChart({ lanes });
    expect(screen.getByRole("button", { name: "Open-ended. Contract term, since 1 Oct 2025, no end date." })).toBeInTheDocument();
    expect(screen.getByRole("listitem", { name: "Lease" })).toHaveTextContent("Nothing coming up");
  });

  it("truncates a page's own second line under a lane's name, like the default one", () => {
    const long = "Stadtwerke Musterstadt Versorgungsgesellschaft mbH & Co. KG";
    renderChart({ describeLane: (lane) => (lane.id === "money" ? { sublabel: <span className="text-muted">{long}</span> } : undefined) });
    const line = within(screen.getByRole("listitem", { name: "Money" })).getByText(long);
    expect(line.parentElement).toHaveClass("truncate");
  });

  it("takes the heading level and loading message of the page it sits on", () => {
    const { unmount } = renderChart({ loading: true, loadingLabel: "Loading your contracts…" });
    expect(screen.getByRole("status")).toHaveTextContent("Loading your contracts…");
    unmount();
    renderChart({ headingLevel: 3 });
    expect(screen.getByRole("heading", { level: 3, name: "Your year ahead" })).toBeInTheDocument();
    // the legend is a named list, not an extra heading in the page outline
    expect(screen.queryByRole("heading", { name: "Legend" })).not.toBeInTheDocument();
  });

  it("shows a loading state and an empty state", () => {
    const { unmount } = renderChart({ loading: true });
    expect(screen.getByRole("status")).toHaveTextContent("Loading your year");
    unmount();
    renderChart({ lanes: [], empty: <p>Nothing yet</p> });
    expect(screen.getByText("Nothing yet")).toBeInTheDocument();
  });
});
