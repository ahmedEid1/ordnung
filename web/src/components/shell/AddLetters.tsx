import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { Link } from "react-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Camera, ChevronLeft, ChevronRight, FileImage, FileStack, FileText, FileUp, Files, Inbox, Lock, Mail, Upload, X, type LucideIcon } from "lucide-react";
import { invalidateLedger, useHealth, useUploadDocuments } from "@/api/hooks";
import type { Health, UploadResult } from "@/api/types";
import type { UploadOptions } from "@/api/endpoints";
import { seedJob } from "@/api/sse";
import { claudeState, type ClaudeState } from "@/features/onboarding/wizard";
import { usePhoneCompanion } from "@/features/phone/client";
import { filesStay, theComputer } from "@/features/phone/copy";
import { isAbort, uploadWithProgress } from "@/features/phone/upload";
import { isStaticDemo } from "@/mocks/mode";
import { Dialog } from "@/components/ui/Dialog";
import { Button, IconButton, buttonVariants } from "@/components/ui/Button";
import { toast } from "@/components/ui/Toast";
import { Switch } from "@/components/ui/Field";
import { getOverlayRoot } from "@/components/ui/internal";
import { formatFileSize } from "@/lib/format";
import { cn, plural } from "@/lib/utils";

/**
 * File types Ordnung accepts: PDFs, phone photos, saved e-mails (`.eml` — each PDF or photo attached
 * becomes a letter of its own, as from the watched folder) and plain text — what intake reads.
 */
export const ACCEPT =
  "application/pdf,image/jpeg,image/png,image/webp,image/heic,image/heif,message/rfc822,text/plain,.pdf,.jpg,.jpeg,.png,.webp,.heic,.heif,.eml,.txt";
/** The accepted types in words (the "skipped" message names them). "e‑mail" has a non-breaking hyphen (U+2011). */
export const ACCEPTED_TYPES = "PDFs, photos (JPG, PNG, WEBP, HEIC), saved e‑mails (.eml) and text files";
/** What can be added, said short (drop zone, empty states, onboarding): "PDFs, phone photos or saved e‑mails". */
export const ACCEPTED_SHORT = "PDFs, phone photos or saved e‑mails";
/** One of them: "a PDF, a phone photo or a saved e‑mail". */
export const ACCEPTED_ONE = "a PDF, a phone photo or a saved e‑mail";

const isImage = (f: File) => f.type.startsWith("image/") || /\.(jpe?g|png|webp|heic|heif)$/i.test(f.name);
const isEmail = (f: File) => f.type === "message/rfc822" || /\.eml$/i.test(f.name);
const isText = (f: File) => isEmail(f) || f.type === "text/plain" || /\.(eml|txt)$/i.test(f.name);
const isAccepted = (f: File) => isImage(f) || isText(f) || f.type === "application/pdf" || /\.pdf$/i.test(f.name);

/** What a file to add is, as its row in the dialog says it: "Photo", "E‑mail", "Text file" or "PDF". */
export function fileKind(f: File): { label: string; icon: LucideIcon } {
  if (isImage(f)) return { label: "Photo", icon: FileImage };
  if (isEmail(f)) return { label: "E‑mail", icon: Mail }; // U+2011: never split at its hyphen
  if (f.type === "text/plain" || /\.txt$/i.test(f.name)) return { label: "Text file", icon: FileText };
  return { label: "PDF", icon: FileText };
}

/** How many files (or photo pages) a dialog lists before "Show all". */
const SHOWN = 8;

/** Why Claude can't read letters now: not installed, not signed in, or older than Ordnung needs. */
export type ClaudeNotReady = Extract<ClaudeState, "missing" | "signed_out" | "outdated">;

/** Why Claude can't read letters now, or `null` when it can — or when this session doesn't use Claude
 * (the demo's recordings, a test backend). Letters added meanwhile are stored and wait in the queue:
 * they are read as soon as Claude is connected. */
export function claudeNotReady(health: Pick<Health, "backend" | "claude"> | undefined): ClaudeNotReady | null {
  if (health?.backend !== "claude") return null;
  const state = claudeState(health.claude);
  return state === "missing" || state === "signed_out" || state === "outdated" ? state : null;
}

interface AddLettersApi {
  /** Open the native file picker (in the online demo: why adding needs the app). */
  openPicker: () => void;
  /** Add files (from the picker, a drop, or a page). Always offers "Keep private — no AI" first, and asks
   * "one letter?" for several photos. */
  addFiles: (files: File[] | FileList) => void;
  uploading: boolean;
}

const Ctx = createContext<AddLettersApi | null>(null);

/** Access the global "Add letters" flow (picker, drop, combine question, upload + progress). */
export function useAddLetters(): AddLettersApi {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useAddLetters must be used inside <AddLettersProvider>");
  return ctx;
}

/** The "Add letters" flow when there is one — `null` outside the provider (a dialog rendered on its own). */
export function useOptionalAddLetters(): AddLettersApi | null {
  return useContext(Ctx);
}

