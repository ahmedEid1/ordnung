import { RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { TOUR_STEPS } from "@/features/tour/steps";
import { useTourController } from "@/features/tour/useTourController";
import { SettingsCard } from "./SettingsCard";

/**
 * Settings › Data, demo only: the guided tour again, from its first step (like the Demo badge's
 * "Restart the demo tour"). The tour card opens and takes the focus (`onTourRestart`).
 */
export function TourCard() {
  const tour = useTourController();
  if (!tour.demo || !tour.state) return null;
  const step = TOUR_STEPS[tour.state.step] ?? TOUR_STEPS[0]!;
  return (
    <SettingsCard
      title="Guided tour"
      id="set-data-tour"
      description="Four short steps through Sam's letters: the new mail, Ideas from your secretary, Ask and the year ahead."
      footer={
        <Button icon={RotateCcw} onClick={() => tour.send({ type: "restart" })}>
          Restart the demo tour
        </Button>
      }
    >
      <p className="text-sm leading-5 text-muted" data-testid="tour-status">
        {tour.visible ? (
          <>
            Open now at step {tour.state.step + 1} of {TOUR_STEPS.length}: <span className="font-medium text-ink">{step.title}</span>.
          </>
        ) : (
          "Hidden right now — restarting opens it at step 1."
        )}
      </p>
    </SettingsCard>
  );
}
