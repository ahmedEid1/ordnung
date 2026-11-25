import { Play, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { TOUR_STEPS } from "@/features/tour/steps";
import { canResumeAt } from "@/features/tour/tourMachine";
import { useTourController } from "@/features/tour/useTourController";
import { FOOTER_ACTION, SettingsCard } from "./SettingsCard";

/**
 * Settings › Data, demo only: the guided tour again, from its first step (like the Demo badge's
 * "Restart the demo tour"), or — hidden part of the way through — at the step it was hidden at. The tour
 * card opens and takes the focus (`onTourRestart`).
 */
export function TourCard() {
  const tour = useTourController();
  if (!tour.demo || !tour.state) return null;
  const step = TOUR_STEPS[tour.state.step] ?? TOUR_STEPS[0]!;
  const at = tour.state.step;
  // ended part of the way through: it can go on from there, not only from the start
  const resumable = !tour.visible && canResumeAt(at);
  return (
    <SettingsCard
      title="Guided tour"
      id="set-data-tour"
      description="Four short steps through Sam's letters: the new mail, Ideas from your secretary, Ask and the year ahead."
      footer={
        <>
          {resumable ? (
            <Button icon={Play} variant="primary" onClick={() => tour.send({ type: "restart", step: at })} className={FOOTER_ACTION}>
              Resume at step {at + 1}
            </Button>
          ) : null}
          <Button icon={RotateCcw} onClick={() => tour.send({ type: "restart" })} className={FOOTER_ACTION}>
            Restart the demo tour
          </Button>
        </>
      }
    >
      <p className="text-sm leading-5 text-muted" data-testid="tour-status">
        {tour.visible ? (
          <>
            Open now at step {at + 1} of {TOUR_STEPS.length}: <span className="font-medium text-ink">{step.title}</span>.
          </>
        ) : resumable ? (
          <>
            Hidden right now, at step {at + 1} of {TOUR_STEPS.length}: <span className="font-medium text-ink">{step.title}</span>. Resume it there, or
            restart it at step 1.
          </>
        ) : (
          "Hidden right now — restarting opens it at step 1."
        )}
      </p>
    </SettingsCard>
  );
}
