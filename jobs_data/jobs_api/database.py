from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = PROJECT_DIR / "jobs.sqlite3"


def database_path() -> Path:
    return Path(os.getenv("JOBS_DB_PATH", DEFAULT_DB_PATH)).expanduser().resolve()


def connect() -> sqlite3.Connection:
    connection = sqlite3.connect(database_path(), check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def get_connection() -> Iterator[sqlite3.Connection]:
    connection = connect()
    try:
        yield connection
    finally:
        connection.close()
