import { useEffect, useRef, useState, type DragEvent, type Ref } from "react";
import { Link, useNavigate } from "react-router";
import { ArrowRight, FileUp, FlaskConical, Lock } from "lucide-react";
import { useHealth } from "@/api/hooks";
import { useAddLetters } from "@/components/shell/AddLetters";
import { Button, buttonVariants } from "@/components/ui/Button";
import { cn } from "@/lib/utils";
import { CopyCommand } from "./CopyCommand";
import { DEMO_CMD } from "./options";
import { StepHeading } from "./Steps";

const hasFiles = (e: DragEvent) => Array.from(e.dataTransfer?.types ?? []).includes("Files");

/**
 * The finish screen: a big drop zone for the first letters (uses the shared "Add letters" flow,
 * so several photos still ask "one letter?") and "Explore the demo instead". Must be rendered
 * inside `<AddLettersProvider>`.
 */
export function StepDone({ firstName, skippedAi, headingRef }: { firstName: string; skippedAi: boolean; headingRef: Ref<HTMLHeadingElement> }) {
  const { addFiles, openPicker, uploading } = useAddLetters();
  const navigate = useNavigate();
  const { data: health } = useHealth();
  const [over, setOver] = useState(false);
  const [showDemo, setShowDemo] = useState(false);
  const depth = useRef(0);
  const wasUploading = useRef(false);

  // once the upload is accepted, continue in the Inbox where the live progress shows
  useEffect(() => {
    if (uploading) wasUploading.current = true;
    else if (wasUploading.current) {
      wasUploading.current = false;
      navigate("/inbox");
    }
  }, [uploading, navigate]);

  const exploreDemo = () => {
    if (health?.demo) navigate("/");
    else setShowDemo(true);
  };

  return (
    <div className="space-y-6">
      <StepHeading
        headingRef={headingRef}
        eyebrow="All set"
        description={
          skippedAi
            ? "Add your first letters — they are stored and searchable now, and read as soon as Claude is connected."
            : "Add your first letters — PDFs or phone photos. Ordnung reads them and files every date and amount."
        }
      >
        {firstName ? `You're all set, ${firstName}` : "You're all set"}
      </StepHeading>

      <div
        onDragEnter={(e) => {
          if (!hasFiles(e)) return;
          e.preventDefault();
          depth.current += 1;
          setOver(true);
        }}
        onDragOver={(e) => {
          if (!hasFiles(e)) return;
          e.preventDefault();
          e.dataTransfer.dropEffect = "copy";
        }}
        onDragLeave={(e) => {
          if (!hasFiles(e)) return;
          depth.current = Math.max(0, depth.current - 1);
          if (!depth.current) setOver(false);
        }}
        onDrop={(e) => {
          if (!hasFiles(e)) return;
          e.preventDefault();
          depth.current = 0;
          setOver(false);
          if (e.dataTransfer.files?.length) addFiles(e.dataTransfer.files);
        }}
        className={cn(
          "flex flex-col items-center rounded-2xl border-2 border-dashed px-6 py-12 text-center transition-colors duration-200",
          over ? "border-accent bg-accent-soft/70" : "border-line-strong bg-surface-2/40",
        )}
      >
        <span className={cn("grid size-16 place-items-center rounded-2xl transition-colors", over ? "bg-accent text-on-accent" : "bg-accent-soft text-accent")}>
          <FileUp className="size-8" aria-hidden />
        </span>
        <p className="display mt-5 text-[22px] font-semibold text-ink">{over ? "Drop to add them" : "Drop your letters here"}</p>
        <p className="mt-1.5 max-w-sm text-[14px] leading-relaxed text-muted">A whole stack at once is fine — bills, contracts, the letter from the Finanzamt.</p>
        <Button variant="primary" size="lg" className="mt-6" onClick={openPicker} loading={uploading}>
          Choose files
        </Button>
        <p className="mt-4 inline-flex items-center gap-1.5 text-[12.5px] text-muted">
          <Lock className="size-3.5" aria-hidden /> Your files stay on this computer.
        </p>
      </div>

      <div className="flex flex-col items-center gap-3 border-t border-line pt-5 sm:flex-row sm:justify-between">
        <Button variant="ghost" icon={FlaskConical} onClick={exploreDemo}>
          Explore the demo instead
        </Button>
        <Link to="/" className={buttonVariants({ variant: "link", className: "text-[14px]" })}>
          Go to Today <ArrowRight className="size-4" aria-hidden />
        </Link>
      </div>

      {showDemo ? (
        <div className="rounded-xl border border-line bg-surface-2/50 p-4">
          <p className="text-[14px] font-medium text-ink">Run this in a terminal</p>
          <p className="mt-0.5 text-[13px] leading-relaxed text-muted">
            It opens Sam Rivera's sample life in a separate, throw-away folder. Your own data stays untouched.
          </p>
          <CopyCommand command={DEMO_CMD} label="start the demo" className="mt-3" />
        </div>
      ) : null}
    </div>
  );
}
