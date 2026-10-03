import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router";
import { useReducedMotion } from "motion/react";
import { Lock, MessagesSquare, Plus, RotateCw, SquarePen } from "lucide-react";
import { useDemoQuestions, useDocuments, useHealth } from "@/api/hooks";
import { isStaticDemo } from "@/mocks/mode";
import { Page } from "@/components/shell/Page";
import { ACCEPTED_ONE, useOptionalAddLetters } from "@/components/shell/AddLetters";
import { Button } from "@/components/ui/Button";
import { Callout } from "@/components/ui/Callout";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton, SkeletonText, LoadingLabel } from "@/components/ui/Skeleton";
import { dismissToast, toast } from "@/components/ui/Toast";
import { AskComposer } from "@/features/ask/AskComposer";
import { AskTurnView, DemoChangedNote } from "@/features/ask/AskTurnView";
import { SuggestedQuestions } from "@/features/ask/SuggestedQuestions";
import { useAskThread } from "@/features/ask/useAskThread";
import { useRefResolver } from "@/features/ask/refs";
import { TOUR_TARGETS } from "@/features/tour/steps";

/** The "Started a new chat" toast (asking the next question closes it: its Undo would drop that question). */
const NEW_CHAT_TOAST = "ask-new-chat";
/** Said (and shown under the question box) when Enter is pressed while an answer is still being written. */
const BUSY_NOTE ="Wait for this answer, or press Stop to ask something else.";

/** Keyboard and mouse users keep typing in the question box; on touch screens focusing it would pop up the keyboard. */
const finePointer = () => Boolean(window.matchMedia?.("(pointer: fine)").matches);

