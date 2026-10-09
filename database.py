from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    """Small SQLite helper. Every query is parameterized; the LLM never sees SQL."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.connect() as conn:
            try:
                conn.execute("BEGIN")
                yield conn
                conn.commit()
            except Exception:
                # Transaction rollback: no half-completed reservation/CRM update.
                conn.rollback()
                raise

    def ping(self) -> bool:
        try:
            with self.connect() as conn:
                conn.execute("SELECT 1").fetchone()
            return True
        except sqlite3.Error:
            return False

    def fetch_all(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return [dict(row) for row in conn.execute(sql, params).fetchall()]

    def fetch_one(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(sql, params).fetchone()
            return dict(row) if row else None


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS customers (
    customer_id TEXT PRIMARY KEY,
    full_name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    phone TEXT,
    city TEXT,
    state TEXT
);

CREATE TABLE IF NOT EXISTS reservations (
    reservation_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    hotel_name TEXT NOT NULL,
    check_in TEXT NOT NULL,
    check_out TEXT NOT NULL,
    room_type TEXT NOT NULL,
    status TEXT NOT NULL,
    nightly_rate REAL,
    FOREIGN KEY(customer_id) REFERENCES customers(customer_id)
);

CREATE TABLE IF NOT EXISTS loyalty (
    customer_id TEXT PRIMARY KEY,
    tier TEXT NOT NULL,
    points INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY(customer_id) REFERENCES customers(customer_id)
);

CREATE TABLE IF NOT EXISTS room_inventory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hotel_name TEXT NOT NULL,
    stay_date TEXT NOT NULL,
    room_type TEXT NOT NULL,
    available_rooms INTEGER NOT NULL DEFAULT 0,
    UNIQUE(hotel_name, stay_date, room_type)
);

CREATE TABLE IF NOT EXISTS crm_cases (
    case_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    customer_name TEXT NOT NULL,
    case_type TEXT NOT NULL,
    description TEXT DEFAULT '',
    status TEXT NOT NULL,
    resolution TEXT DEFAULT '',
    FOREIGN KEY(customer_id) REFERENCES customers(customer_id)
);

CREATE TABLE IF NOT EXISTS interactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    channel TEXT NOT NULL,
    summary TEXT NOT NULL,
    FOREIGN KEY(customer_id) REFERENCES customers(customer_id)
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    action TEXT NOT NULL,
    record_type TEXT NOT NULL,
    record_id TEXT NOT NULL,
    before_value TEXT,
    after_value TEXT,
    success INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS pending_actions (
    action_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    action TEXT NOT NULL,
    reservation_id TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    changes_json TEXT NOT NULL,
    room_options_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    resolved_at TEXT,
    FOREIGN KEY(reservation_id) REFERENCES reservations(reservation_id),
    FOREIGN KEY(customer_id) REFERENCES customers(customer_id)
);
"""


def initialize_schema(db: Database) -> None:
    db.path.parent.mkdir(parents=True, exist_ok=True)
    with db.connect() as conn:
        conn.executescript(SCHEMA_SQL)
        conn.commit()


def seed_from_json(db: Database, seed_path: str | Path) -> None:
    """Seed only when the database has no customers. Uses the user's synthetic JSON."""
    seed = json.loads(Path(seed_path).read_text(encoding="utf-8"))
    initialize_schema(db)
    with db.transaction() as conn:
        count = conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
        if count:
            return

        for c in seed["customers"]:
            conn.execute(
                """INSERT INTO customers(customer_id, full_name, email, phone, city, state)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (c["customer_id"], c["full_name"], c["email"], c.get("phone"), c.get("city"), c.get("state")),
            )

        for r in seed["reservations"]:
            conn.execute(
                """INSERT INTO reservations(
                    reservation_id, customer_id, hotel_name, check_in, check_out,
                    room_type, status, nightly_rate
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    r["reservation_id"], r["customer_id"], r["hotel_name"], r["check_in"],
                    r["check_out"], r["room_type"], r["status"], r.get("nightly_rate")
                ),
            )

        for l in seed["loyalty"]:
            conn.execute(
                "INSERT INTO loyalty(customer_id, tier, points) VALUES (?, ?, ?)",
                (l["customer_id"], l["tier"], l["points"]),
            )

        for key, available in seed.get("availability", {}).items():
            hotel, check_in, check_out, room = key.split("|")
            current = date.fromisoformat(check_in)
            end = date.fromisoformat(check_out)
            while current < end:
                conn.execute(
                    """INSERT INTO room_inventory(hotel_name, stay_date, room_type, available_rooms)
                       VALUES (?, ?, ?, ?)""",
                    (hotel, current.isoformat(), room, available),
                )
                current += timedelta(days=1)

        # Initial synthetic case from the provided browser demo.
        conn.execute(
            """INSERT INTO crm_cases(
                case_id, customer_id, customer_name, case_type, description, status, resolution
            ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                "CASE9001", "C1001", "Jessica Turner",
                "Reservation Modification Request",
                "Synthetic case created for the academic demo.",
                "New", "Awaiting action",
            ),
        )

        interactions = [
            ("C1001", utc_now(), "email", "Asked about a reservation date change."),
            ("C1002", utc_now(), "phone", "Confirmed upcoming San Francisco stay."),
        ]
        conn.executemany(
            "INSERT INTO interactions(customer_id, timestamp, channel, summary) VALUES (?, ?, ?, ?)",
            interactions,
        )


class CRMAdapter:
    """Interface point that can later be replaced by a SuiteCRM REST adapter."""

    def search_customer(
        self, *, name: str | None = None, email: str | None = None, customer_id: str | None = None
    ) -> list[dict[str, Any]]:
        raise NotImplementedError

    def get_cases(self, customer_id: str | None = None) -> list[dict[str, Any]]:
        raise NotImplementedError


class SQLiteCRMAdapter(CRMAdapter):
    def __init__(self, db: Database):
        self.db = db

    def search_customer(
        self, *, name: str | None = None, email: str | None = None, customer_id: str | None = None
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if name:
            clauses.append("LOWER(full_name) = LOWER(?)")
            params.append(name)
        if email:
            clauses.append("LOWER(email) = LOWER(?)")
            params.append(email)
        if customer_id:
            clauses.append("customer_id = ?")
            params.append(customer_id)
        if not clauses:
            return []
        sql = "SELECT * FROM customers WHERE " + " AND ".join(clauses) + " ORDER BY customer_id"
        return self.db.fetch_all(sql, tuple(params))

    def get_cases(self, customer_id: str | None = None) -> list[dict[str, Any]]:
        if customer_id:
            return self.db.fetch_all(
                "SELECT * FROM crm_cases WHERE customer_id = ? ORDER BY case_id", (customer_id,)
            )
        return self.db.fetch_all("SELECT * FROM crm_cases ORDER BY case_id")
