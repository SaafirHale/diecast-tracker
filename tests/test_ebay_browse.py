"""eBay Browse source, against a fake HTTP opener.

The response bodies below are written by hand in the shape of the Browse
item_summary/search response (itemSummaries[].itemId/title/price/
shippingOptions/condition/itemWebUrl). They are not captured from eBay; no
live call is made in these tests.
"""

import io
import json
import tempfile
import unittest
import urllib.parse
from datetime import timedelta
from pathlib import Path

from diecast_tracker import db
from diecast_tracker.alerts import AlertRules
from diecast_tracker.sources import ebay_browse as E
from diecast_tracker.tracker import Listing, Tracker

REVUELTO = "MGT00886"


def item(item_id, title, price, ship=None, condition="New"):
    out = {"itemId": item_id, "title": title, "condition": condition,
           "price": {"value": f"{price:.2f}", "currency": "USD"},
           "itemWebUrl": f"https://www.ebay.com/itm/{item_id.split('|')[1]}"}
    if ship is not None:
        out["shippingOptions"] = [{"shippingCostType": "FIXED", "shippingCost": {"value": f"{ship:.2f}", "currency": "USD"}}]
    return out


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


class FakeEbay:
    """Routes token and search requests; `catalogue` maps a query substring to items."""

    def __init__(self, results):
        self.results = results
        self.requests = []

    def __call__(self, req, timeout=None):
        self.requests.append(req)
        if req.full_url.endswith("/identity/v1/oauth2/token"):
            body = {"access_token": "test-token", "expires_in": 7200, "token_type": "Application Access Token"}
        else:
            q = urllib.parse.parse_qs(urllib.parse.urlparse(req.full_url).query)["q"][0]
            items = [i for key, rows in self.results.items() if key.lower() in q.lower() for i in rows]
            body = {"total": len(items), "itemSummaries": items} if items else {"total": 0}
        return FakeResponse(json.dumps(body).encode())


CREDS = E.Credentials("client-id-for-tests", "client-secret-for-tests")


class Client(unittest.TestCase):
    def test_token_is_fetched_once_and_requests_are_well_formed(self):
        fake = FakeEbay({"MGT00886": [item("v1|111|0", "Mini GT Revuelto Yellow", 20.0, 4.0)]})
        c = E.BrowseClient(CREDS, opener=fake)
        c.search("Mini GT MGT00886")
        c.search("Mini GT MGT00886")
        token_reqs = [r for r in fake.requests if r.full_url.endswith("/token")]
        self.assertEqual(len(token_reqs), 1)
        tok = token_reqs[0]
        self.assertTrue(tok.get_header("Authorization").startswith("Basic "))
        self.assertIn(b"grant_type=client_credentials", tok.data)
        search = fake.requests[-1]
        self.assertTrue(search.full_url.startswith("https://api.ebay.com/buy/browse/v1/item_summary/search?"))
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(search.full_url).query)
        self.assertEqual(qs["category_ids"], ["222"])
        self.assertIn("conditions:{NEW}", qs["filter"][0])
        self.assertIn("priceCurrency:USD", qs["filter"][0])
        self.assertEqual(search.get_header("Authorization"), "Bearer test-token")
        self.assertEqual(search.get_header("X-ebay-c-marketplace-id"), "EBAY_US")

    def test_sandbox_host(self):
        fake = FakeEbay({})
        E.BrowseClient(E.Credentials("a", "b", "sandbox"), opener=fake).search("x")
        self.assertTrue(all(r.full_url.startswith("https://api.sandbox.ebay.com") for r in fake.requests))

    def test_to_listings(self):
        rows = E.to_listings({"itemSummaries": [
            item("v1|1|0", "A", 20.0, 4.5),
            item("v1|2|0", "B", 18.0),                        # no shipping data
            {"itemId": "v1|3|0", "title": "auction only", "currentBidPrice": {"value": "5.00"}},
        ]}, "2026-11-11T12:00:00Z")
        self.assertEqual([r.source_ref for r in rows], ["v1|1|0", "v1|2|0"])
        self.assertEqual((rows[0].shipping, rows[0].shipping_known), (4.5, True))
        self.assertEqual((rows[1].shipping, rows[1].shipping_known), (0.0, False))
        self.assertEqual(rows[0].url, "https://www.ebay.com/itm/1")

    def test_credentials_from_env_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / ".env"
            p.write_text('# keys\nEBAY_CLIENT_ID="abc"\nEBAY_CLIENT_SECRET=def\nEBAY_ENV=sandbox\n', encoding="utf-8")
            saved = {k: E.os.environ.pop(k) for k in ("EBAY_CLIENT_ID", "EBAY_CLIENT_SECRET", "EBAY_ENV")
                     if k in E.os.environ}
            try:
                self.assertEqual(E.load_credentials(p), E.Credentials("abc", "def", "sandbox"))
                self.assertIsNone(E.load_credentials(Path(d) / "missing.env"))
            finally:
                E.os.environ.update(saved)


