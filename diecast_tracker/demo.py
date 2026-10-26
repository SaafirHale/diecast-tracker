"""Seed a demo database with SYNTHETIC prices.

Nothing here is market data. It exists so the dashboard, stats and alerts can
be exercised before a real source is connected. Prices are drawn around the
store's own price with a fixed random seed; titles are generated in the
messy styles the matcher is built for and go through the real matcher, so
the review queue shows genuine matcher decisions on made-up titles.
The dashboard shows a banner whenever the demo flag is set.
"""

from __future__ import annotations

import random
import re
from datetime import timedelta
from pathlib import Path

from . import db
from .tracker import Listing, Tracker

MAKER_SPELLINGS = {
    "Mini GT": ["Mini GT", "MINIGT", "Mini-GT", "mini gt", "TSM Mini GT"],
    "Tarmac Works": ["Tarmac Works", "TARMAC", "Tarmac", "Tarmac Works Global64"],
    "Pop Race": ["Pop Race", "POPRACE", "Pop Race"],
    "Inno Models": ["Inno64", "INNO 64", "Inno Models"],
    "GT Spirit": ["GT Spirit", "GTSpirit"],
    "Otto Mobile": ["Otto Mobile", "OttOmobile", "OTTO"],
    "BM Creations": ["BM Creations", "BMC BM Creations"],
}
SCALE_SPELLINGS = {"1:64": ["1:64", "1/64", "1-64", ""], "1:18": ["1:18", "1/18", "1:18 scale", ""]}
TAILS = ["", "NEW", "SEALED", "🔥", "Free Shipping", "NIB", "Limited", "IN HAND"]
JUNK = [
    ("LOOSE {maker} {short} no box", 0.45),
    ("{maker} lot of 3 - {short} + 2 more", 2.6),
    ("{maker} {short} CHASE", 2.2),
    ("Custom {maker} {short} rubber tires", 1.4),
    ("{maker} {short} box damaged car mint", 0.85),
]


def _short(name: str, rng: random.Random) -> str:
    """What a seller would type: drop quotes, parentheses, and some words."""
    s = re.sub(r'"[^"]*"|\([^)]*\)', " ", name)
    s = re.sub(r"\b(with|and|Special|Edition|Series|Movie|Formula One|Designed by \w+)\b", " ", s)
    words = s.split()
    if len(words) > 7:
        words = words[:7]
    if rng.random() < 0.3:
        words = [w.upper() for w in words]
    return " ".join(words)


def _title(m, rng: random.Random) -> str:
    maker = rng.choice(MAKER_SPELLINGS.get(m.maker, [m.maker]))
    scale = rng.choice(SCALE_SPELLINGS.get(m.scale, [m.scale]))
    sku = m.sku if rng.random() < 0.35 else ""
    parts = [maker, sku, scale, _short(m.name, rng), rng.choice(TAILS)]
    return re.sub(r"\s+", " ", " ".join(p for p in parts if p)).strip()


def seed(db_path: str | Path, n_models: int = 32, seed_value: int = 64) -> dict:
    rng = random.Random(seed_value)
    path = Path(db_path)
    if path.exists():
        path.unlink()
    t = Tracker(path)
    db.set_meta(t.conn, "demo", "1")
    now = db.now_utc()
    models = [m for m in t.models if m.store_price][:n_models]
    listings: list[Listing] = []
    ref = 0

    def add(**kw):
        nonlocal ref
        ref += 1
        listings.append(Listing(source="demo", source_ref=f"demo-{ref}", **kw))

    for m in models:
        centre = m.store_price * rng.uniform(0.82, 1.25)
        ship = 0.0 if m.scale == "1:18" else rng.choice([0.0, 0.0, 3.99, 4.5, 5.25])
        for _ in range(rng.randint(5, 14)):                          # sales, last 90 days
            p = max(4.0, rng.gauss(centre, centre * 0.07))
            if rng.random() < 0.07:
                p *= rng.choice([0.3, 2.6])                          # the odd outlier
            add(title=_title(m, rng), price=round(p - ship, 2), shipping=ship, kind="sold",
                observed_at=db.iso(now - timedelta(days=rng.uniform(1, 88))))
        for _ in range(rng.randint(3, 8)):                           # current asks
            p = max(4.0, rng.gauss(centre * 1.08, centre * 0.08))
            add(title=_title(m, rng), price=round(p - ship, 2), shipping=ship, kind="ask",
                observed_at=db.iso(now - timedelta(hours=rng.uniform(0, 20))))
        if rng.random() < 0.6:                                      # junk the matcher must refuse
            pattern, factor = rng.choice(JUNK)
            maker = rng.choice(MAKER_SPELLINGS.get(m.maker, [m.maker]))
            add(title=pattern.format(maker=maker, short=_short(m.name, rng)),
                price=round(centre * factor, 2), kind="ask",
                observed_at=db.iso(now - timedelta(hours=rng.uniform(0, 20))))

    # History first, so asks are judged against it; then a few planted deals.
    listings.sort(key=lambda li: (li.kind != "sold", li.observed_at))
    t.ingest(listings, now)
    deals = []
    for m in rng.sample(models, 5):
        centre_rows = t.summary(m.id, "sold") or t.summary(m.id, "ask")
        if not centre_rows:
            continue
        ref += 1
        deals.append(Listing("demo", f"demo-{ref}", _title(m, rng),
                             round(centre_rows.median * rng.uniform(0.55, 0.75), 2), 0.0, kind="ask",
                             observed_at=db.iso(now - timedelta(minutes=rng.randint(5, 300)))))
    report = t.ingest(deals, now)
    out = {"models": len(models), "listings": len(listings) + len(deals), "alerts": len(t.alerts())}
    t.conn.close()
    return out
