"""The source-independent pipeline: listing in -> match -> store -> stats -> alerts.

A source (eBay Browse, a CSV of hand-noted comps, a retailer feed) only has
to yield Listing records. Everything after that is shared.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from . import alerts as A
from . import catalogue, db, stats
from .matcher import Matcher

ROOT = Path(__file__).resolve().parent.parent
CATALOGUE_PATH = ROOT / "data" / "catalogue.json"


@dataclass
class Listing:
    source: str
    source_ref: str          # the source's own id (eBay item id, row number...)
    title: str
    price: float
    shipping: float = 0.0
    currency: str = "USD"
    kind: str = "ask"        # ask | sold | cost
    condition: str = ""
    url: str = ""
    observed_at: str = ""    # ISO UTC; defaults to now
    sku: str = ""            # set when the source already knows the model (own costs)


@dataclass
class IngestReport:
    seen: int = 0
    by_status: dict = field(default_factory=dict)
    alerts: int = 0


class Tracker:
    def __init__(self, db_path, catalogue_path=CATALOGUE_PATH, rules: A.AlertRules | None = None):
        self.models = catalogue.load(catalogue_path)
        self.by_id = {m.id: m for m in self.models}
        self.matcher = Matcher(self.models)
        self.rules = rules or A.AlertRules()
        self.conn = db.connect(db_path)
        db.sync_models(self.conn, self.models)

    # -- ingest -------------------------------------------------------------

    def ingest(self, listings, at: datetime | None = None) -> IngestReport:
        at = at or db.now_utc()
        report = IngestReport()
        for li in listings:
            report.seen += 1
            row = self._classify(li, at)
            report.by_status[row["match_status"]] = report.by_status.get(row["match_status"], 0) + 1
            row["id"] = db.upsert_observation(self.conn, row)
            if row["model_id"] and row["comparable"]:
                m = self.by_id.get(row["model_id"])
                found = A.evaluate(self.conn, row, m.store_price if m else None, self.rules,
                                   db.parse_iso(row["observed_at"]))
                report.alerts += A.save(self.conn, row["id"], row["model_id"], found, at)
        self.conn.commit()
        return report

    def _classify(self, li: Listing, at: datetime) -> dict:
        row = {
            "source": li.source, "source_ref": li.source_ref, "kind": li.kind, "title": li.title,
            "price": float(li.price), "shipping": float(li.shipping or 0), "currency": li.currency.upper(),
            "condition": li.condition, "url": li.url, "observed_at": li.observed_at or db.iso(at),
        }
        if li.sku:
            mid = li.sku.upper()
            known = mid in self.by_id
            row.update(model_id=mid if known else None, match_status="matched" if known else "no_match",
                       confidence=1.0 if known else 0.0, how="given", comparable=known, flags={},
                       reasons=["sku given by source" if known else f"unknown sku {li.sku}"], candidates=[])
            return row
        r = self.matcher.match(li.title)
        cond = (li.condition or "").lower()
        flags = dict(r.flags)
        if cond and cond not in ("new", "new other", "brand new", "1000"):
            flags["used"] = cond                      # source says it is not new
        comparable = r.comparable and "used" not in flags
        row.update(model_id=r.model_id, match_status=r.status, confidence=r.confidence, how=r.how,
                   comparable=comparable, flags=flags, reasons=r.reasons, candidates=r.candidates)
        return row

    # -- read side ----------------------------------------------------------

    def summary(self, model_id: str, kind: str, days: int = 90, at: datetime | None = None):
        since = (at or db.now_utc()) - timedelta(days=days)
        return stats.summarise(db.landed_prices(self.conn, model_id, kind, since))

    def overview(self, days: int = 90, at: datetime | None = None) -> list[dict]:
        out = []
        for m in self.models:
            ask = self.summary(m.id, "ask", days, at)
            sold = self.summary(m.id, "sold", days, at)
            cost = self.summary(m.id, "cost", 365, at)
            ref = sold if sold and sold.n >= self.rules.min_samples else ask
            out.append({
                "id": m.id, "sku": m.sku, "maker": m.maker, "scale": m.scale, "name": m.name,
                "marque": m.marque, "store_price": m.store_price, "url": m.url,
                "ask": ask.as_dict() if ask else None,
                "sold": sold.as_dict() if sold else None,
                "cost": cost.as_dict() if cost else None,
                "store_vs_market": round(m.store_price / ref.median - 1, 3) if ref and m.store_price else None,
                "open_alerts": self.conn.execute(
                    "SELECT COUNT(*) FROM alerts WHERE model_id=? AND dismissed=0", (m.id,)).fetchone()[0],
            })
        return out

    def history(self, model_id: str) -> list[dict]:
        rows = self.conn.execute(
            """SELECT id, source, kind, title, price, shipping, currency, url, first_seen, last_seen,
                      comparable, match_status, confidence, flags
               FROM observations WHERE model_id = ? ORDER BY last_seen""", (model_id,)).fetchall()
        return [dict(r, flags=json.loads(r["flags"] or "{}")) for r in rows]

    def alerts(self, include_dismissed=False) -> list[dict]:
        rows = self.conn.execute(
            f"""SELECT a.*, o.title, o.url, o.source, o.last_seen, m.name, m.maker, m.scale
                FROM alerts a JOIN observations o ON o.id = a.observation_id
                JOIN models m ON m.id = a.model_id
                {'' if include_dismissed else 'WHERE a.dismissed = 0'}
                ORDER BY a.created_at DESC, a.pct_below DESC""").fetchall()
        return [dict(r) for r in rows]

    def review_queue(self, limit=200) -> list[dict]:
        rows = self.conn.execute(
            """SELECT id, source, kind, title, price, shipping, match_status, model_id, confidence,
                      flags, reasons, candidates, last_seen
               FROM observations WHERE match_status IN ('ambiguous', 'rejected', 'no_match')
               ORDER BY last_seen DESC LIMIT ?""", (limit,)).fetchall()
        return [dict(r, flags=json.loads(r["flags"] or "{}"), reasons=json.loads(r["reasons"] or "[]"),
                     candidates=json.loads(r["candidates"] or "[]")) for r in rows]

    def dismiss_alert(self, alert_id: int) -> None:
        self.conn.execute("UPDATE alerts SET dismissed = 1 WHERE id = ?", (alert_id,))
        self.conn.commit()

    def purge(self) -> int:
        return db.purge_expired(self.conn)


def read_csv(path, source="manual") -> list[Listing]:
    """CSV columns: title, price[, shipping, currency, kind, condition, url, observed_at, sku, ref]."""
    out = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for i, rec in enumerate(csv.DictReader(f), 1):
            rec = {k.strip().lower(): (v or "").strip() for k, v in rec.items() if k}
            observed = rec.get("observed_at", "")
            if observed and len(observed) == 10:          # a bare date is fine
                observed += "T12:00:00Z"
            out.append(Listing(
                source=source, source_ref=rec.get("ref") or f"{Path(path).name}:{i}",
                title=rec.get("title", ""), price=float(rec["price"]),
                shipping=float(rec.get("shipping") or 0), currency=rec.get("currency") or "USD",
                kind=rec.get("kind") or "sold", condition=rec.get("condition", ""),
                url=rec.get("url", ""), observed_at=observed, sku=rec.get("sku", ""),
            ))
    return out
