"""The fixture dump must not be newer than the target server."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "build_fixture.py"
_SPEC = importlib.util.spec_from_file_location("pgrestoredrill_build_fixture", _PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError("fixture builder is missing")
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


def test_newer_pg_dump_is_refused() -> None:
    with pytest.raises(RuntimeError, match="newer than the target server"):
        _MODULE.require_dump_major(17, 16)


def test_same_major_pg_dump_is_allowed() -> None:
    _MODULE.require_dump_major(16, 16)
