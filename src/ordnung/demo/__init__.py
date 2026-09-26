"""Demo mode: the fictional sample life of Sam Rivera, replayed model answers and a guided tour (SPEC §16).

* :mod:`ordnung.demo.loader` builds, snapshots and checks the demo database.
* :mod:`ordnung.demo.tour` runs the demo: the *New mail* tray and the tour state.

This module describes the sample life itself: ``samples/manifest.json`` lists every SPECIMEN
document (file or photos, SHA-256, received date, whether it waits in the tray) plus the persona
and the simulated "today". Sample files are checked against their recorded hashes before use, so
only the published sample life can ever reach the demo — or a recorded fixture.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from ordnung.config import samples_dir
from ordnung.ids import doc_id_for_sha

MANIFEST_NAME = "manifest.json"


class DemoError(RuntimeError):
    """The demo cannot be built, opened or recorded (the message is written for people)."""


class Persona(BaseModel):
    """The demo person (becomes the profile of the demo database)."""

    name: str
    address: str = ""
    email: str = ""
    phone: str = ""
    language: str = "en"
    country: str = "DE"
    region: str = "NW"
    timezone: str = "Europe/Berlin"
    is_student_visa: bool = False


@dataclass(frozen=True)
class SampleUpload:
    """What the demo uploads for one sample: the file, its name and more photos to combine."""

    data: bytes
    filename: str
    combine_with: list[bytes]


class SampleDocument(BaseModel):
    """One document of the sample life (a file, or several photos combined into one letter)."""

    order: int
    slug: str
    title: str
    subject: str = ""
    language: str = "de"
    file: str | None = None
    files: list[str] = Field(default_factory=list)
    sha256: str | list[str]
    combine: bool = False
    mime: str
    pages: int = 1
    photo: bool = False
    tray: bool = False
    received_date: str | None = None
    truth: dict[str, Any] = Field(default_factory=dict)

    @property
    def filenames(self) -> list[str]:
        """The sample's file names in upload order."""
        return list(self.files) if self.files else [self.file] if self.file else []

    @property
    def hashes(self) -> list[str]:
        """The recorded SHA-256 of each file, in the order of :attr:`filenames`."""
        return [self.sha256] if isinstance(self.sha256, str) else list(self.sha256)

    @property
    def sender(self) -> str:
        """Who the letter is from (ground truth of the sample)."""
        return str(self.truth.get("sender_name") or "")

    @property
    def kind_hint(self) -> str:
        """The document kind the sample is (ground truth of the sample)."""
        return str(self.truth.get("kind") or "other")

    def read_files(self, root: Path) -> list[bytes]:
        """The sample's files, each checked against its recorded hash."""
        names, hashes = self.filenames, self.hashes
        if not names or len(names) != len(hashes):
            raise DemoError(
                f"The sample “{self.slug}” lists {len(names)} file(s) but {len(hashes)} hash(es)."
            )
        contents = []
        for name, expected in zip(names, hashes, strict=True):
            path = root / name
            try:
                data = path.read_bytes()
            except OSError as exc:
                raise DemoError(f"The sample file {path} is missing.") from exc
            if hashlib.sha256(data).hexdigest() != expected:
                raise DemoError(f"The sample file {name} does not match the manifest (it was changed).")
            contents.append(data)
        return contents

    def upload(self, root: Path) -> SampleUpload:
        """The upload of this sample (several photos are combined into one PDF by the pipeline)."""
        first, *rest = self.read_files(root)
        return SampleUpload(data=first, filename=self.filenames[0], combine_with=rest)

    def document_id(self, root: Path) -> str:
        """The id the pipeline gives this sample: from the stored bytes, as ``add_file`` stores them."""
        from ordnung.ingest.intake import combine_images_to_pdf, normalise_upload

        contents = self.read_files(root)
        name = self.filenames[0]
        if len(contents) > 1:
            data = combine_images_to_pdf(contents)
            name = f"{Path(name).stem or 'photos'}.pdf"
        else:
            data = contents[0]
        stored, _, _ = normalise_upload(data, name)
        return doc_id_for_sha(hashlib.sha256(stored).hexdigest())


class Manifest(BaseModel):
    """``samples/manifest.json``: the persona, the simulated today and the documents."""

    schema_version: int = 1
    persona: Persona
    simulated_today: str
    documents: list[SampleDocument]

    @property
    def library(self) -> list[SampleDocument]:
        """Documents already read when the demo opens, in manifest order."""
        return sorted((doc for doc in self.documents if not doc.tray), key=lambda doc: doc.order)

    @property
    def tray(self) -> list[SampleDocument]:
        """The *New mail* letters, read live during the demo, in manifest order."""
        return sorted((doc for doc in self.documents if doc.tray), key=lambda doc: doc.order)

    def document(self, slug: str) -> SampleDocument | None:
        """The sample with this slug."""
        return next((doc for doc in self.documents if doc.slug == slug), None)

    def document_ids(self, root: Path) -> dict[str, str]:
        """Slug → document id of every sample (the only documents a recording may contain)."""
        return {doc.slug: doc.document_id(root) for doc in self.documents}


def samples_root(samples: str | Path | None = None) -> Path:
    """The folder holding the manifest and the sample files (default: the packaged sample life)."""
    return Path(samples) if samples is not None else samples_dir()


def load_manifest(samples: str | Path | None = None) -> Manifest:
    """Read and validate the sample-life manifest."""
    path = samples_root(samples) / MANIFEST_NAME
    try:
        return Manifest.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except OSError as exc:
        raise DemoError(f"The sample life is missing ({path}).") from exc
    except (ValueError, ValidationError) as exc:
        raise DemoError(f"The sample-life manifest {path} is invalid: {exc}") from exc
