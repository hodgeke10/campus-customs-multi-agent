"""Database access for the Campus Customs MCP server.

Every read goes through the working copy at `data/campus_customs_new.db`. The
pristine `data/campus_customs.db` is never opened here, so resetting a run is
always just a file copy.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DB_PATH = ROOT / "data" / "campus_customs_new.db"


# Tables the team writes to. They are not in the original shop database, so
# they are created on demand in the working copy only — the master is untouched.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS approvals (
    id INTEGER PRIMARY KEY,
    ticket_id INTEGER,
    kind TEXT NOT NULL,
    ref_id INTEGER,
    payee TEXT NOT NULL,
    amount REAL NOT NULL,
    account TEXT NOT NULL,
    reason TEXT,
    requested_by TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    decided_by TEXT,
    decided_at TEXT,
    payment_id INTEGER,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS purchase_orders (
    id INTEGER PRIMARY KEY,
    ticket_id INTEGER,
    vendor_id INTEGER NOT NULL,
    sku TEXT NOT NULL,
    size TEXT NOT NULL,
    qty INTEGER NOT NULL,
    unit_cost REAL NOT NULL,
    total_cost REAL NOT NULL,
    expected_date TEXT NOT NULL,
    status TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS drafts (
    id INTEGER PRIMARY KEY,
    ticket_id INTEGER,
    audience TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    check_before_sending TEXT,
    author TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TEXT NOT NULL
);
"""


def init_db() -> None:
    """Create the agent-side tables in the working copy if they are missing."""
    with connect() as conn:
        conn.executescript(_SCHEMA)


def execute(sql: str, params: tuple = ()) -> int:
    """Run one INSERT/UPDATE and return the affected row id or count."""
    with connect() as conn:
        cur = conn.execute(sql, params)
        conn.commit()
        return cur.lastrowid if cur.lastrowid else cur.rowcount


def connect() -> sqlite3.Connection:
    """Open the working copy with row access by column name."""
    if not DB_PATH.exists():
        raise RuntimeError(
            f"Working database missing at {DB_PATH}. "
            "Copy data/campus_customs.db to data/campus_customs_new.db first."
        )
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def query(sql: str, params: tuple = ()) -> list[dict]:
    """Run a SELECT and return rows as plain dicts."""
    with connect() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def query_one(sql: str, params: tuple = ()) -> dict | None:
    """Run a SELECT and return the first row, or None."""
    rows = query(sql, params)
    return rows[0] if rows else None


def shop_today() -> str:
    """The shop's 'today' from the desk table — never the real clock."""
    row = query_one("SELECT date_today FROM desk LIMIT 1")
    if row is None:
        raise RuntimeError("desk table has no row; cannot determine shop date.")
    return str(row["date_today"])