/** A file waiting for the person's choice; `id` keeps two files with the same name apart. */
interface PendingFile {
  id: string;
  file: File;
}

/**
 * Files waiting for the person's choice; `photos`: several photos, so "one letter?" is asked too. `camera`: pages
 * photographed one after another on a paired phone ("Photograph a letter"), named by `stamp` — the dialog shows from
 * the first page on, and asks before they are thrown away.
 */
interface Pending {
  files: PendingFile[];
  photos: boolean;
  camera?: boolean;
  /** When the first page was photographed ("2026-10-07-0814"): the pages' names. */
  stamp?: string;
}

let fileSeq = 0;

/** "2026-10-07-0814": the local minute a letter's first page was photographed. */
export function photoStamp(now: Date = new Date()): string {
  const two = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${two(now.getMonth() + 1)}-${two(now.getDate())}-${two(now.getHours())}${two(now.getMinutes())}`;
}

/** A photo's file extension: from its type ("image/jpeg" → "jpg"), else from its name, else "jpg". */
function photoExtension(file: File): string {
  const byType: Record<string, string> = { "image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/heic": "heic", "image/heif": "heif" };
  return byType[file.type] ?? /\.(jpe?g|png|webp|heic|heif)$/i.exec(file.name)?.[1]?.toLowerCase().replace("jpeg", "jpg") ?? "jpg";
}

/**
 * Page `n` of a letter photographed at `stamp`: "photo-2026-10-07-0814-p1.jpg". A phone's camera names every photo
 * "image.jpg"; this tells the pages apart, in the Inbox and on the computer.
 */
export function photoName(stamp: string, n: number, file: File): string {
  return `photo-${stamp}-p${n}.${photoExtension(file)}`;
}

/** The photographed pages named by their place (after a page was added, moved or removed): p1, p2, … in order. */
function numberPages(files: PendingFile[], stamp: string): PendingFile[] {
  return files.map((entry, i) => {
    const name = photoName(stamp, i + 1, entry.file);
    return entry.file.name === name ? entry : { ...entry, file: new File([entry.file], name, { type: entry.file.type, lastModified: entry.file.lastModified }) };
  });
}

/** A phone's upload in flight: how many files, how far (0–1). */
interface Sending {
  count: number;
  /** Pages of one letter (the camera's), rather than files. */
  pages: boolean;
  fraction: number;
}

/** What the dialog says after a phone's upload ended without the letters (a refusal, no answer, Cancel). */
interface SendNote {
  text: string;
  failed: boolean;
}

/** Said when "Cancel" stopped a phone's upload. */
export const SEND_STOPPED = "Sending stopped — nothing was added. The files are still here.";

/** "a.txt", "b.zip and c.doc", "a, b, c and 2 more" — names of skipped files. */
function nameList(names: string[]): string {
  if (names.length <= 2) return names.join(" and ");
  if (names.length === 3) return `${names[0]}, ${names[1]} and ${names[2]}`;
  return `${names.slice(0, 2).join(", ")} and ${names.length - 2} more`;
}

/**
 * A phone's upload, with progress and a way to stop it (`features/phone/upload.ts`). Its refusals are shown in the
 * dialog that sent it, which stays open meanwhile (so the photos are never lost to a failed send), never as a toast.
 */
function usePhoneUpload() {
  const qc = useQueryClient();
  const [sending, setSending] = useState<Sending | null>(null);
  const abort = useRef<AbortController | null>(null);
  const mutation = useMutation({
    mutationFn: ({ files, pages, ...opts }: { files: File[]; pages: boolean } & UploadOptions): Promise<UploadResult> => {
      const controller = new AbortController();
      abort.current = controller;
      setSending({ count: files.length, pages, fraction: 0 });
      return uploadWithProgress(files, opts, (fraction) => setSending((s) => (s ? { ...s, fraction } : s)), controller.signal);
    },
    meta: { silent: true },
    onSuccess: () => invalidateLedger(qc),
    onSettled: () => {
      abort.current = null;
      setSending(null);
    },
  });
  return { mutation, sending, cancel: () => abort.current?.abort() };
}

/**
 * Provides the "Add letters" flow: hidden file input, a confirmation with "Keep private — no AI" before
 * anything is sent (docs/privacy.md) — for several photos the "Are these pages of one letter?" dialog —,
 * the upload mutation and seeding the live progress stepper. In the online demo (no backend to keep
 * files) the picker and a drop explain straight away that adding letters needs the app.
 *
 * On a paired phone, "Add letters" first asks how: **Photograph a letter** opens the rear camera (a file input with
 * `capture`, so the page never holds a camera permission) one page at a time — each page joins "Pages of one
 * letter", named `photo-<day>-<time>-p<n>`, until "Add letter" sends them as one letter in their order — or
 * **Choose files**. A phone's upload says how far it got and can be stopped; the dialog stays until it is sent.
 */
export function AddLettersProvider({ children }: { children: ReactNode }) {
  const inputRef = useRef<HTMLInputElement>(null);
  const cameraRef = useRef<HTMLInputElement>(null);
  const upload = useUploadDocuments();
  const phone = usePhoneCompanion();
  const phoneUpload = usePhoneUpload();
  const notReady = claudeNotReady(useHealth().data);
  const [pending, setPending] = useState<Pending | null>(null);
  const [keepPrivate, setKeepPrivate] = useState(false);
  const [demoNotice, setDemoNotice] = useState(false);
  const [chooser, setChooser] = useState(false);
  const [discarding, setDiscarding] = useState(false);
  const [sendNote, setSendNote] = useState<SendNote | null>(null);

  /** What an upload's answer says beyond the progress cards: kept private, added before, files that failed. */
  const afterUpload = useCallback(
    (res: UploadResult, priv: boolean) => {
      for (const d of res.documents) {
        if (!priv) seedJob({ job_id: res.jobs.find((j) => j.doc_id === d.id)?.id ?? d.id, doc_id: d.id, stage: "intake", progress: 0, status: "running" });
      }
      if (priv) toast.success(`${plural(res.documents.length, "letter")} stored privately`, { description: `Kept on ${theComputer(phone)} only — not sent to Claude.` });
      if (res.duplicates.length) toast({ title: "Already in your inbox", description: `${plural(res.duplicates.length, "file")} had been added before.` });
      if (res.errors.length)
        toast.warn(`${plural(res.errors.length, "file")} couldn't be added`, {
          description: <span className="[overflow-wrap:anywhere]">{res.errors.map((e) => `${e.filename}: ${e.detail}`).join(" · ")}</span>,
        });
    },
    [phone],
  );

  // The computer: the dialog closes at once, a failure is the request's toast. A phone: the dialog stays and shows
  // how far the photos got; it closes once they are on the computer, and says in place why they aren't.
  const send = useCallback(
    (files: File[], combine: boolean, priv: boolean, pages = false) => {
      if (!phone) {
        upload.mutate({ files, combine, private: priv }, { onSuccess: (res) => afterUpload(res, priv) });
        setPending(null);
        return;
      }
      setSendNote(null);
      phoneUpload.mutation.mutate(
        { files, combine, private: priv, pages },
        {
          onSuccess: (res) => {
            afterUpload(res, priv);
            setPending(null);
          },
          onError: (err) =>
            setSendNote(isAbort(err) ? { text: SEND_STOPPED, failed: false } : { text: err instanceof Error ? err.message : "Sending didn't work.", failed: true }),
        },
      );
    },
    [phone, upload, phoneUpload.mutation, afterUpload],
  );

  const addFiles = useCallback((list: File[] | FileList) => {
    if (isStaticDemo()) {
      setDemoNotice(true);
      return;
    }
    const files = Array.from(list);
    const accepted = files.filter(isAccepted);
    const rejected = files.filter((f) => !isAccepted(f)).map((f) => f.name);
    if (rejected.length)
      toast.warn(`${plural(rejected.length, "file")} skipped`, {
        description: (
          <span className="[overflow-wrap:anywhere]">
            <span className="font-medium text-ink">{nameList(rejected)}</span> {rejected.length === 1 ? "isn't a file Ordnung reads" : "aren't files Ordnung reads"}.
            Ordnung reads {ACCEPTED_TYPES}.
          </span>
        ),
      });
    if (!accepted.length) return;
    setKeepPrivate(false);
    setSendNote(null);
    setPending({
      files: accepted.map((file) => ({ id: `f${++fileSeq}`, file })),
      photos: accepted.length >= 2 && accepted.every(isImage),
    });
  }, []);

  /** Pages from the phone's camera: they join the letter being photographed (or start one). */
  const addPhotos = useCallback((list: File[] | FileList) => {
    const shots = Array.from(list).filter(isImage);
    if (!shots.length) return;
    setSendNote(null);
    setPending((p) => {
      const letter = p?.camera ? p : { files: [], photos: true, camera: true, stamp: photoStamp() };
      const stamp = letter.stamp ?? photoStamp();
      return { ...letter, stamp, files: numberPages([...letter.files, ...shots.map((file) => ({ id: `f${++fileSeq}`, file }))], stamp) };
    });
  }, []);

  const removeFile = useCallback((id: string) => {
    setPending((p) => {
      if (!p) return p;
      const files = p.files.filter((f) => f.id !== id);
      if (!files.length) return null;
      // the camera's pages keep their dialog (and their names follow their places); other photos: one left,
      // nothing to combine any more
      if (p.camera) return { ...p, files: numberPages(files, p.stamp ?? photoStamp()) };
      return { files, photos: p.photos && files.length >= 2 };
    });
  }, []);

  const moveFile = useCallback((id: string, by: -1 | 1) => {
    setPending((p) => {
      if (!p) return p;
      const i = p.files.findIndex((f) => f.id === id);
      const j = i + by;
      if (i < 0 || j < 0 || j >= p.files.length) return p;
      const files = [...p.files];
      [files[i], files[j]] = [files[j]!, files[i]!];
      return { ...p, files: p.camera ? numberPages(files, p.stamp ?? photoStamp()) : files };
    });
  }, []);

  const openPicker = useCallback(() => {
    if (isStaticDemo()) setDemoNotice(true);
    // a phone: photograph the letter, or choose files (the computer has no camera worth asking about)
    else if (phone) setChooser(true);
    else inputRef.current?.click();
  }, [phone]);
  const uploading = upload.isPending || phoneUpload.mutation.isPending;
  const api = useMemo<AddLettersApi>(() => ({ openPicker, addFiles, uploading }), [openPicker, addFiles, uploading]);
  const files = pending?.files.map((f) => f.file) ?? [];
  const sending = phoneUpload.sending;

  // while a phone's upload runs, the dialog stays: Cancel stops it. Photos taken here exist nowhere else, so
  // closing asks before they are thrown away.
  const close = () => {
    if (sending) return;
    if (pending?.camera) setDiscarding(true);
    else setPending(null);
  };

  const fileInput = (
    <input
      ref={inputRef}
      type="file"
      multiple
      accept={ACCEPT}
      className="sr-only"
      tabIndex={-1}
      aria-hidden
      onChange={(e) => {
        if (e.target.files?.length) addFiles(e.target.files);
        e.target.value = "";
      }}
    />
  );

  return (
    <Ctx.Provider value={api}>
      {children}
      {phone
        ? // with the overlays, never under the app while a dialog makes it inert: a tap in the chooser (or "Take
          // another page") opens them
          createPortal(
            <>
              {fileInput}
              <input
                ref={cameraRef}
                type="file"
                accept="image/*"
                capture="environment"
                data-camera=""
                className="sr-only"
                tabIndex={-1}
                aria-hidden
                onChange={(e) => {
                  if (e.target.files?.length) addPhotos(e.target.files);
                  e.target.value = "";
                }}
              />
            </>,
            getOverlayRoot(),
          )
        : fileInput}
      <AddDialog
        files={pending && !pending.photos ? pending.files : null}
        notReady={notReady}
        keepPrivate={keepPrivate}
        onKeepPrivate={setKeepPrivate}
        onRemove={removeFile}
        onClose={close}
        onAdd={() => {
          if (pending) send(files, false, keepPrivate);
        }}
        phone={phone}
        sending={sending}
        note={sendNote}
        onCancelSend={phoneUpload.cancel}
      />
      <CombineDialog
        files={pending?.photos ? pending.files : null}
        camera={Boolean(pending?.camera)}
        notReady={notReady}
        keepPrivate={keepPrivate}
        onKeepPrivate={setKeepPrivate}
        onRemove={removeFile}
        onMove={moveFile}
        onClose={close}
        onChoose={(combine) => {
          // one letter: its pages are sent ("Sending 3 pages…"); separate letters: files
          if (pending) send(files, combine, keepPrivate, combine);
        }}
        onTakeAnother={() => cameraRef.current?.click()}
        phone={phone}
        sending={sending}
        note={sendNote}
        onCancelSend={phoneUpload.cancel}
      />
      <Dialog
        open={discarding}
        onClose={() => setDiscarding(false)}
        size="sm"
        title={`Discard ${plural(pending?.files.length ?? 0, "photo")}?`}
        description="They haven't been sent."
        footer={
          <>
            <Button onClick={() => setDiscarding(false)}>Keep them</Button>
            <Button
              variant="danger"
              icon={X}
              onClick={() => {
                setDiscarding(false);
                setPending(null);
              }}
            >
              Discard
            </Button>
          </>
        }
      />
      <AddChooser
        open={chooser}
        onClose={() => setChooser(false)}
        onCamera={() => {
          setChooser(false);
          setKeepPrivate(false); // a new letter: the switch starts off, as for any added file
          cameraRef.current?.click();
        }}
        onFiles={() => {
          setChooser(false);
          inputRef.current?.click();
        }}
      />
      <DemoNotice open={demoNotice} onClose={() => setDemoNotice(false)} />
    </Ctx.Provider>
  );
}

