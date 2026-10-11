"""store a failure suggestion on a run

Revision ID: 0004_notes
Revises: 0003_ack
Create Date: 2026-10-11

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_notes"
down_revision: str | None = "0003_ack"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("failure_category", sa.String(length=32), nullable=True))
    op.add_column("runs", sa.Column("failure_reason", sa.Text(), nullable=True))
    op.add_column("runs", sa.Column("failure_step", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("runs", "failure_step")
    op.drop_column("runs", "failure_reason")
    op.drop_column("runs", "failure_category")
