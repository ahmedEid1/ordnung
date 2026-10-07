/**
 * Settings' sections: their order (Phone right after the watched folder), their names, and where the privacy log
 * sends phone access's entries.
 */
import { describe, expect, it } from "vitest";
import type { Activity } from "@/api/types";
import { activityHref, deviceActivityHref, leavesSection, parseSection, SECTION_IDS, SECTION_LABELS } from "./logic";

const entry = (kind: string, ref_type: string | null = null, ref_id: string | null = null): Pick<Activity, "kind" | "ref_type" | "ref_id"> => ({ kind, ref_type, ref_id });

describe("Settings sections", () => {
  it("come in this order, Phone right after the watched folder", () => {
    expect(SECTION_IDS).toEqual(["profile", "region", "reminders", "calendar", "folder", "phone", "ai", "claude", "privacy", "rules", "data"]);
    expect(SECTION_LABELS.phone).toBe("Phone");
    expect(parseSection("phone")).toBe("phone");
    expect(parseSection("phones")).toBe("profile");
  });

  it("a filter of the privacy log stays in its section", () => {
    const privacy = { pathname: "/settings", search: "?section=privacy" };
    expect(leavesSection(privacy, { pathname: "/settings", search: "?section=privacy&device=phn_1" })).toBe(false);
    expect(leavesSection(privacy, { pathname: "/settings", search: "?section=phone" })).toBe(true);
  });
});

describe("the privacy log's links for phone access", () => {
  it("lead to Settings → Phone, unless the entry names a letter or a draft", () => {
    expect(activityHref(entry("phone.paired"))).toBe("/settings?section=phone");
    expect(activityHref(entry("phone.removed"))).toBe("/settings?section=phone");
    expect(activityHref(entry("phone.changed", "document", "doc_1"))).toBe("/documents/doc_1");
    expect(activityHref(entry("phone.changed", "draft", "drf_1"))).toBe("/letters/drf_1");
    expect(activityHref(entry("phone.changed", "item", "itm_1"))).toBe("/settings?section=phone");
    // entries of other kinds without a letter lead nowhere, as before
    expect(activityHref(entry("review"))).toBeNull();
  });

  it("filter the privacy log to one phone", () => {
    expect(deviceActivityHref("phn_k3m7")).toBe("/settings?section=privacy&device=phn_k3m7");
  });
});
