/**
 * The demo tour (SPEC §14.10, §16): four short steps, each pointing at one element of a page.
 *
 * Pages mark the element with `data-tour="<target>"` (see {@link TOUR_TARGETS}). When the target
 * is on screen the tour draws a soft pulsing spotlight around it; when it is missing the card
 * still works (no spotlight).
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
    body: "Three letters just arrived for Sam. Open one and watch Ordnung read it — every date and amount is checked against the page.",
    route: "/inbox",
    target: TOUR_TARGETS.newMail,
    showLabel: "Show me the mail",
  },
  {
    id: "idea",
    title: "An idea just arrived",
    body: "When a letter changes something — a price increase, a suspicious payment demand — your secretary suggests what to do, with the reason and the rule behind it. Nothing is ever sent or paid for you.",
    route: "/",
    target: TOUR_TARGETS.ideas,
    showLabel: "Show me the Idea",
  },
  {
    id: "ask",
    title: "Ask anything",
    body: "Ask in plain English — try “When does my phone contract end, and by when do I have to cancel it?”. Answers point to the letters they come from.",
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
