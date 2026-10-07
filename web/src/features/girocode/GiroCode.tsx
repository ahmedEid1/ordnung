/**
 * The GiroCode (EPC-QR) of a payment: a QR code any German banking app scans to pre-fill the
 * transfer, which the person then confirms there with their TAN — Ordnung never pays. The server
 * decides whether there is a code (`girocodes` of the letter's detail); this shows the code, or
 * why there is none, or — for details read from a photo, or not found in the letter's text — asks
 * to compare them with the letter first ("These match the letter", or "They don't match": then type
 * them from the letter, or have the letter read again). A refused comparison, or a failed reading,
 * says why in the block itself — a toast would wait behind a phone's sheet or cover the panel's
 * footer. A code without a reference says so (the letter may name one the reading missed), and on a
 * phone or tablet, which can't scan its own screen, the block says what to do instead.
 *
 * The code stays dark on white with its quiet zone in both themes and in forced-colours mode:
 * scanners need that contrast, whatever the page around it looks like. Each module is a whole
 * number of pixels, at least three, so a phone camera sees even squares.
 */
import { useEffect, useId, useMemo, useRef, useState, type ReactNode, type RefObject } from "react";
import { Check, ChevronDown, CircleCheck, Info, QrCode as QrIcon, RotateCw, ScanLine, ShieldAlert, Smartphone } from "lucide-react";
import type { Document, GiroCode as GiroCodeData, GiroCodeBlocked } from "@/api/types";
import { useConfirmGiroCode, useReadLetterAgain } from "@/api/hooks";
import { dismissJob, seedJob, useJobProgress } from "@/api/sse";
import { setUploadToastHidden } from "@/components/shell/UploadCenter";
import { Button } from "@/components/ui/Button";
import { formatMoney } from "@/lib/format";
import { useIsTabletUp, useMediaQuery } from "@/lib/hooks";
import { cn, prefersReducedMotion } from "@/lib/utils";
import { isStaticDemo } from "@/mocks/mode";
import { qrMatrix, qrPath, readPayload } from "./qr";

export const GIROCODE_TITLE = "GiroCode (EPC-QR)";
export const GIROCODE_HINT = "Scan with your banking app; you confirm the transfer there.";
export const GIROCODE_CHECKED = "You compared these details with the letter.";
/** Below the heading on a phone or tablet: the code is for another device's banking app. */
export const GIROCODE_ON_PHONE = "A phone or tablet can't scan its own screen: open this letter on a computer and scan the code there, or copy the details above.";
/** A code whose letter gave no reference: the reading may have missed it, and a payment without one gets misallocated. */
export const GIROCODE_NO_REFERENCE = "This code carries no reference. If the letter names one (a Kassenzeichen, an invoice number), add it in your banking app.";

/**
 * Reasons the pay panels already explain in their own words: no bank details, nothing to pay, an
 * IBAN failing its check (their red warning — see {@link ibanFailsCheck}).
 */
const QUIET: ReadonlySet<GiroCodeBlocked["reason"]> = new Set(["no_iban", "incoming", "settled", "invalid_iban"]);

/** The pay panels' red "This IBAN fails its checksum" warning shows (the letter says so, or the code does). */
export function ibanFailsCheck(ibanValid: boolean | null | undefined, code: GiroCodeData | undefined): boolean {
  return ibanValid === false || (code?.status === "blocked" && code.reason === "invalid_iban");
}

/** How wide a QR code is drawn unless asked otherwise (a GiroCode), in CSS pixels. */
export const QR_SIDE = 152;

/** A module's side in CSS pixels for a code about `side` px wide: whole, at least 3. */
export function modulePixelsFor(modules: number, side: number): number {
  return Math.max(3, Math.floor(side / modules));
}

/** A module's side in CSS pixels: whole, at least 3, about {@link QR_SIDE} px for the whole code. */
export function modulePixels(modules: number): number {
  return modulePixelsFor(modules, QR_SIDE);
}

/** "They don't match" may offer to read the letter again: not a private letter, not one being read,
 * and not in the online demo (it reads no letters; the button would only fail). */
export function canReadLetterAgain(letter: Pick<Document, "ai_private" | "status"> | undefined): boolean {
  return Boolean(letter && !letter.ai_private && letter.status !== "processing" && letter.status !== "queued" && !isStaticDemo());
}