/**
 * "Add a letter" on a paired phone: photograph it page by page with the rear camera, or choose files (a PDF, a
 * photo from the gallery, a saved e-mail).
 */
function AddChooser({ open, onClose, onCamera, onFiles }: { open: boolean; onClose: () => void; onCamera: () => void; onFiles: () => void }) {
  const cameraButton = useRef<HTMLButtonElement>(null);
  return (
    <Dialog
      open={open}
      onClose={onClose}
      size="sm"
      title="Add a letter"
      description={`Photograph a paper letter page by page, or choose ${ACCEPTED_ONE} on this phone. ${filesStay(true)}`}
      initialFocus={cameraButton}
    >
      <div className="grid gap-2">
        {/* the input opens from the tap itself (a file chooser opens only in answer to one) */}
        <Button ref={cameraButton} variant="primary" size="lg" icon={Camera} onClick={onCamera} className="w-full">
          Photograph a letter
        </Button>
        <Button size="lg" icon={FileUp} onClick={onFiles} className="w-full">
          Choose files
        </Button>
      </div>
    </Dialog>
  );
}

/** "Sending 3 pages… 45%" with Cancel: a phone's upload in the dialog that sent it. */
function SendingBar({ sending, onCancel }: { sending: Sending; onCancel: () => void }) {
  const percent = Math.round(sending.fraction * 100);
  const what = plural(sending.count, sending.pages ? "page" : "file");
  return (
    <div data-sending="" className="flex w-full items-center gap-3">
      <div className="min-w-0 flex-1">
        <p className="text-[13.5px] font-medium tabular-nums text-ink">
          Sending {what}… {percent}%
        </p>
        <div
          role="progressbar"
          aria-label={`Sending ${what}`}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={percent}
          className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-surface-3"
        >
          <div className="h-full rounded-full bg-accent transition-[width] duration-200 motion-reduce:transition-none" style={{ width: `${percent}%` }} />
        </div>
        <span className="sr-only" role="status">{`Sending ${what} to your computer`}</span>
      </div>
      <Button onClick={onCancel}>Cancel</Button>
    </div>
  );
}

