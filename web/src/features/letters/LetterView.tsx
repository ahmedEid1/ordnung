import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useBlocker, useNavigate } from "react-router";
import { Check, Download, Ellipsis, FileCheck2, ListChecks, PenLine, Save, Send, Trash2 } from "lucide-react";
import { api } from "@/api/endpoints";
import { useDeleteDraft, useDocuments, useContracts, useDraftProof, useMarkDraftSent, useParties, useTranslateDraft, useUpdateDraft } from "@/api/hooks";
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
import { Menu } from "@/components/ui/Menu";
import { PartyChip } from "@/components/ui/PartyChip";
import { StatusPill } from "@/components/ui/StatusPill";
import { toast } from "@/components/ui/Toast";
import { DRAFT_KIND_COPY, PROOF_KIND_COPY, copyFor } from "@/lib/copy";
import { formatDate } from "@/lib/format";
import { useHotkey } from "@/lib/hooks";
import { useTodayISO } from "@/lib/today";
import { adviceFor, changedFields, draftTitle, editableOf, followUpDate, pdfFileName, sentVia, versioned, type EditableFields } from "./logic";
import { ChecksPanel } from "./ChecksPanel";
import { DraftKindIcon } from "./DraftList";
import { LetterEditor } from "./LetterEditor";
import { MarkSentDialog } from "./MarkSentDialog";
import { PdfPreview } from "./PdfPreview";
import { ProofPanel } from "./ProofPanel";
import { SendGuidancePanel } from "./SendGuidancePanel";
import { contractHref } from "@/features/contracts/links";
import { focusWhenReady } from "@/features/today/focus";

/** The "Sent by … on …" banner: where focus goes once a letter is marked as sent (its button is gone). */
const SENT_BANNER = "letter-sent";

const MOD_KEY = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent) ? "⌘" : "Ctrl";

const EDITED_KEY = "ordnung.letters.edited";

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

/**
 * The letter editor (`/letters/:id`): German letter and English meaning side by side, checks,
 * "How to send it", the printable PDF, and Save / Download / Mark as sent.
 */
