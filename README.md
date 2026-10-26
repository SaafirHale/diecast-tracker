# diecast-tracker

A price tracker for the 1:64 and 1:18 diecast models that Midnight Garage Co. stocks or could stock. It answers one question before a restock: what does this model actually sell for? It also flags listings that come up well under the recent median.

Python 3.12 standard library only. No packages to install.

![Dashboard on synthetic demo data](docs/dashboard-demo.jpg)

*The screenshot shows the demo database. Those prices are synthetic and the page labels them that way. They are not market prices.*

## Status

The source-independent core is built and tested: catalogue import, title matching, price history, stats, alerts and the dashboard. **No live marketplace source is connected yet.** The choice of source is open, because eBay's terms affect what the tool may store (see [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md)). Until then, data comes in through CSV: your own sales, buy costs, and comps noted by hand.

## Quick start

```bash
python -m diecast_tracker demo
```

This builds `data/demo.db` with synthetic data and serves the dashboard on http://127.0.0.1:8064.

With real data:

```bash
python -m diecast_tracker ingest my-comps.csv
python -m diecast_tracker serve
```

Other commands:

| Command | What it does |
|---|---|
| `import-catalogue` | Rebuild `data/catalogue.json` from the store's public product pages |
| `match "<title>"` | Show how a listing title is matched, with reasons and runner-up candidates |
| `ingest FILE.csv [--source manual]` | Match, store and alert on a CSV of listings, sales or costs |
| `stats [SKU] [--days 90]` | Median and p25 to p75 per model |
| `alerts` | Open alerts |
| `purge` | Delete rows past their source's retention window |
| `serve [--port 8064]` | Dashboard, bound to 127.0.0.1 only |

`--db PATH` picks the database (default `data/tracker.db`).

### CSV format

Header row required. Only `title` and `price` are mandatory.

| column | meaning |
|---|---|
| `title` | listing title as written by the seller |
| `price` | item price |
| `shipping` | shipping charged (default 0). Stats use the **landed** price: item plus shipping |
| `kind` | `sold` (default), `ask` (still listed) or `cost` (what you paid or a dealer quote) |
| `currency` | default `USD`. Stats and alerts only use USD |
| `condition` | anything other than new makes the row non-comparable |
| `observed_at` | `2026-10-01` or ISO UTC. Defaults to now |
| `sku` | set this to skip matching, e.g. for your own invoice lines |
| `url`, `ref` | link, and a stable id so re-importing updates rather than duplicates |

## How it works

```
source -> Listing -> matcher -> observations (SQLite) -> robust stats -> alert rules -> dashboard
```

### Catalogue

`data/catalogue.json` is read from midnightgarageco.com. The importer follows the sitemap to each `/product/` page and reads its schema.org `Product` JSON-LD. It checks `robots.txt` first and never calls `/api/`. Each entry holds the SKU, maker, scale, display name, marque, store price and stock state. The current file has the **60 models** the store lists.

### Matcher (`diecast_tracker/matcher.py`)

The matcher's job is to be right or refuse. A wrong match poisons a model's price history; a missed one only loses a data point. Every title gets one of four outcomes:

- **matched**: one model, confidently, and the listing is comparable.
- **rejected**: probably that model, but a lot, loose, chase, custom, damaged, 3D-printed, signed or box-only.
- **ambiguous**: two models fit about equally, e.g. the same DB5 casting in two Bond films. These go to the review queue.
- **no_match**: nothing fits, or the listing names another maker (Hot Wheels, Tomica, Matchbox and others).

Signals, strongest first:

1. **Item number**, in the spellings sellers use: `MGT00745`, `mgt 745`, `#745` with Mini GT named, `TL021-WH` for `T64G-TL021-WH`, `OT1173`, `GT507`, `64B0283`. A single item-number hit beats any fuzzy near-twin.
2. **Hard gates.** A stated scale, maker or marque that differs from the model's rules that model out.
3. **Rarity-weighted token overlap (IDF over the catalogue).** "Zonda" counts for much more than "RHD" or "Pandem". Before comparing, titles are normalised:
   - `RX-7` becomes `rx7`, and `GT-R` becomes `gtr`.
   - `LBWK`, `LB Works` and `LB-Super Silhouette` are folded to tokens that keep them distinct.
   - `Grey` becomes `gray`, and `Giallo` becomes `yellow`.
   - Adjacent words are glued so `RX 7` still finds `rx7`.
