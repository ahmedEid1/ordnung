import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { AnimatePresence, motion } from "motion/react";
import { FileUp, Lock } from "lucide-react";
import { getOverlayRoot } from "@/components/ui/internal";
import { useAddLetters } from "./AddLetters";

const hasFiles = (e: DragEvent) => Array.from(e.dataTransfer?.types ?? []).includes("Files");

/**
 * Global drop zone: drag files anywhere over the window to add letters. Shows a calm overlay while
 * dragging; several photos trigger the "one letter?" question.
 */
export function DropZone() {
  const { addFiles } = useAddLetters();
  const [active, setActive] = useState(false);
  const depth = useRef(0);

  useEffect(() => {
    const onEnter = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      depth.current += 1;
      setActive(true);
    };
    const onOver = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      if (e.dataTransfer) e.dataTransfer.dropEffect = "copy";
    };
    const onLeave = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      depth.current = Math.max(0, depth.current - 1);
      if (depth.current === 0) setActive(false);
    };
    const onDrop = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      depth.current = 0;
      setActive(false);
      if (e.dataTransfer?.files?.length) addFiles(e.dataTransfer.files);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        depth.current = 0;
        setActive(false);
      }
    };
    window.addEventListener("dragenter", onEnter);
    window.addEventListener("dragover", onOver);
    window.addEventListener("dragleave", onLeave);
    window.addEventListener("drop", onDrop);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("dragenter", onEnter);
      window.removeEventListener("dragover", onOver);
      window.removeEventListener("dragleave", onLeave);
      window.removeEventListener("drop", onDrop);
      window.removeEventListener("keydown", onKey);
    };
  }, [addFiles]);

  return createPortal(
    <AnimatePresence>
      {active ? (
        <motion.div
          className="pointer-events-none fixed inset-0 z-[90] grid place-items-center bg-canvas/80 p-6 backdrop-blur-sm"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.15 }}
          role="status"
          aria-live="polite"
        >
          <motion.div
            initial={{ scale: 0.96, y: 8 }}
            animate={{ scale: 1, y: 0 }}
            transition={{ type: "spring", stiffness: 380, damping: 30 }}
            className="flex w-full max-w-lg flex-col items-center rounded-3xl border-2 border-dashed border-accent/60 bg-surface/90 px-8 py-14 text-center shadow-[var(--shadow-pop)]"
          >
            <span className="grid size-16 place-items-center rounded-2xl bg-accent-soft text-accent">
              <FileUp className="size-8" aria-hidden />
            </span>
            <p className="display mt-5 text-2xl font-semibold text-ink">Drop to add letters</p>
            <p className="mt-2 max-w-sm text-sm leading-relaxed text-muted">
              PDFs or phone photos. Ordnung reads them with your own Claude and files every date and amount.
            </p>
            <p className="mt-4 inline-flex items-center gap-1.5 text-xs text-muted">
              <Lock className="size-3.5" aria-hidden /> Your files stay on this computer.
            </p>
          </motion.div>
        </motion.div>
      ) : null}
    </AnimatePresence>,
    getOverlayRoot(),
  );
}
