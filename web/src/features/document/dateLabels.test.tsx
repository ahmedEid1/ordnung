import { describe, expect, it } from "vitest";
import { screen } from "@testing-library/react";
import type { ComputationReceipt, DateSpec } from "@/api/types";
import { renderWithProviders } from "@/test/render";
import { dueDateLabel, sendByLabel } from "./dateLabels";
import { ReceiptView } from "./WhyThisDate";

const receipt = (r: Partial<ComputationReceipt>): ComputationReceipt => ({
  due_date: "2026-10-08",
  send_by: null,
  safe_date: null,
  holiday_calendar: "DE-BE",
  summary: "The date given is Thu 8 Oct 2026.",
  steps: [],
  rule_ids: [],
  warnings: [],
  confidence: "high",
  ...r,
});
const spec = (nature: DateSpec["nature"]) => ({ type: "fixed", date: "2026-10-08", nature, text: "am 08.10.2026" }) as DateSpec;

describe("what a computed date is called", () => {
  it("follows the deadline's nature, as the Today page does", () => {
    expect(dueDateLabel("appointment", false)).toBe("On");
    expect(dueDateLabel("payment", false)).toBe("Pay by");
    expect(dueDateLabel("other", false)).toBe("Date");
    expect(dueDateLabel("objection", false)).toBe("Must arrive by");
    expect(dueDateLabel(null, false)).toBe("Must arrive by");
    // next to a send-by date, the date is when it must arrive
    expect(dueDateLabel("payment", true)).toBe("Must arrive by");
    expect(sendByLabel("payment")).toBe("Transfer by");
    expect(sendByLabel("notice")).toBe("Send by");
    // money coming in (or collected by direct debit) is transferred by nobody
    expect(sendByLabel("payment", false)).toBe("Send by");
  });

  it("names the letter's own “Why this date?” receipt's dates by it too", () => {
    const first = renderWithProviders(<ReceiptView receipt={receipt({})} spec={spec("appointment")} />);
    expect(screen.getByText("On")).toBeInTheDocument();
    expect(screen.queryByText("Must arrive by")).toBeNull();
    first.unmount();
    const second = renderWithProviders(<ReceiptView receipt={receipt({ send_by: "2026-10-05" })} spec={spec("payment")} transfer />);
    expect(screen.getByText("Transfer by")).toBeInTheDocument();
    expect(screen.getByText("Must arrive by")).toBeInTheDocument();
    second.unmount();
    renderWithProviders(<ReceiptView receipt={receipt({ send_by: "2026-10-05" })} spec={spec("payment")} transfer={false} />);
    expect(screen.getByText("Send by")).toBeInTheDocument();
  });
});
