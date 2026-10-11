"""create alerts table

Revision ID: 0002_alerts
Revises: 0001_initial
Create Date: 2026-10-11

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_alerts"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "alerts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("drill_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("run_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("dedup_key", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["drill_id"], ["drills.id"], name="fk_alerts_drill_id"),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], name="fk_alerts_run_id"),
        sa.UniqueConstraint("dedup_key", name="uq_alerts_dedup_key"),
    )
    op.create_index("ix_alerts_drill_id", "alerts", ["drill_id"])
    op.create_index("ix_alerts_run_id", "alerts", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_alerts_run_id", table_name="alerts")
    op.drop_index("ix_alerts_drill_id", table_name="alerts")
    op.drop_table("alerts")
