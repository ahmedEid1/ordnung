import { useState } from "react";
import { ExternalLink, FileText, ImageOff } from "lucide-react";
import { Skeleton } from "@/components/ui/Skeleton";
import { cn } from "@/lib/utils";

/**
 * The letter as it will be printed: an image of every page of the DIN 5008 PDF, page under page
 * (`/api/drafts/{id}/preview.png`; the static demo draws it as an SVG). An image, not the PDF in a
 * frame: phones show no PDF inline, a PDF viewer in a frame is a dark box in some browsers and a
 * focus stop with no ring in others. `version` (the draft's `updated_at`) reloads it after every
 * save — the last picture stays until the new one has loaded, so the page doesn't jump.
 */
export function PdfPreview({
  src,
  pdfHref,
  version,
  stale,
  className,
}: {
  /** the preview image */
  src: string;
  /** the PDF, for "Open" (only a real API path: the static demo has no PDF) */
  pdfHref?: string;
  version: string;
  stale?: boolean;
  className?: string;
}) {
  const [shown, setShown] = useState<string | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const broken = failed === src;
  const loading = shown !== src && !broken;
  return (
    <div className={cn("relative", className)}>
      <div className="relative mx-auto w-full max-w-[560px]" aria-busy={loading || undefined}>
        {shown && !broken ? (
          <img
            src={shown}
            alt="Preview of the printable letter"
            className={cn(
              // the gap between pages is transparent: each page casts its own shadow
              "block h-auto w-full drop-shadow-[0_1px_1px_rgb(0_0_0/0.10)] drop-shadow-[0_10px_18px_rgb(0_0_0/0.10)] transition-opacity duration-300",
              // a white page would glare in the dark theme
              "dark:brightness-[0.93]",
              loading && "opacity-70",
            )}
          />
        ) : (
          <div className="relative aspect-[1/1.414] w-full overflow-hidden rounded-sm bg-white shadow-[var(--shadow-pop)] dark:brightness-[0.93]">
            {broken ? (
              <p className="absolute inset-0 flex flex-col items-center justify-center gap-2 p-6 text-center text-[13px] leading-5 text-neutral-600" role="status">
                <ImageOff className="size-5" aria-hidden />
                The preview couldn't be drawn.
                {pdfHref ? " Open the PDF to see the letter." : null}
              </p>
            ) : (
              <div className="absolute inset-0 flex flex-col gap-3 p-[8%]" aria-hidden>
                <Skeleton className="h-3 w-1/3 bg-black/5" />
                <Skeleton className="mt-6 h-3 w-2/5 bg-black/5" />
                <Skeleton className="h-3 w-1/3 bg-black/5" />
                <Skeleton className="mt-8 h-3 w-3/4 bg-black/5" />
                <Skeleton className="h-3 w-full bg-black/5" />
                <Skeleton className="h-3 w-5/6 bg-black/5" />
              </div>
            )}
          </div>
        )}
        {loading ? (
          // loads the new picture out of sight; it replaces the old one once it is there
          <img key={version} src={src} alt="" hidden onLoad={() => setShown(src)} onError={() => setFailed(src)} />
        ) : null}
        {stale ? (
          <div className="absolute inset-x-0 bottom-0 flex items-center justify-center bg-linear-to-t from-black/55 to-transparent px-4 pb-3 pt-10">
            <span className="rounded-full bg-surface px-3 py-1 text-[12.5px] font-medium text-ink shadow-[var(--shadow-pop)]">Save to update the preview</span>
          </div>
        ) : null}
      </div>
      <p className="mt-4 flex flex-wrap items-center justify-center gap-x-3 gap-y-1 text-center text-[12.5px] leading-5 text-muted">
        {/* the icon flows with the words, so a wrapped caption stays centred */}
        <span className="text-balance">
          <FileText className="mr-1.5 inline size-3.5 -translate-y-px align-middle" aria-hidden />
          DIN 5008 layout, ready for a window envelope
        </span>
        {pdfHref?.startsWith("/") ? (
          <a href={pdfHref} target="_blank" rel="noreferrer" className="inline-flex min-h-6 items-center gap-1 rounded-sm font-medium text-accent hover:underline">
            Open the PDF <ExternalLink className="size-3" aria-hidden />
            <span className="sr-only">(opens in a new tab)</span>
          </a>
        ) : null}
      </p>
    </div>
  );
}
