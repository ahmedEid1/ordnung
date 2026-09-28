/**
 * The states of My numbers (`/numbers`) and the weekly session (`/week`, and its prompt on Today) —
 * for the demo, the first run and the static demo. Imported by demo.mjs, fresh.mjs and static.mjs.
 */
import { fakeApi, pinToasts } from "../browser.mjs";
import { inMain } from "../steps.mjs";

const STEPS = ["new", "check", "pay", "post", "waiting", "decide", "file"];

/** The day Today suggests the session again after one done or dismissed on `day` (`week.prompt_due`). */
function nextPromptDay(day) {
  const at = (n) => new Date(Date.parse(`${day}T00:00:00Z`) + n * 86_400_000);
  for (let n = 4; n < 7; n += 1) if (at(n).getUTCDay() === 0) return at(n).toISOString().slice(0, 10);
  return at(7).toISOString().slice(0, 10);
}

/** `GET /api/week` as `POST /api/week/done|dismiss` would answer it (the audit stores nothing). */
async function weekAfter(c) {
  const week = await c.page.evaluate(() => fetch("/api/week").then((r) => r.json()));
  return { ...week, due: false, next_prompt: nextPromptDay(week.today) };
}
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
      if (await c.exists(summary)) {
        await c.click(summary);
        await c.page.evaluate(() => window.scrollTo(0, 0)); // the tabs back from under the top bar
      } else c.note("no call sheet with their own numbers");
    },
  });
  add({
    id: "numbers-organisations-search-empty",
    group: NUMBERS,
    route: "/numbers?tab=organisations",
    how: "open the Organisations tab, search for “no such organisation” (words no number holds)",
    description: "Call sheets searched with nothing matching.",
    run: async (c) => {
      await c.goto("/numbers?tab=organisations");
      await c.type(main(c.page).getByRole("searchbox", { name: /Find an organisation/ }), "no such organisation");
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
      await fakeApi(c.page, "POST", /^\/api\/week\/done$/, async (_req) => ({ json: await weekAfter(c) }));
      await pinToasts(c.page);
      await c.goto("/week?step=file");
      await c.click(main(c.page).getByRole("button", { name: /^Finish/ }));
    },
  });
  // endings the demo's today doesn't reach on its own: the rows are the demo's, their days moved
  const today = (week) => week.today;
  const endWith = (id, description, shape) =>
    add({
      id,
      group: WEEK,
      route: "/week?step=file",
      how: "open the last step, press “Finish” (GET /api/week and the POST answered by the audit with the demo's rows, their days moved)",
      description,
      run: async (c) => {
        await fakeApi(c.page, "GET", /^\/api\/week$/, async (_req, original) => ({ json: shape(original) }), { passthrough: true });
        // the page's own GET goes through the shape above
        await fakeApi(c.page, "POST", /^\/api\/week\/done$/, async (_req) => ({ json: await weekAfter(c) }));
        await pinToasts(c.page);
        await c.goto("/week?step=file");
        await c.click(main(c.page).getByRole("button", { name: /^Finish/ }));
      },
    });
  endWith("week-ending-today", "The ending when several things are to do today: “3 things to do today”, the first one, and a way to each step that holds them.", (week) => {
    const pay = week.steps.find((s) => s.id === "pay");
    const moved = pay.entries.slice(0, 2).map((e) => ({ ...e, date: today(week), date_role: "transfer_by", overdue: false, tone: "neutral", note: null }));
    const steps = week.steps.map((s) => (s.id === "pay" ? { ...s, entries: [...moved, ...s.entries.slice(2)] } : s));
    const form = { ...moved[0], key: "item:audit-form", ref: { type: "item", id: "audit-form" }, title: "Hand in the Anmeldung form at the Bürgeramt", kind: "deadline", date_role: "due", amount: null, item: null };
    const now = { id: "now", title: "Act now", summary: "1 to do today", entries: [form], more: 0, total: null, total_other_currencies: {} };
    return { ...week, steps: [now, ...steps], overdue: 0, next_deadline: form, due_today: 3 };
  });
  endWith("week-ending-overdue-steps", "The ending with overdue rows in two steps: “2 things are overdue” and a way to each step.", (week) => {
    const pay = week.steps.find((s) => s.id === "pay");
    const late = { ...pay.entries[0], date: "2026-09-20", overdue: true, tone: "danger" };
    const steps = week.steps.map((s) => (s.id === "pay" ? { ...s, entries: [late, ...s.entries.slice(1)] } : s));
    const task = { ...late, key: "item:audit-task", ref: { type: "item", id: "audit-task" }, title: "Send the documents to the Jobcenter", kind: "task", date_role: "by", amount: null, item: null };
    const now = { id: "now", title: "Act now", summary: "1 overdue", entries: [task], more: 0, total: null, total_other_currencies: {} };
    return { ...week, steps: [now, ...steps], overdue: 2 };
  });
  add({
    id: "week-post-act-today",
    group: WEEK,
    route: "/week?step=post",
    how: "open /week?step=post (GET /api/week answered with the demo's letter as on a day after its send-by day)",
    description: "A letter whose day to post has passed but that can still arrive in time: “Act today — due …”, not overdue.",
    run: async (c) => {
      await fakeApi(
        c.page,
        "GET",
        /^\/api\/week$/,
        async (_req, week) => ({
          json: {
            ...week,
            steps: week.steps.map((s) =>
              s.id === "post"
                ? { ...s, entries: s.entries.map((e, i) => (i === 0 ? { ...e, date: week.today, date_role: "act_today", due_date: e.due_date ?? e.date, overdue: false, note: "The last safe day to post it has passed, but the due date is still ahead: hand it in today, or send it a way that arrives in time (fax, or an online form the sender accepts). Then mark it as sent." } : e)) }
                : s,
            ),
          },
        }),
        { passthrough: true },
      );
      await c.goto("/week?step=post");
    },
  });
  add({
    id: "numbers-cases-late",
    group: NUMBERS,
    route: "/numbers?tab=cases",
    how: "open /numbers, tab “Open cases” (GET /api/numbers answered with the first case's day to act passed and the second one's due date passed)",
    description: "Open cases whose next step is to act on today (the send-by day passed) and one that is overdue.",
    run: async (c) => {
      await fakeApi(
        c.page,
        "GET",
        /^\/api\/numbers$/,
        async (_req, numbers) => {
          const day = (n) => new Date(Date.parse(`${numbers.today}T00:00:00Z`) + n * 86_400_000).toISOString().slice(0, 10);
          const late = (c2, i) =>
            !c2.next_item || i > 1 ? c2 : { ...c2, next_item: { ...c2.next_item, kind: i === 0 ? "deadline" : "payment", at_appointment: false, send_by: day(i === 0 ? -2 : -16), due_date: day(i === 0 ? 3 : -14) } };
          return { json: { ...numbers, open_cases: numbers.open_cases.map(late) } };
        },
        { passthrough: true },
      );
      await c.goto("/numbers?tab=cases");
    },
  });
  add({
    id: "numbers-long-label",
    group: NUMBERS,
    route: "/numbers?tab=organisations",
    how: "open /numbers, tab “Organisations” (GET /api/numbers answered with a long compound German label on the first number)",
    description: "A number whose title is the letter's own long German label: it wraps inside its card.",
    run: async (c) => {
      await fakeApi(
        c.page,
        "GET",
        /^\/api\/numbers$/,
        async (_req, numbers) => {
          const label = "Rentenversicherungsnummer/Sozialversicherungsnummer/Versicherungsnummer";
          const [first, ...rest] = numbers.organisations;
          const [n, ...more] = first.numbers;
          return { json: { ...numbers, organisations: [{ ...first, numbers: [{ ...n, kind: "other", name: "Your number", label }, ...more] }, ...rest] } };
        },
        { passthrough: true },
      );
      await c.goto("/numbers?tab=organisations");
    },
  });
  add({
    id: "today-weekly-dismissed",
    group: "today",
    route: "/",
    how: "open /, “Not now” on the weekly-review prompt (answered by the audit), scroll to the foot",
    description: "Today after “Not now”: the quiet “Weekly review” link at the foot of the page.",
    run: async (c) => {
      await fakeApi(c.page, "POST", /^\/api\/week\/dismiss$/, async (_req) => ({ json: await weekAfter(c) }));
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

/** Pay the first transfer of the static demo's session, then go on to the last step and press Finish. */
async function payFirstThenFinish(c) {
  const main = inMain(c.page);
  await c.click(main.getByRole("button", { name: /^Pay: / }).first());
  await c.click(c.page.getByRole("dialog").getByRole("button", { name: "Mark as paid" }));
  for (let i = 0; i < 8; i += 1) {
    const next = main.getByRole("button", { name: /^Next: / });
    if (!(await c.exists(next))) break;
    await c.click(next);
  }
  await c.click(main.getByRole("button", { name: /^Finish/ }));
  // the mock answers after a short delay: capture the ending, not the pending button
  await main.getByRole("heading", { level: 2, name: /^(All clear|One thing|\d+ things)/ }).waitFor({ timeout: 15_000 });
}

/** The static demo (hash routes; a fourth element: what to do there). */
export function numbersAndWeekStaticPaths() {
  return [
    ["numbers", "/numbers", "Static demo: My numbers."],
    ["numbers-organisations", "/numbers?tab=organisations", "Static demo: My numbers → Organisations."],
    ["week", "/week", "Static demo: the weekly session."],
    ["week-pay", "/week?step=pay", "Static demo: the weekly session, “Pay this week”."],
    ["week-paid-finish", "/week?step=pay", "Static demo: the first transfer marked paid, then Finish — the ending moves on to the next day to act.", payFirstThenFinish],
  ];
}
