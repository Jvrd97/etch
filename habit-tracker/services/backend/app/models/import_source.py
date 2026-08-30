# [review:need-review] PHASE-03/89
# summary: `import_source` — every file the importer read, kept whole with its sha256, so a mark that found no line is still recoverable and a second run can tell "unchanged" from "not imported yet"
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.database import Base

# What kind of file a row keeps. The importer of `#89` reads three; later
# tickets (`#90` summaries, `#94` weeks, `#95` feedback) add their own rather
# than widening the meaning of these.
KIND_PLAN_MD = "plan_md"
KIND_PLAN_HTML = "plan_html"
KIND_PLAN_REPORT_MD = "plan_report_md"
IMPORT_KINDS: tuple[str, ...] = (KIND_PLAN_MD, KIND_PLAN_HTML, KIND_PLAN_REPORT_MD)


class ImportSource(Base):
    """
    One file of `personal-os` as the importer found it.

    **The whole text, not a digest.** The parse is lossy by construction — a
    `<details>` block, a mark whose line moved, a link nobody rewrote. Keeping
    the file itself means every one of those is recoverable from the database
    rather than from a repository that ADR-0014 freezes into an archive. This is
    what makes the import safe to run against files nothing is allowed to
    modify.

    **`path` is the key, and it is relative.** One row per file, updated in
    place: the question this table answers is "what did the importer last read
    here", not "how many times was it read". Relative to the root passed on the
    command line, so the same repository imported from a different checkout is
    the same row rather than a second copy.

    **`sha256` is what makes a second run cheap and honest.** A file whose
    digest has not changed, on a day that already has its plan, is skipped
    whole: no delete, no re-insert, no new uuids, no touched timestamps. That is
    what "the second run changes nothing" means in `#89` — not that the writes
    happen to produce equal values.
    """

    __tablename__ = "import_source"
    # Named here as they are named in the migration: a constraint the database
    # calls one thing and the model another is a difference nobody sees until an
    # error message names the wrong one.
    __table_args__ = (
        UniqueConstraint("path", name="uq_import_source_path"),
        Index("ix_import_source_kind", "kind"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    kind: Mapped[str] = mapped_column(String(length=32), nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(length=64), nullable=False)

    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    raw: Mapped[str] = mapped_column(Text, nullable=False)
