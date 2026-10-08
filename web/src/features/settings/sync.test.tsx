/**
 * Settings → Your computers (hand-off sync): the pure helpers first — the passphrase estimator counted exactly as
 * the server counts it, the numbers pinned to `src/ordnung/sync/__init__.py` — then the section through the mock
 * API: not syncing, unavailable, setting up (a new folder, joining one, refusals under their fields, the synced data
 * folder, the joining choice), in use, standing by, problems with their actions, the other computers, kept copies,
 * disconnecting (twice when the latest changes reached no other computer) and Delete everything.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { qk } from "@/api/hooks";
import { api } from "@/api/endpoints";
import { SYNC_PROBLEM_ACTIONS, SYNC_PROBLEM_CODES, type SyncComputer, type SyncStatus } from "@/api/types";
import { Toaster, __clearToasts } from "@/components/ui/Toast";
import { assertNoRawEnums, assertNoRawEnumsInElement } from "@/lib/copy";
import { SYNC_EXISTING_FOLDER, SYNC_OTHER_NAME, SYNC_STATIC_MESSAGE, WRONG_PASSPHRASE_MESSAGE } from "@/mocks/data/sync";
import SettingsPage from "@/pages/SettingsPage";
import { makeTestQueryClient, renderWithProviders, TEST_HEALTH } from "@/test/render";
import { useMockApi } from "@/test/mockFetch";
import { deleteSyncNote, SYNC_STOPPED } from "./DataSection";
import {
  ACTION_LABELS,
  ARRIVAL_PATIENCE_MINUTES,
  arrivalAdvice,
  arrivingLine,
  calendarElsewhereNote,
  calendarLine,
  choiceSideLine,
  sideContentsLine,
  sideLatestLine,
  chosenMessage,
  computerBadge,
  computerLine,
  fieldFor,
  indicatorLabel,
  KEPT_WARN_BYTES,
  keptRestoreCommand,
  lastSavedLine,
  latestLine,
  looksAbsolute,
  MIN_PASSPHRASE_BITS,
  modeLabel,
  NAME_MAX_CHARS,
  nameProblem,
  newPassphraseProblem,
  passphraseBits,
  COMMON_WORDS_TEXT,
  KEYBOARD_ROWS,
  passphraseTokens,
  PASSPHRASE_WORDING,
  PROBLEM_TITLES,
  problemTitle,
  reassuranceLine,
  sideArrivingLine,
  standbyStatusLine,
  strengthLine,
  SUGGESTED_WORDS,
  suggestSyncPassphrase,
  syncFormProblem,
  TAKE_OVER_WAIT_MINUTES,
  TOKEN_BITS_MAX,
  unreceivedLine,
  WEAK_PASSPHRASE_MESSAGE,
  wordsShort,
} from "./sync";

class RO {
  observe() {}
  unobserve() {}
  disconnect() {}
}

beforeEach(() => {
  vi.stubGlobal("ResizeObserver", RO);
  vi.stubGlobal("scrollTo", () => {});
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  act(() => __clearToasts());
});

const WAIT = { timeout: 5000 };
const POLICY = readFileSync(resolve(__dirname, "../../../../src/ordnung/sync/__init__.py"), "utf8");

/** A constant of the policy module as written there (`NAME = 1800.0`, `NAME = 2 * _GIB`). */
function constant(name: string): string {
  const m = new RegExp(`^${name}(?::[^=]+)? = (.+)$`, "m").exec(POLICY);
  if (!m) throw new Error(`${name} isn't in ordnung/sync/__init__.py`);
  return m[1]!.trim();
}

const computer = (over: Partial<SyncComputer> = {}): SyncComputer => ({
  key: 2,
  name: "desktop",
  this: false,
  in_use: false,
  state: "standing_by",
  arrived_at: null,
  has_latest: null,
  app_version: "0.9.0",
  calendar: "none",
  ...over,
});
const here = computer({ key: 1, name: "anna-thinkpad", this: true, in_use: true, state: "in_use" });

// ------------------------------------------------------------------------------------------------
// The passphrase of a new sync folder
// ------------------------------------------------------------------------------------------------