/** Whether a pay panel shows anything for this code. */
export function showsGiroCode(code: GiroCodeData | undefined): code is GiroCodeData {
  return code != null && (code.status === "ready" || !QUIET.has(code.reason));
}

/** What the code does, for screen readers: "GiroCode: transfer €184.30 to Wohnbau Musterstadt eG, reference …". */
export function giroCodeLabel(payload: string): string {
  const t = readPayload(payload);
  const amount = t.amount != null ? `${formatMoney(t.amount)} ` : "";
  return `GiroCode: transfer ${amount}to ${t.name}${t.reference ? `, reference ${t.reference}` : ""}`;
}

/**
 * The QR code itself: SVG, crisp modules, dark on white with the quiet zone. `size`: about how wide it is drawn
 * (default {@link QR_SIDE}; Settings → Phone draws its pairing code larger, for a phone camera across a desk).
 */
export function QrCode({ payload, label, className, size = QR_SIDE }: { payload: string; label: string; className?: string; size?: number }) {
  const qr = useMemo(() => {
    try {
      return qrMatrix(payload);
    } catch {
      return null;
    }
  }, [payload]);
  if (!qr) {
    return <p className="text-sm text-danger-ink">This code is too long to draw. Copy the details by hand.</p>;
  }
  const side = qr.size * modulePixelsFor(qr.size, size);
  return (
    <svg
      role="img"
      aria-label={label}
      viewBox={`0 0 ${qr.size} ${qr.size}`}
      width={side}
      height={side}
      shapeRendering="crispEdges"
      data-qr-version={qr.version}
      data-qr-modules={qr.size}
      className={cn("block aspect-square h-auto max-w-full bg-white [forced-color-adjust:none]", className)}
    >
      <rect width={qr.size} height={qr.size} fill="#ffffff" />
      <path d={qrPath(qr.modules)} fill="#000000" />
    </svg>
  );
}

export interface GiroCodeSectionProps {
  code: GiroCodeData | undefined;
  /** The letter the payment belongs to (its detail is updated after "These match the letter"). */
  docId: string;
  /** The code starts folded behind "Show code" (Today's pay panel; any pay panel on a phone). */
  collapsible?: boolean;
  /** "They don't match" may offer to read the letter again (it isn't private or being read, and this
   * isn't the online demo, which reads no letters). */
  canReadAgain?: boolean;
  /** "They don't match" opened or closed: the panel turns its copy buttons off meanwhile (the details
   * shown are the ones the person says are wrong). */
  onMismatch?: (open: boolean) => void;
  className?: string;
}

/** A pay panel's GiroCode block: the code, the comparison with the letter, or why there is none. */
export function GiroCodeSection({ code, docId, collapsible = false, canReadAgain = false, onMismatch, className }: GiroCodeSectionProps) {
  const headingRef = useRef<HTMLHeadingElement>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);
  // the mutation lives here, not in the "compare" block: that block is gone once the code is ready,
  // and the feedback must still follow
  const confirm = useConfirmGiroCode();
  const [confirmed, setConfirmed] = useState(false);
  if (!showsGiroCode(code)) return null;

  let body: ReactNode;
  if (code.status === "ready") {
    body = (
      <Ready
        payload={code.payload}
        checked={code.checked}
        collapsible={collapsible && !confirmed}
        reveal={confirmed}
        headingRef={headingRef}
        className={className}
      />
    );
  } else if (code.reason === "check_letter") {
    const onConfirm = () => {
      if (!code.values) return;
      confirm.mutate(
        { itemId: code.item_id, docId, values: code.values },
        {
          // the button is gone: the code's heading takes focus in its place (`Ready`); refused, the
          // reason shows under the button, which gets focus back (`CompareFirst`)
          onSuccess: (next) => setConfirmed(next.status === "ready"),
        },
      );
    };
    body = (
      <CompareFirst
        code={code}
        docId={docId}
        pending={confirm.isPending}
        error={confirm.error}
        onConfirm={onConfirm}
        headingRef={headingRef}
        confirmRef={confirmRef}
        canReadAgain={canReadAgain}
        onMismatch={onMismatch}
        className={className}
      />
    );
  } else {
    body = <NoCode code={code} className={className} />;
  }
  return (
    <>
      {body}
      {/* always in the page, so the change is announced (the block itself is replaced) */}
      <span className="sr-only" aria-live="polite">
        {confirmed && code.status === "ready" ? `GiroCode ready. ${GIROCODE_CHECKED}` : ""}
      </span>
    </>
  );
}

