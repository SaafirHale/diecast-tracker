"""SQLite storage: catalogue, observations, alerts.

An observation is one price seen somewhere: an active listing (kind "ask"),
a completed sale ("sold"), or Saafir's own buy cost or a distributor quote
("cost"). Active listings are upserted on (source, source_ref, kind), so a
listing seen on ten polls counts once, at its latest price.

Every source has a retention policy. Some data may only be kept briefly
(eBay's API License Agreement caps displayed listing data at 6 hours old and
requires deleting ended listings), so rows carry an expires_at and
purge_expired() removes them. Retention is set per source in SOURCES.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .catalogue import Model


@dataclass(frozen=True)
class SourcePolicy:
    retention_hours: float | None   # None = keep
    note: str


SOURCES: dict[str, SourcePolicy] = {
    "manual": SourcePolicy(None, "Entered by hand: own sales, buy costs, comps noted from research."),
    "demo": SourcePolicy(None, "Synthetic demo data. Not market prices."),
    "ebay_browse": SourcePolicy(6, "eBay Browse API. API License Agreement: listing data <= 6h old, delete ended listings."),
}
DEFAULT_POLICY = SourcePolicy(None, "Unregistered source.")

SCHEMA = """
CREATE TABLE IF NOT EXISTS models (
    id TEXT PRIMARY KEY, sku TEXT, maker TEXT, scale TEXT, name TEXT, marque TEXT,
    store_price REAL, in_stock INTEGER, url TEXT
);
CREATE TABLE IF NOT EXISTS observations (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL, source_ref TEXT NOT NULL, kind TEXT NOT NULL,
    title TEXT, price REAL NOT NULL, shipping REAL NOT NULL DEFAULT 0, currency TEXT NOT NULL,
    condition TEXT, url TEXT,
    first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, expires_at TEXT,
    model_id TEXT, match_status TEXT, confidence REAL, how TEXT,
    comparable INTEGER NOT NULL DEFAULT 0,
    flags TEXT, reasons TEXT, candidates TEXT,
    UNIQUE (source, source_ref, kind)
);
CREATE INDEX IF NOT EXISTS obs_model ON observations (model_id, kind, comparable, last_seen);
CREATE INDEX IF NOT EXISTS obs_status ON observations (match_status);
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY,
    observation_id INTEGER NOT NULL REFERENCES observations(id) ON DELETE CASCADE,
    model_id TEXT NOT NULL, rule TEXT NOT NULL, landed REAL NOT NULL,
    reference REAL, reference_kind TEXT, n_reference INTEGER, pct_below REAL,
    note TEXT, created_at TEXT NOT NULL, dismissed INTEGER NOT NULL DEFAULT 0,
    UNIQUE (observation_id, rule)
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def connect(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def sync_models(conn: sqlite3.Connection, models: list[Model]) -> None:
    conn.executemany(
        """INSERT INTO models (id, sku, maker, scale, name, marque, store_price, in_stock, url)
           VALUES (?,?,?,?,?,?,?,?,?)
           ON CONFLICT(id) DO UPDATE SET sku=excluded.sku, maker=excluded.maker, scale=excluded.scale,
             name=excluded.name, marque=excluded.marque, store_price=excluded.store_price,
             in_stock=excluded.in_stock, url=excluded.url""",
        [(m.id, m.sku, m.maker, m.scale, m.name, m.marque, m.store_price,
          None if m.in_stock is None else int(m.in_stock), m.url) for m in models],
    )
    conn.commit()


def upsert_observation(conn: sqlite3.Connection, row: dict) -> int:
    """Insert or refresh an observation; returns its id."""
    policy = SOURCES.get(row["source"], DEFAULT_POLICY)
    seen = row["observed_at"]
    expires = iso(parse_iso(seen) + timedelta(hours=policy.retention_hours)) if policy.retention_hours else None
    j = json.dumps
    cur = conn.execute(
        """INSERT INTO observations (source, source_ref, kind, title, price, shipping, currency,
             condition, url, first_seen, last_seen, expires_at, model_id, match_status, confidence,
             how, comparable, flags, reasons, candidates)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(source, source_ref, kind) DO UPDATE SET
             title=excluded.title, price=excluded.price, shipping=excluded.shipping,
             currency=excluded.currency, condition=excluded.condition, url=excluded.url,
             last_seen=MAX(observations.last_seen, excluded.last_seen),
             first_seen=MIN(observations.first_seen, excluded.first_seen),
             expires_at=excluded.expires_at, model_id=excluded.model_id,
             match_status=excluded.match_status, confidence=excluded.confidence, how=excluded.how,
             comparable=excluded.comparable, flags=excluded.flags, reasons=excluded.reasons,
             candidates=excluded.candidates
           RETURNING id""",
        (row["source"], row["source_ref"], row["kind"], row.get("title", ""), row["price"],
         row.get("shipping") or 0.0, row.get("currency", "USD"), row.get("condition", ""),
         row.get("url", ""), seen, seen, expires, row.get("model_id"), row.get("match_status"),
         row.get("confidence"), row.get("how"), int(bool(row.get("comparable"))),
         j(row.get("flags", {})), j(row.get("reasons", [])), j(row.get("candidates", []))),
    )
    return cur.fetchone()[0]


def purge_expired(conn: sqlite3.Connection, at: datetime | None = None) -> int:
    cur = conn.execute("DELETE FROM observations WHERE expires_at IS NOT NULL AND expires_at <= ?",
                       (iso(at or now_utc()),))
    conn.commit()
    return cur.rowcount


def landed_prices(conn: sqlite3.Connection, model_id: str, kind: str, since: datetime,
                  exclude_id: int | None = None, currency: str = "USD") -> list[float]:
    rows = conn.execute(
        """SELECT price + shipping AS landed FROM observations
           WHERE model_id = ? AND kind = ? AND comparable = 1 AND currency = ?
             AND last_seen >= ? AND id IS NOT ?""",
        (model_id, kind, currency, iso(since), exclude_id),
    ).fetchall()
    return [r["landed"] for r in rows]


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute("INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                 (key, value))
    conn.commit()


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None
