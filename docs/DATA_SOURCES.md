# Data Sources for the Diecast Price Tracker

Research date: 2026-10-26. This is read-only desk research. No accounts were created and no forms were submitted.

Scope: 1:64 and 1:18 diecast/resin model cars from Mini GT, Tarmac Works, Pop Race, Inno Models (Inno64), GT Spirit, OttOmobile, BM Creations, Minichamps and Spark. The goal is to get market prices (active asks, and sold prices where possible) so restocks can be bought below market.

Legend:
- **Verified**: confirmed from the cited page during this research. Quotes are verbatim and under 15 words.
- **Unverified**: from secondary sources, search snippets, or memory, or the page could not be fetched. Confirm it before relying on it.

Access note: developer.ebay.com blocks automated fetches (HTTP 403 bot page). eBay docs were read through eBay's own mirrors (`edp.ebay.com`, `developer.ebay.com/develop/api/buy/*.md`) and search snippets. I did not try to get around the block.

---

## 1. eBay Browse API (active listings)

### What it returns
- **Active listings only.** It does not return sold or completed items. eBay Developer Support said in a community thread that Browse "does not permit access to information about sold listings" (search-snippet quote; thread linked from the [Finding API EOL thread](https://community.ebay.com/t5/RESTful-Buy-APIs-Browse/Finding-API-EOL-in-February-2025-Delays-in-Limit-Adjustments-for/td-p/34822137)). **Verified via snippet.**
- Key method: `GET /buy/browse/v1/item_summary/search`. It searches by keyword (`q`), `category_ids`, GTIN, ePID, charity, or image, with `filter`, `aspect_filter`, `sort` and `fieldgroups`.
- Paging: `limit` defaults to 50 with a max of 200. `offset` runs 0 to 9,999. The method "can return a maximum of 10,000 items." **Verified** ([browse_api.md](https://developer.ebay.com/develop/api/buy/browse_api.md)).
- By default, search returns only fixed-price (Buy It Now) listings. Auctions need `filter=buyingOptions:{AUCTION}`. **Verified via snippet** ([search method](https://www.developer.ebay.com/api-docs/buy/browse/resources/item_summary/methods/search)).
- Useful `itemSummary` fields: `price`, `currentBidPrice`, `buyingOptions`, `condition`, `conditionId` (1000 = New), `itemWebUrl`, `itemAffiliateWebUrl`, `legacyItemId`, `categories`, `image`, `seller`, `shippingOptions`, `itemLocation`, `itemEndDate`. I verified most of these in the spec. Whether `seller` and `shippingOptions` are always populated in search results is **unverified**.
- `getItem` / `getItemByLegacyId` give full detail on one item. `getItems` (batch) is "a Limited Release available only to select Partners." **Verified** ([browse_api.md](https://developer.ebay.com/develop/api/buy/browse_api.md)).

### Filters (field filters for `search`)
**Verified** list from [Buy API field filters](https://www.edp.ebay.com/api-docs/buy/static/ref-buy-browse-filters.html): `bidCount, buyingOptions, charityOnly, conditionIds, conditions, deliveryCountry, deliveryOptions, deliveryPostalCode, excludeCategoryIds, excludeSellers, itemEndDate, itemStartDate, itemLocationCountry, itemLocationRegion, maxDeliveryCost, paymentMethods, pickupCountry, pickupPostalCode, pickupRadius, pickupRadiusUnit, price, priceCurrency, priorityListing, qualifiedPrograms, returnsAccepted, searchInDescription, sellerAccountTypes, sellers`.

Examples:
- `filter=price:[10..60],priceCurrency:USD`. The price filter "must be used with the priceCurrency filter."
- `filter=buyingOptions:{FIXED_PRICE|BEST_OFFER}`. Values are FIXED_PRICE, AUCTION, BEST_OFFER and CLASSIFIED_AD.
- `filter=conditions:{NEW}` (values NEW, USED, UNSPECIFIED) or `conditionIds:{1000}`.
- `filter=itemLocationCountry:US,deliveryCountry:US`
- `aspect_filter=categoryId:180506,Scale:{1:64}`. The aspect names "Scale" and "Brand" are **unverified** for this category. Confirm them with the Taxonomy API `getItemAspectsForCategory`, or with `fieldgroups=ASPECT_REFINEMENTS` on a search.

### Auth model
- Every Browse method needs an **Application access token** from the OAuth **client credentials grant**: "All methods in the Browse API require an Application access token". **Verified** ([browse_api.md](https://developer.ebay.com/develop/api/buy/browse_api.md)).
- Scope: `https://api.ebay.com/oauth/api_scope`. eBay Developer Support stated this in a community thread ([thread](https://community.ebay.com/t5/eBay-APIs-Talk-to-your-fellow/Trying-to-access-some-of-the-end-points-and-getting-permission/m-p/34345698)). **Verified via snippet.**
- Token endpoint: `POST https://api.ebay.com/identity/v1/oauth2/token` with `grant_type=client_credentials` and Basic auth (`client_id:client_secret`). Tokens last about 2 hours. **Unverified** (from memory, standard eBay OAuth).
- Marketplace header: `X-EBAY-C-MARKETPLACE-ID: EBAY_US`.

### Call limits and cost
- Default limit: Browse API "All methods except getItems": "5000 API calls per day". **Verified** ([api_call_limits](https://developer.ebay.com/develop/api/buy/api_call_limits)).
- The free tier is described as "No time limit -- always free!" and "5,000 API calls per day". **Verified** (developer.ebay.com page chrome).
- Higher limits require an **Application Growth Check**, which eBay describes as free. A community report mentions a raise to 100k per day after a ticket. That is anecdotal and **unverified** ([KB 1362](https://developer.ebay.com/support/knowledge-base/1362), [forum](https://community.ebay.com/t5/APIs-Feedback-Comments-and/Get-unlimited-or-very-high-API-Call-limit-per-day/m-p/34508078/highlight/true)).
- There is also a short-window rate limit on bursts. Usage can be checked with the Developer Analytics API `getRateLimits`.
- Sizing: 5,000 calls per day at up to 200 items per call is plenty for a catalogue of a few hundred SKUs refreshed several times a day.

### Production access requirements
- The Developers Program is **free**. You register with an email (business email recommended), accept the API License Agreement, and wait "approximately 1 business day for account approval." **Verified via snippet** ([get started](https://developer.ebay.com/develop/guides/get-started-with-ebay-apis), [join EDP](https://edp.ebay.com/api-docs/static/gs_join-the-ebay-developers-program.html)).
- Sandbox and Production keysets are separate. Create the Production keyset on the Application Keys page.
- Buy APIs: the Buy requirements page says "Many of the Buy APIs are a Limited Release" and limited-release APIs need an application "through the eBay Partner Network" ([buy-requirements](https://www.developer.ebay.com/api-docs/buy/buy-requirements.html)). eBay Developer Support has said most Browse methods are "not restricted and open to all the partners" (snippet). So Browse `search`/`getItem` should work with a normal Production keyset. **Partly verified.** Confirm by calling `search` once the keyset is active.
- **Marketplace Account Deletion notification (keyset gate).** "All active eBay Developers Program applications are required to subscribe" to these notifications, and "Failure to comply with this requirement will result in termination of your access". **Verified** ([marketplace-account-deletion](https://www.developer.ebay.com/marketplace-account-deletion)). There are two options:
  1. **Opt out (exemption):** switch on "Not persisting eBay data" on the Alerts & Notifications page and pick a reason. This is meant for apps that do not store eBay user data. A price tracker that stores only item prices and IDs, and no seller or buyer personal data, plausibly qualifies. Whether eBay accepts that is **unverified**.
  2. **Subscribe:** host a public **HTTPS** endpoint. It cannot be localhost or an internal IP. It must answer eBay's GET challenge with a SHA-256 hash of challengeCode + verificationToken + endpoint URL, then return 200 OK on POSTed deletion notices.
  - Forum threads report that the Production keyset stays disabled until one of these is done, and that users sometimes pick Sandbox instead of Production by mistake.

### eBay category IDs (EBAY_US)
| ID | Name | Status |
|---|---|---|
| 222 | Diecast & Toy Vehicles | **Verified** from eBay browse URLs such as `ebay.com/b/Ebbro-Diecast-Toy-Vehicles/222/...` |
| 180506 | Contemporary Manufacture (Diecast Cars, Trucks & Vans) | **Verified**: [ebay.com/b/Contemporary-Manufacture-Diecast-Cars-Trucks-Vans/180506/bn_1865032](https://www.ebay.com/b/Contemporary-Manufacture-Diecast-Cars-Trucks-Vans/180506/bn_1865032). Breadcrumb: Toys & Hobbies > Diecast & Toy Vehicles > Cars, Trucks & Vans > Contemporary Manufacture. Brand and scale sub-pages exist under it, e.g. OTTOMOBILE and "AUTOart 1:18". |
| (parent) Cars, Trucks & Vans | ID **unverified** | Use the Taxonomy API |
| Vintage Manufacture | ID **unverified** | Use the Taxonomy API |

Before hard-coding these, call Taxonomy API `getCategorySubtree` (category_tree_id 0 = EBAY_US, category 222). Taxonomy uses the same app token.

---

## 2. Sold-price data from eBay

### Marketplace Insights API (`item_sales/search`)
- Status: **Limited Release.** The docs say it is available only to select developers approved by business units. It returns sales history "up to 90 days in the past." The API "does not support all of the eBay categories". Allowed categories are vetted and whitelisted per partner. **Verified via snippets** ([overview](https://developer.ebay.com/api-docs/buy/marketplace-insights/overview.html), [methods](https://developer.ebay.com/api-docs/buy/marketplace-insights/resources/methods)).
- The API License Agreement also counts it as a **Restricted API**, which it defines as APIs that "provide information about market trends, pricing strategies, sales volumes". **Verified** ([API License Agreement](https://www.edp.ebay.com/join/api-license-agreement)).
- **Realistic for a solo small store: very unlikely.** There is no public application form. Community advice is to open a Developer Support ticket describing the use case. eBay says approval is by business units and not guaranteed. Treat it as unavailable.

### Finding API `findCompletedItems`
- **Decommissioned.** eBay docs: "All calls in the Finding API will be decommissioned on February 5, 2025." `findCompletedItems` had been restricted since October 15, 2020. Developer Support later confirmed the Finding API "has been decommissioned." **Verified via snippets** ([API deprecation status](https://developer.ebay.com/develop/apis/api-deprecation-status), [findCompletedItems ref](https://developer.ebay.com/DevZone/finding/CallRef/findCompletedItems.html), [community](https://community.ebay.com/t5/Traditional-APIs-Search/Please-help-me-I-m-hitting-the-rate-limit-without-even-one-call/td-p/35025967)).

### Terapeak / Product Research (Seller Hub) is the legitimate sold-price source
- **Free to all sellers** in Seller Hub > Research > Product research. It shows "Actual sold price (incl. the accepted price for Best Offer listings)", average sold price, range and trend. Date ranges run "anywhere from one day to 3 years". **Verified via snippet** ([eBay help: Product research](https://www.ebay.com/help/selling/selling-tools/product-research?id=4853)).
- Access requires a Seller Hub account, and eBay help says you need at least one sale before opting in (snippet). Saafir's store selling account should qualify.
- **No API.** I found no Terapeak or Product Research developer API. The old `api.terapeak.com` is not a current eBay product. **Export:** none documented. Community posts say you "can't export." **Unverified/likely no export.** It is manual lookup only. Don't automate the Seller Hub UI, because that falls under the User Agreement's automated-means ban (section 3).
- "Sourcing Insights" is a separate tool, free with a Basic store subscription or higher (snippet; **unverified**).

---

## 3. eBay terms on scraping, storage and price analytics (important)

### eBay User Agreement (applies to the website)
The current text was posted 2026-01-20 and took effect 2026-02-20 for existing users ([The Register](https://www.theregister.com/2026/01/22/ebay_updates_legalese_to_ban/), [Value Added Resource](https://www.valueaddedresource.net/ebay-bans-ai-agents-updates-arbitration-user-agreement-feb-2026/)). The official page sits behind a bot check and could not be fetched directly ([User Agreement](https://www.ebay.com/help/policies/member-behaviour-policies/user-agreement?id=4259)).

The User Agreement prohibits using:
> "any robot, spider, scraper, data mining tools, data gathering and extraction tools,"
> "or other automated means … to access our Services for any purpose,"
> "except with the prior express permission of eBay;"

(The 2026 update adds "buy-for-me agents, LLM-driven bots" to the parenthetical.) A related clause bars circumventing robot exclusion headers and technical measures.

**eBay robots.txt** ([ebay.com/robots.txt](https://www.ebay.com/robots.txt)), **verified**: "The use of robots or other automated means to access the eBay site" … "without the express permission of eBay is strictly prohibited." `/sch/` (search results) is disallowed for `User-agent: *`.

**Conclusion: do not scrape eBay search or sold pages. Use the Browse API for actives and Product Research manually for solds.**

### eBay API License Agreement (applies to API data)
Source: [edp.ebay.com/join/api-license-agreement](https://www.edp.ebay.com/join/api-license-agreement). The page shows "Sept 3, 2025". Amendments take effect 30 days after posting. **Verified quotes:**

- **§9.5 (prohibited without eBay consent):** "Use eBay Content, either alone or in combination with third-party information," / "to suggest or model prices for items listed on eBay Site."
- **§9 lead-in:** you may not use eBay Services in ways that "undermine eBay's business interests without eBay's prior written consent."
- **§8.1(d)(1):** "express prior written permission" is needed to use eBay Content "in any way that enables derivation of" items including "Average selling price or gross merchandise sold for any eBay category."
- **§8.1(c) freshness:** "Displayed item listing information may not be more than six (6) hours older" than eBay. Other eBay Content must be no more than 24 hours older.
- **§8.1(b):** "When the eBay Content is no longer publicly available, you must delete it from your Application."
- **§3.1(b):** "Making limited intermediate copies of eBay Content only as necessary". "All intermediate copies must be deleted when they are no longer required".
- **§9.7:** no "copy, store or modify eBay Content," "other than for the purposes allowed by this API License Agreement."
- **§16.3:** on termination, destroy eBay Content "within ten (10) days after termination".
- **§8.1(b) co-mingling:** "eBay Content in a Public Display may not be co-mingled or combined with non-eBay Content." This applies to public display, not a private internal tool.
- **§8.5 / Restricted APIs (June 2025 change):** Restricted API data may not go into third-party generative AI tools without eBay's written consent ([EcommerceBytes](https://www.ecommercebytes.com/2025/07/18/ebay-restricts-developers-from-using-its-data-to-train-ai/)).

**What this means for the tracker (my reading, not legal advice):**
1. A long-lived historical database of eBay listing prices used to compute "market price" for items on eBay sits close to §9.5 ("model prices") and §8.1(d) (average prices). The safest pattern is **live lookup**: query Browse when Saafir checks a SKU, show the current lowest and median ask with links, and keep cached eBay results for no more than 6 hours (24 hours at most). Delete listings that have ended. Don't build a permanent eBay price history.
2. Saafir's own records are not eBay Content. That includes what they paid, what they sold for, and notes they type in after a manual Product Research lookup. §1 excludes info "you lawfully obtain independent of eBay." Whether manual notes taken from Terapeak count as "independent" is a gray area and **unverified**. Storing a single "Terapeak median I observed on date X" figure that they typed in themself is low risk, but it is not explicitly blessed.
3. Keep it **private and internal**. Don't resell, publish or share the eBay-derived data.
4. If the tool grows beyond personal use, ask eBay Developer Support (or a lawyer) whether internal restock pricing is acceptable under §9.5.

---

## 4. Other sources

### Mercari (US)
- **No public developer API** was found. **Unverified absence.** Third-party "Mercari API" products are scrapers of Mercari's internal GraphQL.
- The Prohibited Conduct policy bans using "any robot, spambot, spider, crawler, scraper or other automated means" (snippet). **Verified via snippet** ([prohibited conduct](https://www.mercari.com/us/help_center/topics/account/policies/prohibited-conduct/)). The ToS page shows a new version "Effective November 5, 2026" ([ToS](https://www.mercari.com/us/help_center/topics/account/policies/terms-of-service/)).
- robots.txt does not block listing pages for `*`, but the ToS ban governs. **Use manually only.** Mercari's sold filter is a good manual cross-check.

### Facebook Marketplace
- **No general developer API.** Meta's Content Library API has a Marketplace endpoint limited to qualified academic and nonprofit researchers (secondary source, **unverified**).
- Meta's [Automated Data Collection terms](https://developers.facebook.com/docs/development/terms-and-policies/automated-data-collection/) prohibit automated collection without prior written permission. **Manual only.**

### Etsy
- Etsy Open API v3 has `findAllListingsActive` (`GET /v3/application/listings/active`), which searches public active listings with an API key (`x-api-key`). Apps need approval: personal and commercial tiers, with reported waits of about 30 days. **Unverified** (third-party sources; etsy.com/legal/api returned 403).
- Etsy's API terms (updated 2025-06-16, per a secondary source) prohibit scraping. An archived version caps how stale displayed content can be at about 24 hours (**unverified**). Etsy has little Mini GT or Tarmac Works inventory, so it's **low priority**.

### hobbyDB
- It has a price guide ("Estimated Value") built from Price Points. Its marketplace sales are recorded automatically, and volunteers add completed eBay sales ([help](https://help.hobbydb.com/support/solutions/articles/36000247575)).
- **API exists but is paid and by application:** "Database Items, Estimated Values, Subjects and Items for Sale are all accessible through the API." It costs "a one-off set-up fee of at least $1,200" plus monthly charges. **Verified** ([Access to the hobbyDB API](https://help.hobbydb.com/support/solutions/articles/36000265069-access-to-the-hobbydb-api)).
- robots.txt allows general crawling. It declares "Content-Signal: search=yes, ai-input=yes, ai-train=no" and blocks named scraper tools. **Verified.** The hobbyDB ToS clause on scraping is **unverified** (not found).
- Coverage of new Mini GT and Tarmac releases is likely thin or volunteer-driven (**unverified**). It's useful for manual reference on older and rarer 1:18 pieces.

### Paid sold-price aggregators
- WorthPoint and similar services sell historical sold-price lookups. They are manual or subscription-based, and their terms on redistribution are **unverified**. Optional.

### Maker sites (checked 2026-10-26)
| Brand | Site | Platform / feed | Sells direct? | Notes |
|---|---|---|---|---|
| Mini GT (TSM) | [minigt.tsm-models.com](https://minigt.tsm-models.com/) (minigt.com redirects here); parent [tsm-models.com](https://tsm-models.com) | Not Shopify | No prices or cart on the Mini GT site | Good **catalogue source**: MGT SKUs (e.g. #MGT01417) and news. Has a "Distributions" section; only Chicane (AU) was visible. US distributor not listed on the page. |
| Tarmac Works | [tarmacworks.com](https://www.tarmacworks.com) | **Shopify** (cdn.shopify.com) | Yes (Shop) plus a "Where to buy" page | robots.txt is the standard Shopify file (disallows /cart, /checkout, /account; does not disallow /products). `/products.json?limit=1` returned **429 rate limited** to a plain request, so the endpoint exists but is throttled. Their ToS page had no visible scraping clause (content didn't render). Only light, polite use, or none. |
| Pop Race | No official site confirmed. poprace.com redirects to tiny.com.hk | n/a | n/a | **Unverified** official domain |
| Inno Models / Inno64 | [inno-models.com](https://www.inno-models.com) | WordPress / WooCommerce | Yes | robots.txt (Yoast) allows all except wp-admin and WC logs. WooCommerce Store API (`/wp-json/wc/store/products`) may be public; **not tested**. |
| GT Spirit | No official domain confirmed. gtspirit.com is an unrelated car blog; gt-spirit.com did not respond | n/a | n/a | **Unverified** |
| OttOmobile | [otto-models.com](https://otto-models.com/fr/) (ottomobile.fr is an unrelated car dealer) | PrestaShop | Yes (EU, French) | robots.txt not checked |
| BM Creations | No official site confirmed. bmcreations.com is an unrelated marketing agency | n/a | n/a | **Unverified** |
| Minichamps | [minichamps.de](https://www.minichamps.de) | Shopware | Yes (EU) | robots.txt allows `/` but disallows `/*?` (query URLs), account and checkout |
| Spark | [sparkmodel.com](https://www.sparkmodel.com) ("SparkmodelWeb") | Unknown | Catalogue | robots.txt returned 404 |

None of the makers publish a documented public price feed or affiliate product feed that I could find (**unverified absence**). They're best used as **catalogue and MSRP references**, not market prices.

### Shopify retailer storefronts (competitor asking prices)
- Many US and Canadian diecast retailers run Shopify (e.g. ModelCars.com, Downskale, Turbo Diecast, Hanz Driven; seen in search results, **platforms not individually verified**).
- Shopify's documented, unauthenticated **Ajax API** (`/products/{handle}.js`) returns product JSON for one product ([shopify.dev Ajax Product API](https://shopify.dev/docs/api/ajax/reference/product)). The bulk `/products.json` is undocumented but common, and it is rate-limited (Tarmac returned 429).
- Each store's own Terms of Service governs automated access. Many Shopify themes' ToS forbid scraping. Check robots.txt and ToS per store before polling. Use a low frequency (daily at most) and an honest User-Agent, and stop if asked.

### Distributors / wholesale (for actual restock cost)
These are leads only. Wholesale price lists are behind dealer accounts, and **none of the following is verified**:
- **M & J Toys Inc.** ([mjtoysinc.com](https://www.mjtoysinc.com/brand/mini-gt/)): "Die-Cast Distribution", "Since 1987". Lists Mini GT (and per search, Tarmac Works). Likely a US wholesaler; ask about a dealer account.
- **Hanz Driven** (Canada): search results show an "Inno64 Distribution" page with a call for shops to carry Inno64, plus "Pop Race & Inno64 Wholesale". The page returned 404 when fetched.
- **Five Diecast** ([fivediecast.com](https://fivediecast.com/manufacturer/mini-gt/)) claims to be an authorized US Mini GT dealer. It is a retailer, not confirmed as a distributor.
- Contact Mini GT/TSM (Distributions section), Tarmac Works ("Where to buy"), Inno Models, Minichamps and Spark directly to ask who their North American importer is. Dealer price lists typically require a resale certificate and business details. Saafir must do this themself.

---

## 5. Recommended approach for a solo store owner

**Phase 1: quick wins, no code needed**
1. **Seller Hub > Research > Product research** (free): sold prices for up to 3 years, manually, per SKU, when deciding a restock. Record Saafir's own observed numbers and their own costs in the tracker.
2. **Wholesale costs:** contact distributors (M&J Toys, Hanz Driven for Inno64/Pop Race, brand "Where to buy"/distribution pages). Real dealer cost is the key input for "buy under market."

**Phase 2: automate active asks via the eBay Browse API**
3. Saafir creates (only they can do this):
   - an **eBay Developers Program account** (free, about 1 business day approval) at developer.ebay.com, accepting the API License Agreement;
   - a **Production keyset** (App ID / Client ID + Cert ID / Client Secret);
   - the **Marketplace Account Deletion** setting: choose **"Not persisting eBay data"** (opt-out) if the tracker stores no eBay user data, or else host an HTTPS endpoint. Without this the Production keyset stays disabled.
   - Store the keys in a local `.env` or OS keychain, never in git.
4. The tracker uses client-credentials tokens and calls `item_summary/search` per SKU with, for example, `q="Mini GT MGT00636"`, `category_ids=180506` (or 222), and `filter=conditions:{NEW},itemLocationCountry:US,priceCurrency:USD,buyingOptions:{FIXED_PRICE|BEST_OFFER}`. Compute lowest and median ask including shipping, and show links.
5. Compliance guardrails: keep eBay results at most 6 hours old, purge ended listings, keep no long-term eBay price history, use it privately and internally only, and stay under 5,000 calls per day.

**Phase 3 (optional)**
6. Competitor Shopify retail prices, polled politely (daily, `/products/{handle}.js`) only where robots.txt and ToS allow. This gives a "retail ceiling" price.
7. hobbyDB API only if budget allows (from $1,200 setup plus monthly). Marketplace Insights is not realistic.

**Don'ts:** don't scrape eBay, Mercari or Facebook Marketplace pages, and don't automate Seller Hub or Terapeak. All of these are prohibited by their terms. Also don't feed eBay API data into third-party AI tools if any Restricted API is ever obtained.

---

## Unverified items to double-check
- Browse OAuth token lifetime (about 2 hours) and the exact itemSummary fields returned by default.
- Whether Browse `search` works immediately on a new Production keyset without an EPN application. Developer Support says most methods are open; test it.
- Whether eBay accepts the "Not persisting eBay data" opt-out for this use case.
- Category IDs for "Cars, Trucks & Vans" and "Vintage Manufacture", and the exact aspect names ("Scale", "Brand") in 180506.
- Whether Product Research can export results (likely not).
- Etsy API terms details, hobbyDB ToS scraping clause, and Mercari policy currency.
- Official sites for Pop Race, GT Spirit and BM Creations, and US distributors for every brand.
