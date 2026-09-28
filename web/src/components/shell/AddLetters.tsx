import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router";
import { ChevronLeft, ChevronRight, FileImage, FileStack, FileText, Files, Inbox, Lock, Upload, X } from "lucide-react";
import { useUploadDocuments } from "@/api/hooks";
import { seedJob } from "@/api/sse";
import { isStaticDemo } from "@/mocks/mode";
import { Dialog } from "@/components/ui/Dialog";
import { Button, IconButton, buttonVariants } from "@/components/ui/Button";
import { toast } from "@/components/ui/Toast";
import { Switch } from "@/components/ui/Field";
import { formatFileSize } from "@/lib/format";
import { cn, plural } from "@/lib/utils";

/**
 * File types Ordnung accepts: PDFs, phone photos, saved e-mails (`.eml` — each PDF or photo attached
 * becomes a letter of its own, as from the watched folder) and plain text — what intake reads.
 */
export const ACCEPT =
  "application/pdf,image/jpeg,image/png,image/webp,image/heic,image/heif,message/rfc822,text/plain,.pdf,.jpg,.jpeg,.png,.webp,.heic,.heif,.eml,.txt";
/** The accepted types in words (the "skipped" message names them). */
export const ACCEPTED_TYPES = "PDFs, photos (JPG, PNG, WEBP, HEIC), saved e-mails (.eml) and text files";

const isImage = (f: File) => f.type.startsWith("image/") || /\.(jpe?g|png|webp|heic|heif)$/i.test(f.name);
const isText = (f: File) => f.type === "message/rfc822" || f.type === "text/plain" || /\.(eml|txt)$/i.test(f.name);
const isAccepted = (f: File) => isImage(f) || isText(f) || f.type === "application/pdf" || /\.pdf$/i.test(f.name);

/** How many files (or photo pages) a dialog lists before "Show all". */
const SHOWN = 8;

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

/** Files waiting for the person's choice; `photos`: several photos, so "one letter?" is asked too. */
interface Pending {
  files: PendingFile[];
  photos: boolean;
}

let fileSeq = 0;

/** "a.txt", "b.zip and c.doc", "a, b, c and 2 more" — names of skipped files. */
function nameList(names: string[]): string {
  if (names.length <= 2) return names.join(" and ");
  if (names.length === 3) return `${names[0]}, ${names[1]} and ${names[2]}`;
  return `${names.slice(0, 2).join(", ")} and ${names.length - 2} more`;
}

/**
 * Provides the "Add letters" flow: hidden file input, a confirmation with "Keep private — no AI" before
 * anything is sent (docs/privacy.md) — for several photos the "Are these pages of one letter?" dialog —,
 * the upload mutation and seeding the live progress stepper. In the online demo (no backend to keep
 * files) the picker and a drop explain straight away that adding letters needs the app.
 */
