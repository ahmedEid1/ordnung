import { describe, expect, it, vi } from "vitest";
import { fireEvent, screen, within } from "@testing-library/react";
import type { Lane } from "@/api/types";
import { assertNoRawEnumsInElement } from "@/lib/copy";
import { renderWithProviders } from "@/test/render";
import { LanesChart } from "./LanesChart";

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
    // label column: next date on the lane, coloured by urgency
    expect(within(lanes[1]!).getByText(/Send by 8 Oct · in 10 days/)).toBeInTheDocument();
    // legend lists what is on the chart
    for (const label of ["Valid", "Contract term", "Time to cancel", "Send by", "Must arrive by", "Payment", "Expires"]) {
      expect(screen.getAllByText(label).length).toBeGreaterThan(0);
    }
    assertNoRawEnumsInElement(container);
  });

  it("gives every bar and marker a descriptive accessible name", () => {
    renderChart();
    expect(screen.getByRole("button", { name: /^Residence permit\. Valid, 1 Dec 2024 – 30 Nov 2026\. Coming up\. Opens the letter\.$/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Time to cancel\. Time to cancel, 8 Sep – 14 Oct\. Act now\. Opens the contract\.$/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Send by · Thu 8 Oct, in 10 days\. Phone · FunkNetz · Time to cancel\. Opens the contract\./ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Rent · Mon 5 Oct, in 7 days\. Money\./ })).toBeInTheDocument();
  });

  it("is one tab stop with arrow-key navigation along and across lanes", () => {
    renderChart();
    const chart = screen.getByRole("group", { name: "Your year ahead" });
    const marks = Array.from(chart.querySelectorAll<HTMLElement>("[data-mark-key]"));
    expect(marks.filter((m) => m.tabIndex === 0)).toHaveLength(1);
    const first = marks.find((m) => m.tabIndex === 0)!;
    expect(first.getAttribute("data-mark-lane")).toBe("0");

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
    expect((document.activeElement as HTMLElement).getAttribute("data-mark-lane")).toBe("1");
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

  it("switches zoom and shows loading and empty states", () => {
    renderChart();
    const zoom = screen.getByRole("radiogroup", { name: "Zoom" });
    fireEvent.click(within(zoom).getByRole("radio", { name: /Zoom in/ }));
    expect(within(zoom).getByRole("radio", { name: /Zoom in/ })).toHaveAttribute("aria-checked", "true");
  });

  it("shows a loading state and an empty state", () => {
    const { unmount } = renderChart({ loading: true });
    expect(screen.getByRole("status")).toHaveTextContent("Loading your year");
    unmount();
    renderChart({ lanes: [], empty: <p>Nothing yet</p> });
    expect(screen.getByText("Nothing yet")).toBeInTheDocument();
  });
});