describe("the passphrase estimator (the server's `passphrase_bits`, counted the same way)", () => {
  // each value is what `ordnung.sync.passphrase_bits` / `passphrase_tokens` answers
  const VECTORS: [string, string[], number][] = [
    ["correct horse battery staple", ["correct", "horse", "battery", "staple"], 56],
    ["correct horse battery staple orbit", ["correct", "horse", "battery", "staple", "orbit"], 70],
    ["CorrectHorseBatteryStapleOrbit", ["Correct", "Horse", "Battery", "Staple", "Orbit"], 70],
    ["k7qmx-3vxdp-9tawr-2emnb", ["k", "7", "qmx", "3", "vxdp", "9", "tawr", "2", "emnb"], 73.988152],
    ["aaaaaaaaaaaaaaaaaaaa", ["aaaaaaaaaaaaaaaaaaaa"], 5.70044],
    ["cat cat cat cat cat cat", ["cat", "cat", "cat", "cat", "cat", "cat"], 14],
    ["Straße STRASSE strasse", ["Straße", "STRASSE", "strasse"], 14],
    ["1234567890 0987654321", ["1234567890", "0987654321"], 8.643856],
    ["ab cd ef gh ij kl mn op", ["ab", "cd", "ef", "gh", "ij", "kl", "mn", "op"], 5.70044],
    ["kirun-bodaf-sumel-tavok-perin", ["kirun", "bodaf", "sumel", "tavok", "perin"], 70],
    ["Über Äpfel Öfen Zürich Genève", ["Über", "Äpfel", "Öfen", "Zürich", "Genève"], 70],
    ["a1b2c3", ["a", "1", "b", "2", "c", "3"], 24.067103],
    ["ﬁsh fish FISH", ["ﬁsh", "fish", "FISH"], 14],
    ["", [], 0],
    ["ΣΊΣΥΦΟΣ σίσυφος", ["ΣΊΣΥΦΟΣ", "σίσυφος"], 14],
    ["x\u0301yz abc", ["x", "yz", "abc"], 19.801759],
    // the review's patterns: a character again and again, runs in order, keyboard walks, common words
    ["aaa bbb ccc ddd eee", ["aaa", "bbb", "ccc", "ddd", "eee"], 28.502199],
    ["abc def ghi jkl mno", ["abc", "def", "ghi", "jkl", "mno"], 5.70044],
    ["12345 23456 34567 45678 56789", ["12345", "23456", "34567", "45678", "56789"], 21.60964],
    ["one two three four five", ["one", "two", "three", "four", "five"], 35],
    ["january february march april may", ["january", "february", "march", "april", "may"], 35],
    ["qwerty asdfgh zxcvbn password letmein", ["qwerty", "asdfgh", "zxcvbn", "password", "letmein"], 31.101319],
    ["a b c d e f g h i j k l m n o", ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l", "m", "n", "o"], 5.70044],
    ["the cat sat on the mat today", ["the", "cat", "sat", "on", "the", "mat", "today"], 63],
    ["Sommer 2025 Urlaub Sommer", ["Sommer", "2025", "Urlaub", "Sommer"], 34.287712],
  ];

  it.each(VECTORS)("%j", (passphrase, tokens, bits) => {
    expect(passphraseTokens(passphrase)).toEqual(tokens);
    expect(passphraseBits(passphrase)).toBeCloseTo(bits, 5);
  });

  it("uses the policy's numbers and words", () => {
    expect(Number(constant("MIN_PASSPHRASE_BITS"))).toBe(MIN_PASSPHRASE_BITS);
    expect(Number(constant("TOKEN_BITS_MAX"))).toBe(TOKEN_BITS_MAX);
    expect(Number(constant("SUGGESTED_WORDS"))).toBe(SUGGESTED_WORDS);
    expect(Number(constant("NAME_MAX_CHARS"))).toBe(NAME_MAX_CHARS);
    expect(Number(constant("TAKE_OVER_WAIT_MAX_S"))).toBe(TAKE_OVER_WAIT_MINUTES * 60);
    expect(Number(constant("ARRIVAL_PATIENCE_S"))).toBe(ARRIVAL_PATIENCE_MINUTES * 60);
    expect(constant("KEPT_WARN_BYTES")).toBe("2 * _GIB");
    expect(KEPT_WARN_BYTES).toBe(2 * 1024 ** 3);
    const weak = /^WEAK_PASSPHRASE_MESSAGE = \(\s*((?:"[^"]*"\s*)+)\)/m.exec(POLICY)?.[1] ?? "";
    expect([...weak.matchAll(/"([^"]*)"/g)].map((m) => m[1]).join("")).toBe(WEAK_PASSPHRASE_MESSAGE);
    const common = /^COMMON_WORDS_TEXT = \(\s*((?:"[^"]*"\s*)+)\)/m.exec(POLICY)?.[1] ?? "";
    expect([...common.matchAll(/"([^"]*)"/g)].map((m) => m[1]).join("")).toBe(COMMON_WORDS_TEXT);
    const rows = /^KEYBOARD_ROWS: tuple\[str, \.\.\.\] = \(([^)]*)\)/m.exec(POLICY)?.[1] ?? "";
    expect([...rows.matchAll(/"([^"]*)"/g)].map((m) => m[1])).toEqual(KEYBOARD_ROWS);
    expect(Number(constant("COMMON_WORD_BITS"))).toBe(7);
  });

  it("refuses a new passphrase that is short, weak or typed differently twice — before asking the server", () => {
    expect(newPassphraseProblem("short")).toEqual({ field: "passphrase", message: "Use a passphrase of at least 12 characters — five or more words that don't belong together work well." });
    expect(newPassphraseProblem("correct horse battery staple")).toEqual({ field: "passphrase", message: WEAK_PASSPHRASE_MESSAGE });
    expect(newPassphraseProblem("correct horse battery staple orbit", "correct horse battery staple")).toEqual({ field: "repeat", message: "The two passphrases differ." });
    expect(newPassphraseProblem("correct horse battery staple orbit", "correct horse battery staple orbit")).toBeNull();
    expect(newPassphraseProblem("x".repeat(1025))?.message).toMatch(/at most 1024/);
  });

  it("says how many more words it takes", () => {
    expect(wordsShort("correct horse battery staple")).toBe(1);
    expect(wordsShort("cat dog")).toBe(3);
    expect(wordsShort("correct horse battery staple orbit")).toBe(0);
    expect(strengthLine("")).toBeNull();
    expect(strengthLine("correct horse battery staple")).toEqual({ tone: "warn", text: expect.stringContaining("add one more word") });
    expect(strengthLine("cat dog")?.text).toContain("add 3 more words");
    expect(strengthLine("correct horse battery staple orbit")).toEqual({ tone: "ok", text: "Strong enough for a folder your sync provider keeps." });
  });

  it("suggests five made-up words that pass, drawn again when two are alike", () => {
    for (let i = 0; i < 20; i++) {
      const suggestion = suggestSyncPassphrase();
      expect(suggestion).toMatch(/^[bdfgjklmnprstvz][aeiou][bdfgjklmnprstvz][aeiou][bdfgjklmnprstvz](-[bdfgjklmnprstvz][aeiou][bdfgjklmnprstvz][aeiou][bdfgjklmnprstvz]){4}$/);
      expect(passphraseBits(suggestion)).toBeGreaterThanOrEqual(MIN_PASSPHRASE_BITS);
      expect(newPassphraseProblem(suggestion, suggestion)).toBeNull();
    }
    // the first draw gives the same word six times: the repeats are drawn again
    let calls = 0;
    let seed = 7;
    const random = (bytes: Uint8Array) => {
      calls += 1;
      return bytes.map(() => {
        if (calls === 1) return 0;
        seed = (Math.imul(seed, 1103515245) + 12345) >>> 0;
        return seed >>> 24;
      });
    };
    const suggestion = suggestSyncPassphrase(random);
    expect(calls).toBeGreaterThan(1);
    expect(suggestion.startsWith("babab-")).toBe(true);
    expect(new Set(suggestion.split("-")).size).toBe(5);
    // random numbers that never vary can't make one: said, never a loop without end
    expect(() => suggestSyncPassphrase((bytes) => bytes.fill(0))).toThrow(/keep repeating/);
  });

  it("never reuses the backup's 'Ordnung never stores it': the sync passphrase is kept in the password store", () => {
    expect(PASSPHRASE_WORDING).toContain("keeps this passphrase in this computer's password store");
    expect(PASSPHRASE_WORDING).not.toMatch(/never stores/);
  });
});

// ------------------------------------------------------------------------------------------------
// The other helpers
// ------------------------------------------------------------------------------------------------

describe("hand-off sync helpers", () => {
  it("checks the setup form before asking the server", () => {
    const ok = { folder: "/home/sam/Nextcloud/Ordnung", name: "sam-laptop", passphrase: "kirun-bodaf-sumel-tavok-perin", repeat: "kirun-bodaf-sumel-tavok-perin" };
    expect(syncFormProblem(ok, "new")).toBeNull();
    expect(syncFormProblem({ ...ok, folder: "" }, null)?.field).toBe("folder");
    expect(syncFormProblem({ ...ok, folder: "Nextcloud/Ordnung" }, null)?.message).toMatch(/whole path/);
    expect(syncFormProblem({ ...ok, name: " " }, "new")?.field).toBe("name");
    expect(syncFormProblem({ ...ok, name: "x".repeat(NAME_MAX_CHARS + 1) }, "new")?.message).toBe(`Use at most ${NAME_MAX_CHARS} characters.`);
    expect(syncFormProblem({ ...ok, passphrase: "" }, "existing")?.field).toBe("passphrase");
    expect(syncFormProblem({ ...ok, passphrase: "short", repeat: "" }, "existing")).toBeNull(); // joining: the folder says whether it opens
    expect(syncFormProblem({ ...ok, repeat: "" }, "new")?.field).toBe("repeat");
    expect(nameProblem("line\nbreak")).toMatch(/no line breaks/);
    for (const path of ["/home/sam/x", "~/Dropbox/Ordnung", "C:\\Users\\Sam\\Dropbox", "D:/Sync", "\\\\nas\\share"]) expect(looksAbsolute(path)).toBe(true);
    for (const path of ["Dropbox", "./x", "x/y"]) expect(looksAbsolute(path)).toBe(false);
  });

  it("puts a refusal next to its field", () => {
    expect(fieldFor("folder")).toBe("folder");
    expect(fieldFor("full")).toBe("folder");
    expect(fieldFor("name")).toBe("name");
    expect(fieldFor("wrong_passphrase")).toBe("passphrase");
    expect(fieldFor("passphrase")).toBe("passphrase");
    expect(fieldFor("unavailable")).toBe("form");
    expect(fieldFor(null)).toBe("form");
  });

  it("names this computer's state, and the others'", () => {
    const status = { connected: true, mode: "in_use" as const, choice: null, problem: null };
    expect(modeLabel(status)).toEqual({ label: "In use", tone: "ok" });
    expect(modeLabel({ ...status, mode: "standing_by" })).toEqual({ label: "Standing by", tone: "neutral" });
    expect(modeLabel({ ...status, problem: { code: "folder_full", title: "t", message: "m", actions: [] } }).label).toBe("Paused");
    expect(modeLabel({ ...status, choice: { joining: false, sides: [], chosen: null } }).label).toBe("Needs a choice");
    expect(modeLabel({ ...status, connected: false }).label).toBe("Not syncing");
    expect(computerBadge(computer({ in_use: true, state: "in_use" })).label).toBe("In use");
    expect(computerBadge(computer({ state: "closed" })).label).toBe("Closed");
    expect(computerBadge(computer({ state: "left" })).label).toBe("Disconnected");
    expect(computerBadge(computer({ state: "unknown" }))).toEqual({ label: "Can't read it now", tone: "warn" });
    const now = new Date("2026-10-07T12:00:00Z");
    expect(computerLine(computer({ arrived_at: "2026-10-07T09:00:00Z" }), now)).toBe("Last change arrived 3 h ago.");
    expect(computerLine(computer(), now)).toBe("Nothing of it has arrived here yet.");
    expect(latestLine(computer({ has_latest: true }))).toEqual({ tone: "ok", text: "Has your latest changes" });
    expect(latestLine(computer({ has_latest: false }))).toEqual({ tone: "warn", text: "Hasn't received your latest changes yet" });
    expect(latestLine(computer({ has_latest: null }))).toBeNull();
    expect(calendarLine(computer({ calendar: "different_mode" }))).toMatch(/each switch rewrites/);
    expect(calendarLine(computer())).toBeNull();
  });

  it("says when this computer last saved, and what is arriving", () => {
    const now = new Date("2026-10-07T12:00:00Z");
    expect(lastSavedLine({ activity: "idle", last_saved_at: "2026-10-07T11:58:00Z", pending_changes: false }, now)).toBe("Saved to the sync folder 2 min ago.");
    expect(lastSavedLine({ activity: "saving", last_saved_at: null, pending_changes: true }, now)).toBe("Saving to the sync folder…");
    expect(lastSavedLine({ activity: "idle", last_saved_at: "2026-10-07T11:58:00Z", pending_changes: true }, now)).toMatch(/Newer changes follow in a moment/);
    const arriving = { from_computer: "desktop", have: 328, need: 340, have_bytes: 100, need_bytes: 3_355_543, since: "", stalled: false, online_only: 0 };
    expect(arrivingLine(arriving)).toBe("Waiting for 12 of 340 files from your sync tool (3.2 MB).");
    expect(arrivalAdvice(arriving)).toBeNull();
    expect(arrivalAdvice({ ...arriving, stalled: true })).toMatch(/^Nothing more has arrived for 30 minutes/);
    // dataless / online-only files never arrive by themselves (finding 6)
    expect(arrivalAdvice({ ...arriving, online_only: 3 })).toMatch(/^3 files are online only on this computer.*available offline/);
  });

  it("words the standing-by screen", () => {
    const now = new Date("2026-10-07T12:00:00Z");
    const holder = computer({ name: "anna-thinkpad", in_use: true, state: "in_use", arrived_at: "2026-10-07T11:56:00Z" });
    const status = { arriving: null, up_to_date: true, computers: [holder], in_use_on: "anna-thinkpad", base_arrived_at: null };
    expect(standbyStatusLine(status, now)).toBe("Everything from anna-thinkpad has arrived here (the last change arrived 4 min ago).");
    expect(
      standbyStatusLine({ ...status, up_to_date: false, arriving: { from_computer: "anna-thinkpad", have: 5, need: 9, have_bytes: 0, need_bytes: 0, since: "", stalled: false, online_only: 0 } }, now),
    ).toBe("anna-thinkpad's latest changes are still on their way: 5 of 9 files are here.");
    expect(reassuranceLine(status)).toBe("anna-thinkpad's Ordnung is still open. If you use it here, anna-thinkpad switches to standing by — nothing is lost.");
    expect(reassuranceLine({ ...status, computers: [{ ...holder, state: "closed" }] })).toBe("anna-thinkpad was closed. Use Ordnung here: nothing is lost.");
  });

  it("says in the top bar whether the other computer has the latest", () => {
    const base = { activity: "idle" as const, problem: null, pending_changes: false, last_saved_at: "2026-10-07T11:58:00Z" };
    expect(indicatorLabel({ ...base, computers: [here, computer({ has_latest: true })] })).toEqual({ state: "saved", label: "Saved · desktop has it" });
    expect(indicatorLabel({ ...base, computers: [here, computer({ has_latest: false })] }).label).toBe("Saved · desktop hasn't received it yet");
    expect(indicatorLabel({ ...base, pending_changes: true, computers: [here] })).toEqual({ state: "saving", label: "Saving…" });
    expect(indicatorLabel({ ...base, computers: [here] }).label).toBe("Saved to the sync folder");
    expect(indicatorLabel({ ...base, problem: { code: "folder_full", title: "The sync folder is full", message: "", actions: [] }, computers: [here] })).toEqual({
      state: "problem",
      label: "Not saved: The sync folder is full",
    });
    expect(indicatorLabel({ ...base, computers: [here, computer({ has_latest: true }), computer({ key: 3, name: "mac", has_latest: true })] }).label).toBe(
      "Saved · your other computers have it",
    );
  });

  it("words the choice — and says the other side's copy is made by its own computer, once it next starts (finding 28)", () => {
    expect(choiceSideLine({ letters: 342, added: 2 })).toBe("342 letters, 2 added since you last switched");
    expect(choiceSideLine({ letters: 1, added: 0 })).toBe("1 letter");
    expect(choiceSideLine({ letters: 12, added: 12 }, true)).toBe("12 letters");
    expect(sideArrivingLine({ complete: false, arriving: { from_computer: "x", have: 5, need: 9, have_bytes: 0, need_bytes: 0, since: "", stalled: false, online_only: 0 } })).toBe(
      "Still arriving: 5 of 9 files",
    );
    expect(sideArrivingLine({ complete: true, arriving: null })).toBeNull();
    expect(sideContentsLine({ items: 2, done: 1, notes: 0 })).toBe("2 open dates and to-dos · 1 done");
    expect(sideContentsLine({ items: 1, done: 0, notes: 1 })).toBe("1 open date or to-do · 0 done · 1 note");
    expect(sideLatestLine({ latest: [] })).toBeNull();
    expect(
      sideLatestLine({
        latest: [
          { kind: "to-do", label: "Renew the passport", on: "2026-10-07" },
          { kind: "note", label: "Called the landlord", on: "2026-10-05" },
        ],
      }),
    ).toBe("Latest: to-do “Renew the passport” (7 Oct), note “Called the landlord” (5 Oct)");
    const sides = [
      { this: true, computer: "desktop" },
      { this: false, computer: "anna-thinkpad" },
    ];
    expect(chosenMessage(sides[0]!, sides)).toEqual({
      title: "Kept this computer's Ordnung",
      description: "anna-thinkpad's version stays on that computer as a kept copy once it next starts. Nothing is thrown away.",
    });
    expect(chosenMessage(sides[1]!, sides)).toEqual({ title: "Kept anna-thinkpad's Ordnung", description: "This computer's is saved as a backup (Settings → Your computers)." });
  });

  it("asks twice before going while no other computer has this one's latest changes (finding 2)", () => {
    expect(unreceivedLine({ connected: true, others_have_latest: true, computers: [here, computer({ has_latest: true })] })).toBeNull();
    expect(unreceivedLine({ connected: true, others_have_latest: false, computers: [here, computer({ has_latest: false })] })).toMatch(
      /^desktop hasn't received your latest changes yet/,
    );
    expect(unreceivedLine({ connected: true, others_have_latest: false, computers: [here] })).toMatch(/^No other computer has joined this sync yet/);
    expect(unreceivedLine({ connected: false, others_have_latest: false, computers: [] })).toBeNull();
  });

  it("says where calendar sync runs when it isn't connected here (design §6.4)", () => {
    const status = { connected: true, mode: "in_use" as const, computers: [here, computer({ calendar: "other" })] };
    expect(calendarElsewhereNote(status, false)).toBe(
      "Calendar sync is set up on desktop only. Connect it here too, so your calendar stays current while you use this computer.",
    );
    expect(calendarElsewhereNote(status, true)).toBeNull();
    expect(calendarElsewhereNote({ ...status, computers: [here, computer()] }, false)).toBeNull();
  });

  it("gives the restore command of a kept copy, quoted when its path needs it", () => {
    expect(keptRestoreCommand({ name: "k.ordnung-backup", path: "/home/sam/.local/share/ordnung/sync/kept/k.ordnung-backup" })).toBe(
      "ordnung restore /home/sam/.local/share/ordnung/sync/kept/k.ordnung-backup --data-dir ~/Ordnung-kept",
    );
    expect(keptRestoreCommand({ name: "k", path: "/Users/Sam Rivera/Library/Ordnung/sync/kept/k" })).toBe(
      "ordnung restore '/Users/Sam Rivera/Library/Ordnung/sync/kept/k' --data-dir ~/Ordnung-kept",
    );
  });

  it("has words for every problem and action, and never shows a code", () => {
    for (const code of SYNC_PROBLEM_CODES) {
      expect(PROBLEM_TITLES[code]).toBeTruthy();
      assertNoRawEnums(PROBLEM_TITLES[code]);
      expect(problemTitle({ code, title: "" })).toBe(PROBLEM_TITLES[code]);
    }
    for (const action of SYNC_PROBLEM_ACTIONS) assertNoRawEnums(ACTION_LABELS[action]);
    expect(problemTitle({ code: "folder_full", title: "The server's words" })).toBe("The server's words");
  });
});

// ------------------------------------------------------------------------------------------------
// Settings → Your computers
// ------------------------------------------------------------------------------------------------

function openSection(client = makeTestQueryClient()) {
  renderWithProviders(
    <>
      <SettingsPage />
      <Toaster />
    </>,
    { route: "/settings?section=computers", client },
  );
  return client;
}

const section = () => screen.getByRole("region", { name: "Your computers" });

describe("Settings → Your computers: setting up", () => {
  it("is in Settings' list, before Data, and explains itself before asking anything", async () => {
    const { calls } = useMockApi();
    openSection();
    const card = await screen.findByRole("region", { name: "Use Ordnung on more than one computer" }, WAIT);
    const nav = screen.getByRole("navigation", { name: "Settings sections" });
    const names = within(nav)
      .getAllByRole("link")
      .map((l) => l.textContent);
    expect(names.indexOf("Your computers")).toBe(names.indexOf("Data") - 1);
    expect(within(card).getByText("In use on one computer at a time — the others stand by")).toBeInTheDocument();
    expect(within(card).getByLabelText("Sync folder")).toBeInTheDocument();
    expect(within(card).getByLabelText("This computer's name")).toHaveValue("sam-laptop");
    expect(within(card).queryByLabelText("Passphrase")).toBeNull(); // the folder decides what is asked
    expect(within(card).getByRole("button", { name: "Next" })).toBeInTheDocument();
    expect(calls.filter((c) => c.method !== "GET")).toEqual([]);
    assertNoRawEnumsInElement(section());
  });

  it("sets up a new sync folder: a weak passphrase is said as it is typed, a suggested one passes", async () => {
    const { srv } = useMockApi();
    const user = userEvent.setup();
    openSection();
    const card = await screen.findByRole("region", { name: "Use Ordnung on more than one computer" }, WAIT);
    await user.type(within(card).getByLabelText("Sync folder"), "/home/sam/Nextcloud/Ordnung-new");
    await user.click(within(card).getByRole("button", { name: "Next" }));
    expect(await within(card).findByText("A new sync starts in this folder.", {}, WAIT)).toBeInTheDocument();
    const passphrase = within(card).getByLabelText("Passphrase");
    await waitFor(() => expect(passphrase).toHaveFocus());
    await user.type(passphrase, "correct horse battery staple");
    expect(within(card).getByText(/Too easy to guess yet: add one more word/)).toBeInTheDocument();
    await user.type(within(card).getByLabelText("Repeat the passphrase"), "correct horse battery staple");
    await user.click(within(card).getByRole("button", { name: "Start syncing" }));
    expect(passphrase).toHaveAccessibleDescription(WEAK_PASSPHRASE_MESSAGE);
    expect(passphrase).toHaveFocus();
    expect(srv.sync.connected).toBe(false);

    await user.click(within(card).getByRole("button", { name: "Suggest a strong one" }));
    const suggested = (passphrase as HTMLInputElement).value;
    expect(suggested.split("-")).toHaveLength(5);
    expect(within(card).getByLabelText("Repeat the passphrase")).toHaveValue(suggested);
    expect(within(card).getByRole("button", { name: "Copy passphrase" })).toBeInTheDocument();
    expect(within(card).getByText(PASSPHRASE_WORDING)).toBeInTheDocument();
    await user.click(within(card).getByRole("button", { name: "Start syncing" }));
    expect(await screen.findByText("Syncing to your folder", {}, WAIT)).toBeInTheDocument();
    const mine = await screen.findByRole("region", { name: "This computer" }, WAIT);
    expect(within(mine).getByText("sam-laptop")).toBeInTheDocument();
    expect(within(mine).getByText("In use")).toBeInTheDocument();
    expect(srv.sync.connected).toBe(true);
    expect(srv.db.state.activity[0]?.kind).toBe("sync.connected");
  });

  it("says a folder's refusal, and a wrong passphrase, under their fields", async () => {
    useMockApi();
    const user = userEvent.setup();
    openSection();
    const card = await screen.findByRole("region", { name: "Use Ordnung on more than one computer" }, WAIT);
    const folder = within(card).getByLabelText("Sync folder");
    await user.type(folder, "Nextcloud/Ordnung");
    await user.click(within(card).getByRole("button", { name: "Next" }));
    expect(folder).toHaveAccessibleDescription(/whole path/);
    await user.clear(folder);
    await user.type(folder, "/home/sam/Documents");
    await user.tab(); // looked at when the field is left
    await waitFor(() => expect(folder).toHaveAccessibleDescription(/holds other files/));

    await user.clear(folder);
    await user.type(folder, SYNC_EXISTING_FOLDER);
    await user.click(within(card).getByRole("button", { name: "Next" }));
    expect(await within(card).findByText(/holds a sync from your other computer/, {}, WAIT)).toBeInTheDocument();
    const passphrase = within(card).getByLabelText("The sync passphrase");
    expect(within(card).queryByLabelText("Repeat the passphrase")).toBeNull(); // joining: typed once
    expect(within(card).queryByRole("button", { name: "Suggest a strong one" })).toBeNull();
    await user.type(passphrase, "wrong horse battery staple");
    await user.click(within(card).getByRole("button", { name: "Bring it here" }));
    await waitFor(() => expect(passphrase).toHaveAccessibleDescription(WRONG_PASSPHRASE_MESSAGE));
    await waitFor(() => expect(passphrase).toHaveFocus());
  });

  it("takes the computer's name typed while the folder is looked at (leaving the folder field looks at it)", async () => {
    useMockApi();
    const mocked = globalThis.fetch;
    let asked = false;
    let release!: () => void;
    const held = new Promise<void>((done) => (release = done));
    vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).includes("/api/sync/inspect")) {
        asked = true;
        await held;
      }
      return mocked(input, init);
    });
    const user = userEvent.setup();
    openSection();
    const card = await screen.findByRole("region", { name: "Use Ordnung on more than one computer" }, WAIT);
    await user.type(within(card).getByLabelText("Sync folder"), "/home/sam/Nextcloud/Ordnung-new");
    const name = within(card).getByLabelText("This computer's name");
    await user.click(name);
    await waitFor(() => expect(asked).toBe(true), WAIT);
    await user.clear(name);
    await user.type(name, "desk");
    expect(name).toHaveValue("desk");
    release();
    expect(await within(card).findByRole("button", { name: "Start syncing" }, WAIT)).toBeEnabled();
    expect(name).toHaveValue("desk");
  });

  it("warns when Ordnung's data folder itself is inside a synced folder", async () => {
    const { srv } = useMockApi();
    srv.sync.dataFolderSynced = true;
    const user = userEvent.setup();
    openSection();
    const card = await screen.findByRole("region", { name: "Use Ordnung on more than one computer" }, WAIT);
    await user.type(within(card).getByLabelText("Sync folder"), "/home/sam/Nextcloud/Ordnung-new");
    await user.click(within(card).getByRole("button", { name: "Next" }));
    expect(await within(card).findByText("Ordnung's data folder is inside a synced folder", {}, WAIT)).toBeInTheDocument();
    expect(within(card).getByText(/unencrypted/)).toBeInTheDocument();
  });

  it("joining while this computer has letters asks first which Ordnung to keep — nothing preselected", async () => {
    const { srv } = useMockApi();
    const user = userEvent.setup();
    openSection();
    const card = await screen.findByRole("region", { name: "Use Ordnung on more than one computer" }, WAIT);
    await user.type(within(card).getByLabelText("Sync folder"), SYNC_EXISTING_FOLDER);
    await user.click(within(card).getByRole("button", { name: "Next" }));
    await user.type(await within(card).findByLabelText("The sync passphrase", {}, WAIT), "kirun bodaf sumel tavok perin");
    await user.click(within(card).getByRole("button", { name: "Bring it here" }));
    const choice = await within(card).findByRole("group", { name: /This computer already has its own Ordnung \(\d+ letters\)\. sam-desktop's has 340 letters\. Which do you want to keep\?/ }, WAIT);
    const radios = within(choice).getAllByRole("radio");
    expect(radios).toHaveLength(2);
    for (const r of radios) expect(r).not.toBeChecked();
    expect(within(card).getByRole("button", { name: "Keep this one" })).toBeDisabled();
    expect(srv.sync.connected).toBe(false); // nothing is connected before the answer
    await user.click(within(choice).getByRole("radio", { name: /sam-desktop/ }));
    await user.click(within(card).getByRole("button", { name: "Keep this one" }));
    expect(await screen.findByText("Ordnung is in use here now", {}, WAIT)).toBeInTheDocument();
    // this computer's own Ordnung was kept as a copy first
    const kept = await screen.findByRole("region", { name: "Kept copies" }, WAIT);
    expect(within(kept).getByText(/before you brought sam-desktop's Ordnung here/)).toBeInTheDocument();
  });

  it("a name another computer has already gets “ (2)” (finding 29)", async () => {
    const { srv } = useMockApi();
    srv.db.state.documents = []; // nothing here yet: joining brings the other computer's Ordnung over
    const user = userEvent.setup();
    openSection();
    const card = await screen.findByRole("region", { name: "Use Ordnung on more than one computer" }, WAIT);
    expect(within(card).getByLabelText("This computer's name")).toHaveAccessibleDescription(/A name already taken gets “ \(2\)”/);
    await user.type(within(card).getByLabelText("Sync folder"), SYNC_EXISTING_FOLDER);
    await user.click(within(card).getByRole("button", { name: "Next" }));
    const name = within(card).getByLabelText("This computer's name");
    await user.clear(name);
    await user.type(name, SYNC_OTHER_NAME);
    await user.type(await within(card).findByLabelText("The sync passphrase", {}, WAIT), "kirun bodaf sumel tavok perin");
    await user.click(within(card).getByRole("button", { name: "Bring it here" }));
    const mine = await screen.findByRole("region", { name: "This computer" }, WAIT);
    expect(within(mine).getByText(`${SYNC_OTHER_NAME} (2)`)).toBeInTheDocument();
  });

  it("says why it can't be used here: the online demo, or a password store to install", async () => {
    vi.stubEnv("VITE_STATIC_DEMO", "1");
    useMockApi({ staticDemo: true });
    openSection();
    expect(await screen.findByRole("note", {}, WAIT)).toHaveTextContent(SYNC_STATIC_MESSAGE);
    expect(screen.queryByLabelText("Sync folder")).toBeNull();
    vi.unstubAllEnvs();
  });

  it("offers the command that installs a password store", async () => {
    useMockApi();
    const status = await api.sync();
    vi.spyOn(api, "sync").mockResolvedValue({ ...status, available: false, unavailable: "No password store on this computer.", install_command: "pipx inject ordnung keyring-pass" });
    openSection();
    expect(await screen.findByText("One more package, then this works", {}, WAIT)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Copy command to install the password store: pipx inject ordnung keyring-pass/ })).toBeInTheDocument();
  });
});

describe("Settings → Your computers: connected", () => {
  it("in use: the folder, the last save, Save now, the other computer and whether it has the latest", async () => {
    const { srv } = useMockApi();
    srv.sync.setUp();
    srv.sync.computers[1]!.calendar = "same";
    const user = userEvent.setup();
    openSection();
    const mine = await screen.findByRole("region", { name: "This computer" }, WAIT);
    expect(within(mine).getByText("In use")).toBeInTheDocument();
    expect(within(mine).getByText(SYNC_EXISTING_FOLDER)).toBeInTheDocument();
    expect(within(mine).getByText("Saved to the sync folder 2 min ago.")).toBeInTheDocument();
    await user.click(within(mine).getByRole("button", { name: "Save now" }));
    expect(await screen.findByText("Saved to the sync folder", {}, WAIT)).toBeInTheDocument();
    const others = screen.getByRole("region", { name: "Your other computers" });
    expect(within(others).getByText(SYNC_OTHER_NAME)).toBeInTheDocument();
    expect(within(others).getByText("Standing by")).toBeInTheDocument();
    expect(within(others).getByText("Last change arrived 10 min ago.")).toBeInTheDocument();
    expect(within(others).getByText("Has your latest changes")).toBeInTheDocument();
    expect(within(others).getByText("Sends to the same calendar as this computer.")).toBeInTheDocument();
    assertNoRawEnumsInElement(section());
  });

  it("standing by (this page stays open): Use Ordnung here takes over", async () => {
    const { srv } = useMockApi();
    srv.sync.setUp().otherTakesOver();
    const user = userEvent.setup();
    openSection();
    const mine = await screen.findByRole("region", { name: "This computer" }, WAIT);
    expect(within(mine).getByText("Standing by")).toBeInTheDocument();
    expect(within(mine).getByText(/In use on sam-desktop\. Everything from sam-desktop has arrived here/)).toBeInTheDocument();
    await user.click(within(mine).getByRole("button", { name: "Use Ordnung here" }));
    expect(await screen.findByText("Ordnung is in use here now", {}, WAIT)).toBeInTheDocument();
    await waitFor(() => expect(within(screen.getByRole("region", { name: "This computer" })).getByText("In use")).toBeInTheDocument());
  });

  it("a problem says what to do: the passphrase typed again (a wrong one refused under its field)", async () => {
    const { srv } = useMockApi();
    srv.sync.setUp().setProblem("passphrase_needed");
    const user = userEvent.setup();
    openSection();
    const mine = await screen.findByRole("region", { name: "This computer" }, WAIT);
    expect(within(mine).getByText("Paused")).toBeInTheDocument();
    expect(within(mine).getByText("Type the sync passphrase again")).toBeInTheDocument();
    const field = within(mine).getByLabelText("Sync passphrase");
    await user.type(field, "wrong one");
    await user.click(within(mine).getByRole("button", { name: "Save passphrase" }));
    await waitFor(() => expect(field).toHaveAccessibleDescription(WRONG_PASSPHRASE_MESSAGE));
    await user.clear(field);
    await user.type(field, "kirun bodaf sumel tavok perin");
    await user.click(within(mine).getByRole("button", { name: "Save passphrase" }));
    expect(await screen.findByText("Saved in this computer's password store", {}, WAIT)).toBeInTheDocument();
    expect(srv.sync.problem).toBeNull();
  });

  it.each([
    ["copied_folder", "This is the same computer"],
    ["folder_empty", "Fill it again from this computer"],
    ["local_rollback", "Keep this computer's data as it is"],
    ["pull_unfinished", "Give up bringing it over"],
  ] as const)("%s: %s", async (code, action) => {
    const { srv } = useMockApi();
    srv.sync.setUp().setProblem(code);
    const user = userEvent.setup();
    openSection();
    const mine = await screen.findByRole("region", { name: "This computer" }, WAIT);
    expect(within(mine).getByText(PROBLEM_TITLES[code])).toBeInTheDocument();
    await user.click(within(mine).getByRole("button", { name: action }));
    await waitFor(() => expect(srv.sync.problem).toBeNull());
    await waitFor(() => expect(within(screen.getByRole("region", { name: "This computer" })).queryByText(PROBLEM_TITLES[code])).toBeNull());
    assertNoRawEnumsInElement(section());
  });

  it("a copied data folder can also be set up as a new computer (it disconnects first)", async () => {
    const { srv } = useMockApi();
    srv.sync.setUp().setProblem("copied_folder");
    const user = userEvent.setup();
    openSection();
    const mine = await screen.findByRole("region", { name: "This computer" }, WAIT);
    await user.click(within(mine).getByRole("button", { name: "Set up as a new computer" }));
    const dialog = await screen.findByRole("dialog", { name: "Disconnect this computer?" });
    await user.click(within(dialog).getByRole("button", { name: "Disconnect" }));
    expect(await screen.findByRole("region", { name: "Use Ordnung on more than one computer" }, WAIT)).toBeInTheDocument();
  });

  it("forgets a lost computer — and says it still knows the passphrase", async () => {
    const { srv } = useMockApi();
    srv.sync.setUp();
    srv.sync.addComputer({ name: "old-laptop" });
    const user = userEvent.setup();
    openSection();
    const others = await screen.findByRole("region", { name: "Your other computers" }, WAIT);
    const row = within(others).getByText("old-laptop").closest("li")!;
    expect(within(row).getByText("Hasn't received your latest changes yet")).toBeInTheDocument();
    await user.click(within(row).getByRole("button", { name: "Forget…" }));
    const dialog = await screen.findByRole("dialog", { name: "Forget old-laptop?" });
    expect(within(dialog).getByText(/old-laptop still knows the passphrase/)).toBeInTheDocument();
    await waitFor(() => expect(within(dialog).getByRole("button", { name: "Cancel" })).toHaveFocus());
    await user.click(within(dialog).getByRole("button", { name: "Forget" }));
    expect(await screen.findByText("old-laptop was removed from sync", {}, WAIT)).toBeInTheDocument();
    expect(srv.sync.computers.map((c) => c.name)).not.toContain("old-laptop");
  });

  it("lists kept copies: download one, delete one, and how to open one", async () => {
    const { srv } = useMockApi();
    srv.sync.setUp();
    const kept = srv.sync.addKept();
    const created = vi.fn(() => "blob:kept");
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: created, revokeObjectURL: () => {} }));
    const user = userEvent.setup();
    openSection();
    const card = await screen.findByRole("region", { name: "Kept copies" }, WAIT);
    expect(within(card).getByText(kept.name, { selector: "p" })).toBeInTheDocument();
    expect(within(card).getByText(/before you kept sam-desktop's Ordnung/)).toBeInTheDocument();
    expect(within(card).getByRole("button", { name: /Copy command to restore the kept copy: ordnung restore .*--data-dir/ })).toBeInTheDocument();
    expect(within(card).getByText(/never synced, never deleted by themselves/)).toBeInTheDocument();
    await user.click(within(card).getByRole("button", { name: `Download ${kept.name}` }));
    await waitFor(() => expect(created).toHaveBeenCalled());
    await user.click(within(card).getByRole("button", { name: `Delete… ${kept.name}` }));
    const dialog = await screen.findByRole("dialog", { name: "Delete this kept copy?" });
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(screen.queryByRole("region", { name: "Kept copies" })).toBeNull());
    expect(srv.sync.kept).toEqual([]);
  });

  it("shows notices once, until dismissed", async () => {
    const { srv } = useMockApi();
    srv.sync.setUp();
    srv.sync.addNotice("take_over_cancelled", "Ordnung stopped waiting: sam-desktop saved a new change meanwhile.");
    const user = userEvent.setup();
    openSection();
    expect(await screen.findByText("Ordnung stopped waiting to take over", {}, WAIT)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Dismiss" }));
    await waitFor(() => expect(screen.queryByText("Ordnung stopped waiting to take over")).toBeNull());
  });

  it("disconnects at once while another computer has the latest, focusing the setup card after", async () => {
    const { srv } = useMockApi();
    srv.sync.setUp();
    const user = userEvent.setup();
    openSection();
    const mine = await screen.findByRole("region", { name: "This computer" }, WAIT);
    await user.click(within(mine).getByRole("button", { name: "Disconnect…" }));
    const dialog = await screen.findByRole("dialog", { name: "Disconnect this computer?" });
    await waitFor(() => expect(within(dialog).getByRole("button", { name: "Cancel" })).toHaveFocus());
    expect(within(dialog).queryByText(/haven't reached another computer/)).toBeNull();
    await user.click(within(dialog).getByRole("button", { name: "Disconnect" }));
    expect(await screen.findByText("This computer stopped syncing", {}, WAIT)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("heading", { name: "Use Ordnung on more than one computer" })).toHaveFocus());
    expect(srv.sync.connected).toBe(false);
  });

  it("asks a second time while no other computer has this one's latest changes (finding 2)", async () => {
    const { srv, calls } = useMockApi();
    srv.sync.setUp();
    srv.sync.computers[1]!.has_latest = false;
    const user = userEvent.setup();
    openSection();
    const mine = await screen.findByRole("region", { name: "This computer" }, WAIT);
    await user.click(within(mine).getByRole("button", { name: "Disconnect…" }));
    const dialog = await screen.findByRole("dialog", { name: "Disconnect this computer?" });
    expect(within(dialog).getByText(/sam-desktop hasn't received your latest changes yet/)).toBeInTheDocument();
    const go = within(dialog).getByRole("button", { name: "Disconnect anyway" });
    expect(go).toBeDisabled();
    await user.click(within(dialog).getByRole("checkbox", { name: /Disconnect anyway/ }));
    await user.click(go);
    expect(await screen.findByText("This computer stopped syncing", {}, WAIT)).toBeInTheDocument();
    expect(calls.find((c) => c.method === "DELETE" && c.path === "/sync")?.body).toEqual({ forget_passphrase: true, unreceived_ok: true });
  });
});

describe("Settings → Data → Delete everything, with hand-off sync", () => {
  it("says this computer stops syncing, asks a second time when needed, and leaves a shared calendar's events", async () => {
    const { srv, calls } = useMockApi();
    srv.db.state.health.demo = false;
    srv.sync.setUp();
    srv.sync.computers[1]!.has_latest = false;
    srv.sync.computers[1]!.calendar = "same";
    const client = makeTestQueryClient();
    client.setQueryData(qk.health, { ...TEST_HEALTH, demo: false });
    const user = userEvent.setup();
    renderWithProviders(
      <>
        <SettingsPage />
        <Toaster />
      </>,
      { route: "/settings?section=data", client },
    );
    await user.click(await screen.findByRole("button", { name: "Delete everything…" }, WAIT));
    const dialog = await screen.findByRole("dialog", { name: "Delete everything?" });
    expect(await within(dialog).findByText(new RegExp(deleteSyncNote(SYNC_EXISTING_FOLDER).slice(0, 60).replace(/[.()]/g, "\\$&")), {}, WAIT)).toBeInTheDocument();
    expect(within(dialog).getByText(/sam-desktop sends to the same calendar, so Ordnung's events stay there/)).toBeInTheDocument();
    expect(within(dialog).getByText(/sam-desktop hasn't received your latest changes yet/)).toBeInTheDocument();
    await user.type(within(dialog).getByLabelText("Type DELETE to confirm"), "DELETE");
    const confirm = within(dialog).getByRole("button", { name: "Delete everything" });
    expect(confirm).toBeDisabled();
    await user.click(within(dialog).getByRole("checkbox", { name: /Delete anyway/ }));
    await user.click(confirm);
    const toast = await screen.findByText("Everything was deleted", {}, WAIT);
    const description = toast.closest("li")!;
    expect(description).toHaveTextContent(SYNC_STOPPED);
    expect(description).toHaveTextContent("Ordnung's events stay in your calendar: sam-desktop still sends to it.");
    expect(calls.find((c) => c.method === "DELETE" && c.path === "/data")?.body).toEqual({ confirm: "DELETE", unreceived_ok: true });
    expect(srv.sync.connected).toBe(false);
  });

  it("asks the second question when the server does (409 not_received)", async () => {
    const { srv } = useMockApi();
    srv.db.state.health.demo = false;
    srv.sync.setUp();
    const client = makeTestQueryClient();
    client.setQueryData(qk.health, { ...TEST_HEALTH, demo: false });
    // the status still says another computer has the latest; the server knows better by now
    const status: SyncStatus = srv.sync.status();
    vi.spyOn(api, "sync").mockResolvedValue(status);
    srv.sync.computers[1]!.has_latest = false;
    const user = userEvent.setup();
    renderWithProviders(
      <>
        <SettingsPage />
        <Toaster />
      </>,
      { route: "/settings?section=data", client },
    );
    await user.click(await screen.findByRole("button", { name: "Delete everything…" }, WAIT));
    const dialog = await screen.findByRole("dialog", { name: "Delete everything?" });
    await user.type(within(dialog).getByLabelText("Type DELETE to confirm"), "DELETE");
    await user.click(within(dialog).getByRole("button", { name: "Delete everything" }));
    expect(await within(dialog).findByText(/No other computer has this computer's latest changes yet/, {}, WAIT)).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Delete everything" })).toBeDisabled();
    await user.click(within(dialog).getByRole("checkbox", { name: /Delete anyway/ }));
    await user.click(within(dialog).getByRole("button", { name: "Delete everything" }));
    expect(await screen.findByText("Everything was deleted", {}, WAIT)).toBeInTheDocument();
  });
});