/** Why the files weren't sent (or that sending was stopped), at the top of the dialog that sent them. */
function SendNoteLine({ note }: { note: SendNote | null }) {
  if (!note) return null;
  return note.failed ? (
    <p role="alert" className="mb-3 rounded-xl border border-danger/25 bg-danger-soft px-3.5 py-2.5 text-[13.5px] leading-relaxed text-danger-ink [overflow-wrap:anywhere]">
      Not sent: {note.text}
    </p>
  ) : (
    <p role="status" className="mb-3 rounded-xl bg-surface-2 px-3.5 py-2.5 text-[13.5px] leading-relaxed text-ink/85">
      {note.text}
    </p>
  );
}

/** An object URL for `file` while mounted (set a frame later, so the first paint isn't held up). */
function useObjectUrl(file: File): string | null {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    const u = URL.createObjectURL(file);
    const raf = requestAnimationFrame(() => setUrl(u));
    return () => {
      cancelAnimationFrame(raf);
      URL.revokeObjectURL(u);
    };
  }, [file]);
  return url;
}

/**
 * A file name that fits one line: the start ends in "…", the end (number, extension) stays —
 * "Einkommensteuerbescheid_2025_Fin…78901_Seite1.pdf". The full name is on hover and read out.
 */
export function FileName({ name, className }: { name: string; className?: string }) {
  const cut = Math.max(0, name.length - 14);
  return (
    <span title={name} className={cn("block min-w-0", className)}>
      <span className="sr-only">{name}</span>
      <span aria-hidden className="flex min-w-0">
        <span className="overflow-hidden text-ellipsis whitespace-pre">{name.slice(0, cut)}</span>
        <span className="shrink-0 whitespace-pre">{name.slice(cut)}</span>
      </span>
    </span>
  );
}

