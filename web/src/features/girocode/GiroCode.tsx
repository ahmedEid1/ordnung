/**
 * The GiroCode (EPC-QR) of a payment: a QR code any German banking app scans to pre-fill the
 * transfer, which the person then confirms there with their TAN — Ordnung never pays. The server
 * decides whether there is a code (`girocodes` of the letter's detail); this shows the code, or
 * why there is none, or — for details read from a photo — asks to compare them with the paper
 * letter first ("These match the letter").
 *
 * The code stays dark on white with its quiet zone in both themes and in forced-colours mode:
 * scanners need that contrast, whatever the page around it looks like.
 */
import { useId, useMemo, useRef, useState, type RefObject } from "react";
import { Check, ChevronDown, CircleCheck, Info, QrCode as QrIcon, ScanLine, ShieldAlert } from "lucide-react";
import type { GiroCode as GiroCodeData, GiroCodeBlocked } from "@/api/types";
import { useConfirmGiroCode } from "@/api/hooks";
import { Button } from "@/components/ui/Button";
import { toast } from "@/components/ui/Toast";
import { formatMoney } from "@/lib/format";
import { cn } from "@/lib/utils";
import { qrMatrix, qrPath, readPayload } from "./qr";

export const GIROCODE_TITLE = "GiroCode (EPC-QR)";
export const GIROCODE_HINT = "Scan with your banking app; you confirm the transfer there.";

/** Reasons the pay panels already explain in their own words (no bank details, nothing to pay). */
const QUIET: ReadonlySet<GiroCodeBlocked["reason"]> = new Set(["no_iban", "incoming", "settled"]);

/** Whether a pay panel shows anything for this code. */
export function showsGiroCode(code: GiroCodeData | undefined): code is GiroCodeData {
  return code != null && (code.status === "ready" || !QUIET.has(code.reason));
}

/** What the code does, for screen readers: "GiroCode: transfer €184.30 to Wohnbau Musterstadt eG". */
export function giroCodeLabel(payload: string): string {
  const t = readPayload(payload);
  const amount = t.amount != null ? `${formatMoney(t.amount)} ` : "";
  return `GiroCode: transfer ${amount}to ${t.name}${t.reference ? `, reference ${t.reference}` : ""}`;
}

/** The QR code itself: SVG, crisp modules, dark on white with the quiet zone. */
export function QrCode({ payload, label, className }: { payload: string; label: string; className?: string }) {
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
  return (
    <svg
      role="img"
      aria-label={label}
      viewBox={`0 0 ${qr.size} ${qr.size}`}
      shapeRendering="crispEdges"
      data-qr-version={qr.version}
      data-qr-modules={qr.size}
      className={cn("block aspect-square bg-white [forced-color-adjust:none]", className)}
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
  /** Today's pay panel: the code starts folded behind "Show code". */
  collapsible?: boolean;
  className?: string;
}

/** A pay panel's GiroCode block: the code, the comparison with the paper letter, or why there is none. */
export function GiroCodeSection({ code, docId, collapsible = false, className }: GiroCodeSectionProps) {
  const headingRef = useRef<HTMLHeadingElement>(null);
  // the mutation lives here, not in the "compare" block: that block is gone once the code is ready,
  // and the success feedback must still run
  const confirm = useConfirmGiroCode();
  if (!showsGiroCode(code)) return null;
  if (code.status === "ready") {
    return <Ready payload={code.payload} checked={code.checked} collapsible={collapsible} headingRef={headingRef} className={className} />;
  }
  if (code.reason === "check_letter") {
    const onConfirm = () => {
      if (!code.values) return;
      confirm.mutate(
        { itemId: code.item_id, docId, values: code.values },
        {
          onSuccess: (next) => {
            if (next.status !== "ready") return;
            toast({ tone: "success", title: "GiroCode ready", description: "You compared the details with the paper letter." });
            // the button is gone: focus the code's heading, which takes its place
            requestAnimationFrame(() => headingRef.current?.focus());
          },
        },
      );
    };
    return <CompareFirst code={code} pending={confirm.isPending} onConfirm={onConfirm} headingRef={headingRef} className={className} />;
  }
  return <NoCode code={code} className={className} />;
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
  headingRef,
  className,
}: {
  payload: string;
  checked: boolean;
  collapsible: boolean;
  headingRef: RefObject<HTMLHeadingElement | null>;
  className?: string;
}) {
  const id = useId();
  const [open, setOpen] = useState(!collapsible);
  const label = giroCodeLabel(payload);
  return (
    <section aria-labelledby={`${id}-h`} data-girocode="ready" className={cn("@container rounded-lg border border-line p-3", className)}>
      <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1">
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
            onClick={() => setOpen((v) => !v)}
            className={cn("[&_svg]:transition-transform motion-reduce:[&_svg]:transition-none", open && "[&_svg]:rotate-180")}
          >
            {open ? "Hide code" : "Show code"}
          </Button>
        ) : null}
      </div>
      <div id={`${id}-code`} hidden={!open} className="mt-3">
        <div className="mx-auto w-44 max-w-full rounded-md bg-white p-1 shadow-[0_0_0_1px_rgb(0_0_0/0.08)] dark:shadow-none">
          <QrCode payload={payload} label={label} />
        </div>
        {checked ? (
          <p className="mt-2 flex items-start justify-center gap-1.5 text-center text-xs leading-5 text-ok-ink">
            <CircleCheck className="mt-[3px] size-3.5 shrink-0" aria-hidden />
            You compared these details with the paper letter.
          </p>
        ) : null}
      </div>
    </section>
  );
}

function CompareFirst({
  code,
  pending,
  onConfirm,
  headingRef,
  className,
}: {
  code: GiroCodeBlocked;
  pending: boolean;
  onConfirm: () => void;
  headingRef: RefObject<HTMLHeadingElement | null>;
  className?: string;
}) {
  const id = useId();
  return (
    <section aria-labelledby={`${id}-h`} data-girocode="check" className={cn("rounded-lg border border-warn/25 bg-warn-soft p-3", className)}>
      <Heading id={`${id}-h`} headingRef={headingRef} icon={ScanLine} tone="text-warn-ink" />
      <p className="mt-1 text-sm leading-relaxed text-ink/85">{code.message}</p>
      <Button variant="secondary" size="sm" icon={Check} className="mt-2.5" loading={pending} onClick={onConfirm} disabled={!code.values}>
        These match the letter
      </Button>
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
      <p className={cn("mt-1 text-sm leading-relaxed", scam ? "text-danger-ink" : "text-muted")}>{code.message}</p>
    </section>
  );
}
