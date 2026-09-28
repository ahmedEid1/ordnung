import { useEffect, useRef, useState, type DragEvent, type Ref } from "react";
import { Link, useNavigate } from "react-router";
import { ArrowRight, FileUp, FlaskConical, Inbox, Lock } from "lucide-react";
import { useHealth } from "@/api/hooks";
import { ACCEPTED_SHORT, useAddLetters } from "@/components/shell/AddLetters";
import { Button, buttonVariants } from "@/components/ui/Button";
import { isStaticDemo } from "@/mocks/mode";
import { cn } from "@/lib/utils";
import { CopyCommand } from "./CopyCommand";
import { DEMO_CMD } from "./options";
import { StepHeading } from "./Steps";

const hasFiles = (e: DragEvent) => Array.from(e.dataTransfer?.types ?? []).includes("Files");

/** "Go to Today" — the way into the app; replaces `/welcome` in the history, so Back doesn't restart setup. */
function GoToToday() {
  return (
    <Link to="/" replace className={buttonVariants({ variant: "secondary", className: "w-full sm:w-auto" })}>
      Go to Today <ArrowRight aria-hidden />
    </Link>
  );
}

/**
 * The finish screen: a big drop zone for the first letters (uses the shared "Add letters" flow,
 * so several photos still ask "one letter?"), "Explore the demo instead" and "Go to Today". Every
 * way out replaces `/welcome` in the history. In the online demo, which can't keep files, it
 * points to Sam's letters in New mail instead. Must be rendered inside `<AddLettersProvider>`.
 */
export function StepDone({ firstName, skippedAi, headingRef }: { firstName: string; skippedAi: boolean; headingRef: Ref<HTMLHeadingElement> }) {
  const { addFiles, openPicker, uploading } = useAddLetters();
  const navigate = useNavigate();
  const { data: health } = useHealth();
  const [over, setOver] = useState(false);
  const [showDemo, setShowDemo] = useState(false);
  const depth = useRef(0);
  const wasUploading = useRef(false);
  const online = isStaticDemo();

  // once the upload is accepted, continue in the Inbox where the live progress shows
  useEffect(() => {
    if (uploading) wasUploading.current = true;
    else if (wasUploading.current) {
      wasUploading.current = false;
      navigate("/inbox", { replace: true });
    }
  }, [uploading, navigate]);

  const heading = firstName ? `You're all set, ${firstName}` : "You're all set";

  if (online) {
    return (
      <div className="space-y-6">
        <StepHeading
          headingRef={headingRef}
          eyebrow="Setup complete"
          description="This online demo already holds Sam Rivera's sample life — letters, dates, contracts and drafts. It can't keep files of your own."
        >
          {heading}
        </StepHeading>
        <div className="flex flex-col items-center rounded-2xl border border-line bg-surface-2/40 px-5 py-10 text-center sm:px-6">
          <span className="grid size-16 place-items-center rounded-2xl bg-accent-soft text-accent">
            <Inbox className="size-8" aria-hidden />
          </span>
          <h2 className="display mt-5 text-balance text-[22px] font-semibold text-ink">Sam's letters are waiting</h2>
          <p className="mt-1.5 max-w-sm text-pretty text-[14px] leading-relaxed text-muted">
            Open New mail and let Ordnung read them while you watch. To add your own letters, install Ordnung on your computer.
          </p>
          <Link to="/inbox" replace className={buttonVariants({ variant: "primary", size: "lg", className: "mt-6" })}>
            <Inbox aria-hidden />
            Open New mail
          </Link>
        </div>
        <div className="flex border-t border-line pt-5 sm:justify-end">
          <GoToToday />
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <StepHeading
        headingRef={headingRef}
        eyebrow="Setup complete"
        description={
          skippedAi
            ? "Add your first letters — they are stored and searchable now, and read as soon as Claude is connected."
            : `Add your first letters — ${ACCEPTED_SHORT}. Ordnung reads them and files every date and amount.`
        }
      >
        {heading}
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
          "flex flex-col items-center rounded-2xl border-2 border-dashed px-5 py-10 text-center transition-colors duration-200 sm:px-6 sm:py-12",
          over ? "border-accent bg-accent-soft/70" : "border-line-strong bg-surface-2/40",
        )}
      >
        <span className={cn("grid size-16 place-items-center rounded-2xl transition-colors", over ? "bg-accent text-on-accent" : "bg-accent-soft text-accent")}>
          <FileUp className="size-8" aria-hidden />
        </span>
        {/* phones and tablets can't drop files: there it's about taking photos or choosing PDFs */}
        <h2 className="display mt-5 text-balance text-[22px] font-semibold text-ink">
          {over ? (
            "Drop to add them"
          ) : (
            <>
              <span className="pointer-coarse:hidden">Drop your letters here</span>
              <span className="hidden pointer-coarse:inline">Add your letters</span>
            </>
          )}
        </h2>
        <p className="mt-1.5 max-w-sm text-pretty text-[14px] leading-relaxed text-muted">
          <span className="pointer-coarse:hidden">A whole stack at once is fine — bills, contracts, the letter from the Finanzamt.</span>
          <span className="hidden pointer-coarse:inline">Take a photo of each page or choose PDFs — a whole stack at once is fine.</span>
        </p>
        <Button variant="primary" size="lg" className="mt-6" onClick={openPicker} loading={uploading}>
          Choose files
        </Button>
        <p className="mt-4 text-pretty text-[12.5px] text-muted">
          <Lock className="mr-1.5 inline-block size-3.5 align-[-0.15em]" aria-hidden />
          Your files stay on this computer.
        </p>
      </div>

      <div className="flex flex-col-reverse gap-2 border-t border-line pt-5 sm:flex-row sm:items-center sm:justify-between">
        {/* in the demo, Today already is the demo */}
        {health?.demo ? null : (
          <Button variant="ghost" icon={FlaskConical} className="w-full sm:w-auto" onClick={() => setShowDemo(true)} aria-expanded={showDemo}>
            Explore the demo instead
          </Button>
        )}
        <div className="flex sm:ml-auto">
          <GoToToday />
        </div>
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
