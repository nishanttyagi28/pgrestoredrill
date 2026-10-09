"""Load assertion YAML."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from pgrestoredrill.assertions.models import AssertionSpec


def load_assertions(path: Path) -> list[AssertionSpec]:
    if not path.is_file():
        raise FileNotFoundError("assertions file not found")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        raise ValueError("invalid assertions file") from None
    items = _items(raw)
    if not items:
        raise ValueError("invalid assertions file")
    try:
        return [AssertionSpec.model_validate(item) for item in items]
    except ValidationError:
        raise ValueError("invalid assertions file") from None


def _items(raw: object) -> list[object]:
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        nested = raw.get("assertions")
        if isinstance(nested, list):
            return nested
    raise ValueError("invalid assertions file")
