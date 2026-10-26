"""End-to-end: listings in, stats and alerts out, retention enforced."""

import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from diecast_tracker import db
from diecast_tracker.alerts import AlertRules
from diecast_tracker.tracker import Listing, Tracker, read_csv

REVUELTO = "MGT00886"   # store price 22.99


def sold(ref, price, days_ago, at, ship=0.0, title="Mini GT Lamborghini Revuelto Giallo Yellow 1:64"):
    return Listing("manual", ref, title, price, ship, kind="sold",
                   observed_at=db.iso(at - timedelta(days=days_ago)))


class TrackerFlow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.t = Tracker(Path(self.tmp.name) / "t.db", rules=AlertRules(margin=None))
        self.at = db.now_utc()

    def tearDown(self):
        self.t.conn.close()
        self.tmp.cleanup()

    def seed_sales(self):
        prices = [24.0, 25.5, 26.0, 26.0, 27.0, 28.5, 25.0]
        self.t.ingest([sold(f"s{i}", p, i + 1, self.at) for i, p in enumerate(prices)], self.at)

    def test_below_median_alert_fires_once(self):
        self.seed_sales()
        deal = Listing("manual", "ask1", "MINI GT LAMBO REVUELTO YELLOW 1/64 SEALED", 15.0, 4.0)
        rep = self.t.ingest([deal], self.at)
        self.assertEqual(rep.alerts, 1)
        a = self.t.alerts()[0]
        self.assertEqual((a["rule"], a["model_id"], a["reference_kind"]), ("below_median", REVUELTO, "sold"))
        self.assertAlmostEqual(a["landed"], 19.0)
        self.assertAlmostEqual(a["reference"], 26.0)
        # Seen again on the next poll: still one row, still one alert.
        rep2 = self.t.ingest([deal], self.at + timedelta(hours=1))
        self.assertEqual(rep2.alerts, 0)
        n = self.t.conn.execute("SELECT COUNT(*) FROM observations WHERE source_ref='ask1'").fetchone()[0]
        self.assertEqual(n, 1)

    def test_shipping_counts(self):
        self.seed_sales()
        # $15 + $12 shipping = $27 landed: not a deal.
        rep = self.t.ingest([Listing("manual", "ask2", "Mini GT Revuelto Yellow 1:64", 15.0, 12.0)], self.at)
        self.assertEqual(rep.alerts, 0)

    def test_no_alert_without_enough_history(self):
        self.t.ingest([sold("s1", 26.0, 1, self.at), sold("s2", 27.0, 2, self.at)], self.at)
        rep = self.t.ingest([Listing("manual", "ask3", "Mini GT Revuelto Yellow 1:64", 10.0)], self.at)
        self.assertEqual(rep.alerts, 0)

    def test_loose_or_lot_never_alerts_or_counts(self):
        self.seed_sales()
        rep = self.t.ingest([
            Listing("manual", "x1", "LOOSE Mini GT Lamborghini Revuelto Yellow no box", 8.0),
            Listing("manual", "x2", "Mini GT lot of 4 Revuelto Yellow, Porsche 901, Capri", 40.0),
        ], self.at)
        self.assertEqual(rep.alerts, 0)
        self.assertEqual(self.t.summary(REVUELTO, "ask").n if self.t.summary(REVUELTO, "ask") else 0, 0)
        statuses = {r["title"][:5]: r["match_status"] for r in self.t.review_queue()}
        self.assertEqual(set(statuses.values()), {"rejected"})

    def test_used_condition_from_source_is_not_comparable(self):
        self.seed_sales()
        li = Listing("manual", "u1", "Mini GT Revuelto Giallo Yellow 1:64", 12.0, condition="Used")
        rep = self.t.ingest([li], self.at)
        self.assertEqual(rep.alerts, 0)

    def test_suspiciously_cheap_is_tagged(self):
        self.seed_sales()
        self.t.ingest([Listing("manual", "cheap", "Mini GT MGT00886 Revuelto Yellow", 6.0)], self.at)
        self.assertIn("check seller", self.t.alerts()[0]["note"])

    def test_old_sales_fall_out_of_window(self):
        self.t.ingest([sold(f"old{i}", 60.0, 200 + i, self.at) for i in range(6)], self.at)
        self.assertIsNone(self.t.summary(REVUELTO, "sold", days=90, at=self.at))

    def test_restock_margin_rule(self):
        t = Tracker(Path(self.tmp.name) / "m.db", rules=AlertRules(margin=0.35))
        rep = t.ingest([Listing("manual", "r1", "Mini GT Lamborghini Revuelto Yellow 1:64", 13.5, 1.0)], self.at)
        self.assertEqual(rep.alerts, 1)       # 14.50 <= 22.99 * 0.65 = 14.94
        self.assertEqual(t.alerts()[0]["rule"], "restock_margin")
        t.conn.close()

    def test_retention_purges_short_lived_sources(self):
        li = Listing("ebay_browse", "v1|123", "Mini GT MGT00886 Revuelto Yellow", 24.0,
                     observed_at=db.iso(self.at))
        self.t.ingest([li], self.at)
        manual = sold("keep", 25.0, 0, self.at)
        self.t.ingest([manual], self.at)
        self.assertEqual(db.purge_expired(self.t.conn, self.at + timedelta(hours=5)), 0)
        self.assertEqual(db.purge_expired(self.t.conn, self.at + timedelta(hours=6, minutes=1)), 1)
        left = [r["source"] for r in self.t.conn.execute("SELECT source FROM observations")]
        self.assertEqual(left, ["manual"])

    def test_given_sku_bypasses_matcher(self):
        rep = self.t.ingest([Listing("manual", "c1", "Distributor invoice line 14", 12.4, kind="cost",
                                     sku="mgt00886")], self.at)
        self.assertEqual(rep.by_status, {"matched": 1})
        self.assertAlmostEqual(self.t.summary(REVUELTO, "cost").median, 12.4)

    def test_csv_import(self):
        p = Path(self.tmp.name) / "comps.csv"
        p.write_text("title,price,shipping,kind,observed_at\n"
                     "Mini GT Revuelto Giallo 1:64,26.00,4.50,sold,2026-10-01\n"
                     "Tarmac Works Zonda Cinque Bianco Benny,31.00,0,sold,2026-10-03\n", encoding="utf-8")
        rows = read_csv(p)
        self.assertEqual([r.observed_at for r in rows], ["2026-10-01T12:00:00Z", "2026-10-03T12:00:00Z"])
        rep = self.t.ingest(rows, self.at)
        self.assertEqual(rep.by_status, {"matched": 2})


if __name__ == "__main__":
    unittest.main()