class Refresh(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.t = Tracker(Path(self.tmp.name) / "t.db", rules=AlertRules(margin=None))
        self.model = self.t.by_id[REVUELTO]
        self.now = db.now_utc()

    def tearDown(self):
        self.t.conn.close()
        self.tmp.cleanup()

    def seed_own_sales(self):
        self.t.ingest([Listing("manual", f"s{i}", "Mini GT Lamborghini Revuelto Yellow 1:64", p, kind="sold",
                               observed_at=db.iso(self.now - timedelta(days=i + 1)))
                       for i, p in enumerate([25.0, 26.0, 26.0, 27.0, 25.5, 26.5])], self.now)

    def run_refresh(self, results):
        client = E.BrowseClient(CREDS, opener=FakeEbay(results))
        return E.refresh(self.t, client, [self.model], log=lambda s: None)

    def test_ebay_asks_are_shown_but_never_build_the_reference(self):
        rep = self.run_refresh({"MGT00886": [
            item("v1|10|0", "Mini GT MGT00886 Lamborghini Revuelto Giallo 1:64", 24.0, 4.0),
            item("v1|11|0", "MINI GT REVUELTO YELLOW 1/64 SEALED", 21.0, 5.0),
            item("v1|12|0", "Hot Wheels Lamborghini Revuelto", 6.0, 3.0),
        ]})
        self.assertEqual((rep.calls, rep.seen), (2, 3))       # item-number query + name query
        self.assertIsNone(self.t.summary(REVUELTO, "ask"))      # not modelled
        live = self.t.live_asks(REVUELTO)
        self.assertEqual((live["n"], live["lowest"]), (2, 26.0))

    def test_alert_against_own_reference(self):
        self.seed_own_sales()
        rep = self.run_refresh({"Revuelto": [item("v1|20|0", "Mini GT Lamborghini Revuelto Yellow 1:64", 14.0, 4.0)]})
        self.assertEqual(rep.alerts, 1)
        a = self.t.alerts()[0]
        self.assertEqual((a["rule"], a["source"], a["reference_kind"]), ("below_median", "ebay_browse", "sold"))

    def test_unknown_shipping_is_noted_on_the_alert(self):
        self.seed_own_sales()
        self.run_refresh({"Revuelto": [item("v1|21|0", "Mini GT Lamborghini Revuelto Yellow 1:64", 14.0)]})
        self.assertIn("shipping not stated", self.t.alerts()[0]["note"])

    def test_ended_listings_are_deleted_on_the_next_refresh(self):
        self.run_refresh({"MGT00886": [item("v1|30|0", "Mini GT MGT00886 Revuelto Yellow", 24.0, 4.0),
                                       item("v1|31|0", "Mini GT MGT00886 Revuelto Yellow", 25.0, 4.0)]})
        rep = self.run_refresh({"MGT00886": [item("v1|31|0", "Mini GT MGT00886 Revuelto Yellow", 25.0, 4.0)]})
        self.assertEqual(rep.retired, 1)
        refs = [r[0] for r in self.t.conn.execute("SELECT source_ref FROM observations WHERE source='ebay_browse'")]
        self.assertEqual(refs, ["v1|31|0"])

    def test_daily_cap(self):
        take = E.daily_budget(self.t.conn, cap=2)
        client = E.BrowseClient(CREDS, opener=FakeEbay({}), call_budget=take)
        client.search("a")
        client.search("b")
        with self.assertRaises(E.EbayError):
            client.search("c")


if __name__ == "__main__":
    unittest.main()
