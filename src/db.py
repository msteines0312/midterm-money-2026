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
    _move_old_outside_spending(conn)
    _drop_old_pac_industries(conn)
    conn.executescript(SCHEMA_PATH.read_text())


def _move_old_outside_spending(conn):
    """Rename an old-style `outside_spending` table so its rows are kept.

    The Oct 23 snapshot was built from the by-candidate endpoint, a different
    method with different columns (no `election_type`). The schema script uses
    CREATE TABLE IF NOT EXISTS, so it would leave that table in place. Renaming
    it first lets the new table be created and keeps the old snapshot intact.

    Parameters
    ----------
    conn : sqlite3.Connection
    """
    columns = {row[1] for row in conn.execute("PRAGMA table_info(outside_spending)")}
    # An empty set means the table does not exist yet, so there is nothing to move
    if columns and "election_type" not in columns:
        conn.execute("ALTER TABLE outside_spending RENAME TO outside_spending_by_candidate_endpoint")
        conn.commit()


def _drop_old_pac_industries(conn):
    """Drop a `pac_industries` table that predates the `network` column.

    Like `outside_spending`, this table is made with CREATE TABLE IF NOT
    EXISTS, so an old copy would block the new column. Dropping is safe here
    because the old table was never filled: the labels live in
    data/manual/pac_industries.csv and are reloaded on every pull.

    Parameters
    ----------
    conn : sqlite3.Connection
    """
    columns = {row[1] for row in conn.execute("PRAGMA table_info(pac_industries)")}
    # An empty set means the table does not exist yet, so there is nothing to drop
    if columns and "network" not in columns:
        conn.execute("DROP TABLE pac_industries")
        conn.commit()


def _check_table(conn, table):
    """Raise ValueError unless `table` is a real table in the database.

    Table names can't be passed as SQL parameters, so the name is checked
    against the real tables before it goes in a query string.
    """
    known = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if table not in known:
        raise ValueError(f"Unknown table: {table}")


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
    _check_table(conn, table)
    if not rows:
        return 0

    columns = list(rows[0])
    placeholders = ", ".join(f":{c}" for c in columns)
    conn.executemany(
        f"INSERT OR REPLACE INTO {table} ({', '.join(columns)}) VALUES ({placeholders})", rows
    )
    conn.commit()
    return len(rows)


def replace_rows(conn, table, rows, pulled_at=None):
    """Delete a table's rows, or one snapshot's rows, then insert new ones.

    `upsert_rows` only adds and overwrites, so a row that is no longer in the
    source would stay behind. This is for data where that matters: a committee
    dropped from the label CSV, or a snapshot rebuilt with different keys.
    Both steps run in one transaction, so a failed insert leaves the old rows.

    Parameters
    ----------
    conn : sqlite3.Connection
    table : str
        Name of a table in the schema.
    rows : list of dict
        Rows to write. Every dict must have the same keys.
    pulled_at : str, optional
        Only delete rows with this `pulled_at`, leaving other snapshots alone.
        By default every row in the table is deleted.

    Returns
    -------
    int
        Number of rows written.

    Raises
    ------
    ValueError
        If `table` is not in the schema.
    """
    _check_table(conn, table)
    # `with conn` commits if everything succeeds and rolls back the DELETE if
    # the insert fails. The commit inside upsert_rows ends the same transaction.
    with conn:
        if pulled_at is None:
            conn.execute(f"DELETE FROM {table}")
        else:
            conn.execute(f"DELETE FROM {table} WHERE pulled_at = ?", (pulled_at,))
        return upsert_rows(conn, table, rows)
