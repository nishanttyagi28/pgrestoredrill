"""store a human ack on a run

Revision ID: 0003_ack
Revises: 0002_alerts
Create Date: 2026-10-11

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_ack"
down_revision: str | None = "0002_alerts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("acked_by", sa.String(length=200), nullable=True))
    op.add_column("runs", sa.Column("acked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("runs", sa.Column("note", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("runs", "note")
    op.drop_column("runs", "acked_at")
    op.drop_column("runs", "acked_by")