/**
 * After a list changes under the keyboard (a row removed, a page moved), put focus back on the
 * control that stands in the same place — never drop it on the page.
 */
function useKeepFocus<T>(deps: T) {
  const listRef = useRef<HTMLElement | null>(null);
  const next = useRef<(() => HTMLElement | null | undefined) | null>(null);
  useEffect(() => {
    const pick = next.current;
    next.current = null;
    pick?.()?.focus();
  }, [deps]);
  return {
    listRef,
    /** Call before the change: `find` runs after it and returns the element to focus. */
    refocus: (find: (list: HTMLElement) => HTMLElement | null | undefined) => {
      next.current = () => (listRef.current ? find(listRef.current) : null);
    },
  };
}

/** The files about to be added: icon, name (middle-truncated), type and size, and a way to take one out. */
function FileList({ files, onRemove }: { files: PendingFile[]; onRemove: (id: string) => void }) {
  const [showAll, setShowAll] = useState(false);
  const shown = showAll ? files : files.slice(0, SHOWN);
  const { listRef, refocus } = useKeepFocus(files);
  return (
    <>
      <ul ref={(el) => void (listRef.current = el)} aria-label="Files to add" className="divide-y divide-line overflow-hidden rounded-xl border border-line">
        {shown.map(({ id, file }, i) => {
          const { label: kind, icon: Icon } = fileKind(file);
          return (
            <li key={id} className="flex items-center gap-3 py-2 pl-3 pr-1.5">
              <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-surface-2 text-muted">
                <Icon className="size-4" aria-hidden />
              </span>
              <span className="min-w-0 flex-1">
                <FileName name={file.name} className="text-base font-medium text-ink" />
                <span className="block text-xs text-muted">
                  {kind} · {formatFileSize(file.size)}
                </span>
              </span>
              {files.length > 1 ? (
                <IconButton
                  icon={X}
                  size="sm"
                  label={`Remove ${file.name}`}
                  title="Remove"
                  data-remove=""
                  onClick={() => {
                    // the row that moves up into this place (or the one above, at the end) keeps focus
                    refocus((list) => {
                      const buttons = list.querySelectorAll<HTMLElement>("[data-remove]");
                      return buttons[Math.min(i, buttons.length - 1)];
                    });
                    onRemove(id);
                  }}
                />
              ) : null}
            </li>
          );
        })}
      </ul>
      {files.length > shown.length ? (
        <Button variant="link" size="sm" className="mt-2" onClick={() => setShowAll(true)}>
          Show all {files.length} files
        </Button>
      ) : null}
    </>
  );
}

