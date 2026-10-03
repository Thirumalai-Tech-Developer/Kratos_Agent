import json
from contextlib import closing
from pathlib import Path
import sqlite3

import pytest

from kratos_agent.data_transfer import import_omniroute_data


def _create_store(directory: Path, value: str) -> None:
    directory.mkdir(parents=True)
    with closing(sqlite3.connect(directory / "storage.sqlite")) as db:
        db.execute("CREATE TABLE settings (value TEXT)")
        db.execute("INSERT INTO settings VALUES (?)", (value,))
        db.commit()
    (directory / "oauth").mkdir()
    (directory / "oauth" / "session.json").write_text('{"state":"saved"}', encoding="utf-8")


def test_import_preserves_source_and_rollback(tmp_path: Path) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "studio" / "gateway"
    _create_store(source, "original")
    _create_store(destination, "previous")
    source_env = tmp_path / ".env"
    source_env.write_text("STORAGE_ENCRYPTION_KEY=source-secret\nJWT_SECRET=source-jwt\n", encoding="utf-8")

    result = import_omniroute_data(source, destination, source_env)
    rollback = Path(result["rollback"])
    with closing(sqlite3.connect(destination / "storage.sqlite")) as db:
        assert db.execute("SELECT value FROM settings").fetchone() == ("original",)
    with closing(sqlite3.connect(rollback / "storage.sqlite")) as db:
        assert db.execute("SELECT value FROM settings").fetchone() == ("previous",)
    assert (destination / "oauth" / "session.json").is_file()
    assert json.loads((destination / "studio-secrets.json").read_text())["STORAGE_ENCRYPTION_KEY"] == "source-secret"
    with closing(sqlite3.connect(source / "storage.sqlite")) as db:
        assert db.execute("SELECT value FROM settings").fetchone() == ("original",)


def test_import_rejects_nested_target_and_missing_key(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _create_store(source, "original")
    source_env = tmp_path / ".env"
    source_env.write_text("JWT_SECRET=unused\n", encoding="utf-8")
    with pytest.raises(ValueError, match="separate"):
        import_omniroute_data(source, source / "nested", source_env)
    with pytest.raises(ValueError, match="STORAGE_ENCRYPTION_KEY"):
        import_omniroute_data(source, tmp_path / "other", source_env)


def test_import_includes_committed_wal_frames(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _create_store(source, "base")
    source_env = tmp_path / ".env"
    source_env.write_text("STORAGE_ENCRYPTION_KEY=key\n", encoding="utf-8")
    with closing(sqlite3.connect(source / "storage.sqlite")) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("INSERT INTO settings VALUES ('in-wal')")
        writer.commit()
        result = import_omniroute_data(source, tmp_path / "target", source_env)
        with closing(sqlite3.connect(Path(result["imported_to"]) / "storage.sqlite")) as restored:
            assert restored.execute("SELECT value FROM settings ORDER BY rowid").fetchall() == [
                ("base",), ("in-wal",)
            ]
