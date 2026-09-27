/**
 * The states of My numbers (`/numbers`) and the weekly session (`/week`, and its prompt on Today) —
 * for the demo, the first run and the static demo. Imported by demo.mjs, fresh.mjs and static.mjs.
 */
import { fakeApi, pinToasts } from "../browser.mjs";
import { inMain } from "../steps.mjs";

const STEPS = ["new", "check", "pay", "post", "waiting", "decide", "file"];
const NUMBERS = "numbers";
const WEEK = "week";

/** Click every "Show" button in the page's main area (hidden numbers become readable). */
async function showAll(c) {
  const buttons = inMain(c.page).getByRole("button", { name: /^Show / });
  const n = await buttons.count();
  for (let i = 0; i < n; i += 1) await c.click(buttons.nth(0), { settleAfter: i === n - 1 });
}

/** Read-only states of the demo (main phase, in parallel). */
export function numbersAndWeekDemoStates() {
  const S = [];
  const add = (s) => S.push(s);
  const main = inMain;

  add({ id: "numbers", group: NUMBERS, route: "/numbers", how: "open /numbers", description: "My numbers → About you: your numbers (hidden) and your documents with their expiry.", run: (c) => c.goto("/numbers") });
  add({
    id: "numbers-shown",
    group: NUMBERS,
    route: "/numbers",
    how: "open /numbers, press every “Show”",
    description: "About you with every number shown (the longest values, check-digit notes).",
    run: async (c) => {
      await c.goto("/numbers");
      await showAll(c);
    },
  });
  add({
    id: "numbers-copied",
    group: NUMBERS,
    route: "/numbers",
    how: "open /numbers, press the first “Copy”",
    description: "A number just copied (“Copied”, announced to screen readers).",
    run: async (c) => {
      await c.goto("/numbers");
      await c.click(main(c.page).getByRole("button", { name: /^Copy / }).first(), { settleAfter: false });
      await c.wait(150);
    },
  });
  add({
    id: "numbers-check-tooltip",
    group: NUMBERS,
    route: "/numbers",
    how: "open /numbers, hover the first check-digit badge",
    description: "The tooltip that says what the check digit proves (and what not).",
    run: async (c) => {
      await c.goto("/numbers");
      await c.hover(main(c.page).getByRole("button", { name: /^(Check digit OK|Does not check)/ }).first());
    },
  });
  add({ id: "numbers-cases", group: NUMBERS, route: "/numbers?tab=cases", how: "open /numbers, tab “Open cases”", description: "Open cases: the references to quote and each case's next step.", run: (c) => c.goto("/numbers?tab=cases") });
  add({
    id: "numbers-organisations",
    group: NUMBERS,
    route: "/numbers?tab=organisations",
    how: "open /numbers, tab “Organisations”",
    description: "A call sheet per organisation: contact, your numbers, open cases, last letter.",
    run: (c) => c.goto("/numbers?tab=organisations"),
  });
  add({
    id: "numbers-organisations-theirs",
    group: NUMBERS,
    route: "/numbers?tab=organisations",
    how: "open the Organisations tab, open the first “Their own numbers”, show its numbers",
    description: "A call sheet with the organisation's own registry and bank numbers open.",
    run: async (c) => {
      await c.goto("/numbers?tab=organisations");
      const summary = main(c.page).locator("summary").first();
      if (await c.exists(summary)) await c.click(summary);
      else c.note("no call sheet with their own numbers");
    },
  });
  add({
    id: "numbers-organisations-search-empty",
    group: NUMBERS,
    route: "/numbers?tab=organisations",
    how: "open the Organisations tab, search for “zzz”",
    description: "Call sheets searched with nothing matching.",
    run: async (c) => {
      await c.goto("/numbers?tab=organisations");
      await c.type(main(c.page).getByRole("searchbox", { name: /Find an organisation/ }), "zzz");
    },
  });

  for (const step of STEPS) {
    add({
      id: `week-${step}`,
      group: WEEK,
      route: `/week?step=${step}`,
      how: `open /week?step=${step}`,
      description: `The weekly session, step “${step}”.`,
      run: (c) => c.goto(step === "new" ? "/week" : `/week?step=${step}`),
    });
  }
  add({
    id: "week-pay-panel",
    group: WEEK,
    route: "/week?step=pay",
    how: "open /week?step=pay, press the first “Pay”",
    description: "The Pay panel opened from the weekly session.",
    run: async (c) => {
      await c.goto("/week?step=pay");
      await c.click(main(c.page).getByRole("button", { name: /^Pay: / }).first());
    },
  });
  add({
    id: "week-all-clear",
    group: WEEK,
    route: "/week?step=file",
    how: "open the last step, press “Finish” (the POST is answered by the audit: nothing is stored)",
    description: "“All clear until …” at the end of the session.",
    run: async (c) => {
      await fakeApi(c.page, "POST", /^\/api\/week\/done$/, async (_req) => ({ json: { ...(await c.page.evaluate(() => fetch("/api/week").then((r) => r.json()))), due: false } }));
      await pinToasts(c.page);
      await c.goto("/week?step=file");
      await c.click(main(c.page).getByRole("button", { name: /^Finish/ }));
    },
  });
  add({
    id: "today-weekly-dismissed",
    group: "today",
    route: "/",
    how: "open /, “Not now” on the weekly-review prompt (answered by the audit), scroll to the foot",
    description: "Today after “Not now”: the quiet “Weekly review” link at the foot of the page.",
    run: async (c) => {
      await fakeApi(c.page, "POST", /^\/api\/week\/dismiss$/, async (_req) => ({ json: { ...(await c.page.evaluate(() => fetch("/api/week").then((r) => r.json()))), due: false } }));
      await c.goto("/");
      const notNow = main(c.page).getByRole("button", { name: "Not now" });
      if (await c.exists(notNow)) await c.click(notNow);
      else c.note("no weekly-review prompt on Today");
      await c.scrollTo(main(c.page).getByRole("link", { name: /Weekly review/ }));
    },
  });
  return S;
}

/** Mutation-phase states (after the audit drafted letters and marked one as sent). */
export function numbersAndWeekMutationStates() {
  return [
    { id: "week-post-with-letters", group: WEEK, route: "/week?step=post", how: "open /week?step=post after the audit drafted letters and sent one", description: "Letters to post, and a sent letter with what proves sending.", run: (c) => c.goto("/week?step=post") },
    { id: "week-waiting-with-reply", group: WEEK, route: "/week?step=waiting", how: "open /week?step=waiting after a letter was marked as sent", description: "Waiting for a reply to the letter the audit sent.", run: (c) => c.goto("/week?step=waiting") },
  ];
}

/** First run: both pages with no letters. */
export function numbersAndWeekEmptyStates(group) {
  return [
    { id: "empty-numbers", group, route: "/numbers", how: "open /numbers", description: "My numbers with no letters (Add letters).", run: (c) => c.goto("/numbers") },
    { id: "empty-week", group, route: "/week", how: "open /week", description: "The weekly session with nothing to look at.", run: (c) => c.goto("/week") },
  ];
}

/** The static demo (hash routes). */
export function numbersAndWeekStaticPaths() {
  return [
    ["numbers", "/numbers", "Static demo: My numbers."],
    ["numbers-organisations", "/numbers?tab=organisations", "Static demo: My numbers → Organisations."],
    ["week", "/week", "Static demo: the weekly session."],
    ["week-pay", "/week?step=pay", "Static demo: the weekly session, “Pay this week”."],
  ];
}