export function LetterView({ draft }: { draft: Draft }) {
  const navigate = useNavigate();
  const today = useTodayISO();
  const parties = useParties();
  const docs = useDocuments();
  const contracts = useContracts();
  const update = useUpdateDraft();
  const markSent = useMarkDraftSent();
  const remove = useDeleteDraft();
  const translate = useTranslateDraft();

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

  const party = draft.party_id ? (parties.data ?? []).find((p) => p.id === draft.party_id) ?? null : null;
  const doc = draft.doc_id ? (docs.data ?? []).find((d) => d.id === draft.doc_id) ?? null : null;
  const contract = draft.contract_id ? (contracts.data ?? []).find((c) => c.id === draft.contract_id) ?? null : null;
  const title = draftTitle(draft, party?.name);
  const [bodyEdited, setBodyEdited] = useState(() => readEdited(draft.id));

  const pdfUrl = versioned(api.draftPdfUrl(draft.id), draft.updated_at);
  const fileName = pdfFileName(draft);

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
        description: err instanceof ApiError ? err.message : "Please try again in a moment.",
      });
    }
  }, [draft.id, save, translate]);

  const saveWithToast = useCallback(() => {
    if (!dirty || update.isPending) return;
    void save().then(() => toast.success("Letter saved", { description: "Checks and the PDF are up to date." }));
  }, [dirty, save, update.isPending]);

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

  const confirmSent = async (channel: SendChannelKind, date: string, trackingNumber: string | null) => {
    try {
      if (dirty) await save();
      const again = isSent;
      // an emptied number is sent as "" (it removes the stored one), no number at all for other channels
      await markSent.mutateAsync({ id: draft.id, channel, date, ...(trackingNumber !== null ? { tracking_number: trackingNumber } : {}) });
      setSentOpen(false);
      // "Mark as sent" is gone with the dialog: focus the banner that says so, above the proof card
      if (!again) focusWhenReady(() => document.getElementById(SENT_BANNER));
      if (again) toast.success("Changed how and when you sent it", { description: `Sent ${sentVia(channel)} on ${formatDate(date, { style: "short", today })}.` });
      else
        toast.success(`We'll remind you to check for a reply on ${formatDate(followUpDate(date, draft.kind), { style: "short", today })}`, {
          description: `Marked as sent ${sentVia(channel)} on ${formatDate(date, { style: "short", today })}.`,
        });
    } catch {
      /* the global mutation handler shows the error */
    }
  };

  const kindCopy = copyFor(DRAFT_KIND_COPY, draft.kind);

  return (
    <div>
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
            <h1 className="display mt-1.5 text-[28px] font-semibold leading-[1.15] text-ink sm:text-[34px]">{title}</h1>
          </div>
        </div>
        <div className="mt-3 flex flex-col gap-3 sm:pl-16 md:flex-row md:items-center">
          <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2 text-[13px] text-muted">
            {party ? <PartyChip party={party} /> : null}
            {doc ? (
              <Link to={`/documents/${doc.id}`} className="inline-flex max-w-full items-center gap-1 rounded-full border border-line bg-surface px-2.5 py-0.5 font-medium text-ink hover:border-line-strong hover:bg-surface-2">
                <span className="text-muted">About</span> <span className="truncate">{doc.title ?? doc.filename}</span>
              </Link>
            ) : contract ? (
              <Link to={contractHref(contract.id)} className="inline-flex max-w-full items-center gap-1 rounded-full border border-line bg-surface px-2.5 py-0.5 font-medium text-ink hover:border-line-strong hover:bg-surface-2">
                <span className="text-muted">About</span> <span className="truncate">{contract.name}</span>
              </Link>
            ) : null}
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {!isSent ? (
              <Button icon={dirty ? Save : Check} onClick={saveWithToast} disabled={!dirty} loading={update.isPending} title={`Save (${MOD_KEY}+S)`}>
                {dirty ? "Save" : "Saved"}
              </Button>
            ) : null}
            <a href={pdfUrl} download={fileName} onClick={download} className={buttonVariants({ variant: "secondary" })}>
              <Download aria-hidden />
              Download PDF
            </a>
            {!isSent ? (
              <Button variant="primary" icon={Send} onClick={() => setSentOpen(true)}>
                Mark as sent
              </Button>
            ) : null}
            <Menu
              label="More actions"
              items={[
                ...(!isSent && draft.status !== "final" ? [{ label: "Mark as ready to send", icon: FileCheck2, onSelect: () => update.mutate({ id: draft.id, patch: { status: "final" } }) }] : []),
                ...(isSent ? [{ label: "Change how or when you sent it", icon: PenLine, onSelect: () => setSentOpen(true) }] : []),
                { label: "Delete this letter", icon: Trash2, danger: true, onSelect: () => setDeleteOpen(true) },
              ]}
            >
              <IconButton icon={Ellipsis} label="More actions" variant="ghost" />
            </Menu>
          </div>
        </div>
      </header>

      {isSent ? (
        <div id={SENT_BANNER} tabIndex={-1} className="mb-6 rounded-xl outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent">
          <Callout
            tone="success"
            title={["Sent", sentVia(draft.sent_channel), "on", formatDate(draft.sent_at?.slice(0, 10) ?? today, { style: "short", today })].filter(Boolean).join(" ")}
          >
            {/* what it waits for, and when Ordnung reminds, is in the proof card below */}
            Keep your proof of sending with it below.
          </Callout>
        </div>
      ) : dirty ? (
        <p className="mb-4 flex items-center gap-2 text-[12.5px] text-muted" role="status">
          <span className="size-1.5 rounded-full bg-warn" aria-hidden /> Unsaved changes · <Kbd>{MOD_KEY}</Kbd>
          <Kbd>S</Kbd> to save
        </p>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_340px] xl:grid-cols-[minmax(0,1fr)_370px]">
        <div className="min-w-0 space-y-6 lg:col-start-1 lg:row-start-1">
          {isSent ? <ProofPanel draft={draft} onChangeSending={() => setSentOpen(true)} /> : null}
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
          />
          {draft.notes_for_user.length ? (
            <Callout tone="info" title="Good to know">
              <ul className="space-y-1 [overflow-wrap:anywhere]">
                {draft.notes_for_user.map((n) => (
                  <li key={n}>{n}</li>
                ))}
              </ul>
            </Callout>
          ) : null}
        </div>

        <aside className="min-w-0 space-y-6 lg:col-start-2 lg:row-span-2 lg:row-start-1" aria-label="Sending and checks">
          <Card as="section" aria-labelledby="send-title" padding="md">
            <CardHeader title={<span id="send-title">How to send it</span>} icon={Send} />
            <SendGuidancePanel guidance={draft.send_guidance} sent={isSent} />
          </Card>
          <Card as="section" aria-labelledby="checks-title" padding="md">
            <CardHeader title={<span id="checks-title">Checks</span>} icon={ListChecks} />
            <ChecksPanel checks={draft.checks} stale={dirty} />
          </Card>
          <Disclaimer advice={draft.kind === "objection" ? adviceFor(doc?.area) : undefined} className="px-1" />
        </aside>

        <section aria-labelledby="pdf-title" className="min-w-0 lg:col-start-1 lg:row-start-2">
          <h2 id="pdf-title" className="mb-3 px-1 text-[12.5px] font-semibold uppercase tracking-[0.07em] text-muted">
            Print preview
          </h2>
          <div className="rounded-[var(--radius-card)] border border-line bg-surface-2/60 px-4 py-6 sm:px-8 sm:py-8">
            <PdfPreview src={pdfUrl} version={draft.updated_at} stale={dirty} />
          </div>
        </section>
      </div>

      <MarkSentDialog
        key={`${draft.id}-${draft.status}-${sentOpen}`}
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
        title="Delete this letter?"
        description={
          isSent
            ? "The letter, its PDF and what Ordnung recorded about sending it are removed from Ordnung. Nothing is sent or withdrawn — the letter you posted stays posted."
            : "The draft and its PDF are removed from Ordnung."
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
            <Button onClick={() => blocker.reset?.()}>Keep editing</Button>
            <Button variant="danger" onClick={() => blocker.proceed?.()}>
              Discard changes
            </Button>
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
