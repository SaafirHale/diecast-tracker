"""The catalogue: the models the store stocks or could stock.

A catalogue entry is the thing a messy marketplace listing gets matched to.
The canonical copy lives in data/catalogue.json so the matcher, the tests and
the dashboard never need the network. `import_from_store` rebuilds that file
from the store's public product pages (sitemap -> each /product/ page ->
its schema.org Product JSON-LD). It only reads pages robots.txt allows and
never touches /api/.
"""

from __future__ import annotations

import html
import json
import re
import time
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path

STORE_ORIGIN = "https://www.midnightgarageco.com"
USER_AGENT = "diecast-tracker/0.1 (catalogue import; owner's own store)"


@dataclass
class Model:
    sku: str                 # maker's item number, e.g. MGT00745
    maker: str               # canonical maker name, e.g. "Mini GT"
    scale: str               # "1:64" or "1:18"
    name: str                # short display name: casting + colourway/livery
    marque: str = ""         # car brand, e.g. "Porsche"
    store_price: float | None = None
    in_stock: bool | None = None
    url: str = ""
    aliases: list[str] = field(default_factory=list)  # extra names sellers use

    @property
    def id(self) -> str:
        return self.sku.upper()


def load(path: str | Path) -> list[Model]:
    rows = json.loads(Path(path).read_text(encoding="utf-8"))
    return [Model(**row) for row in rows["models"]]


def save(models: list[Model], path: str | Path, source: str) -> None:
    payload = {
        "source": source,
        "imported_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "count": len(models),
        "models": [asdict(m) for m in models],
    }
    Path(path).write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# --- import from the store's public pages -----------------------------------

def _get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _disallowed_paths(robots_txt: str) -> list[str]:
    """Disallow rules for `User-agent: *` (the only group the store publishes)."""
    rules, applies = [], False
    for raw in robots_txt.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip().lower(), value.strip()
        if key == "user-agent":
            applies = value == "*"
        elif key == "disallow" and applies and value:
            rules.append(value)
    return rules


def parse_product_page(page: str, url: str) -> Model | None:
    product, crumbs = None, []
    for block in re.findall(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', page, re.S):
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        if data.get("@type") == "Product":
            product = data
        elif data.get("@type") == "BreadcrumbList":
            crumbs = data.get("itemListElement", [])
    if not product:
        return None

    props = {p.get("name"): p.get("value") for p in product.get("additionalProperty", [])}
    offer = product.get("offers") or {}
    # The last breadcrumb is the full display name; og:title truncates long ones
    # with an ellipsis, and the JSON-LD name is the long SEO form (kept as an alias).
    if len(crumbs) >= 4:
        short, marque = html.unescape(crumbs[-1]["name"]), crumbs[2]["name"]
    else:
        short, marque = product["name"], ""
    # A few store names carry the SEO tail ("1/64 Diecast Model by ..."); drop it.
    short = re.sub(r"\s+1/\d+ (?:Die\s?cast|Model Car by) .*$", "", short, flags=re.I).strip()
    price = offer.get("price")
    return Model(
        sku=product.get("sku") or product.get("mpn") or "",
        maker=(product.get("brand") or {}).get("name", ""),
        scale=props.get("Scale", ""),
        name=short,
        marque=marque,
        store_price=float(price) if price else None,
        in_stock=offer.get("availability", "").endswith("InStock") if offer else None,
        url=product.get("url", url),
        aliases=[product["name"]] if product.get("name") and product["name"] != short else [],
    )


def import_from_store(delay: float = 1.0, log=print) -> list[Model]:
    disallowed = _disallowed_paths(_get(STORE_ORIGIN + "/robots.txt"))
    sitemap = _get(STORE_ORIGIN + "/sitemap.xml")
    urls = [u for u in re.findall(r"<loc>([^<]+)</loc>", sitemap) if "/product/" in u]
    models = []
    for i, url in enumerate(urls, 1):
        path = "/" + url.split("/", 3)[3]
        if any(path.startswith(rule) for rule in disallowed):
            log(f"skip (robots.txt): {path}")
            continue
        model = parse_product_page(_get(url), url)
        if model:
            models.append(model)
            log(f"[{i}/{len(urls)}] {model.sku}  {model.maker} {model.scale}  {model.name}")
        time.sleep(delay)
    return models
