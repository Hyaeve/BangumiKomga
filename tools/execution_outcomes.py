"""Per-entry task outcomes, separate from noisy operational log messages."""
import os
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path


def ensure_table(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS execution_outcomes (
        execution_id TEXT NOT NULL, server_id TEXT NOT NULL, item_key TEXT NOT NULL,
        failed INTEGER NOT NULL, recorded_at TEXT NOT NULL,
        PRIMARY KEY(execution_id,server_id,item_key))""")


def record_outcome(kind, item_id, failed=False, conn=None):
    execution = os.environ.get("BANGUMI_EXECUTION_ID")
    if not execution:
        return
    server = os.environ.get("BANGUMI_EXECUTION_SERVER", "")

    def write(connection):
        ensure_table(connection)
        # One failed field makes the entry failed; a later successful field
        # must not erase that failure or count the entry a second time.
        connection.execute("""INSERT INTO execution_outcomes VALUES (?,?,?,?,?)
            ON CONFLICT(execution_id,server_id,item_key) DO UPDATE SET
            failed=MAX(failed,excluded.failed),recorded_at=excluded.recorded_at""",
                           (execution, server, f"{kind}:{item_id}", int(failed),
                            datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        connection.commit()
    if conn is not None:
        write(conn)
    else:
        with closing(sqlite3.connect(Path(__file__).resolve().parents[1] / "recordsRefreshed.db", timeout=30)) as connection:
            write(connection)
