import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type RefObject } from "react";
import { Link, useBlocker, useNavigate } from "react-router";
import { Check, ChevronRight, CircleCheck, Download, Ellipsis, FilePen, FileCheck2, ListChecks, PenLine, Save, Send, Trash2, TriangleAlert, Undo2 } from "lucide-react";
import { api } from "@/api/endpoints";
import { useDeleteDraft, useDocuments, useContracts, useDraftProof, useMarkDraftSent, useParties, useProfile, useTranslateDraft, useUpdateDraft } from "@/api/hooks";
import { ApiError } from "@/api/client";
import type { Draft, SendChannelKind } from "@/api/types";
import { Button, IconButton, buttonVariants } from "@/components/ui/Button";
import { Callout } from "@/components/ui/Callout";
import { Card, CardHeader } from "@/components/ui/Card";
import { DateText } from "@/components/ui/DateText";
import { Dialog } from "@/components/ui/Dialog";
import { Checkbox } from "@/components/ui/Field";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { Kbd } from "@/components/ui/Kbd";
import { Menu, type MenuItem } from "@/components/ui/Menu";
import { PartyChip } from "@/components/ui/PartyChip";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { StatusPill } from "@/components/ui/StatusPill";
import { toast } from "@/components/ui/Toast";
import { DRAFT_KIND_COPY, PROOF_KIND_COPY, SEND_CHANNEL_COPY, copyFor } from "@/lib/copy";
import { formatDate } from "@/lib/format";
import { useHotkey } from "@/lib/hooks";
import { useTodayISO } from "@/lib/today";
import { cn, prefersReducedMotion } from "@/lib/utils";
import { usePhoneCompanion } from "@/features/phone/client";
import { OnYourComputer } from "@/features/phone/ComputerOnly";
import { PDF_ON_COMPUTER } from "@/features/phone/copy";
import {
  adviceFor,
  changedFields,
  channelCounts,
  checksSummary,
  draftTitle,
  editableOf,
  firstLine,
  followUpDate,
  notesToShow,
  pdfFileName,
  plainText,
  sameName,
  sendChoices,
  sentVia,
  versioned,
  type EditableFields,
} from "./logic";
import { ChecksPanel } from "./ChecksPanel";
import { DraftKindIcon } from "./DraftList";
import { LetterEditor } from "./LetterEditor";
import { MarkSentDialog } from "./MarkSentDialog";
import { PdfPreview } from "./PdfPreview";
import { ProofPanel } from "./ProofPanel";
import { SendGuidancePanel } from "./SendGuidancePanel";
import { contractHref } from "@/features/contracts/links";
import { hasLongWord } from "@/features/document/verdict";
import { focusWhenReady } from "@/features/today/focus";

/** The "Sent by … on …" banner: where focus goes once a letter is marked as sent (its button is gone). */
const SENT_BANNER = "letter-sent";

const MOD_KEY = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent) ? "⌘" : "Ctrl";

const EDITED_KEY = "ordnung.letters.edited";

/**
 * The sending panel sits beside the letter only when the letter still gets 760 px (its two panes
 * side by side) next to it: 760 + 24 gap + 370. Narrower, the letter takes the whole width and the
 * panels follow below it. Measured on the page, so it follows the sidebar too.
 */
const BESIDE_MIN_WIDTH = 1154;

/** Drafts whose German text was changed after drafting (their translation no longer matches). */
function readEdited(id: string): boolean {
  try {
    return (JSON.parse(localStorage.getItem(EDITED_KEY) ?? "[]") as string[]).includes(id);
  } catch {
    return false;
  }
}

function markEdited(id: string, edited = true) {
  try {
    const ids = new Set(JSON.parse(localStorage.getItem(EDITED_KEY) ?? "[]") as string[]);
    if (edited) ids.add(id);
    else ids.delete(id);
    localStorage.setItem(EDITED_KEY, JSON.stringify([...ids].slice(-200)));
  } catch {
    /* storage unavailable */
  }
}

