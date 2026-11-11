# Portfolio entry (draft)

- **slug:** diecast-tracker
- **category:** software
- **title:** diecast-tracker: market prices for my store's catalogue
- **blurb:** Matches messy marketplace listing titles to the exact models Midnight Garage Co stocks, keeps a robust price history, and flags listings that come up well under the recent median.

## Body

Midnight Garage Co sells 1:64 and 1:18 diecast from makers like Mini GT, Tarmac Works, Pop Race and GT Spirit. Restocking well means knowing what a specific model actually sells for: one casting in one colourway, not the casting in general. diecast-tracker reads the store's catalogue from its own public product pages. It follows the sitemap and reads each page's schema.org data, and it respects robots.txt. Each of the 60 listed models becomes a target that marketplace listings are matched against.

The matcher is the hard part. Sellers write the same Mini GT as "MINIGT #745", "mini gt mgt 745" or "Cadillac V Series R Whelen 1/64". The matcher's design rule is that a wrong match costs more than a missed one, so every title ends up matched, rejected, ambiguous or no-match, with reasons.

- **Item numbers** in their common spellings decide first.
- **Gates:** a stated scale, maker or car brand that differs rules a model out.
- **Weighted words:** the remaining words are weighted by how rare they are across the catalogue, so "Zonda" outweighs "RHD".
- **Conflicts:** a stated colour, race number or steering side that the model doesn't have marks a sibling variant.
- **Exclusions:** lots, loose cars, chase variants, customs and empty boxes are recognised and kept out of the stats. The exception is when the word is part of the model's own name: one Aston Martin DB5 in the catalogue is literally the "Damaged" Skyfall version.

The test suite has 55 hand-written listing titles in sellers' styles, including near-twins it has to refuse to guess between.

Prices are compared on a landed basis (item plus shipping). Stats are medians and percentiles after outlier rejection, using a MAD-based modified z-score that falls back to IQR fences when most sellers list at the same price. Alerts fire when a listing lands at least 20% under the recent median (sold prices when there are enough, asking prices otherwise), or when it leaves a set margin under my own shelf price. A local dashboard shows each model's price history against the store price, the open alerts, and a review queue of listings the matcher would not commit to. Running it on generated demo listings surfaced two matcher bugs through that queue, and both are now covered by tests.

Before writing any fetcher, I checked what the data sources allow:

- eBay's User Agreement bans scraping.
- Its Browse API returns active listings only.
- Its API License Agreement restricts using API data to model prices and caps how long listing data can be stored.

So every source carries a policy: how long its rows live, and whether its prices may build the reference median. The eBay Browse client is built to those rules:

- eBay asks expire after six hours.
- Each refresh deletes the listings it no longer sees.
- eBay asks never feed the median. They show as live asks and are checked against my own sales and shelf prices.

## Stack

Python 3.12 (standard library only), SQLite, eBay Browse API (OAuth client credentials), schema.org JSON-LD, vanilla JavaScript with inline SVG charts, unittest
