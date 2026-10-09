"""create drill run history tables

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-10

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "drills",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("source_kind", sa.String(length=32), nullable=False),
        sa.Column("source_uri", sa.Text(), nullable=False),
        sa.Column("rpo_minutes", sa.Integer(), nullable=False),
        sa.Column("assertions", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("name", name="uq_drills_name"),
    )
    op.create_table(
        "runs",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("drill_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("dump_key", sa.Text(), nullable=True),
        sa.Column("dump_bytes", sa.BigInteger(), nullable=True),
        sa.Column("dump_sha256", sa.String(length=64), nullable=True),
        sa.Column("restore_seconds", sa.Float(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('running', 'passed', 'failed', 'error')",
            name="ck_runs_status",
        ),
        sa.ForeignKeyConstraint(["drill_id"], ["drills.id"], name="fk_runs_drill_id"),
    )
    op.create_index("ix_runs_drill_id", "runs", ["drill_id"])
    op.create_table(
        "assertion_results",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("run_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("observed", sa.Text(), nullable=True),
        sa.Column("expected", sa.Text(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["runs.id"],
            name="fk_assertion_results_run_id",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("run_id", "name", name="uq_assertion_results_run_name"),
    )
    op.create_index("ix_assertion_results_run_id", "assertion_results", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_assertion_results_run_id", table_name="assertion_results")
    op.drop_table("assertion_results")
    op.drop_index("ix_runs_drill_id", table_name="runs")
    op.drop_table("runs")
    op.drop_table("drills")
