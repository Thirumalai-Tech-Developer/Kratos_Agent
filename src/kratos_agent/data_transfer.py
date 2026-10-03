"""Offline, lossless transfer of an OmniRoute data directory into Kratos Studio."""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import uuid
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from dotenv import dotenv_values

SQLITE_SIDECARS = {"storage.sqlite", "storage.sqlite-wal", "storage.sqlite-shm"}


def _same_or_nested(first: Path, second: Path) -> bool:
    return first == second or first in second.parents


def _copy_snapshot(source: Path, destination: Path) -> None:
    """Copy the store while taking a consistent online SQLite snapshot."""
    if (source / "storage.sqlite").is_symlink():
        raise ValueError("Refusing symlinked SQLite database")
    if not (source / "storage.sqlite").is_file():
        raise ValueError(f"No OmniRoute storage.sqlite in {source}")
    destination.mkdir(parents=True)
    for item in source.iterdir():
        if item.name in SQLITE_SIDECARS:
            continue
        if item.is_symlink():
            raise ValueError(f"Refusing symlink in data directory: {item}")
        target = destination / item.name
        if item.is_dir():
            if any(child.is_symlink() for child in item.rglob("*")):
                raise ValueError(f"Refusing symlink in data directory: {item}")
            shutil.copytree(item, target, symlinks=False)
        elif item.is_file():
            shutil.copy2(item, target)
    # sqlite3.backup includes committed WAL frames without copying transient locks.
    with (
        closing(sqlite3.connect(f"file:{(source / 'storage.sqlite').as_posix()}?mode=ro", uri=True)) as original,
        closing(sqlite3.connect(destination / "storage.sqlite")) as snapshot,
    ):
        original.backup(snapshot)
        result = snapshot.execute("PRAGMA quick_check").fetchone()
        if not result or result[0] != "ok":
            raise RuntimeError("SQLite snapshot failed integrity check")


def import_omniroute_data(source: Path, destination: Path, source_env: Path) -> dict[str, str]:
    """Copy current data, preserve encryption key, and retain rollback snapshot.

    Destination services must be stopped. Source may stay online; SQLite's backup
    API supplies a consistent database view. Import never mutates the source.
    """
    source = source.resolve(strict=True)
    destination = destination.resolve()
    source_env = source_env.resolve(strict=True)
    if _same_or_nested(source, destination) or _same_or_nested(destination, source):
        raise ValueError("Source and destination data directories must be separate")
    if not source.is_dir():
        raise ValueError("Source data directory is not a directory")
    values = dotenv_values(source_env)
    encryption_key = values.get("STORAGE_ENCRYPTION_KEY")
    if not encryption_key:
        raise ValueError("Source environment needs STORAGE_ENCRYPTION_KEY to retain encrypted credentials")
    parent = destination.parent
    parent.mkdir(parents=True, exist_ok=True)
    staging = parent / f".{destination.name}.import-{uuid.uuid4().hex}"
    rollback: Path | None = None
    try:
        _copy_snapshot(source, staging)
        previous_secrets = {}
        if destination.exists():
            prior_path = destination / "studio-secrets.json"
            if prior_path.is_file():
                previous_secrets = json.loads(prior_path.read_text(encoding="utf-8"))
        copied_secrets = staging / "studio-secrets.json"
        if copied_secrets.exists():
            copied_secrets.unlink()
        import secrets
        saved_secrets = {
            "STORAGE_ENCRYPTION_KEY": encryption_key,
            "JWT_SECRET": values.get("JWT_SECRET") or previous_secrets.get("JWT_SECRET") or secrets.token_urlsafe(48),
            "INITIAL_PASSWORD": previous_secrets.get("INITIAL_PASSWORD") or secrets.token_urlsafe(24),
        }
        descriptor = os.open(copied_secrets, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(saved_secrets, output)
        if destination.exists():
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            rollback = parent / f"{destination.name}.rollback-{stamp}-{uuid.uuid4().hex[:8]}"
            destination.rename(rollback)
        try:
            staging.rename(destination)
        except Exception:
            if rollback is not None:
                rollback.rename(destination)
            raise
        return {"imported_to": str(destination), "rollback": str(rollback) if rollback else ""}
    finally:
        if staging.exists():
            shutil.rmtree(staging)