function PagePreview({ file, page, count, onClose }: { file: File | null; page: number; count: number; onClose: () => void }) {
  return (
    <Dialog open={Boolean(file)} onClose={onClose} title={`Page ${page} of ${count}`} size="lg">
      {file ? <PreviewImage file={file} page={page} /> : null}
    </Dialog>
  );
}

function PreviewImage({ file, page }: { file: File; page: number }) {
  const url = useObjectUrl(file);
  return (
    <div className="grid min-h-40 place-items-center">
      {url ? <img src={url} alt={`Page ${page}: ${file.name}`} className="max-h-[70dvh] w-auto max-w-full rounded-lg border border-line object-contain" /> : null}
    </div>
  );
}

function Thumb({
  entry,
  index,
  count,
  onMove,
  onRemove,
  onOpen,
}: {
  entry: PendingFile;
  index: number;
  count: number;
  onMove: (by: -1 | 1) => void;
  onRemove: () => void;
  onOpen: () => void;
}) {
  const url = useObjectUrl(entry.file);
  const n = index + 1;
  // 24 px buttons in a row under the page (never on top of it: no target covers another)
  const small = "size-6 rounded-md [&_svg]:size-3.5";
  const gap = <span aria-hidden className="size-6" />;
  return (
    <li className="min-w-0">
      <button
        type="button"
        onClick={onOpen}
        aria-label={`Page ${n}: ${entry.file.name} — show larger`}
        title={entry.file.name}
        className="relative block aspect-[3/4] w-full overflow-hidden rounded-lg border border-line bg-surface-2 shadow-[var(--shadow-card)] transition-[border-color] hover:border-line-strong"
      >
        {url ? <img src={url} alt="" className="size-full object-cover" /> : null}
        <span aria-hidden className="absolute left-1 top-1 rounded-md bg-surface/90 px-1.5 text-xs font-medium tabular-nums text-ink shadow-[var(--shadow-card)]">
          {n}
        </span>
      </button>
      <div className="mt-1.5 flex items-center justify-center gap-1">
        {index > 0 ? (
          <IconButton icon={ChevronLeft} label={`Move page ${n} earlier`} title="Move earlier" data-move={`${entry.id}:-1`} onClick={() => onMove(-1)} className={small} />
        ) : (
          gap
        )}
        <IconButton icon={X} label={`Remove page ${n}`} title="Remove page" data-remove="" onClick={onRemove} className={small} />
        {index < count - 1 ? (
          <IconButton icon={ChevronRight} label={`Move page ${n} later`} title="Move later" data-move={`${entry.id}:1`} onClick={() => onMove(1)} className={small} />
        ) : (
          gap
        )}
      </div>
    </li>
  );
}

/** The photos as pages: in a grid that wraps (never cut off), in the order they will be combined. */
function PageThumbs({ files, onMove, onRemove }: { files: PendingFile[]; onMove: (id: string, by: -1 | 1) => void; onRemove: (id: string) => void }) {
  const [showAll, setShowAll] = useState(false);
  const [preview, setPreview] = useState<string | null>(null);
  const { listRef, refocus } = useKeepFocus(files);
  const shown = showAll ? files : files.slice(0, SHOWN);
  const previewIndex = files.findIndex((f) => f.id === preview);
  return (
    <>
      <ol ref={(el) => void (listRef.current = el)} aria-label="Pages, in order" className="grid grid-cols-[repeat(auto-fill,minmax(5rem,1fr))] gap-3">
        {shown.map((entry, i) => (
          <Thumb
            key={entry.id}
            entry={entry}
            index={i}
            count={files.length}
            onOpen={() => setPreview(entry.id)}
            onMove={(by) => {
              if (i + by >= SHOWN) setShowAll(true);
              // the moved page keeps focus on the same arrow (the other one once it reaches an end)
              refocus(
                (list) =>
                  list.querySelector<HTMLElement>(`[data-move="${entry.id}:${by}"]`) ??
                  list.querySelector<HTMLElement>(`[data-move="${entry.id}:${-by}"]`),
              );
              onMove(entry.id, by);
            }}
            onRemove={() => {
              refocus((list) => {
                const buttons = list.querySelectorAll<HTMLElement>("[data-remove]");
                return buttons[Math.min(i, buttons.length - 1)];
              });
              onRemove(entry.id);
            }}
          />
        ))}
        {files.length > shown.length ? (
          <li>
            <button
              type="button"
              onClick={() => setShowAll(true)}
              className="grid aspect-[3/4] w-full place-items-center rounded-lg border border-dashed border-line-strong text-sm font-semibold text-accent transition-colors hover:bg-accent-soft"
            >
              <span>
                +{files.length - shown.length} more
                <span className="sr-only"> pages — show all</span>
              </span>
            </button>
          </li>
        ) : null}
      </ol>
      <PagePreview file={previewIndex >= 0 ? files[previewIndex]!.file : null} page={previewIndex + 1} count={files.length} onClose={() => setPreview(null)} />
    </>
  );
}