export function AddLettersProvider({ children }: { children: ReactNode }) {
  const inputRef = useRef<HTMLInputElement>(null);
  const upload = useUploadDocuments();
  const [pending, setPending] = useState<Pending | null>(null);
  const [keepPrivate, setKeepPrivate] = useState(false);
  const [demoNotice, setDemoNotice] = useState(false);

  const send = useCallback(
    (files: File[], combine: boolean, priv: boolean) => {
      upload.mutate(
        { files, combine, private: priv },
        {
          onSuccess: (res) => {
            for (const d of res.documents) {
              if (!priv) seedJob({ job_id: res.jobs.find((j) => j.doc_id === d.id)?.id ?? d.id, doc_id: d.id, stage: "intake", progress: 0, status: "running" });
            }
            if (priv) toast.success(`${plural(res.documents.length, "letter")} stored privately`, { description: "Kept on this computer only — not sent to Claude." });
            if (res.duplicates.length) toast({ title: "Already in your inbox", description: `${plural(res.duplicates.length, "file")} had been added before.` });
            if (res.errors.length)
              toast.warn(`${plural(res.errors.length, "file")} couldn't be added`, {
                description: <span className="[overflow-wrap:anywhere]">{res.errors.map((e) => `${e.filename}: ${e.detail}`).join(" · ")}</span>,
              });
          },
        },
      );
    },
    [upload],
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
    setPending({
      files: accepted.map((file) => ({ id: `f${++fileSeq}`, file })),
      photos: accepted.length >= 2 && accepted.every(isImage),
    });
  }, []);

  const removeFile = useCallback((id: string) => {
    setPending((p) => {
      if (!p) return p;
      const files = p.files.filter((f) => f.id !== id);
      if (!files.length) return null;
      // one photo left: nothing to combine any more
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
      return { ...p, files };
    });
  }, []);

  const openPicker = useCallback(() => {
    if (isStaticDemo()) setDemoNotice(true);
    else inputRef.current?.click();
  }, []);
  const api = useMemo<AddLettersApi>(() => ({ openPicker, addFiles, uploading: upload.isPending }), [openPicker, addFiles, upload.isPending]);
  const files = pending?.files.map((f) => f.file) ?? [];

  return (
    <Ctx.Provider value={api}>
      {children}
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
      <AddDialog
        files={pending && !pending.photos ? pending.files : null}
        keepPrivate={keepPrivate}
        onKeepPrivate={setKeepPrivate}
        onRemove={removeFile}
        onClose={() => setPending(null)}
        onAdd={() => {
          if (pending) send(files, false, keepPrivate);
          setPending(null);
        }}
      />
      <CombineDialog
        files={pending?.photos ? pending.files : null}
        keepPrivate={keepPrivate}
        onKeepPrivate={setKeepPrivate}
        onRemove={removeFile}
        onMove={moveFile}
        onClose={() => setPending(null)}
        onChoose={(combine) => {
          if (pending) send(files, combine, keepPrivate);
          setPending(null);
        }}
      />
      <DemoNotice open={demoNotice} onClose={() => setDemoNotice(false)} />
    </Ctx.Provider>
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
          const photo = isImage(file);
          const Icon = photo ? FileImage : FileText;
          return (
            <li key={id} className="flex items-center gap-3 py-2 pl-3 pr-1.5">
              <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-surface-2 text-muted">
                <Icon className="size-4" aria-hidden />
              </span>
              <span className="min-w-0 flex-1">
                <FileName name={file.name} className="text-base font-medium text-ink" />
                <span className="block text-xs text-muted">
                  {photo ? "Photo" : "PDF"} · {formatFileSize(file.size)}
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

function KeepPrivateSwitch({ checked, onCheckedChange, several }: { checked: boolean; onCheckedChange: (v: boolean) => void; several: boolean }) {
  return (
    <Switch
      className="mt-4 rounded-xl border border-line bg-surface-2/50 p-3"
      checked={checked}
      onCheckedChange={onCheckedChange}
      label="Keep private — no AI"
      description={`Store and search ${several ? "them" : "it"} on this computer only; Claude never sees ${several ? "them" : "it"}.`}
    />
  );
}

/** What happens to the files, in the words of the switch's current choice. */
function addDescription(keepPrivate: boolean, several: boolean): string {
  const [it, its] = several ? ["them", "their"] : ["it", "its"];
  return keepPrivate
    ? `Stored on this computer only and searchable by ${its} text. Claude never reads ${it}, so Ordnung won't find ${its} dates — you can add them by hand.`
    : `Claude reads ${it} through your Claude account to find dates, amounts and what to do. Your files stay on this computer.`;
}

/** "Add this letter?" — every upload offers "Keep private — no AI" before anything is sent to Claude. */
function AddDialog({
  files,
  keepPrivate,
  onKeepPrivate,
  onRemove,
  onClose,
  onAdd,
}: {
  files: PendingFile[] | null;
  keepPrivate: boolean;
  onKeepPrivate: (v: boolean) => void;
  onRemove: (id: string) => void;
  onClose: () => void;
  onAdd: () => void;
}) {
  const addRef = useRef<HTMLButtonElement>(null);
  const count = files?.length ?? 0;
  const several = count > 1;
  return (
    <Dialog
      open={Boolean(files)}
      onClose={onClose}
      title={several ? `Add ${count} letters?` : "Add this letter?"}
      description={addDescription(keepPrivate, several)}
      initialFocus={addRef}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button ref={addRef} variant="primary" icon={keepPrivate ? Lock : Upload} onClick={onAdd}>
            {keepPrivate ? "Store privately" : several ? "Add letters" : "Add letter"}
          </Button>
        </>
      }
    >
      {files ? <FileList files={files} onRemove={onRemove} /> : null}
      <KeepPrivateSwitch checked={keepPrivate} onCheckedChange={onKeepPrivate} several={several} />
    </Dialog>
  );
}

/** "Are these pages of one letter?" — shown when several photos are added at once. */
function CombineDialog({
  files,
  keepPrivate,
  onKeepPrivate,
  onRemove,
  onMove,
  onClose,
  onChoose,
}: {
  files: PendingFile[] | null;
  keepPrivate: boolean;
  onKeepPrivate: (v: boolean) => void;
  onRemove: (id: string) => void;
  onMove: (id: string, by: -1 | 1) => void;
  onClose: () => void;
  onChoose: (combine: boolean) => void;
}) {
  const combineRef = useRef<HTMLButtonElement>(null);
  const count = files?.length ?? 0;
  return (
    <Dialog
      open={Boolean(files)}
      onClose={onClose}
      title="Are these pages of one letter?"
      description={
        keepPrivate
          ? `You added ${count} photos. Combined, they are kept as one letter with its pages in this order — on this computer only.`
          : `You added ${count} photos. Pages of the same letter are read together, so dates and amounts are found across pages.`
      }
      initialFocus={combineRef}
      footer={
        <>
          <Button icon={Files} onClick={() => onChoose(false)}>
            Separate letters
          </Button>
          <Button ref={combineRef} variant="primary" icon={FileStack} onClick={() => onChoose(true)}>
            Combine into one letter
          </Button>
        </>
      }
    >
      {files ? <PageThumbs files={files} onMove={onMove} onRemove={onRemove} /> : null}
      <KeepPrivateSwitch checked={keepPrivate} onCheckedChange={onKeepPrivate} several />
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
