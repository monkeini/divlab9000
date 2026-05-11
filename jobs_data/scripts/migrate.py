from __future__ import annotations

import re
import sqlite3
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = PROJECT_DIR / "migrations"
DEFAULT_DB_PATH = PROJECT_DIR / "jobs.sqlite3"
MIGRATION_NAME_PATTERN = re.compile(r"^(\d+)_.*\.sql$")


def connect(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def ensure_migration_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        )
        """
    )
    connection.commit()


def migration_files() -> list[tuple[int, Path]]:
    migrations: list[tuple[int, Path]] = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        match = MIGRATION_NAME_PATTERN.match(path.name)
        if not match:
            raise ValueError(f"Migration filename must start with a numeric version: {path.name}")
        migrations.append((int(match.group(1)), path))
    return migrations


def applied_versions(connection: sqlite3.Connection) -> set[int]:
    rows = connection.execute("SELECT version FROM schema_migrations").fetchall()
    return {int(row[0]) for row in rows}


def apply_migrations(db_path: Path = DEFAULT_DB_PATH) -> None:
    with connect(db_path) as connection:
        ensure_migration_table(connection)
        applied = applied_versions(connection)

        for version, path in migration_files():
            if version in applied:
                continue

            sql = path.read_text(encoding="utf-8")
            with connection:
                connection.executescript(sql)
                connection.execute(
                    "INSERT INTO schema_migrations (version, name) VALUES (?, ?)",
                    (version, path.name),
                )
            print(f"Applied migration {path.name}")


def main() -> None:
    apply_migrations()
    print(f"Database ready: {DEFAULT_DB_PATH}")


if __name__ == "__main__":
    main()
