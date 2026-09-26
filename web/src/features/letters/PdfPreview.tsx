import { useState } from "react";
import { ExternalLink, FileText } from "lucide-react";
import { Skeleton } from "@/components/ui/Skeleton";
import { cn } from "@/lib/utils";

/**
 * The letter as it will be printed (DIN 5008 PDF from `/api/drafts/{id}/pdf`). `version` (the
 * draft's `updated_at`) reloads the preview after every save.
 */
export function PdfPreview({ src, version, stale, className }: { src: string; version: string; stale?: boolean; className?: string }) {
  const [loaded, setLoaded] = useState<string | null>(null);
  const ready = loaded === version;
  const isImage = src.startsWith("data:image/") || src.startsWith("blob:");
  return (
    <div className={cn("relative", className)}>
      <div className="relative mx-auto aspect-[1/1.414] w-full max-w-[560px] overflow-hidden rounded-lg border border-line bg-white shadow-[var(--shadow-pop)]">
        {!ready ? (
          <div className="absolute inset-0 flex flex-col gap-3 p-[8%]" aria-hidden>
            <Skeleton className="h-3 w-1/3 bg-black/5" />
            <Skeleton className="mt-6 h-3 w-2/5 bg-black/5" />
            <Skeleton className="h-3 w-1/3 bg-black/5" />
            <Skeleton className="mt-8 h-3 w-3/4 bg-black/5" />
            <Skeleton className="h-3 w-full bg-black/5" />
            <Skeleton className="h-3 w-5/6 bg-black/5" />
          </div>
        ) : null}
        {isImage ? (
          // demo mode renders the letter as an image instead of a PDF
          <img
            key={version}
            src={src}
            alt="Preview of the printable letter"
            onLoad={() => setLoaded(version)}
            className={cn("absolute inset-0 size-full object-contain transition-opacity duration-300", ready ? "opacity-100" : "opacity-0")}
          />
        ) : (
          <iframe
            key={version}
            src={`${src}${src.includes("#") ? "" : "#toolbar=0&navpanes=0&view=FitH"}`}
            title="Preview of the printable letter (PDF)"
            onLoad={() => setLoaded(version)}
            className={cn("absolute inset-0 size-full border-0 bg-white transition-opacity duration-300", ready ? "opacity-100" : "opacity-0")}
          />
        )}
        {stale ? (
          <div className="absolute inset-x-0 bottom-0 flex items-center justify-center bg-linear-to-t from-black/55 to-transparent px-4 pb-3 pt-10">
            <span className="rounded-full bg-surface px-3 py-1 text-[12.5px] font-medium text-ink shadow-[var(--shadow-pop)]">Save to update the preview</span>
          </div>
        ) : null}
      </div>
      <p className="mt-3 flex items-center justify-center gap-3 text-[12.5px] text-muted">
        <span className="inline-flex items-center gap-1.5">
          <FileText className="size-3.5" aria-hidden /> DIN 5008 layout, ready for a window envelope
        </span>
        {src.startsWith("/") ? (
          <a href={src} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 font-medium text-accent hover:underline">
            Open <ExternalLink className="size-3" aria-hidden />
            <span className="sr-only">the PDF in a new tab</span>
          </a>
        ) : null}
      </p>
    </div>
  );
}
