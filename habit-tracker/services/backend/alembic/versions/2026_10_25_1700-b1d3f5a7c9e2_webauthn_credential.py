"""webauthn credential

Revision ID: b1d3f5a7c9e2
Revises: a9c1e3f5b7d0
Create Date: 2026-10-25 17:00:00.000000+00:00
"""

# [review:need-review] 205
# summary: reversible table of passkeys — credential id (unique), public key, signature counter, transports, name, added/last-used

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "b1d3f5a7c9e2"
down_revision: str | None = "a9c1e3f5b7d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "webauthn_credential",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("credential_id", sa.LargeBinary(), nullable=False),
        sa.Column("public_key", sa.LargeBinary(), nullable=False),
        sa.Column("sign_count", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("transports", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "credential_id", name="uq_webauthn_credential_credential_id"
        ),
    )


def downgrade() -> None:
    op.drop_table("webauthn_credential")