4. **Conflicts.** A stated colour, race number (`#31` vs `#311`) or steering side the model doesn't have means a sibling variant, not this model. A rare catalogue word belonging to another model ("Skyfall" vs "Thunderball") lowers the score.

Flag words that are part of the model's own name are ignored. The Skyfall DB5 is literally called "Damaged", so a listing saying so is not rejected. Words in a box-condition phrase ("box damaged, car mint") don't count against the car.

### Stats (`diecast_tracker/stats.py`)

Median and p10, p25, p75 and p90 (linear interpolation, matching numpy's default) are computed after outlier rejection:

- The main test is the modified z-score (Iglewicz and Hoaglin, |z| > 3.5, based on the MAD).
- When most prices are identical, the MAD is zero, so Tukey IQR fences take over.
- Below five points nothing is rejected.

An active listing seen on many polls counts once, at its latest price. Stats use a 90-day window. The dashboard compares the store price with the market only once there are at least five data points.

### Alerts (`diecast_tracker/alerts.py`)

- **below_median**: landed price at least 20% under the reference median. The reference is the sold median when there are at least five sales in 90 days, otherwise the asking median, never including the listing itself. A price under half the median still alerts, tagged *check seller and photos*.
- **restock_margin**: landed price leaves at least 35% of the store's own price as margin.

Alerts fire only on comparable, confidently matched (≥ 0.75) USD asks. Each fires once per listing. Thresholds live in `AlertRules`.

### Retention

Each source has a retention policy in `db.SOURCES`. `manual` rows are kept. `ebay_browse` rows expire after 6 hours and are deleted by `purge` (and on dashboard start). That follows the eBay API License Agreement's freshness and deletion rules as summarised in [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md).

## Data sources

[docs/DATA_SOURCES.md](docs/DATA_SOURCES.md) records what was checked on 2026-10-26 and marks each item verified or unverified. In short:

- The **eBay Browse API** (free developer account) gives active listings only.
- **Sold data** through Marketplace Insights is limited release. The Finding API's `findCompletedItems` is decommissioned. Seller Hub's Product Research shows sold prices by hand only.
- eBay's **User Agreement prohibits scraping**.
- eBay's **API License Agreement** restricts using API data "to suggest or model prices". It also limits how long listing data may be kept.

Any developer account is the store owner's to create.

## Tests

```bash
python -m unittest
```

There are 31 tests:

- **Matcher:** 55 hand-written listing titles in sellers' styles (37 matched, 6 rejected, 3 ambiguous, 9 no-match), plus normalisation and flag unit tests.
- **Stats:** checked against numpy's percentile definition, plus outlier cases (fishing listings, starting bids, MSRP clusters, genuine wide spreads).
- **End to end:** de-duplication, shipping in the landed price, minimum samples, loose and lot exclusion, used condition, the suspicious tag, window cut-off, the restock rule, 6-hour retention, given SKUs and CSV import.

## Layout

```
diecast_tracker/
  catalogue.py   store import (sitemap + JSON-LD) and the Model type
  normalize.py   scale, maker, marque, colour, race-number and token normalisation
  matcher.py     title -> model, or a reasoned refusal
  stats.py       percentiles, MAD/IQR outlier rejection
  db.py          SQLite schema, upserts, per-source retention
  alerts.py      alert rules
  tracker.py     ingest pipeline, overview, history, review queue, CSV reader
  server.py      localhost dashboard server
  static/        dashboard page (vanilla JS, inline SVG chart, light and dark)
  demo.py        synthetic demo data
data/catalogue.json
docs/DATA_SOURCES.md
tests/
```

## Known limits

- The catalogue is what the store lists today: 60 models, no Minichamps or Spark yet. Maker aliases for both exist but have no catalogue entries to test against.
- Mini GT regional variants (for example `-MJ` Japan blister cards) are not modelled separately yet.
- A special or event edition listed without its edition name is held as ambiguous, because it may be the regular release.