function triggerDownload(href: string, filename: string) {
  const a = document.createElement("a");
  a.href = href;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
}

/** The element's width, measured before paint and kept up to date (0 until measured). */
function useWidth(ref: RefObject<HTMLElement | null>): number {
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    setWidth(el.getBoundingClientRect().width);
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => setWidth(el.getBoundingClientRect().width));
    ro.observe(el);
    return () => ro.disconnect();
  }, [ref]);
  return width;
}

/** Whether the element is on screen below the sticky top bar (true where that can't be observed). */
function useOnScreen(ref: RefObject<HTMLElement | null>): boolean {
  const [on, setOn] = useState(true);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver(([entry]) => setOn(Boolean(entry?.isIntersecting)), { rootMargin: "-56px 0px 0px 0px" });
    io.observe(el);
    return () => io.disconnect();
  }, [ref]);
  return on;
}

/**
 * While the save bar shows, whatever gets focus behind it (Tab to the next link) scrolls up clear of
 * it — focus is never hidden under the bar (WCAG 2.4.11), like the Settings save bar.
 */
function useFocusClearOf(bar: RefObject<HTMLElement | null>, shown: boolean) {
  useEffect(() => {
    if (!shown) return;
    let frame = 0;
    const onFocusIn = (e: FocusEvent) => {
      const el = e.target;
      if (!(el instanceof HTMLElement) || !bar.current || bar.current.contains(el)) return;
      cancelAnimationFrame(frame);
      // after the browser's own scroll-into-view
      frame = requestAnimationFrame(() => {
        const b = bar.current?.getBoundingClientRect();
        const r = el.getBoundingClientRect();
        // a tall field (the letter's text) only needs its top clear
        if (b && r.top < b.bottom && r.top + Math.min(r.height, 48) > b.top) window.scrollBy({ top: r.top + Math.min(r.height, 48) - b.top + 12 });
      });
    };
    document.addEventListener("focusin", onFocusIn);
    return () => {
      cancelAnimationFrame(frame);
      document.removeEventListener("focusin", onFocusIn);
    };
  }, [bar, shown]);
}

/*
 * The save bar floats above whatever covers the bottom of the screen, like the Settings save bar:
 * the phone tab bar (h-16 + home indicator), then the demo tour card (--ordnung-toast-lift) and the
 * toasts (--ordnung-toast-space) — each gap only counts when there is something to clear.
 */
const clearOf = (v: string, gap: string) => `min(var(${v}, 0px) * 999, var(${v}, 0px) + var(${gap}))`;
const SAVE_BAR_BOTTOM = `calc(var(--pin-base) + ${clearOf("--ordnung-toast-lift", "--pin-lift-gap")} + ${clearOf("--ordnung-toast-space", "--pin-gap")})`;
const SAVE_BAR =
  "sticky z-20 [--pin-base:calc(4.75rem+env(safe-area-inset-bottom,0px))] [--pin-lift-gap:0.75rem] [--pin-gap:1.25rem] " +
  "md:[--pin-base:1.25rem] md:[--pin-lift-gap:1.25rem] md:[--pin-gap:1.75rem]";

/** "● Unsaved changes · Ctrl S to save" (the shortcut only where there is a keyboard). */
function UnsavedNote({ className }: { className?: string }) {
  return (
    <span className={cn("items-center gap-1.5 text-[13px] text-warn-ink", className)}>
      <span className="size-1.5 shrink-0 rounded-full bg-warn" aria-hidden />
      <span>Unsaved changes</span>
      <span className="hidden items-center gap-1 text-muted pointer-fine:inline-flex" aria-hidden>
        · <Kbd>{MOD_KEY}</Kbd>
        <Kbd>S</Kbd>
      </span>
    </span>
  );
}

/**
 * The letter editor (`/letters/:id`): German letter and English meaning side by side, checks,
 * "How to send it", the printable letter, and Save / Download / Mark as sent.
 */