/** `/ask` — questions about your letters, answered with a visible tool trace and cited sources. */
export default function AskPage() {
  const thread = useAskThread();
  const { resolve, titleOf } = useRefResolver();
  const [params, setParams] = useSearchParams();
  const [draft, setDraft] = useState(() => params.get("q") ?? "");
  const [busy, setBusy] = useState(false);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const startRef = useRef<HTMLHeadingElement | null>(null);
  const reduce = useReducedMotion();
  const health = useHealth();
  const demo = isStaticDemo() || Boolean(health.data?.demo);
  const replayDemo = isStaticDemo() || health.data?.backend === "replay";
  const documents = useDocuments();
  const adder = useOptionalAddLetters();
  // nothing to ask about yet: offer to add letters instead of questions about someone else's (UI audit round 1)
  const noLetters = !demo && documents.data?.length === 0;
  // the demo's answers were recorded on Sam's letters as it started: once the person changed them, the backend
  // offers no suggested question (each would miss) and a question asked says so — the page then says how to
  // start over instead of offering what just failed (FEAT G2)
  const recorded = useDemoQuestions(demo);
  const demoChanged = demo && (recorded.data?.length === 0 || thread.all.some((t) => t.answer.errorCode === "demo_changed"));

  // `?q=` (e.g. "Ask about them" in the People drawer) pre-fills the question once
  useEffect(() => {
    if (!params.get("q")) return;
    inputRef.current?.focus();
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.delete("q");
        return next;
      },
      { replace: true },
    );
  }, [params, setParams]);

  const send = (q: string) => {
    dismissToast(NEW_CHAT_TOAST);
    setBusy(false);
    void thread.ask(q);
    setDraft("");
    // a chip that started the question disappears — keep keyboard focus in the question box
    if (finePointer()) inputRef.current?.focus({ preventScroll: true });
  };

  // "New chat" can be undone, and leaves focus where the next question is typed (UI audit round 1: the
  // conversation was gone at once and focus fell back to the page)
  const startNewChat = () => {
    const undo = thread.newChat();
    setDraft("");
    const focusStart = () => requestAnimationFrame(() => (finePointer() ? inputRef.current?.focus({ preventScroll: true }) : startRef.current?.focus()));
    focusStart();
    toast({
      id: NEW_CHAT_TOAST,
      title: "Started a new chat",
      description: "Your last conversation is closed.",
      undo: () => {
        undo();
        requestAnimationFrame(() => inputRef.current?.focus({ preventScroll: true }));
      },
    });
  };
  useEffect(() => () => dismissToast(NEW_CHAT_TOAST), []);

  // the "wait for this answer" note goes when the answer does (and is reset by the next question)
  const busyShown = busy && thread.streaming;

  const last = thread.turns[thread.turns.length - 1];
  const lastKey = last?.key;
  const lastLen = last?.answer.text.length ?? 0;
  // the answer's words only come once checked (ADR 0008): while it is worked on, the trace's steps and the
  // "Writing the answer" line are what grows (review round 2: they grew behind the composer on phones)
  const lastSteps = last?.answer.tools.length ?? 0;
  const lastWriting = last?.answer.writing ?? false;
  const lastStatus = last?.answer.status;

  // the sticky composer covers the bottom of the screen: its height is published (--ask-composer-h) so that
  // whatever gets focus or is scrolled to stops clear of it, as of the tab bar (WCAG 2.4.11, review round 2)
  const composerRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const el = composerRef.current;
    const root = document.documentElement;
    if (!el) return;
    const publish = () => root.style.setProperty("--ask-composer-h", `${Math.ceil(el.getBoundingClientRect().height)}px`);
    publish();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(publish);
    observer?.observe(el);
    return () => {
      observer?.disconnect();
      root.style.removeProperty("--ask-composer-h");
    };
  }, []);

  // a new question scrolls into view at the top
  useEffect(() => {
    if (!lastKey) return;
    const el = document.querySelector<HTMLElement>(`[data-turn="${lastKey}"]`);
    el?.scrollIntoView?.({ block: "start", behavior: reduce ? "auto" : "smooth" });
  }, [lastKey, reduce]);

  // while it is worked on — and when it arrives — keep the growing turn visible above the composer (and, on
  // phones, the tab bar). While it is worked on, the newest step and the "Writing the answer" line stay in view
  // even when the question has to scroll off (review round 4 of phase 2: at 320×640 they stayed behind the
  // composer for the whole write); the answer that arrives never scrolls its question away
  useEffect(() => {
    if (!lastKey || (!thread.streaming && lastStatus !== "done")) return;
    const el = document.querySelector<HTMLElement>(`[data-turn="${lastKey}"]`);
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const composer = composerRef.current?.getBoundingClientRect();
    const covered = composer ? window.innerHeight - composer.top : window.innerWidth < 768 ? 190 : 130;
    const overflow = rect.bottom - (window.innerHeight - covered);
    const working = thread.streaming && lastStatus !== "done";
    const room = working ? overflow : rect.top - 72;
    if (overflow > 0 && room > 0) window.scrollBy({ top: Math.min(overflow, room) });
  }, [lastLen, lastSteps, lastWriting, lastStatus, thread.streaming, lastKey]);

  // a stored conversation opens at its last question, clear of the top bar (the page's scroll-padding), with
  // as much of its answer as fits (UI audit round 1: scrolled to the very end, the question sat under the bar)
  const hadHistory = thread.past.length > 0;
  useEffect(() => {
    if (!hadHistory) return;
    const turns = document.querySelectorAll<HTMLElement>("[data-turn]");
    turns[turns.length - 1]?.scrollIntoView?.({ block: "start" });
  }, [hadHistory]);

  const empty = !thread.all.length && !thread.loadingHistory;
  const asked = thread.all.map((t) => t.question);
  const announce = busyShown
    ? BUSY_NOTE
    : last
      ? last.answer.status === "streaming"
        ? last.answer.writing
          ? "Writing the answer — it appears once Ordnung has checked it."
          : "Looking through your records…"
        : last.answer.status === "done"
          ? "Answer ready."
          : last.answer.status === "error"
            ? last.answer.errorCode === "demo_miss"
              ? "No recorded answer for this question."
              : last.answer.errorCode === "demo_changed"
                ? "The recorded answers no longer fit."
                : "The answer could not be completed."
            : "Stopped."
      : "";

  return (
    <Page title="Ask" width="narrow" className="flex flex-1 flex-col pb-0 md:pb-0">
      <p className="sr-only" aria-live="polite" role="status">
        {announce}
      </p>

      {empty ? (
        <section aria-labelledby="ask-title" className="flex flex-1 flex-col justify-center pb-6 pt-4 sm:pt-10">
          {thread.historyError ? (
            <Callout
              tone="warn"
              className="mb-6"
              title="Couldn't load your last conversation"
              action={
                <>
                  <Button size="sm" icon={RotateCw} onClick={thread.retryHistory}>
                    Try again
                  </Button>
                  <Button size="sm" variant="ghost" icon={SquarePen} onClick={() => thread.newChat()}>
                    Start a new chat
                  </Button>
                </>
              }
            >
              Try again in a moment, or start a new chat.
            </Callout>
          ) : null}
          <div className="text-center">
            <span className="mx-auto mb-5 grid size-12 place-items-center rounded-2xl bg-accent-soft text-accent">
              <MessagesSquare className="size-6" aria-hidden />
            </span>
            <h1 id="ask-title" ref={startRef} tabIndex={-1} className="display text-[30px] font-semibold leading-tight text-ink outline-none sm:text-[38px]">
              Ask about your letters
            </h1>
            <p className="mx-auto mt-2.5 max-w-md text-[15px] leading-relaxed text-muted">
              Plain-English answers from your own records. Every answer shows what it looked at and links to the letter it comes from.
            </p>
          </div>
          {noLetters ? (
            <>
              <EmptyState
                className="mt-8"
                size="sm"
                illustration="inbox"
                title="Add a few letters first"
                description={`Ask answers from your own letters. Add ${ACCEPTED_ONE} of one — Ordnung reads it and files every date and amount.`}
                action={
                  adder ? (
                    <Button variant="primary" icon={Plus} onClick={adder.openPicker}>
                      Add letters
                    </Button>
                  ) : undefined
                }
              />
              <p className="mt-6 text-center text-[13px] text-muted">Once they are in, you can ask things like:</p>
              <SuggestedQuestions className="mt-3" onPick={send} disabled />
            </>
          ) : demoChanged ? (
            // where the chips were: the tour's "Ask anything" step rings this note instead
            <div data-tour={TOUR_TARGETS.askChips} className="mt-8">
              <DemoChangedNote />
            </div>
          ) : (
            <SuggestedQuestions className="mt-8" onPick={send} />
          )}
          {replayDemo && !demoChanged ? (
            <p className="mx-auto mt-5 max-w-lg text-balance text-center text-[12.5px] leading-5 text-muted">
              Demo: the suggested questions replay answers recorded for the sample letters as the demo starts.
            </p>
          ) : null}
          {/* the lock sits in the line, beside the words it is about (not floating left of a centred block) */}
          <p className={`mx-auto max-w-lg text-balance text-center text-[12.5px] leading-5 text-muted ${replayDemo ? "mt-2" : "mt-6"}`}>
            <Lock className="mr-1.5 inline size-3.5 align-[-0.15em]" aria-hidden />
            Claude searches your records with read-only tools. Only the letters it opens are sent to Anthropic, through your own Claude account.
          </p>
        </section>
      ) : (
        <div className="flex-1">
          <div className="mb-6 flex items-start gap-3">
            {/* the title wraps rather than cut off ("Ask about you…"); on the narrowest phones the button is its icon */}
            <h1 className="display min-w-0 flex-1 text-balance pt-0.5 text-[22px] font-semibold leading-tight text-ink">Ask about your letters</h1>
            <Button size="sm" variant="ghost" icon={SquarePen} onClick={startNewChat} disabled={thread.loadingHistory} title="New chat">
              <span className="max-[359px]:sr-only">New chat</span>
            </Button>
          </div>

          {thread.loadingHistory ? (
            <div aria-busy="true" className="space-y-8">
              <LoadingLabel>Loading your conversation…</LoadingLabel>
              {[0, 1].map((i) => (
                <div key={i} className="space-y-4">
                  <Skeleton className="ml-auto h-10 w-2/3 rounded-2xl" />
                  <div className="flex gap-2 sm:gap-3">
                    <Skeleton className="size-5 rounded-md sm:size-7 sm:rounded-lg" />
                    <SkeletonText lines={3} className="flex-1" />
                  </div>
                </div>
              ))}
            </div>
          ) : null}

          <div className="space-y-10">
            {thread.all.map((turn) => (
              <AskTurnView
                key={turn.key}
                turn={turn}
                resolve={resolve}
                titleOf={titleOf}
                // a question the demo has no recording for can't be answered by asking it again
                onRetry={thread.turns.includes(turn) && !turn.answer.errorCode ? () => thread.retry(turn.key) : undefined}
                demoChanged={demoChanged}
              />
            ))}
          </div>

          {/* once the demo changed, the answer's note says how to start over: no chips that would miss */}
          {!thread.streaming && !thread.loadingHistory && !demoChanged ? (
            <div className="mt-10">
              <SuggestedQuestions variant="row" exclude={asked} onPick={send} />
            </div>
          ) : null}
        </div>
      )}

      {/* on phones the demo tour's bar sits above the tab bar: the composer stays above both */}
      {/* opaque down to the screen's edge (under the see-through tab bar too), so the answer never
          shows around the tour's bar or through the tab bar */}
      {/* on phones it keeps to the essentials — less fade above it, a one-line hint — so the answer has
          the screen (UI audit round 1: box, hint, tour bar and tab bar took half of a 320 × 640 screen) */}
      <div ref={composerRef} data-ask-composer className="sticky bottom-[calc(4rem+env(safe-area-inset-bottom))] z-10 -mx-4 mt-6 bg-linear-to-t from-canvas from-80% to-transparent px-4 pb-[calc(0.75rem+var(--ordnung-toast-lift,0px))] pt-3 after:pointer-events-none after:absolute after:inset-x-0 after:top-full after:h-[calc(4rem+env(safe-area-inset-bottom))] after:bg-canvas sm:-mx-6 sm:px-6 sm:pt-6 md:bottom-0 md:pb-[calc(1.25rem+var(--ordnung-toast-lift,0px))] md:after:hidden lg:-mx-10 lg:px-10">
        <AskComposer
          value={draft}
          onChange={(v) => {
            setDraft(v);
            setBusy(false);
          }}
          onSubmit={send}
          onStop={thread.stop}
          onBusy={() => setBusy(true)}
          streaming={thread.streaming}
          textareaRef={inputRef}
        />
        <p id="ask-hint" className="mt-2 text-center text-[12px] leading-5 text-muted">
          {busyShown ? (
            <span className="font-medium text-ink">{BUSY_NOTE}</span>
          ) : (
            <>
              <span className="sm:hidden">Answers can be wrong — not legal advice.</span>
              <span className="max-sm:hidden">Answers can be wrong — check the source. Not legal advice.</span>
            </>
          )}
        </p>
      </div>
    </Page>
  );
}
