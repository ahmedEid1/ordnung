/**
 * The demo tour (SPEC §14.10, §16): four short steps, each pointing at one element of a page.
 *
 * Pages mark the element with `data-tour="<target>"` (see {@link TOUR_TARGETS}), and may mark a
 * smaller part of it for phones and short screens ({@link TOUR_PART_ATTR}). When the target is on
 * screen the tour draws a soft spotlight around it (two pulses, then a still ring); when it is
 * missing the card still works (no spotlight). Two steps follow the demo's data
 * ({@link stepCopy}): the New-mail step counts the letters still in the tray, and the Idea step
 * says "An idea just arrived" only when a letter really brought one.
 */
export const TOUR_TARGETS = {
  /** Inbox: the demo's "New mail" tray. */
  newMail: "new-mail-tray",
  /** Today: the "Ideas from your secretary" section. */
  ideas: "today-ideas",
  /** Ask: the suggested-question chips. */
  askChips: "ask-chips",
  /** Timeline: the year-ahead life lanes. */
  timelineLanes: "timeline-lanes",
} as const;

export type TourTarget = (typeof TOUR_TARGETS)[keyof typeof TOUR_TARGETS];

/**
 * Marks the part of a target the ring goes around when the whole won't do — on phones, and when
 * the whole is taller than the screen (`useSpotlight`'s `wantsPart`): the tray's first envelope,
 * the first Idea. A target without one keeps the ring around the whole.
 */
export const TOUR_PART_ATTR = "data-tour-part";

/** The sidebar's free space (between the navigation and its footer) where the tour card docks. */
export const TOUR_DOCK_ID = "tour-dock";

export interface TourStep {
  id: string;
  title: string;
  body: string;
  /** Route the step lives on. */
  route: string;
  /** `data-tour` value of the element to highlight. */
  target: TourTarget;
  /** Label of the "take me there" button. */
  showLabel: string;
}

export const TOUR_STEPS: readonly TourStep[] = [
  {
    id: "new-mail",
    title: "You have new mail",
    body: "New letters just arrived for Sam. Open one and watch Ordnung read it — every date and amount is checked against the page.",
    route: "/inbox",
    target: TOUR_TARGETS.newMail,
    showLabel: "Show me the mail",
  },
  {
    id: "idea",
    // neutral: the step is also reached with Next or the dots, before any letter brought an Idea
    title: "Ideas from your secretary",
    body: "When a letter changes something — a price increase, a suspicious payment demand — your secretary suggests what to do, with the reason and the rule behind it. Nothing is ever sent or paid for you.",
    route: "/",
    target: TOUR_TARGETS.ideas,
    showLabel: "Show me the Ideas",
  },
  {
    id: "ask",
    title: "Ask anything",
    body: "Ask in plain English — try “When does my phone contract end, and by when do I have to cancel it?” Answers point to the letters they come from.",
    route: "/ask",
    target: TOUR_TARGETS.askChips,
    showLabel: "Try a question",
  },
  {
    id: "timeline",
    title: "Your year ahead",
    body: "Permit, contracts, semesters and deadlines on calm lanes — including the windows in which you can still cancel.",
    route: "/timeline",
    target: TOUR_TARGETS.timelineLanes,
    showLabel: "Show my year",
  },
];

/** Does `pathname` belong to the step's route? ("/" matches only the Today page.) */
export function onStepRoute(step: Pick<TourStep, "route">, pathname: string): boolean {
  if (step.route === "/") return pathname === "/";
  return pathname === step.route || pathname.startsWith(`${step.route}/`);
}

/** What the demo's data says right now (each part unknown while it loads). */
export interface TourFacts {
  /** The New-mail tray: letters not opened yet, of how many. */
  tray?: { unread: number; total: number };
  /** A letter from the tray brought a headline Idea (a price increase, a scam warning…). */
  ideaFromMail?: boolean;
}

const NUMBER_WORDS = ["No", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine"];
const inWords = (n: number) => NUMBER_WORDS[n] ?? String(n);

/**
 * A step as it should read now. The New-mail step follows the tray: the letters that just arrived,
 * then the ones still waiting (with a way on when a letter brought no Idea), then "all read". The
 * Idea step announces an Idea only when one came with the mail. Other steps read as written.
 */
export function stepCopy(step: TourStep, facts: TourFacts = {}): TourStep {
  if (step.id === "new-mail" && facts.tray && facts.tray.total > 0) {
    const { unread, total } = facts.tray;
    if (unread <= 0) {
      return {
        ...step,
        title: "All new mail read",
        body: "Every new letter has been read and filed. Next, see what your secretary suggests about them.",
      };
    }
    if (unread < total) {
      const waiting = unread === 1 ? "One letter is" : `${inWords(unread)} letters are`;
      return {
        ...step,
        body: `${waiting} still waiting for Sam. Open ${unread === 1 ? "it" : "another"} to watch Ordnung read it — or go on and see what your secretary suggests.`,
      };
    }
    const arrived = unread === 1 ? "One letter just arrived" : `${inWords(unread)} letters just arrived`;
    return {
      ...step,
      body: `${arrived} for Sam. Open ${unread === 1 ? "it" : "one"} and watch Ordnung read it — every date and amount is checked against the page.`,
    };
  }
  if (step.id === "idea" && facts.ideaFromMail) {
    return { ...step, title: "An idea just arrived", showLabel: "Show me the Idea" };
  }
  return step;
}