function Heading({ id, headingRef, icon: Icon = QrIcon, tone }: { id: string; headingRef: RefObject<HTMLHeadingElement | null>; icon?: typeof QrIcon; tone?: string }) {
  return (
    <h3 id={id} ref={headingRef} tabIndex={-1} className={cn("flex items-center gap-1.5 text-sm font-semibold text-ink outline-none", tone)}>
      <Icon className="size-4 shrink-0" aria-hidden />
      {GIROCODE_TITLE}
    </h3>
  );
}

function Ready({
  payload,
  checked,
  collapsible,
  reveal,
  headingRef,
  className,
}: {
  payload: string;
  checked: boolean;
  collapsible: boolean;
  /** Just unlocked: bring the code into view. */
  reveal: boolean;
  headingRef: RefObject<HTMLHeadingElement | null>;
  className?: string;
}) {
  const id = useId();
  const [unfolded, setUnfolded] = useState(false);
  const [toggled, setToggled] = useState(false);
  // derived, not stored: a panel that stops folding (the code was just unlocked) shows the code
  const open = !collapsible || unfolded;
  const codeRef = useRef<HTMLDivElement>(null);
  const noReference = !readPayload(payload).reference;
  // a phone (or a tablet) can't scan its own screen, upright or turned sideways
  const tabletUp = useIsTabletUp();
  const touch = useMediaQuery("(hover: none) and (pointer: coarse)");
  const onPhone = !tabletUp || touch;
  // a code the person just unfolded (or unlocked) scrolls into the panel's view; an unlocked one
  // takes focus on its heading first — without scrolling, which would cancel the smooth scroll
  useEffect(() => {
    if (!open || !(toggled || reveal)) return;
    if (reveal) headingRef.current?.focus({ preventScroll: true });
    codeRef.current?.scrollIntoView?.({ block: "nearest", behavior: prefersReducedMotion() ? "auto" : "smooth" });
  }, [open, toggled, reveal, headingRef]);
  return (
    <section aria-labelledby={`${id}-h`} data-girocode="ready" className={cn("rounded-lg border border-line p-3", className)}>
      <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-2">
        <div className="min-w-0 flex-1 basis-40">
          <Heading id={`${id}-h`} headingRef={headingRef} />
          <p className="mt-0.5 text-xs leading-5 text-muted">{GIROCODE_HINT}</p>
        </div>
        {collapsible ? (
          <Button
            variant="soft"
            size="sm"
            iconRight={ChevronDown}
            aria-expanded={open}
            aria-controls={`${id}-code`}
            onClick={() => {
              setUnfolded((v) => !v);
              setToggled(true);
            }}
            className={cn("[&_svg]:transition-transform motion-reduce:[&_svg]:transition-none", open && "[&_svg]:rotate-180")}
          >
            {open ? "Hide code" : "Show code"}
          </Button>
        ) : null}
      </div>
      {/* the whole width, not squeezed next to "Show code" */}
      {onPhone ? (
        <p data-girocode-phone="" className="mt-2 flex gap-1.5 text-xs leading-5 text-muted">
          <Smartphone className="mt-[3px] size-3.5 shrink-0" aria-hidden />
          {GIROCODE_ON_PHONE}
        </p>
      ) : null}
      {noReference ? (
        <p data-girocode-no-reference="" className="mt-2 flex gap-1.5 text-xs leading-5 text-warn-ink">
          <Info className="mt-[3px] size-3.5 shrink-0" aria-hidden />
          {GIROCODE_NO_REFERENCE}
        </p>
      ) : null}
      <div id={`${id}-code`} ref={codeRef} hidden={!open} className="mt-3 scroll-my-24">
        <div className="mx-auto w-fit max-w-full rounded-md bg-white p-1 shadow-[0_0_0_1px_rgb(0_0_0/0.08)] dark:shadow-none">
          <QrCode payload={payload} label={giroCodeLabel(payload)} />
        </div>
        {checked ? (
          <p className="mt-2 text-center text-xs leading-5 text-ok-ink">
            <CircleCheck className="mr-1 inline size-3.5 align-[-2px]" aria-hidden />
            {GIROCODE_CHECKED}
          </p>
        ) : null}
      </div>
    </section>
  );
}