function KeepPrivateSwitch({
  checked,
  onCheckedChange,
  several,
  phone = false,
  disabled,
}: {
  checked: boolean;
  onCheckedChange: (v: boolean) => void;
  several: boolean;
  phone?: boolean;
  disabled?: boolean;
}) {
  return (
    <Switch
      className="mt-4 rounded-xl border border-line bg-surface-2/50 p-3"
      checked={checked}
      onCheckedChange={onCheckedChange}
      disabled={disabled}
      label="Keep private — no AI"
      description={`Store and search ${several ? "them" : "it"} on ${theComputer(phone)} only; Claude never sees ${several ? "them" : "it"}.`}
    />
  );
}

/** "Claude isn't installed yet" / "… signed in yet" / "… needs an update": why the letters wait to be read. */
const NOT_READY: Record<ClaudeNotReady, string> = {
  missing: "Claude isn't installed yet",
  signed_out: "Claude isn't signed in yet",
  outdated: "Claude Code needs an update",
};

/**
 * What happens to the files, in the words of the switch's current choice (and whether Claude is ready); `phone`:
 * said on a paired phone, whose files go to the computer.
 */
export function addDescription(keepPrivate: boolean, several: boolean, notReady: ClaudeNotReady | null = null, phone = false): string {
  const [it, its] = several ? ["them", "their"] : ["it", "its"];
  const where = theComputer(phone);
  // found by name and by the file's own text, or the text a scanner added to it (ADR 0020); a photo by its name
  if (keepPrivate)
    return `Stored on ${where} only. Search finds ${it} by ${several ? "their names" : "its name"} and by any text in the ${several ? "files" : "file"}. Claude never reads ${it}, so Ordnung won't find ${its} dates — you can add them by hand.`;
  if (notReady)
    return `${NOT_READY[notReady]}, so Ordnung stores ${it} now and reads ${it} as soon as Claude is connected (Settings → Claude connection). ${filesStay(phone)}`;
  return `Claude reads ${it} through your Claude account to find dates, amounts and what to do. ${filesStay(phone)}`;
}

/** A phone's upload in the dialog that sends it. */
interface SendProps {
  /** On a paired phone (the wording, and an upload that shows its progress here). */
  phone?: boolean;
  /** The upload in flight: the footer shows its progress and Cancel instead of the choices. */
  sending?: Sending | null;
  /** Why the last try didn't send them, or that it was stopped. */
  note?: SendNote | null;
  onCancelSend?: () => void;
}

/**
 * "Add this letter?" — every upload offers "Keep private — no AI" before anything is sent to Claude.
 * While Claude isn't ready the default is "Store now, read later": the letter waits in the queue.
 */
function AddDialog({
  files,
  notReady,
  keepPrivate,
  onKeepPrivate,
  onRemove,
  onClose,
  onAdd,
  phone = false,
  sending = null,
  note = null,
  onCancelSend = () => {},
}: {
  files: PendingFile[] | null;
  notReady: ClaudeNotReady | null;
  keepPrivate: boolean;
  onKeepPrivate: (v: boolean) => void;
  onRemove: (id: string) => void;
  onClose: () => void;
  onAdd: () => void;
} & SendProps) {
  const addRef = useRef<HTMLButtonElement>(null);
  const count = files?.length ?? 0;
  const several = count > 1;
  return (
    <Dialog
      open={Boolean(files)}
      onClose={onClose}
      hideClose={Boolean(sending)}
      dismissible={!sending}
      title={several ? `Add ${count} letters?` : "Add this letter?"}
      description={addDescription(keepPrivate, several, notReady, phone)}
      initialFocus={addRef}
      footer={
        sending ? (
          <SendingBar sending={sending} onCancel={onCancelSend} />
        ) : (
          <>
            <Button onClick={onClose}>Cancel</Button>
            <Button ref={addRef} variant="primary" icon={keepPrivate ? Lock : Upload} onClick={onAdd}>
              {keepPrivate ? "Store privately" : notReady ? "Store now, read later" : several ? "Add letters" : "Add letter"}
            </Button>
          </>
        )
      }
    >
      <SendNoteLine note={note} />
      {files ? <FileList files={files} onRemove={onRemove} /> : null}
      <KeepPrivateSwitch checked={keepPrivate} onCheckedChange={onKeepPrivate} several={several} phone={phone} disabled={Boolean(sending)} />
    </Dialog>
  );
}

