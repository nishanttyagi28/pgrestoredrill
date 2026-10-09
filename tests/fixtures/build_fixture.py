"""Build a small pg_dump -Fc file from the sample schema."""

from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql

from pgrestoredrill.db.urls import for_libpq, swap_database
from pgrestoredrill.redact import redact


def _statements() -> tuple[str, ...]:
    path = Path(__file__).resolve().parent / "sample_data.py"
    spec = importlib.util.spec_from_file_location("pgrestoredrill_sample_data", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("sample data is missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    statements = getattr(module, "STATEMENTS", None)
    if not isinstance(statements, tuple):
        raise RuntimeError("sample data is missing")
    return statements


STATEMENTS = _statements()

_FIXTURE_NAME = re.compile(r"^pgrestoredrill_fixture_[0-9a-f]{32}$")
_ROOT = Path(__file__).resolve().parents[2]


def build_dump(admin_url: str, output: Path) -> Path:
    name = f"pgrestoredrill_fixture_{uuid4().hex}"
    if _FIXTURE_NAME.fullmatch(name) is None:
        raise RuntimeError("unexpected fixture database name")
    output.parent.mkdir(parents=True, exist_ok=True)
    url = swap_database(admin_url, name)
    with psycopg.connect(for_libpq(admin_url), autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    try:
        with psycopg.connect(url, autocommit=True) as conn:
            for statement in STATEMENTS:
                conn.execute(statement)
        completed = subprocess.run(
            [
                "pg_dump",
                "--format=custom",
                "--no-owner",
                "--no-acl",
                "--file",
                str(output),
                "--dbname",
                url,
            ],
            check=False,
            capture_output=True,
        )
        if completed.returncode != 0:
            detail = redact(_tail(completed.stderr))
            raise RuntimeError(f"pg_dump failed: {detail}")
    finally:
        with psycopg.connect(for_libpq(admin_url), autocommit=True) as conn:
            conn.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
            )
    return output


def main() -> int:
    url = _target_url()
    output = _ROOT / "tests" / "fixtures" / "dumps" / "sample.dump"
    build_dump(url, output)
    print(f"wrote {output}")
    return 0


def _target_url() -> str:
    from_env = os.environ.get("TARGET_URL")
    if from_env:
        return from_env
    env_path = Path(".env")
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("TARGET_URL="):
                return stripped.split("=", 1)[1].strip().strip('"').strip("'")
    print("TARGET_URL is required", file=sys.stderr)
    raise SystemExit(1)


def _tail(data: bytes | None) -> str:
    if not data:
        return ""
    text = data.decode("utf-8", errors="replace").strip()
    if len(text) <= 2000:
        return text
    return text[-2000:]


if __name__ == "__main__":
    raise SystemExit(main())
