"""import_source: every file the personal-os importer read, kept whole

Revision ID: f1c3e5a7b9d2
Revises: e0b2d4f6a8c1
Create Date: 2026-08-31 09:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f1c3e5a7b9d2"
down_revision: Union[str, None] = "e0b2d4f6a8c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "import_source",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        # `plan_md`, `plan_html`, `plan_report_md` today; later tickets of the
        # phase add their own. No CHECK: the vocabulary is expected to widen with
        # every file kind that gets imported, and a refused insert during a
        # migration of history teaches nothing.
        sa.Column("kind", sa.String(length=32), nullable=False),
        # Relative to the root given on the command line, and unique: one row per
        # file, updated in place. The table records what was last read from a
        # path, not how many times it was read.
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "imported_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # The file itself. The parse is lossy on purpose (a `<details>` block, a
        # mark whose line moved); this column is what keeps the loss recoverable
        # once personal-os is frozen into an archive.
        sa.Column("raw", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("path", name="uq_import_source_path"),
    )
    op.create_index("ix_import_source_kind", "import_source", ["kind"])


def downgrade() -> None:
    op.drop_index("ix_import_source_kind", table_name="import_source")
    op.drop_table("import_source")
