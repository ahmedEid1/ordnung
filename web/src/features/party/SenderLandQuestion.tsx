/**
 * "Is FunkNetz Mobil GmbH in Berlin? (12351 on their letter)" — the state (Land) the postcode on a sender's letter
 * suggests, asked in their details and on a letter whose dates may change with it (ADR 0019). A question, never
 * an answer: nothing is set until the person taps Yes, Yes is never focused by itself, and the postcode it comes
 * from is shown so a wrong one can be seen.
 *
 * - **Yes** saves the state (`PATCH /api/parties/{id}`, which recomputes their dates), with an Undo that sets it
 *   back to unknown.
 * - **Other state…** goes to the State picker (`onOther`).
 * - **Don't know**, while the sender's Idea stands, dismisses that Idea (`PATCH /api/suggestions/{id}`) with the
 *   Idea's own Undo: the letter and Today stop asking, their details keep the question. Its toast says the dates
 *   stay the earlier ones, unless one was counted backwards (`may_be_late`): then to act a working day before it.
 *
 * While an answer is saved its button is `aria-disabled` (`AnswerButton`): after a failed save the keyboard is
 * still on it, and the hook's own toast says what went wrong.
 */
import { useId, useState, type ReactNode } from "react";
import { Check } from "lucide-react";
import { useUpdateParty, useUpdateSuggestion } from "@/api/hooks";
import type { Party, RegionSuggestion } from "@/api/types";
import { Button } from "@/components/ui/Button";
import { toast } from "@/components/ui/Toast";
import { AnswerButton } from "@/features/inbox/AnswerButton";
import { focusWhenReady } from "@/features/today/focus";
import { cn } from "@/lib/utils";
import { regionName } from "./timeline";

export type PartyUpdate = ReturnType<typeof useUpdateParty>;

export interface SenderLandQuestionProps {
  party: Pick<Party, "id" | "name">;
  suggestion: RegionSuggestion;
  /** Under the question: what answering may change. */
  children?: ReactNode;
  /** "Other state…": the State picker. */
  onOther: () => void;
  /** Yes was saved: what moved, said in the toast after the state's holidays. */
  afterYes?: () => Promise<string | null> | string | null;
  /** Where the keyboard goes once Yes was saved and the question has gone (never `<body>`). */
  focusAfterYes?: () => HTMLElement | null;
  /** "Don't know" was tapped (a leaving card watches focus from the click). */
  onDontKnow?: () => void;
  /** Where the keyboard goes once "Don't know" was saved and its button has gone. */
  focusAfterDontKnow?: () => HTMLElement | null;
  /** The drawer's own mutation, so its State picker shows the state while it is saved. */
  update?: PartyUpdate;
  /** On a letter's "Please check" card the question is as large as the card's others. */
  place?: "drawer" | "card";
  className?: string;
}

export function SenderLandQuestion({
  party,
  suggestion,
  children,
  onOther,
  afterYes,
  focusAfterYes,
  onDontKnow,
  focusAfterDontKnow,
  update: given,
  place = "drawer",
  className,
}: SenderLandQuestionProps) {
  const own = useUpdateParty();
  const update = given ?? own;
  const idea = useUpdateSuggestion();
  const [busy, setBusy] = useState<"yes" | "dont_know" | null>(null);
  const questionId = useId();
  const groupId = `${questionId}-group`;
  const dontKnowId = `${questionId}-dont-know`;
  const land = regionName(suggestion.region) ?? suggestion.region;
  const ideaId = suggestion.declined ? null : suggestion.idea_id;

  const yes = async () => {
    setBusy("yes");
    let saved: Party;
    try {
      saved = await update.mutateAsync({ id: party.id, patch: { region: suggestion.region } });
    } catch {
      setBusy(null);
      return; // the hook's toast says what went wrong; the question stays, the keyboard on Yes
    }
    setBusy(null);
    if (focusAfterYes) focusWhenReady(() => (document.getElementById(groupId) ? null : focusAfterYes()));
    const state = regionName(saved.region) ?? land;
    const moved = afterYes ? await afterYes() : null;
    toast.success(`Saved: ${saved.name} is in ${state}`, {
      description: [`Their dates now skip the public holidays of ${state}.`, moved].filter(Boolean).join(" "),
      undo: () => update.mutateAsync({ id: party.id, patch: { region: null } }).then(
        () => undefined,
        () => undefined,
      ),
    });
  };

  const dontKnow = () => {
    if (!ideaId) return;
    onDontKnow?.();
    setBusy("dont_know");
    idea.mutateAsync({ id: ideaId, patch: { status: "dismissed" } }).then(
      () => {
        setBusy(null);
        toast({
          title: `Okay — nationwide holidays for ${party.name}`,
          description: `${
            suggestion.may_be_late ? "A holiday in their state could make a date earlier: act a working day before it." : "Their dates stay the earlier ones."
          } You can choose their state any time in their details.`,
          undo: () => idea.mutateAsync({ id: ideaId, patch: { status: "new" } }).then(
            () => undefined,
            () => undefined,
          ),
        });
        if (focusAfterDontKnow) focusWhenReady(() => (document.getElementById(dontKnowId) ? null : focusAfterDontKnow()));
      },
      () => setBusy(null),
    );
  };

  return (
    <div id={groupId} role="group" aria-labelledby={questionId} className={className}>
      <p
        id={questionId}
        className={cn("text-ink wrap-break-word", place === "card" ? "mt-1 text-[15px] font-medium leading-snug" : "text-[14px] font-medium leading-5")}
      >
        Is {party.name} in {land}? <span className="font-normal text-ink/75">({suggestion.postcode} on their letter)</span>
      </p>
      {children ? <p className="mt-1 text-[13px] leading-5 text-ink/75">{children}</p> : null}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <AnswerButton size="sm" variant="secondary" icon={Check} busy={busy === "yes"} blocked={busy === "dont_know"} onClick={() => void yes()}>
          Yes
        </AnswerButton>
        <Button size="sm" variant="ghost" onClick={onOther}>
          Other state…
        </Button>
        {ideaId ? (
          <AnswerButton id={dontKnowId} size="sm" variant="ghost" busy={busy === "dont_know"} blocked={busy === "yes"} onClick={dontKnow}>
            Don't know
          </AnswerButton>
        ) : null}
      </div>
    </div>
  );
}
