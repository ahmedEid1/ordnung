/**
 * Unsaved edits in Settings: every form's SaveBar reports whether it is dirty — and how to save it —
 * so the Settings page can ask before switching sections (or leaving): keep editing, throw the
 * edits away, or save them and go on.
 */
import { createContext, useContext, useEffect, useId, useRef } from "react";

/** Saves a form's edits; resolves `true` when they were saved (`false`: invalid or the save failed). */
export type SaveForm = () => Promise<boolean>;

/** Receives "this form has unsaved edits" reports: its save, or `null` once nothing is unsaved. */
type DirtyReporter = (key: string, save: SaveForm | null) => void;
const DirtyContext = createContext<DirtyReporter | null>(null);

/** Provided by the Settings page: every `SaveBar` below reports whether its form is dirty. */
export const SettingsDirtyProvider = DirtyContext.Provider;

/**
 * Report unsaved edits of a settings form (cleared when it unmounts) with the function that saves
 * them (always the latest one). No-op outside the Settings page.
 */
export function useReportDirty(dirty: boolean, save?: SaveForm): void {
  const report = useContext(DirtyContext);
  const key = useId();
  const latest = useRef(save);
  useEffect(() => {
    latest.current = save;
  });
  useEffect(() => {
    if (!report) return;
    report(key, dirty ? () => latest.current?.() ?? Promise.resolve(false) : null);
    return () => report(key, null);
  }, [report, key, dirty]);
}
