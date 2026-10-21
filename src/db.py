"""SQLite connection, schema setup, and inserts."""

import sqlite3
from pathlib import Path

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def connect(db_path):
    """Open the database, creating its folder if needed.

    Parameters
    ----------
    db_path : pathlib.Path
        Database file location.

    Returns
    -------
    sqlite3.Connection
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(db_path)


def create_schema(conn):
    """Create every table. Safe to run on an existing database.

    Parameters
    ----------
    conn : sqlite3.Connection
    """
    conn.executescript(SCHEMA_PATH.read_text())


def upsert_rows(conn, table, rows):
    """Insert rows, replacing any with the same primary key.

    Because snapshot tables include `pulled_at` in their key, rerunning a pull
    on the same day overwrites that day's rows, while a new day adds new ones.

    Parameters
    ----------
    conn : sqlite3.Connection
    table : str
        Name of a table in the schema.
    rows : list of dict
        Rows to write. Every dict must have the same keys.

    Returns
    -------
    int
        Number of rows written.

    Raises
    ------
    ValueError
        If `table` is not in the schema.
    """
    # Table names can't be passed as SQL parameters, so check the name against
    # the real tables before putting it in the query string
    known = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if table not in known:
        raise ValueError(f"Unknown table: {table}")
    if not rows:
        return 0

    columns = list(rows[0])
    placeholders = ", ".join(f":{c}" for c in columns)
    conn.executemany(
        f"INSERT OR REPLACE INTO {table} ({', '.join(columns)}) VALUES ({placeholders})", rows
    )
    conn.commit()
    return len(rows)
