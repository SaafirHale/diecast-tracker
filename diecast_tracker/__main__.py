"""Command line: python -m diecast_tracker <command>"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import catalogue
from .tracker import CATALOGUE_PATH, ROOT, Tracker, read_csv

DEFAULT_DB = ROOT / "data" / "tracker.db"
DEMO_DB = ROOT / "data" / "demo.db"


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(prog="diecast_tracker", description="Diecast price tracker")
    p.add_argument("--db", default=str(DEFAULT_DB), help="SQLite file (default data/tracker.db)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("import-catalogue", help="refresh data/catalogue.json from the store's public pages")
    m = sub.add_parser("match", help="show how a listing title is matched")
    m.add_argument("title")
    i = sub.add_parser("ingest", help="ingest a CSV of listings/sales/costs")
    i.add_argument("csv")
    i.add_argument("--source", default="manual")
    s = sub.add_parser("stats", help="market summary per model")
    s.add_argument("sku", nargs="?")
    s.add_argument("--days", type=int, default=90)
    sub.add_parser("alerts", help="open alerts")
    sub.add_parser("purge", help="delete rows past their source's retention")
    e = sub.add_parser("ebay", help="look up current eBay asks (your own Browse API keys in .env)")
    e.add_argument("skus", nargs="*", help="models to check (default: the whole catalogue)")
    e.add_argument("--in-stock", action="store_true", help="only models the store has in stock")
    v = sub.add_parser("serve", help="run the dashboard on localhost")
    v.add_argument("--port", type=int, default=8064)
    d = sub.add_parser("demo", help="build data/demo.db with SYNTHETIC prices and serve it")
    d.add_argument("--port", type=int, default=8064)
    d.add_argument("--no-serve", action="store_true")
    a = p.parse_args(argv)

    if a.cmd == "import-catalogue":
        models = catalogue.import_from_store()
        catalogue.save(models, CATALOGUE_PATH,
                       "midnightgarageco.com public product pages (sitemap + schema.org JSON-LD)")
        print(f"saved {len(models)} models to {CATALOGUE_PATH}")
    elif a.cmd == "match":
        from .matcher import Matcher
        r = Matcher(catalogue.load(CATALOGUE_PATH)).match(a.title)
        print(json.dumps({"status": r.status, "model": r.model_id, "name": r.model.name if r.model else None,
                          "confidence": r.confidence, "how": r.how, "flags": r.flags,
                          "comparable": r.comparable, "reasons": r.reasons, "candidates": r.candidates},
                         indent=2, ensure_ascii=False))
    elif a.cmd == "ingest":
        rep = Tracker(a.db).ingest(read_csv(a.csv, a.source))
        print(f"{rep.seen} rows: {rep.by_status}; {rep.alerts} new alerts")
    elif a.cmd == "stats":
        t = Tracker(a.db)
        rows = [r for r in t.overview(a.days) if not a.sku or r["id"] == a.sku.upper()]
        for r in rows:
            ref = r["sold"] or r["ask"]
            if not ref and not a.sku:
                continue
            print(f"{r['sku']:<20} {r['name'][:44]:<44} store ${r['store_price'] or 0:>7.2f}  "
                  + (f"median ${ref['median']:.2f} (n={ref['n']}, p25-p75 ${ref['p25']:.2f}-${ref['p75']:.2f})"
                     if ref else "no data"))
    elif a.cmd == "alerts":
        for x in Tracker(a.db).alerts():
            print(f"[{x['rule']}] {x['model_id']} ${x['landed']:.2f} vs ${x['reference'] or 0:.2f} "
                  f"({x['pct_below']:.0%} under) {x['title'][:60]} {x['note']}")
    elif a.cmd == "ebay":
        from .sources import ebay_browse as E
        creds = E.load_credentials(ROOT / ".env")
        if not creds:
            print("No eBay keys found. Put EBAY_CLIENT_ID and EBAY_CLIENT_SECRET (Production keyset) "
                  "in .env at the repo root, or in the environment. See README > eBay Browse.")
            return 2
        t = Tracker(a.db)
        wanted = {s.upper() for s in a.skus}
        models = [m for m in t.models if (not wanted or m.id in wanted) and (not a.in_stock or m.in_stock)]
        unknown = wanted - {m.id for m in models}
        if unknown:
            print("not in catalogue:", ", ".join(sorted(unknown)))
        client = E.BrowseClient(creds, call_budget=E.daily_budget(t.conn))
        try:
            rep = E.refresh(t, client, models)
        except E.EbayError as err:
            print("eBay error:", err)
            return 1
        print(f"{rep.models} models, {rep.calls} calls, {rep.seen} listings {rep.by_status}; "
              f"{rep.alerts} new alerts; {rep.retired} ended listings removed; {rep.purged} expired rows purged")
    elif a.cmd == "purge":
        print(f"purged {Tracker(a.db).purge()} rows")
    elif a.cmd == "serve":
        from .server import serve
        serve(a.db, a.port)
    elif a.cmd == "demo":
        from . import demo
        print("seeding SYNTHETIC demo data (not market prices):", demo.seed(DEMO_DB), flush=True)
        if not a.no_serve:
            from .server import serve
            serve(DEMO_DB, a.port)


if __name__ == "__main__":
    sys.exit(main())
