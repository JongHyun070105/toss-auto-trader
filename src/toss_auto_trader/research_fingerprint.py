"""Immutable fingerprints for local research inputs."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from typing import Any


def file_fingerprint(path: str | Path) -> dict[str, Any]:
    source = Path(path).resolve()
    stat = source.stat()
    sample_size = 1024 * 1024
    sample_digest = hashlib.sha256()
    with source.open("rb") as handle:
        sample_digest.update(handle.read(sample_size))
        if stat.st_size > sample_size:
            handle.seek(max(0, stat.st_size - sample_size))
            sample_digest.update(handle.read(sample_size))
    full_digest = hashlib.sha256()
    with source.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            full_digest.update(chunk)
    return {
        "path": str(source),
        "sample_sha256": sample_digest.hexdigest(),
        "full_sha256": full_digest.hexdigest(),
        "size_bytes": stat.st_size,
    }


def candle_database_fingerprint(path: str | Path) -> dict[str, Any]:
    result = file_fingerprint(path)
    connection = sqlite3.connect(
        f"file:{Path(path).resolve()}?mode=ro", uri=True
    )
    try:
        row = connection.execute(
            """
            SELECT COUNT(*),COUNT(DISTINCT symbol),
              MIN(substr(timestamp,1,10)),MAX(substr(timestamp,1,10))
            FROM candle_cache WHERE interval='1d'
            """
        ).fetchone()
    finally:
        connection.close()
    result.update(
        {
            "daily_rows": int(row[0]),
            "daily_symbols": int(row[1]),
            "first_date": row[2],
            "latest_date": row[3],
        }
    )
    return result