/**
 * What "Pages of one letter" says (a paired phone's camera, page by page): how many pages, what comes next, and
 * where the photos go.
 */
export function cameraDescription(pages: number, keepPrivate: boolean, notReady: ClaudeNotReady | null = null): string {
  const so = `${plural(pages, "page")}. Photograph the next page, or add the letter.`;
  if (keepPrivate) return `${so} The photos go to your computer only, and Claude never reads them.`;
  if (notReady) return `${so} ${NOT_READY[notReady]}: your computer stores the letter now and reads it as soon as Claude is connected.`;
  return `${so} The photos go to your computer and stay there.`;
}

/**
 * "Are these pages of one letter?" — shown when several photos are added at once. `camera`: "Pages of one letter",
 * the phone's camera variant, from its first page on — "Take another page", "Add letter" (one letter, its pages in
 * this order) or, from two pages, "Separate letters".
 */
function CombineDialog({
  files,
  camera = false,
  notReady,
  keepPrivate,
  onKeepPrivate,
  onRemove,
  onMove,
  onClose,
  onChoose,
  onTakeAnother = () => {},
  phone = false,
  sending = null,
  note = null,
  onCancelSend = () => {},
}: {
  files: PendingFile[] | null;
  camera?: boolean;
  notReady: ClaudeNotReady | null;
  keepPrivate: boolean;
  onKeepPrivate: (v: boolean) => void;
  onRemove: (id: string) => void;
  onMove: (id: string, by: -1 | 1) => void;
  onClose: () => void;
  onChoose: (combine: boolean) => void;
  /** The camera variant: photograph the next page (the tap opens the camera). */
  onTakeAnother?: () => void;
} & SendProps) {
  const combineRef = useRef<HTMLButtonElement>(null);
  const count = files?.length ?? 0;
  const footer = sending ? (
    <SendingBar sending={sending} onCancel={onCancelSend} />
  ) : camera ? (
    <>
      <Button icon={Camera} onClick={onTakeAnother}>
        Take another page
      </Button>
      {count >= 2 ? (
        <Button variant="ghost" icon={Files} onClick={() => onChoose(false)}>
          Separate letters
        </Button>
      ) : null}
      <Button ref={combineRef} variant="primary" icon={keepPrivate ? Lock : FileStack} onClick={() => onChoose(true)}>
        {keepPrivate ? "Store privately" : notReady ? "Store now, read later" : "Add letter"}
      </Button>
    </>
  ) : (
    <>
      <Button icon={Files} onClick={() => onChoose(false)}>
        Separate letters
      </Button>
      <Button ref={combineRef} variant="primary" icon={FileStack} onClick={() => onChoose(true)}>
        Combine into one letter
      </Button>
    </>
  );
  return (
    <Dialog
      open={Boolean(files)}
      onClose={onClose}
      hideClose={Boolean(sending)}
      dismissible={!sending}
      title={camera ? "Pages of one letter" : "Are these pages of one letter?"}
      description={
        camera
          ? cameraDescription(count, keepPrivate, notReady)
          : keepPrivate
            ? `You added ${count} photos. Combined, they are kept as one letter with its pages in this order — on ${theComputer(phone)} only.`
            : notReady
              ? `You added ${count} photos. ${NOT_READY[notReady]}: Ordnung stores them now, and pages of the same letter are read together as soon as Claude is connected.`
              : `You added ${count} photos. Pages of the same letter are read together, so dates and amounts are found across pages.`
      }
      initialFocus={combineRef}
      footer={footer}
    >
      <SendNoteLine note={note} />
      {files ? <PageThumbs files={files} onMove={onMove} onRemove={onRemove} /> : null}
      {/* the camera's pages are one letter: "it" */}
      <KeepPrivateSwitch checked={keepPrivate} onCheckedChange={onKeepPrivate} several={!camera} phone={phone} disabled={Boolean(sending)} />
    </Dialog>
  );
}

/** The online demo can't keep files: say so when "Add letters" is pressed or files are dropped, before any picker. */
function DemoNotice({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <Dialog
      open={open}
      onClose={onClose}
      size="sm"
      title="Install Ordnung to add your own letters"
      description="This online demo runs in your browser with Sam Rivera's sample letters — it can't read or keep your files. Try the letters waiting in New mail: Ordnung reads them while you watch."
      footer={
        <>
          <Button onClick={onClose}>Not now</Button>
          <Link to="/inbox" onClick={onClose} className={buttonVariants({ variant: "primary" })}>
            <Inbox aria-hidden />
            Open New mail
          </Link>
        </>
      }
    />
  );
}