export function LetterView({ draft }: { draft: Draft }) {
  const navigate = useNavigate();
  const today = useTodayISO();
  // on a paired phone the PDF is downloaded (and the letter deleted) on the computer; writing, translating,
  // "sent", tracking and proof photos all work here
  const phone = usePhoneCompanion();
  const parties = useParties();
  const docs = useDocuments();
  const contracts = useContracts();
  const update = useUpdateDraft();
  const markSent = useMarkDraftSent();
  const remove = useDeleteDraft();
  const translate = useTranslateDraft();
  const ownName = useProfile().data?.name?.trim() ?? "";

  const saved = useMemo(() => editableOf(draft), [draft]);
  const [form, setForm] = useState<EditableFields>(saved);
  const [sentOpen, setSentOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [keepProofFiles, setKeepProofFiles] = useState(false);
  const changes = changedFields(saved, form);
  const dirty = Object.keys(changes).length > 0;
  const isSent = draft.status === "sent";
  // a sent letter's proofs go with it when it is deleted: the dialog names them (the panel loads the same query)
  const proofs = useDraftProof(draft.id, { enabled: isSent }).data?.proofs ?? [];
  const proofFiles = proofs.filter((p) => p.document?.source === "proof");

  const rootRef = useRef<HTMLDivElement>(null);
  const actionsRef = useRef<HTMLDivElement>(null);
  const width = useWidth(rootRef);
  const beside = width >= BESIDE_MIN_WIDTH;
  const actionsOnScreen = useOnScreen(actionsRef);
  const saveBarRef = useRef<HTMLDivElement>(null);
  const saveBarShown = dirty && !actionsOnScreen;
  useFocusClearOf(saveBarRef, saveBarShown);

  const party = draft.party_id ? (parties.data ?? []).find((p) => p.id === draft.party_id) ?? null : null;
  const doc = draft.doc_id ? (docs.data ?? []).find((d) => d.id === draft.doc_id) ?? null : null;
  const contract = draft.contract_id ? (contracts.data ?? []).find((c) => c.id === draft.contract_id) ?? null : null;
  const title = draftTitle(draft, party?.name);
  const [bodyEdited, setBodyEdited] = useState(() => readEdited(draft.id));

  const pdfUrl = versioned(api.draftPdfUrl(draft.id), draft.updated_at);
  const previewUrl = versioned(api.draftPreviewUrl(draft.id), draft.updated_at);
  const fileName = pdfFileName(draft);
  const notes = notesToShow(draft.notes_for_user);
  const summary = checksSummary(draft.checks);
  const counts = channelCounts(draft.send_guidance, draft.sent_channel);

  const save = useCallback(async () => {
    if (!dirty) return draft;
    const updated = await update.mutateAsync({ id: draft.id, patch: changes });
    if ("body" in changes || "subject" in changes) {
      markEdited(draft.id);
      setBodyEdited(true);
    }
    setForm(editableOf(updated));
    return updated;
  }, [changes, dirty, draft, update]);

  // "Re-translate": save pending edits first, then translate the letter as it now stands
  const retranslate = useCallback(async () => {
    if (translate.isPending) return;
    let current: Draft;
    try {
      current = await save();
    } catch {
      return; // the save error is already shown
    }
    try {
      await translate.mutateAsync(current.id);
      markEdited(draft.id, false);
      setBodyEdited(false);
      toast.success("Translation updated", { description: "The English text now matches your letter." });
    } catch (err) {
      const demo = err instanceof ApiError && (err.status === 409 || err.isStaticDemo);
      toast({
        tone: demo ? "info" : "danger",
        title: demo ? "Not available in the demo" : "Couldn't translate the letter",
        description: err instanceof ApiError ? plainText(err.message) : "Please try again in a moment.",
      });
    }
  }, [draft.id, save, translate]);

  const saveWithToast = useCallback(() => {
    if (!dirty || update.isPending) return;
    void save().then(() => toast.success("Letter saved", { description: "Checks and the PDF are up to date." }));
  }, [dirty, save, update.isPending]);

  const discard = () => {
    const edits = form;
    setForm(saved);
    toast({ title: "Changes discarded", undo: () => setForm(edits) });
  };

  useHotkey((e) => (e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "s", (e) => {
    e.preventDefault();
    saveWithToast();
  }, true);

  // leaving with unsaved changes
  const blocker = useBlocker(({ currentLocation, nextLocation }) => dirty && currentLocation.pathname !== nextLocation.pathname);
  useEffect(() => {
    if (!dirty) return;
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      e.preventDefault();
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [dirty]);

  const download = (e: React.MouseEvent) => {
    if (!dirty) return;
    e.preventDefault();
    void save().then((d) => triggerDownload(versioned(api.draftPdfUrl(d.id), d.updated_at), fileName));
  };

  const dueBy = draft.send_guidance?.send_by ?? draft.send_guidance?.must_arrive_by ?? null;
  /** "Also post a signed copy by Thu 8 Oct." — what to do when the way it went doesn't count. */
  const fallbackAdvice = (when: string | null) =>
    draft.send_guidance?.form === "written_form"
      ? `This letter must be signed by hand on paper: also post a signed copy${when ? ` by ${formatDate(when, { style: "short", today })}` : ""}, ideally by Einschreiben, and keep the receipt.`
      : `This way isn't accepted for this letter: also send it one of the ways under “How to send it”${when ? ` by ${formatDate(when, { style: "short", today })}` : ""}.`;

  const confirmSent = async (channel: SendChannelKind, date: string, trackingNumber: string | null) => {
    const again = isSent;
    try {
      if (dirty) await save();
      // an emptied number is sent as "" (it removes the stored one), no number at all for other channels
      await markSent.mutateAsync({ id: draft.id, channel, date, ...(trackingNumber !== null ? { tracking_number: trackingNumber } : {}) });
      setSentOpen(false);
      // "Mark as sent" is gone with the dialog: focus the banner that says so, above the proof card
      if (!again) focusWhenReady(() => document.getElementById(SENT_BANNER));
      const followUp = formatDate(followUpDate(date, draft.kind), { style: "short", today });
      const how = [sentVia(channel), "on", formatDate(date, { style: "short", today })].filter(Boolean).join(" ");
      if (!channelCounts(draft.send_guidance, channel)) {
        toast.warn(again ? "Updated — this way may not count" : "Marked as sent — this way may not count", {
          description: `${fallbackAdvice(dueBy && dueBy >= today ? dueBy : null)} We'll remind you to check for a reply on ${followUp}.`,
        });
      } else {
        toast.success(`We'll remind you to check for a reply on ${followUp}`, {
          description: `${again ? "Now marked as sent" : "Marked as sent"} ${how}.`,
        });
      }
    } catch {
      /* the global mutation handler shows the error */
    }
  };

  const setStatus = (status: "draft" | "final") => {
    const back = status === "draft" ? "final" : "draft";
    update.mutate(
      { id: draft.id, patch: { status } },
      {
        onSuccess: () =>
          toast.success(status === "final" ? "Marked as ready to send" : "Back to draft", {
            description: status === "final" ? "It shows as ready in your letters." : undefined,
            undo: async () => {
              await update.mutateAsync({ id: draft.id, patch: { status: back } });
            },
          }),
      },
    );
  };

  const jumpToChecks = (e: React.MouseEvent) => {
    const el = document.getElementById("letter-checks");
    if (!el) return;
    e.preventDefault();
    el.scrollIntoView({ block: "start", behavior: prefersReducedMotion() ? "auto" : "smooth" });
    el.focus({ preventScroll: true });
  };

  const kindCopy = copyFor(DRAFT_KIND_COPY, draft.kind);
  const sentChannelLabel = draft.sent_channel ? sendChoices(draft.send_guidance).find((c) => c.channel === draft.sent_channel)?.label ?? copyFor(SEND_CHANNEL_COPY, draft.sent_channel as SendChannelKind).label : null;
  const sentOn = draft.sent_at?.slice(0, 10) ?? today;
  const sentTitle = ["Sent", sentVia(draft.sent_channel), "on", formatDate(sentOn, { style: "short", today })].filter(Boolean).join(" ");

  const menuItems: MenuItem[] = [
    ...(isSent
      ? [{ label: "Change how or when you sent it", icon: PenLine, onSelect: () => setSentOpen(true) }]
      : draft.status === "final"
        ? [{ label: "Back to draft", icon: FilePen, onSelect: () => setStatus("draft") }]
        : [{ label: "Mark as ready to send", icon: FileCheck2, onSelect: () => setStatus("final") }]),
    ...(phone ? [] : [{ label: "Delete this letter", icon: Trash2, danger: true, onSelect: () => setDeleteOpen(true) }]),
  ];

  const aboutCls =
    "inline-flex min-h-6 max-w-full items-start gap-1 rounded-2xl border border-line bg-surface px-2.5 py-0.5 text-sm font-medium leading-5 text-ink hover:border-line-strong hover:bg-surface-2";
  const about = doc ? { to: `/documents/${doc.id}`, name: doc.title ?? doc.filename } : contract ? { to: contractHref(contract.id), name: contract.name } : null;

  // -- the panels -------------------------------------------------------------------------------

  const proofPanel = isSent ? <ProofPanel draft={draft} onChangeSending={() => setSentOpen(true)} /> : null;

  const editor = (
    <div className="min-w-0 space-y-6">
      <LetterEditor
        value={form}
        onChange={setForm}
        translation={draft.body_translation}
        language={draft.language}
        enclosures={draft.enclosures}
        translationStale={bodyEdited || form.body !== saved.body || form.subject !== saved.subject}
        onRetranslate={() => void retranslate()}
        retranslating={translate.isPending}
        readOnly={isSent}
        // a letter that goes out in someone else's name: its sender isn't "you"
        senderLabel={ownName && firstLine(form.sender_block) && !sameName(firstLine(form.sender_block), ownName) ? "From" : "From (you)"}
      />
      {notes.length ? (
        <Callout tone="info" title="Good to know">
          <ul className="space-y-1 [overflow-wrap:anywhere]">
            {notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        </Callout>
      ) : null}
    </div>
  );

  const sending = isSent ? (
    <Card as="section" aria-labelledby="send-title" padding="md" className="min-w-0">
      <CardHeader level={2} title={<span id="send-title">How it was sent</span>} icon={Send} />
      <p className="flex items-start gap-2 text-[14px] leading-5 text-ink">
        {counts ? <CircleCheck className="mt-0.5 size-4 shrink-0 text-ok" aria-hidden /> : <TriangleAlert className="mt-0.5 size-4 shrink-0 text-warn" aria-hidden />}
        <span className="min-w-0 [overflow-wrap:anywhere]">
          {sentChannelLabel ? <span className="font-medium">{sentChannelLabel}</span> : "Sent"}, on <DateText date={sentOn} style="short" />.{" "}
          <span className={counts ? "text-muted" : "text-warn-ink"}>{counts ? "Counts for this letter." : "May not count for this letter."}</span>
        </span>
      </p>
      <details className="group mt-4 border-t border-line pt-3">
        <summary className="-mx-2 flex min-h-8 w-fit cursor-pointer list-none items-center gap-1.5 rounded-md px-2 text-[13px] font-medium text-muted hover:bg-surface-2/70 hover:text-ink [&::-webkit-details-marker]:hidden">
          <ChevronRight className="size-3.5 transition-transform group-open:rotate-90 motion-reduce:transition-none" aria-hidden />
          The ways to send this letter
        </summary>
        <div className="mt-3">
          <SendGuidancePanel guidance={draft.send_guidance} sent />
        </div>
      </details>
    </Card>
  ) : (
    <Card as="section" aria-labelledby="send-title" padding="md" className="min-w-0">
      <CardHeader level={2} title={<span id="send-title">How to send it</span>} icon={Send} />
      <SendGuidancePanel guidance={draft.send_guidance} />
    </Card>
  );

  const checks = (
    <div className="min-w-0 space-y-6">
      <Card as="section" id="letter-checks" tabIndex={-1} aria-labelledby="checks-title" padding="md" className="scroll-mt-20 outline-none">
        <CardHeader level={2} title={<span id="checks-title">Checks</span>} icon={ListChecks} />
        <ChecksPanel checks={draft.checks} stale={dirty} />
      </Card>
      <Disclaimer advice={draft.kind === "objection" ? adviceFor(doc?.area) : undefined} className="px-1" />
    </div>
  );

  const preview = (
    <section aria-labelledby="pdf-title" className="min-w-0">
      <SectionHeader id="pdf-title" title="Print preview" />
      <div className="rounded-[var(--radius-card)] border border-line bg-surface-2/60 px-4 py-6 sm:px-8 sm:py-8">
        <PdfPreview src={previewUrl} pdfHref={phone ? undefined : pdfUrl} version={draft.updated_at} stale={dirty} />
      </div>
      {phone ? <OnYourComputer className="mt-2 px-1">{PDF_ON_COMPUTER}</OnYourComputer> : null}
    </section>
  );

  return (
    <div ref={rootRef}>
      {/* header */}
      <header className="mb-6">
        <div className="flex min-w-0 gap-4">
          <DraftKindIcon kind={draft.kind} size="lg" className="mt-1 hidden sm:grid" />
          <div className="min-w-0 flex-1">
            <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[13px] text-muted">
              <span className="font-medium text-ink/80">{kindCopy.label}</span>
              <span aria-hidden>·</span>
              <StatusPill of="draft" status={draft.status} />
              <span aria-hidden>·</span>
              <span>
                Started <DateText date={draft.created_at.slice(0, 10)} style="day" />
              </span>
            </p>
            {/* the detail pages' one title size (--text-detail); a very long word one step smaller on phones */}
            <h1 className={cn("display mt-1.5 font-semibold text-ink [overflow-wrap:anywhere]", hasLongWord(title) ? "text-detail-long" : "text-detail")}>{title}</h1>
          </div>
        </div>
        <div className="mt-3 flex flex-col gap-3 sm:pl-16 xl:flex-row xl:items-start">
          {party || about || draft.checks.length ? (
            // their own row until xl: next to the buttons they would shrink to "FunkNetz M…"
            <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2 xl:pt-1.5">
              {party ? <PartyChip party={party} /> : null}
              {about ? (
                <Link to={about.to} className={aboutCls} title={about.name}>
                  <span className="shrink-0 font-normal text-muted">About</span>
                  <span className="line-clamp-2 min-w-0 [overflow-wrap:anywhere]">{about.name}</span>
                </Link>
              ) : null}
              {draft.checks.length ? (
                // the checks, summed up at the top (the list itself is far down on a phone)
                <a
                  href="#letter-checks"
                  onClick={jumpToChecks}
                  className={cn(
                    "inline-flex min-h-6 items-center gap-1.5 rounded-full px-2.5 py-0.5 text-sm font-medium transition-colors",
                    summary.failed ? "bg-warn-soft text-warn-ink hover:bg-warn-soft/70" : "bg-ok-soft text-ok-ink hover:bg-ok-soft/70",
                  )}
                >
                  {summary.failed ? <TriangleAlert className="size-3.5 shrink-0" aria-hidden /> : <CircleCheck className="size-3.5 shrink-0" aria-hidden />}
                  {summary.text}
                </a>
              ) : null}
            </div>
          ) : null}

          <div
            ref={actionsRef}
            className={cn(
              // phones: the main action first, on its own row; then the rest side by side
              "grid gap-2 sm:flex sm:flex-wrap sm:items-center sm:justify-end xl:ml-auto xl:shrink-0",
              // the row under "Mark as sent": Save, Download and the menu — a paired phone has no Download (the PDF is
              // downloaded on the computer), a sent letter no Save
              isSent && phone
                ? "grid-cols-[auto] justify-end"
                : isSent || phone
                  ? "grid-cols-[minmax(0,1fr)_auto]"
                  : "grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]",
            )}
          >
            {!isSent ? (
              // unsaved changes: a dot on Save (no line of text that would push the page down or the
              // chips over); the live region below says it, the save bar spells it out further down
              <Button
                icon={dirty ? Save : Check}
                onClick={saveWithToast}
                disabled={!dirty}
                loading={update.isPending}
                title={dirty ? `Unsaved changes — save (${MOD_KEY}+S)` : "All changes saved"}
                className="min-w-0 max-[359px]:px-2.5"
              >
                <span className="min-w-0 truncate">{dirty ? "Save" : "Saved"}</span>
                {dirty ? <span className="absolute -right-1 -top-1 size-2.5 rounded-full bg-warn ring-2 ring-canvas" data-unsaved aria-hidden /> : null}
              </Button>
            ) : null}
            {phone ? null : (
              <a href={pdfUrl} download={fileName} onClick={download} aria-label="Download PDF" className={buttonVariants({ variant: "secondary", className: "min-w-0 max-[359px]:px-2.5" })}>
                <Download aria-hidden />
                <span className="min-w-0 truncate">
                  Download<span className="max-[359px]:hidden"> PDF</span>
                </span>
              </a>
            )}
            {!isSent ? (
              <Button variant="primary" icon={Send} onClick={() => setSentOpen(true)} className="max-sm:order-first max-sm:col-span-full">
                Mark as sent
              </Button>
            ) : null}
            <Menu label="More actions" heading={title} items={menuItems}>
              <IconButton icon={Ellipsis} label="More actions" variant="ghost" />
            </Menu>
          </div>
        </div>
      </header>
      {/* one live region for the save state, whatever shows it on screen */}
      <p className="sr-only" role="status">
        {dirty ? "Unsaved changes" : ""}
      </p>

      {isSent ? (
        // what it waits for, and when Ordnung reminds, is in the proof card below
        <div id={SENT_BANNER} tabIndex={-1} className="mb-6 rounded-xl outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent">
          {counts ? (
            <Callout tone="success" title={sentTitle}>
              Keep your proof of sending with it below.
            </Callout>
          ) : (
            <Callout
              tone="warn"
              title={`${sentTitle} — that may not count`}
              action={
                <Button size="sm" icon={Send} onClick={() => setSentOpen(true)}>
                  Change how it was sent
                </Button>
              }
            >
              {fallbackAdvice(dueBy && dueBy >= today ? dueBy : null)} Keep your proof of sending with it below.
            </Callout>
          )}
        </div>
      ) : null}

      {beside ? (
        <div className="grid grid-cols-[minmax(0,1fr)_370px] items-start gap-6">
          <div className="min-w-0 space-y-6">
            {proofPanel}
            {editor}
            {preview}
          </div>
          <div className="min-w-0 space-y-6">
            {sending}
            {checks}
          </div>
        </div>
      ) : (
        <div className="space-y-6">
          {proofPanel}
          {editor}
          <div className="grid items-start gap-6 md:grid-cols-2">
            {sending}
            <div className="min-w-0 space-y-6">
              {checks}
              {preview}
            </div>
          </div>
        </div>
      )}

      {saveBarShown ? (
        // Save stays in reach while you edit further down (the header's buttons scrolled away)
        <div ref={saveBarRef} className={cn(SAVE_BAR, "mt-6")} style={{ bottom: SAVE_BAR_BOTTOM }} data-save-bar>
          <div className="flex flex-wrap items-center justify-end gap-x-3 gap-y-2 rounded-2xl border border-line bg-surface px-4 py-2.5 shadow-[var(--shadow-pop)]">
            <UnsavedNote className="mr-auto inline-flex" />
            <div className="flex items-center gap-2">
              <Button variant="ghost" size="sm" onClick={discard}>
                Discard
              </Button>
              <Button variant="primary" size="sm" icon={Save} onClick={saveWithToast} loading={update.isPending}>
                Save
              </Button>
            </div>
          </div>
        </div>
      ) : null}

      <MarkSentDialog
        key={`${draft.id}:${draft.status}:${draft.sent_channel ?? ""}:${draft.sent_at ?? ""}:${draft.tracking_number ?? ""}:${sentOpen}`}
        open={sentOpen}
        onClose={() => setSentOpen(false)}
        draft={draft}
        onConfirm={confirmSent}
        pending={markSent.isPending || update.isPending}
      />

      <Dialog
        open={deleteOpen}
        onClose={() => setDeleteOpen(false)}
        size="sm"
        title={isSent ? "Delete this sent letter?" : "Delete this letter?"}
        description={
          isSent
            ? "Its text, its PDF and what Ordnung recorded about sending it are removed from Ordnung. It doesn't unsend anything — the letter you posted stays posted — and the reminder to check for a reply stays on your list."
            : "This draft and its PDF are removed from Ordnung."
        }
        footer={
          <>
            <Button onClick={() => setDeleteOpen(false)}>Keep it</Button>
            <Button
              variant="danger"
              icon={Trash2}
              loading={remove.isPending}
              onClick={() =>
                remove.mutate(
                  { id: draft.id, keepProofFiles: proofFiles.length > 0 && keepProofFiles },
                  {
                    onSuccess: () => {
                      setDeleteOpen(false);
                      toast.success("Letter deleted", { description: proofFiles.length && keepProofFiles ? "Its proof files stay in Ordnung, in your Inbox." : undefined });
                      navigate("/letters", { replace: true });
                    },
                  },
                )
              }
            >
              Delete
            </Button>
          </>
        }
      >
        {proofFiles.length ? (
          <div className="space-y-3 text-[14px] leading-relaxed text-ink/85">
            <p>
              Its {proofFiles.length === 1 ? "proof file" : `${proofFiles.length} proof files`} —{" "}
              {proofFiles
                .map((p) =>
                  copyFor(PROOF_KIND_COPY, p.proof.kind)
                    .label.replace(/\s*\(.*\)$/, "")
                    .toLowerCase(),
                )
                .join(", ")}{" "}
              — {keepProofFiles
                ? `stay${proofFiles.length === 1 ? "s" : ""} in Ordnung as your own document${proofFiles.length === 1 ? "" : "s"}.`
                : `${proofFiles.length === 1 ? "is" : "are"} deleted for good too.`}
            </p>
            <Checkbox
              label="Keep the proof files"
              description="They stay private in your Inbox, so you still have the receipt if they ever say the letter didn't arrive."
              checked={keepProofFiles}
              onChange={(e) => setKeepProofFiles(e.target.checked)}
            />
          </div>
        ) : null}
      </Dialog>

      <Dialog
        open={blocker.state === "blocked"}
        onClose={() => blocker.reset?.()}
        size="md"
        title="Leave without saving?"
        description="Your changes to the letter haven't been saved yet."
        footer={
          <>
            <Button variant="ghost" icon={Undo2} onClick={() => blocker.proceed?.()} className="text-danger-ink hover:bg-danger-soft hover:text-danger-ink sm:mr-auto">
              Discard changes
            </Button>
            <Button onClick={() => blocker.reset?.()}>Keep editing</Button>
            <Button
              variant="primary"
              icon={Save}
              loading={update.isPending}
              onClick={() =>
                void save().then(
                  () => blocker.proceed?.(),
                  () => blocker.reset?.(),
                )
              }
            >
              Save and leave
            </Button>
          </>
        }
      />
    </div>
  );
}
