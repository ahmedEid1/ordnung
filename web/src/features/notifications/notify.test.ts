import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Item, Suggestion } from "@/api/types";
import { formatMoney } from "@/lib/format";
import { item } from "@/mocks/data/helpers";
import { SUGGESTIONS } from "@/mocks/data/suggestions";
import {
  MAX_AT_ONCE,
  NOTIFY_ENABLED_KEY,
  NOTIFY_SENT_KEY,
  batchForDisplay,
  notYetShown,
  notifyPermission,
  planNotifications,
  readNotifyEnabled,
  readSentLog,
  recordSent,
  writeNotifyEnabled,
} from "./notify";

const TODAY = "2026-09-28";

const todo = (id: string, over: Partial<Item>): Item => item({ id, kind: "deadline", title: `To-do ${id}`, ...over });
const idea = (id: string, over: Partial<Suggestion>): Suggestion => ({ ...SUGGESTIONS[0]!, id, title: `Idea ${id}`, body: "First sentence. Second sentence.", ...over });

beforeEach(() => localStorage.clear());
afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe("what deserves a notification", () => {
  it("to-dos due or to be posted today or tomorrow, and overdue critical Ideas — most urgent first", () => {
    const items = [
      todo("later", { due_date: "2026-09-30" }),
      todo("tomorrow", { due_date: "2026-09-29", action: "Pay online", amount: 20, currency: "EUR", doc_id: "doc_parking" }),
      todo("today", { due_date: "2026-09-28" }),
      todo("post", { due_date: "2026-10-05", send_by: "2026-09-29", title: "Cancel the gym" }),
      todo("done", { due_date: "2026-09-28", status: "done" }),
      todo("snoozed", { due_date: "2026-09-28", status: "snoozed" }),
      todo("undated", { due_date: null }),
      todo("meet", { due_date: "2026-09-29", kind: "appointment", title: "Dentist" }),
    ];
    const ideas = [
      idea("overdue", { priority: "critical", status: "new", due_date: "2026-09-27" }),
      idea("dueToday", { priority: "critical", status: "new", due_date: TODAY }),
      idea("normal", { priority: "high", status: "new", due_date: "2026-09-20" }),
      idea("dismissed", { priority: "critical", status: "dismissed", due_date: "2026-09-20" }),
    ];

    const planned = planNotifications(items, ideas, TODAY);

    expect(planned.map((n) => n.key)).toEqual(["idea:overdue", "item:today", "item:post", "item:tomorrow", "item:meet"]);
    const byKey = Object.fromEntries(planned.map((n) => [n.key, n]));
    expect(byKey["idea:overdue"]).toMatchObject({ title: "Overdue: Idea overdue", body: "First sentence." });
    expect(byKey["item:today"]!.title).toBe("Due today: To-do today");
    expect(byKey["item:post"]!.title).toBe("Post by tomorrow: Cancel the gym");
    expect(byKey["item:tomorrow"]).toMatchObject({ title: "Due tomorrow: To-do tomorrow", body: `Pay online · ${formatMoney(20)}`, href: "/documents/doc_parking" });
    expect(byKey["item:meet"]!.title).toBe("Tomorrow: Dentist");
  });

  it("a busy day becomes a few notifications and one summary", () => {
    const many = Array.from({ length: 6 }, (_, i) => todo(`t${i}`, { due_date: TODAY }));
    const shown = batchForDisplay(planNotifications(many, [], TODAY));
    expect(shown).toHaveLength(MAX_AT_ONCE);
    expect(shown.at(-1)).toMatchObject({ key: "summary", title: "4 more dates need you today or tomorrow" });
    expect(batchForDisplay(planNotifications(many.slice(0, 2), [], TODAY))).toHaveLength(2);
  });
});

describe("at most once a day", () => {
  it("remembers what was shown per day and forgets after a week", () => {
    const planned = planNotifications([todo("a", { due_date: TODAY }), todo("b", { due_date: "2026-09-29" })], [], TODAY);
    expect(notYetShown(planned, TODAY)).toHaveLength(2);
    recordSent(["item:a"], TODAY);
    expect(notYetShown(planned, TODAY).map((n) => n.key)).toEqual(["item:b"]);
    // the next day it may be shown again (it is due tomorrow → today)
    expect(notYetShown(planned, "2026-09-29")).toHaveLength(2);
    recordSent(["item:old"], "2026-09-10");
    recordSent(["item:b"], TODAY);
    expect(readSentLog()).toEqual({ "item:a": TODAY, "item:b": TODAY });
  });

  it("survives broken or missing storage", () => {
    localStorage.setItem(NOTIFY_SENT_KEY, "{not json");
    expect(readSentLog()).toEqual({});
    localStorage.setItem(NOTIFY_SENT_KEY, "[1,2]");
    expect(readSentLog()).toEqual({});
  });
});

describe("permission and preference", () => {
  it("reads the Notification API's permission", () => {
    vi.stubGlobal("Notification", undefined);
    expect(notifyPermission()).toBe("unsupported");
    vi.stubGlobal("Notification", { permission: "denied" });
    expect(notifyPermission()).toBe("denied");
    vi.stubGlobal("Notification", { permission: "default" });
    expect(notifyPermission()).toBe("default");
  });

  it("is off until turned on in this browser", () => {
    expect(readNotifyEnabled()).toBe(false);
    writeNotifyEnabled(true);
    expect(localStorage.getItem(NOTIFY_ENABLED_KEY)).toBe("true");
    expect(readNotifyEnabled()).toBe(true);
    writeNotifyEnabled(false);
    expect(readNotifyEnabled()).toBe(false);
  });
});
