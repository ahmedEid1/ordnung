"""Paths and persisted settings.

Data directory resolution: ``--data-dir`` > ``ORDNUNG_HOME`` > platform user data dir.
Layout::

    <data_dir>/
      ordnung.db          SQLite (WAL)
      files/ab/<sha>.pdf  originals (content addressed)
      derived/<doc_id>/   page renders + thumbnail
      drafts/             generated letter PDFs
      inbox/              optional watched folder (default location)
      phone/              phone access's certificates (once it was turned on)

The data directory and its folders are private to the person (``0700`` on POSIX, tightened on every
start); files in it are written ``0600``.
"""

from __future__ import annotations

import contextlib
import os
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_data_dir

PACKAGE_DIR = Path(__file__).resolve().parent
REPO_DIR = PACKAGE_DIR.parent.parent  # only meaningful in a source checkout
PRIVATE_DIR_MODE = 0o700


def private_dir(path: Path) -> Path:
    """Create ``path`` (and missing parents) and make it accessible to its owner only (POSIX)."""
    path.mkdir(mode=PRIVATE_DIR_MODE, parents=True, exist_ok=True)
    if os.name == "posix":
        with contextlib.suppress(OSError):  # not ours to change (e.g. a shared mount): leave it
            path.chmod(PRIVATE_DIR_MODE)
    return path


def default_data_dir() -> Path:
    env = os.environ.get("ORDNUNG_HOME")
    if env:
        return Path(env).expanduser().resolve()
    return Path(user_data_dir("ordnung", appauthor=False)).resolve()


@dataclass(frozen=True)
class Paths:
    data_dir: Path

    @property
    def db(self) -> Path:
        return self.data_dir / "ordnung.db"

    @property
    def files(self) -> Path:
        return self.data_dir / "files"

    @property
    def derived(self) -> Path:
        return self.data_dir / "derived"

    @property
    def drafts(self) -> Path:
        return self.data_dir / "drafts"

    @property
    def inbox(self) -> Path:
        return self.data_dir / "inbox"

    @property
    def phone(self) -> Path:
        """Phone access's certificates (made at its first turn-on, never by :meth:`ensure`; never in a
        backup or the database)."""
        return self.data_dir / "phone"

    def ensure(self) -> Paths:
        """Create the layout; the data directory and its folders are private to the owner."""
        for p in (self.data_dir, self.files, self.derived, self.drafts):
            private_dir(p)
        return self


def resolve_paths(data_dir: str | Path | None = None) -> Paths:
    base = Path(data_dir).expanduser().resolve() if data_dir else default_data_dir()
    return Paths(base).ensure()


def fixtures_dir() -> Path:
    """Recorded LLM responses used by demo mode / CI replay.

    Shipped inside the package (``ordnung/demo/fixtures``) so an installed wheel can run the demo.
    """
    env = os.environ.get("ORDNUNG_FIXTURES")
    if env:
        return Path(env)
    return PACKAGE_DIR / "demo" / "fixtures"


def samples_dir() -> Path:
    """Sample-life documents used by demo mode (shipped inside the package)."""
    env = os.environ.get("ORDNUNG_SAMPLES")
    if env:
        return Path(env)
    return PACKAGE_DIR / "demo" / "samples"


def web_dist_dir() -> Path:
    return PACKAGE_DIR / "web" / "dist"
