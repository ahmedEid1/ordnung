import { Fragment } from "react";
import { NB_HYPHEN, protectRefs } from "@/lib/glue";

/**
 * A file name shown as a title (a letter nobody read has none yet): it breaks after an underscore,
 * never inside a date or a reference ("Rechnung_" / "2026‑09_FunkNetz.pdf", not "Rechnung_2026-" /
 * "09_FunkNetz.pdf"; "FN-5521904-" / "…" neither) — as the letter's verdict headline does. A run too
 * long for the line still breaks where the element's `overflow-wrap` lets it. Display only: the
 * hyphens are non-breaking ones, copied as "-" (see `plainText`).
 */
export function FileNameText({ name }: { name: string }) {
  // "_" is a word character, so a date or a reference right after one is only found part by part
  const parts = name.split("_").map((part) => protectRefs(part.replace(/\d+(?:-\d+)+/g, (d) => d.replace(/-/g, NB_HYPHEN))));
  return (
    <>
      {parts.map((part, i) => (
        <Fragment key={i}>
          {i ? (
            <>
              _<wbr />
            </>
          ) : null}
          {part}
        </Fragment>
      ))}
    </>
  );
}
