"""Build the sample life: render every document, number them chronologically, write ``manifest.json``."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tempfile
import zlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import fontTools
import fpdf
import PIL
import pypdfium2.version

from ordnung.models import Profile
from samplelife import docs_contracts, docs_home, docs_misc, docs_official, docs_work_study
from samplelife import persona as sam
from samplelife.letter import SPECIMEN
from samplelife.truth import Rendered, Sample

REPO = Path(__file__).resolve().parents[2]
DEFAULT_OUT = REPO / "src" / "ordnung" / "demo" / "samples"
GENERATED = re.compile(r"^\d\d_[a-z0-9_]+\.(pdf|jpg)$")
MIME = {"pdf": "application/pdf", "jpg": "image/jpeg"}

BUILDERS: tuple[Callable[[], Sample], ...] = (
    docs_contracts.mobilfunk,
    docs_contracts.fitness,
    docs_home.mietvertrag,
    docs_home.stadtwerke_vertrag,
    docs_contracts.deutschlandticket,
    docs_contracts.haftpflicht,
    docs_work_study.arbeitsvertrag,
    docs_misc.rechnung,
    docs_work_study.gehaltsabrechnung,
    docs_work_study.rueckmeldung,
    docs_work_study.immatrikulationsbescheinigung,
    docs_work_study.stipendium,
    docs_home.nebenkostenabrechnung,
    docs_official.bkk_beitragsbescheid,
    docs_misc.mahnung,
    docs_official.rundfunkbeitrag,
    docs_official.auslaenderbehoerde,
    docs_misc.reisepass,
    docs_contracts.bank_preisaenderung,
    docs_official.bibliothek_mahnung,
    docs_official.knoellchen,
    docs_misc.zahnarzt_termin,
    docs_official.steuerbescheid,
    docs_home.stadtwerke_preisanpassung,
    docs_misc.scam,
)


@dataclass(frozen=True)
class Planned:
    """A sample with its position in the chronological order and its file names."""

    order: int
    sample: Sample

    def names(self, rendered: Rendered) -> list[str]:
        """File names ``NN_slug.ext`` (``NN_slug_pK.jpg`` for multi-photo documents)."""
        stem = f"{self.order:02d}_{self.sample.slug}"
        if len(rendered.files) == 1:
            return [f"{stem}.{rendered.extension}"]
        return [f"{stem}_p{index}.{rendered.extension}" for index in range(1, len(rendered.files) + 1)]


def plan() -> list[Planned]:
    """All samples, ordered chronologically (by arrival); the new-mail tray comes last."""
    samples = [build() for build in BUILDERS]
    slugs = [s.slug for s in samples]
    if len(set(slugs)) != len(slugs):
        raise ValueError("duplicate slugs")
    position = {slug: index for index, slug in enumerate(slugs)}

    def key(sample: Sample) -> tuple[bool, str, str, int]:
        doc_date = sample.sort_date or sample.truth.document_date or sample.received_date
        first = doc_date if sample.tray else sample.received_date
        return (sample.tray, first, doc_date, position[sample.slug])

    ordered = sorted(samples, key=key)
    known = set(slugs)
    for sample in ordered:
        for slug, _relation in sample.truth.related:
            if slug not in known:
                raise ValueError(f"{sample.slug}: unknown related slug {slug!r}")
    return [Planned(index, sample) for index, sample in enumerate(ordered, start=1)]


def environment() -> dict[str, str]:
    """Library versions that influence the output bytes (committed files match this environment)."""
    return {
        "fpdf2": fpdf.__version__,
        "fonttools": fontTools.version,
        "pillow": PIL.__version__,
        "pypdfium2": str(pypdfium2.version.PYPDFIUM_INFO),
        "pdfium": str(pypdfium2.version.PDFIUM_INFO),
        "zlib": zlib.ZLIB_RUNTIME_VERSION,
    }


def _persona() -> dict[str, Any]:
    profile = Profile(**sam.PROFILE)
    keys = (
        "name",
        "address",
        "email",
        "phone",
        "language",
        "country",
        "region",
        "timezone",
        "is_student_visa",
    )
    data = profile.model_dump(include=set(keys))
    return {key: data[key] for key in keys}


def _entry(
    item: Planned, rendered: Rendered, names: list[str], order_of: Callable[[str], int]
) -> dict[str, Any]:
    sample = item.sample
    hashes = [hashlib.sha256(data).hexdigest() for data in rendered.files]
    entry: dict[str, Any] = {
        "order": item.order,
        "slug": sample.slug,
        "title": sample.title,
        "subject": sample.subject_hint,
        "language": sample.language,
    }
    if len(names) == 1:
        entry.update(file=names[0], sha256=hashes[0])
    else:
        entry.update(files=names, sha256=hashes, combine=True)
    entry.update(
        mime=MIME[rendered.extension],
        pages=rendered.pages,
        photo=sample.photo,
        tray=sample.tray,
        received_date=sample.received_date,
    )
    if sample.captured_date:
        entry["captured_date"] = sample.captured_date
    entry["truth"] = sample.truth.to_json(order_of)
    return entry


def build(
    out: Path, *, only: Sequence[str] = (), sources: Path | None = None, log: bool = True
) -> list[Path]:
    """Render the samples into ``out``; with ``only`` render just those slugs and skip the manifest."""
    planned = plan()
    order_of = {p.sample.slug: p.order for p in planned}.__getitem__
    selected = [p for p in planned if not only or p.sample.slug in only]
    if only and len(selected) != len(set(only)):
        raise SystemExit(f"unknown slug in --only: {sorted(set(only) - {p.sample.slug for p in planned})}")
    out.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    documents: list[dict[str, Any]] = []
    for item in selected:
        rendered = item.sample.render()
        names = item.names(rendered)
        for name, data in zip(names, rendered.files, strict=True):
            (out / name).write_bytes(data)
            written.append(out / name)
        if sources is not None and rendered.source_pdf is not None:
            sources.mkdir(parents=True, exist_ok=True)
            (sources / f"{item.order:02d}_{item.sample.slug}.source.pdf").write_bytes(rendered.source_pdf)
        documents.append(_entry(item, rendered, names, order_of))
        if log:
            size = sum(len(data) for data in rendered.files) // 1024
            print(f"  {', '.join(names):<60} {rendered.pages} p. {size:>5} KiB")
    if only:
        return written
    manifest = {
        "schema_version": 1,
        "notice": f"{SPECIMEN}. All people, organisations, addresses, phone numbers, accounts and identifiers are "
        "fictional; IBANs carry valid checksums but belong to no one.",
        "generator": {"script": "scripts/make_sample_life.py", "environment": environment()},
        "persona": _persona(),
        "simulated_today": sam.SIMULATED_TODAY,
        "documents": documents,
    }
    path = out / "manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    written.append(path)
    keep = {p.name for p in written}
    for stale in sorted(out.iterdir()):
        if GENERATED.match(stale.name) and stale.name not in keep:
            stale.unlink()
    return written


def check(out: Path) -> int:
    """Regenerate into a temporary directory and compare byte by byte with ``out``."""
    with tempfile.TemporaryDirectory() as tmp:
        fresh = build(Path(tmp), log=False)
        mismatches = [
            p.name
            for p in fresh
            if not (out / p.name).is_file() or (out / p.name).read_bytes() != p.read_bytes()
        ]
    if mismatches:
        print("samples are out of date: " + ", ".join(mismatches))
        return 1
    print(f"samples are up to date ({len(fresh)} files)")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Command-line entry point (see ``scripts/make_sample_life.py --help``)."""
    parser = argparse.ArgumentParser(
        description="Generate Sam Rivera's fictional sample life (deterministic)."
    )
    parser.add_argument(
        "--out", type=Path, default=DEFAULT_OUT, help="output directory (default: the demo samples)"
    )
    parser.add_argument("--only", default="", help="comma-separated slugs to render (no manifest is written)")
    parser.add_argument(
        "--sources", type=Path, help="also write the source PDFs of photographed documents here"
    )
    parser.add_argument(
        "--check", action="store_true", help="verify that --out is up to date instead of writing"
    )
    args = parser.parse_args(argv)
    if args.check:
        return check(args.out)
    only = [slug for slug in args.only.split(",") if slug]
    files = build(args.out, only=only, sources=args.sources)
    total = sum(p.stat().st_size for p in files) / 1024 / 1024
    print(f"wrote {len(files)} files ({total:.1f} MiB) to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
