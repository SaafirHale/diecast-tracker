"""eBay Browse API source: current asking prices, looked up live.

Terms this module is built around (see docs/DATA_SOURCES.md for sources):
  * Scraping eBay is prohibited; this uses the Browse API only.
  * API License Agreement s8.1: displayed listing data no more than 6 hours
    old; delete listings that are no longer available. Rows from this source
    expire after 6 hours (db.SOURCES) and a refresh deletes the asks it no
    longer sees.
  * s9.5: no using eBay content to suggest or model prices. These asks are
    shown and checked against the store's own reference, but never feed the
    reference median (SourcePolicy.reference=False).

Credentials are the owner's own Production keyset, read from the environment
or a local .env file (gitignored): EBAY_CLIENT_ID, EBAY_CLIENT_SECRET, and
optionally EBAY_ENV=sandbox. Nothing here creates accounts or keys.
"""

from __future__ import annotations

import base64
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .. import db
from ..catalogue import Model
from ..tracker import Listing, Tracker

SOURCE = "ebay_browse"
HOSTS = {"production": "https://api.ebay.com", "sandbox": "https://api.sandbox.ebay.com"}
SCOPE = "https://api.ebay.com/oauth/api_scope"
CATEGORY_ID = "222"   # Diecast & Toy Vehicles (verified, docs/DATA_SOURCES.md)
FILTERS = "conditions:{NEW},buyingOptions:{FIXED_PRICE|BEST_OFFER},priceCurrency:USD,deliveryCountry:US"
DAILY_CAP = 1000      # well under the default 5,000 Browse calls per day
USER_AGENT = "diecast-tracker/0.2"


class EbayError(RuntimeError):
    pass


@dataclass
class Credentials:
    client_id: str
    client_secret: str
    env: str = "production"


def load_credentials(env_file: Path | None = None) -> Credentials | None:
    values = dict(os.environ)
    if env_file and env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            key, sep, val = line.strip().partition("=")
            if sep and not key.startswith("#"):
                values.setdefault(key.strip(), val.strip().strip('"').strip("'"))
    cid, secret = values.get("EBAY_CLIENT_ID"), values.get("EBAY_CLIENT_SECRET")
    if not cid or not secret:
        return None
    env = values.get("EBAY_ENV", "production").lower()
    if env not in HOSTS:
        raise EbayError(f"EBAY_ENV must be one of {sorted(HOSTS)}")
    return Credentials(cid, secret, env)


class BrowseClient:
    def __init__(self, creds: Credentials, opener=urllib.request.urlopen, call_budget=None):
        self.creds = creds
        self.host = HOSTS[creds.env]
        self.opener = opener
        self.call_budget = call_budget   # callable() -> bool, False when the day's cap is spent
        self._token, self._token_expiry = None, 0.0

    def _send(self, req: urllib.request.Request) -> dict:
        req.add_header("User-Agent", USER_AGENT)
        try:
            with self.opener(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")[:300]
            raise EbayError(f"HTTP {e.code} from {req.full_url.split('?')[0]}: {body}") from None

    def token(self) -> str:
        if self._token and time.time() < self._token_expiry:
            return self._token
        basic = base64.b64encode(f"{self.creds.client_id}:{self.creds.client_secret}".encode()).decode()
        req = urllib.request.Request(
            self.host + "/identity/v1/oauth2/token",
            data=urllib.parse.urlencode({"grant_type": "client_credentials", "scope": SCOPE}).encode(),
            headers={"Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded"},
            method="POST")
        data = self._send(req)
        self._token = data["access_token"]
        self._token_expiry = time.time() + int(data.get("expires_in", 7200)) - 120
        return self._token

    def search(self, q: str, limit: int = 50) -> dict:
        if self.call_budget and not self.call_budget():
            raise EbayError(f"daily call cap reached ({DAILY_CAP}); try again tomorrow")
        params = urllib.parse.urlencode({"q": q, "category_ids": CATEGORY_ID, "filter": FILTERS,
                                         "limit": str(limit)})
        req = urllib.request.Request(
            f"{self.host}/buy/browse/v1/item_summary/search?{params}",
            headers={"Authorization": f"Bearer {self.token()}", "X-EBAY-C-MARKETPLACE-ID": "EBAY_US"})
        return self._send(req)


def queries_for(m: Model) -> list[str]:
    """One search by item number (when the maker has usable ones) and one by name."""
    # Casting words only: stop at the livery/event part, keep it short so
    # eBay's all-words search stays broad; the matcher does the narrowing.
    casting = re.split(r'["(#]| - ', m.name, maxsplit=1)[0]
    words = [w for w in casting.split() if w.lower() not in {"with", "and", "rhd"}][:4]
    out = [f"{m.maker} {' '.join(words)}"]
    if re.match(r"^(MGT|KHMG|T64|IN64|PR|OT|GT|64B|JC64)", m.sku, re.I):
        out.insert(0, f"{m.maker} {m.sku.split('-007')[0]}")
    return out


def to_listings(payload: dict, observed_at: str) -> list[Listing]:
    out = []
    for item in payload.get("itemSummaries", []) or []:
        price = item.get("price") or {}
        if not price.get("value"):
            continue                                     # auction-only rows have no fixed price
        costs = [float(o["shippingCost"]["value"]) for o in item.get("shippingOptions", []) or []
                 if (o.get("shippingCost") or {}).get("value") is not None]
        out.append(Listing(
            source=SOURCE, source_ref=item["itemId"], title=item.get("title", ""),
            price=float(price["value"]), shipping=min(costs) if costs else 0.0,
            shipping_known=bool(costs), currency=price.get("currency", "USD"), kind="ask",
            condition=item.get("condition", ""), url=item.get("itemWebUrl", ""),
            observed_at=observed_at))
    return out


def daily_budget(conn, cap: int = DAILY_CAP):
    key = f"ebay_calls:{date.today().isoformat()}"

    def take() -> bool:
        used = int(db.get_meta(conn, key) or 0)
        if used >= cap:
            return False
        db.set_meta(conn, key, str(used + 1))
        return True
    return take


@dataclass
class RefreshReport:
    models: int = 0
    calls: int = 0
    seen: int = 0
    by_status: dict = None
    alerts: int = 0
    retired: int = 0
    purged: int = 0


def refresh(tracker: Tracker, client: BrowseClient, models: list[Model], log=print) -> RefreshReport:
    """Look up current asks for these models, ingest them, and drop what is gone."""
    start = db.now_utc()
    stamp = db.iso(start)
    rep = RefreshReport(by_status={})
    rep.purged = tracker.purge()
    seen: set[str] = set()
    for m in models:
        found: dict[str, Listing] = {}
        for q in queries_for(m):
            rep.calls += 1
            for li in to_listings(client.search(q), stamp):
                found[li.source_ref] = li
        seen |= set(found)
        r = tracker.ingest(found.values(), start)
        rep.models += 1
        rep.seen += r.seen
        rep.alerts += r.alerts
        for k, v in r.by_status.items():
            rep.by_status[k] = rep.by_status.get(k, 0) + v
        log(f"{m.sku:<20} {len(found):>3} listings  {r.by_status}")
    rep.retired = db.retire_unseen(tracker.conn, SOURCE, [m.id for m in models], seen)
    return rep