export const GIROCODE_MISMATCH =
  "Then type the payee, IBAN, reference and amount into your banking app yourself, as the paper letter shows them — not the details above, which Ordnung read differently (their copy buttons are off now).";
/** Over the transfer details while "They don't match" is open. */
export const GIROCODE_MISMATCH_DETAILS = "Doesn't match the letter — type the details from the paper.";
export const GIROCODE_READING_AGAIN = "Reading it again — the details here update when it's done.";
/** Once the letter was read again and its code still asks to compare. */
export const GIROCODE_READ_AGAIN = "Read again — compare the details above with the paper letter once more.";

/** How the reading asked for with "Read the letter again" ended. */
interface ReadOutcome {
  jobId: string;
  failed: boolean;
  error: string | null;
}

/** Bring a message that opened below a button clear of the panel's sticky footer. */
function scrollClear(element: HTMLElement | null) {
  element?.scrollIntoView?.({ block: "nearest", behavior: prefersReducedMotion() ? "auto" : "smooth" });
}

function CompareFirst({
  code,
  docId,
  pending,
  error,
  onConfirm,
  headingRef,
  confirmRef,
  canReadAgain,
  onMismatch,
  className,
}: {
  code: GiroCodeBlocked;
  docId: string;
  pending: boolean;
  error: Error | null;
  onConfirm: () => void;
  headingRef: RefObject<HTMLHeadingElement | null>;
  confirmRef: RefObject<HTMLButtonElement | null>;
  canReadAgain: boolean;
  onMismatch?: (open: boolean) => void;
  className?: string;
}) {
  const id = useId();
  const [mismatch, setMismatch] = useState(false);
  // the panel's copy buttons follow the note; gone (the code is ready, or refused for another reason), they come back
  useEffect(() => {
    onMismatch?.(mismatch);
  }, [mismatch, onMismatch]);
  useEffect(() => () => onMismatch?.(false), [onMismatch]);
  const noteRef = useRef<HTMLDivElement>(null);
  const refusedRef = useRef<HTMLParagraphElement>(null);
  const readAgainRef = useRef<HTMLButtonElement>(null);
  const readFailedRef = useRef<HTMLParagraphElement>(null);
  // the answer to "They don't match", a refused comparison and a failed reading open below their
  // button: each is brought clear of the panel's footer (a short Today popover hides it otherwise).
  // A button that asked was disabled meanwhile, which drops focus to the page: once the answer is
  // shown — the button enabled again in the same render — it gets focus back, without a scroll that
  // would cancel the smooth one.
  useEffect(() => {
    if (mismatch) scrollClear(noteRef.current);
  }, [mismatch]);
  useEffect(() => {
    if (!error) return;
    confirmRef.current?.focus({ preventScroll: true });
    scrollClear(refusedRef.current);
  }, [error, confirmRef]);
  const reprocess = useReadLetterAgain();
  const answered = reprocess.isSuccess || reprocess.isError;
  useEffect(() => {
    if (!answered) return;
    readAgainRef.current?.focus({ preventScroll: true });
    if (reprocess.error) scrollClear(readFailedRef.current);
  }, [answered, reprocess.error]);
  // The reading asked for here, followed to its end: the block stays (its code may still ask to compare), so
  // it says when the reading is done — or why it failed — and offers it again (UI audit round 2: "Reading it
  // again" for good). Kept once seen: the letter's page drops a finished job from the progress list.
  const job = useJobProgress(docId);
  const asked = reprocess.data?.id;
  const [outcome, setOutcome] = useState<ReadOutcome | null>(null);
  if (asked && job?.job_id === asked && (job.status === "done" || job.status === "failed") && outcome?.jobId !== asked) {
    setOutcome({ jobId: asked, failed: job.status === "failed", error: job.error ?? null });
  }
  const ended = asked && outcome?.jobId === asked ? outcome : null;
  const reading = reprocess.isSuccess && !ended;
  const failure = reprocess.error ? reprocess.error.message : ended?.failed ? (ended.error ?? "something went wrong while reading it.") : null;
  const statusRef = useRef<HTMLSpanElement>(null);
  const endedAs = ended ? (ended.failed ? "failed" : "done") : null;
  useEffect(() => {
    if (endedAs) scrollClear(endedAs === "failed" ? readFailedRef.current : statusRef.current);
  }, [endedAs]);
  // once asked, the block says how the reading goes: no progress card over the panel's footer (as the letter's
  // own progress card does) — hidden before the reading's first progress arrives; closed, the card shows it
  // again, unless the reading was said done here
  const [follows, setFollows] = useState(false);
  useEffect(() => {
    if (!follows) return;
    setUploadToastHidden(docId, true);
    return () => setUploadToastHidden(docId, false);
  }, [follows, docId]);
  const doneHere = endedAs === "done";
  useEffect(() => {
    if (!doneHere) return;
    return () => dismissJob(docId);
  }, [doneHere, docId]);
  const readAgain = () => {
    if (reprocess.isPending || reading) return;
    setFollows(true);
    reprocess.mutate(docId, {
      onSuccess: (started) => seedJob({ job_id: started.id, doc_id: docId, stage: "intake", progress: 0, status: "running" }),
    });
  };
  // once asked, the button and its answer stay while the letter is read (the panel stops offering it)
  const showReadAgain = canReadAgain || !reprocess.isIdle;
  return (
    <section aria-labelledby={`${id}-h`} data-girocode="check" className={cn("rounded-lg border border-warn/25 bg-warn-soft p-3", className)}>
      <Heading id={`${id}-h`} headingRef={headingRef} icon={ScanLine} tone="text-warn-ink" />
      <p className="mt-1 text-sm leading-relaxed text-ink/85 wrap-break-word">{code.message}</p>
      <div className="mt-2.5 flex flex-wrap gap-2">
        <Button ref={confirmRef} variant="secondary" size="sm" icon={Check} loading={pending} onClick={onConfirm} disabled={!code.values}>
          These match the letter
        </Button>
        <Button variant="ghost" size="sm" aria-expanded={mismatch} aria-controls={`${id}-mismatch`} onClick={() => setMismatch((v) => !v)}>
          They don't match
        </Button>
      </div>
      {error ? (
        <p ref={refusedRef} role="alert" className="mt-2 scroll-my-24 text-sm leading-relaxed text-danger-ink wrap-break-word">
          Not confirmed: {error.message}
        </p>
      ) : null}
      <div id={`${id}-mismatch`} ref={noteRef} hidden={!mismatch} className="mt-2.5 scroll-my-24 border-t border-warn/25 pt-2.5">
        <p className="text-sm leading-relaxed text-ink/85">{GIROCODE_MISMATCH}</p>
        {showReadAgain ? (
          <>
            <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1">
              <Button
                ref={readAgainRef}
                variant="secondary"
                size="sm"
                icon={RotateCw}
                loading={reprocess.isPending}
                aria-disabled={reading || undefined}
                onClick={readAgain}
              >
                Read the letter again
              </Button>
              <span ref={statusRef} role="status" className="scroll-my-24 text-xs leading-5 text-muted">
                {reading ? GIROCODE_READING_AGAIN : ended && !ended.failed ? GIROCODE_READ_AGAIN : ""}
              </span>
            </div>
            {failure ? (
              <p ref={readFailedRef} role="alert" className="mt-2 scroll-my-24 text-sm leading-relaxed text-danger-ink wrap-break-word">
                Couldn't read the letter again: {failure}
              </p>
            ) : null}
          </>
        ) : null}
      </div>
    </section>
  );
}

function NoCode({ code, className }: { code: GiroCodeBlocked; className?: string }) {
  const id = useId();
  const scam = code.reason === "scam";
  return (
    <section
      aria-labelledby={`${id}-h`}
      data-girocode="blocked"
      className={cn("rounded-lg border p-3", scam ? "border-danger/25 bg-danger-soft" : "border-line bg-surface-2", className)}
    >
      <h3 id={`${id}-h`} className={cn("flex items-center gap-1.5 text-sm font-semibold", scam ? "text-danger-ink" : "text-ink")}>
        {scam ? <ShieldAlert className="size-4 shrink-0" aria-hidden /> : <Info className="size-4 shrink-0 text-muted" aria-hidden />}
        {GIROCODE_TITLE}
      </h3>
      <p className={cn("mt-1 text-sm leading-relaxed wrap-break-word", scam ? "text-danger-ink" : "text-muted")}>{code.message}</p>
    </section>
  );
}
