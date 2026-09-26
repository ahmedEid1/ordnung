import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { FileStack, Files, Upload } from "lucide-react";
import { useUploadDocuments } from "@/api/hooks";
import { seedJob } from "@/api/sse";
import { Dialog } from "@/components/ui/Dialog";
import { Button } from "@/components/ui/Button";
import { toast } from "@/components/ui/Toast";
import { Switch } from "@/components/ui/Field";
import { plural } from "@/lib/utils";

/** File types Ordnung accepts (PDFs and phone photos). */
export const ACCEPT = "application/pdf,image/jpeg,image/png,image/webp,image/heic,image/heif,.pdf,.jpg,.jpeg,.png,.webp,.heic,.heif";

const isImage = (f: File) => f.type.startsWith("image/") || /\.(jpe?g|png|webp|heic|heif)$/i.test(f.name);
const isAccepted = (f: File) => isImage(f) || f.type === "application/pdf" || /\.pdf$/i.test(f.name);

interface AddLettersApi {
  /** Open the native file picker. */
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

/** Files waiting for the person's choice; `photos`: several photos, so "one letter?" is asked too. */
interface Pending {
  files: File[];
  photos: boolean;
}

/**
 * Provides the "Add letters" flow: hidden file input, a confirmation with "Keep private — no AI" before
 * anything is sent (docs/privacy.md) — for several photos the "Are these pages of one letter?" dialog —,
 * the upload mutation and seeding the live progress stepper.
 */
export function AddLettersProvider({ children }: { children: ReactNode }) {
  const inputRef = useRef<HTMLInputElement>(null);
  const upload = useUploadDocuments();
  const [pending, setPending] = useState<Pending | null>(null);
  const [keepPrivate, setKeepPrivate] = useState(false);

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
              toast.warn(`${plural(res.errors.length, "file")} couldn't be added`, { description: res.errors.map((e) => `${e.filename}: ${e.detail}`).join(" · ") });
          },
        },
      );
    },
    [upload],
  );

  const addFiles = useCallback(
    (list: File[] | FileList) => {
      const files = Array.from(list);
      const accepted = files.filter(isAccepted);
      const rejected = files.length - accepted.length;
      if (rejected) toast.warn(`${plural(rejected, "file")} skipped`, { description: "Ordnung reads PDFs and photos (JPG, PNG, HEIC)." });
      if (!accepted.length) return;
      const images = accepted.filter(isImage);
      setKeepPrivate(false);
      setPending({ files: accepted, photos: images.length >= 2 && images.length === accepted.length });
    },
    [],
  );

  const openPicker = useCallback(() => inputRef.current?.click(), []);
  const api = useMemo<AddLettersApi>(() => ({ openPicker, addFiles, uploading: upload.isPending }), [openPicker, addFiles, upload.isPending]);

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
        onClose={() => setPending(null)}
        onAdd={() => {
          if (pending) send(pending.files, false, keepPrivate);
          setPending(null);
        }}
      />
      <CombineDialog
        files={pending?.photos ? pending.files : null}
        keepPrivate={keepPrivate}
        onKeepPrivate={setKeepPrivate}
        onClose={() => setPending(null)}
        onChoose={(combine) => {
          if (pending) send(pending.files, combine, keepPrivate);
          setPending(null);
        }}
      />
    </Ctx.Provider>
  );
}

function Thumb({ file, index }: { file: File; index: number }) {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    const u = URL.createObjectURL(file);
    const raf = requestAnimationFrame(() => setUrl(u));
    return () => {
      cancelAnimationFrame(raf);
      URL.revokeObjectURL(u);
    };
  }, [file]);
  return (
    <figure className="relative w-24 shrink-0">
      <div className="aspect-[3/4] overflow-hidden rounded-lg border border-line bg-surface-2 shadow-[var(--shadow-card)]">
        {url ? <img src={url} alt="" className="size-full object-cover" /> : null}
      </div>
      <figcaption className="mt-1 truncate text-center text-[11px] text-muted">Page {index + 1}</figcaption>
    </figure>
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

/** "Add this letter?" — every upload offers "Keep private — no AI" before anything is sent to Claude. */
function AddDialog({
  files,
  keepPrivate,
  onKeepPrivate,
  onClose,
  onAdd,
}: {
  files: File[] | null;
  keepPrivate: boolean;
  onKeepPrivate: (v: boolean) => void;
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
      description={`Claude reads ${several ? "them" : "it"} through your Claude account to find dates, amounts and what to do. Your files stay on this computer.`}
      initialFocus={addRef}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button ref={addRef} variant="primary" icon={Upload} onClick={onAdd}>
            {keepPrivate ? "Store privately" : several ? "Add letters" : "Add letter"}
          </Button>
        </>
      }
    >
      <ul className="space-y-1 text-[13px] text-ink [overflow-wrap:anywhere]">
        {files?.slice(0, 8).map((f, i) => <li key={`${f.name}-${i}`}>{f.name}</li>)}
        {count > 8 ? <li className="text-muted">and {plural(count - 8, "more file")}</li> : null}
      </ul>
      <KeepPrivateSwitch checked={keepPrivate} onCheckedChange={onKeepPrivate} several={several} />
    </Dialog>
  );
}

/** "Are these pages of one letter?" — shown when several photos are added at once. */
function CombineDialog({
  files,
  keepPrivate,
  onKeepPrivate,
  onClose,
  onChoose,
}: {
  files: File[] | null;
  keepPrivate: boolean;
  onKeepPrivate: (v: boolean) => void;
  onClose: () => void;
  onChoose: (combine: boolean) => void;
}) {
  const combineRef = useRef<HTMLButtonElement>(null);
  return (
    <Dialog
      open={Boolean(files)}
      onClose={onClose}
      title="Are these pages of one letter?"
      description={files ? `You added ${files.length} photos. Pages of the same letter are read together, so dates and amounts are found across pages.` : undefined}
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
      <div className="flex gap-3 overflow-x-auto pb-2 scrollbar-thin">
        {files?.slice(0, 8).map((f, i) => <Thumb key={`${f.name}-${i}`} file={f} index={i} />)}
      </div>
      <KeepPrivateSwitch checked={keepPrivate} onCheckedChange={onKeepPrivate} several />
    </Dialog>
  );
}
