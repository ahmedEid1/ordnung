/**
 * The guided demo tour (SPEC §14.10, §16): a New-mail letter is read live through the real
 * pipeline (recorded answers), the viewer shows the evidence and the objection deadline with its
 * receipt, and the tour card walks on through Idea → Ask → Timeline.
 */
import { apiGet, envelope, expect, expectAccessible, open, openMail, setTour, test, type TourState } from "./helpers";

const FINANZAMT = "Finanzamt Musterstadt";

test("New mail → the tax assessment is read → evidence, Einspruch deadline and why this date", async ({ page }, testInfo) => {
  await setTour(page, 0);
  const tray = await apiGet<{ sender: string; opened: boolean }[]>(page, "/api/demo/mail");
  // the "tour" project runs first, on the untouched demo; a retry finds the letter already read
  const fresh = !tray.find((t) => t.sender === FINANZAMT)?.opened;
  const pristine = tray.every((t) => !t.opened);

  await open(page, "/inbox");
  const tour = page.getByRole("complementary", { name: "Demo tour" });
  if (pristine) await expect(tour.getByRole("heading", { name: "You have new mail" })).toBeVisible();

  if (fresh) {
    const letter = envelope(page, FINANZAMT);
    // the envelope shows the letter's subject and what it is (a phone photo), never a raw value
    await expect(letter.getByText("Steuerbescheid 2025", { exact: true })).toBeVisible();
    await expect(letter.getByText("Phone photo", { exact: true })).toBeVisible();
    await expectAccessible(page, testInfo, "inbox-new-mail");

    await letter.getByRole("button", { name: "Let Ordnung read it" }).click();
    const stepper = letter.getByRole("list", { name: `Reading the letter from ${FINANZAMT}` });
    await expect(stepper.getByRole("listitem")).toHaveText([/Reading/, /Understanding/, /Checking/, /Computing dates/, /Filing/]);
    // every stage is shown for a moment in the demo: watch the stepper reach the last one
    // (polled every frame; it lasts ≥ 600 ms), then the Inbox opens the letter by itself
    await page.waitForFunction(
      (label) => {
        const items = document.querySelectorAll(`ol[aria-label="${label}"] > li`);
        const last = items[items.length - 1];
        return (last && last.getAttribute("aria-current") === "step") || location.pathname.startsWith("/documents/");
      },
      `Reading the letter from ${FINANZAMT}`,
      { polling: "raf", timeout: 30_000 },
    );
    await page.waitForURL(/\/documents\/doc_/, { timeout: 30_000 });
    await page.waitForLoadState("networkidle");
  } else {
    await openMail(page, FINANZAMT); // a retry: the letter was read before
  }

  // ---- the viewer: verdict card first -----------------------------------------------------
  const verdict = page.getByRole("article", { name: /Income Tax Assessment 2025/ });
  await expect(verdict.getByRole("heading", { level: 1 })).toContainText("Income Tax Assessment 2025");
  await expect(verdict).toContainText("Einspruch"); // the objection, with its German term
  await expect(verdict.locator("time", { hasText: "Wed 21 Oct" })).toBeVisible();
  await expect(verdict.getByText("Not legal advice", { exact: false })).toBeVisible();

  // ---- the evidence: the sentence the deadline comes from, highlighted -------------------
  const todos = page.getByRole("region", { name: /^To-dos & dates/ });
  const objection = todos.getByRole("listitem").filter({ hasText: "Objection deadline (Einspruchsfrist)" });
  await expect(objection.locator("time", { hasText: "Wed 21 Oct" })).toBeVisible();
  await objection.getByRole("button", { name: /show “Objection deadline \(Einspruchsfrist\)” on the page/ }).click();
  const evidence = page.getByRole("region", { name: "Letter pages" }).getByTestId("evidence-quote");
  await expect(evidence).toBeVisible();
  // a phone photo has no text layer: the quote is shown highlighted, labelled as read by AI
  await expect(evidence).toContainText("Read by AI from the photo");
  const marked = evidence.locator(".marker");
  await expect(marked).toBeVisible();
  await expect(marked).toContainText(/Einspruch|Rechtsbehelf|Monat/);

  // ---- "Why this date?": plain sentence first, then the 4-day rule steps ----------------
  await verdict.getByRole("button", { name: "Why this date?" }).click();
  const receipt = page.getByRole("dialog", { name: "Why this date?" });
  await expect(receipt).toBeVisible();
  await expect(receipt).toContainText("counts as delivered on Sat 19 Sep");
  await receipt.getByRole("button", { name: "Show the rules" }).click();
  const steps = receipt.getByRole("listitem");
  await expect(steps.filter({ hasText: "Counts as delivered on the 4th day after posting: Sat 19 Sep 2026" })).toContainText("§ 122 Abs. 2 Nr. 1 AO");
  await expect(steps.filter({ hasText: "is a Saturday, so delivery moves to Mon 21 Sep 2026" })).toBeVisible();
  await expect(steps.filter({ hasText: "One month later: Wed 21 Oct 2026" })).toBeVisible();
  await expect(receipt).toContainText("Not legal advice");
  await expectAccessible(page, testInfo, "viewer-why-this-date");
  await page.keyboard.press("Escape");
  await expect(receipt).toBeHidden();
});

test("the tour card walks through Idea → Ask → Timeline and finishes", async ({ page }) => {
  await setTour(page, 1);
  await open(page, "/inbox");
  const tour = page.getByRole("complementary", { name: "Demo tour" });
  await expect(tour.getByRole("heading", { name: "An idea just arrived" })).toBeVisible();

  await tour.getByRole("button", { name: "Show me the Idea" }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByTestId("tour-spotlight")).toHaveAttribute("data-target", "today-ideas");

  await tour.getByRole("button", { name: "Next" }).click();
  await expect(tour.getByRole("heading", { name: "Ask anything" })).toBeVisible();
  await tour.getByRole("button", { name: "Try a question" }).click();
  await expect(page).toHaveURL(/\/ask$/);
  await expect(page.getByRole("list", { name: "Suggested questions" })).toBeVisible();

  await tour.getByRole("button", { name: "Next" }).click();
  await expect(tour.getByRole("heading", { name: "Your year ahead" })).toBeVisible();
  await tour.getByRole("button", { name: "Show my year" }).click();
  await expect(page).toHaveURL(/\/timeline$/);
  await expect(page.getByTestId("tour-spotlight")).toHaveAttribute("data-target", "timeline-lanes");

  await tour.getByRole("button", { name: "Finish" }).click();
  await expect(tour).toBeHidden();
  await expect.poll(async () => (await apiGet<TourState>(page, "/api/demo/tour")).completed).toBe(true);
});
