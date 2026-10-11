"""Pick the newest custom-format dump in a folder."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pgrestoredrill.errors import DumpNotFound


@dataclass(frozen=True)
class LocalDump:
    path: Path
    size: int
    sha256: str
    modified: datetime
    key: str
    temporary: bool = False


def newest_dump(folder: Path) -> LocalDump:
    if not folder.is_dir():
        raise DumpNotFound("dump folder not found")
    dumps = [path for path in folder.iterdir() if path.is_file() and path.suffix == ".dump"]
    if not dumps:
        raise DumpNotFound("no custom-format dump found")
    chosen = max(dumps, key=lambda path: (path.stat().st_mtime, path.name))
    stat = chosen.stat()
    return LocalDump(
        path=chosen,
        size=stat.st_size,
        sha256=file_sha256(chosen),
        modified=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
        key=str(chosen),
    )


def release_dump(dump: LocalDump) -> None:
    if not dump.temporary:
        return
    try:
        dump.path.unlink(missing_ok=True)
    except OSError:
        return


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()
