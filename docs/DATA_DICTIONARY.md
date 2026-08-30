# Data dictionary — the 18 source "worksheets"

Every file in `sources/` mimics the export of a real system: its own format,
its own date convention, its own bad habits. Row counts below are exact —
the generator is seeded, so they are identical on every rebuild.

Sources marked **[flattened]** contribute columns to `flat_sales.csv`;
sources marked **[side table]** describe months rather than order lines and
feed the dashboard's aggregate charts directly.

---

## 1. `crm_customers.csv` — CRM · CSV · 800 rows **[flattened]**

Who the customers are. The dirtiest source by design.

| Column | Type | Notes |
|---|---|---|
| customer_id | text | `C20000`… primary key |
| full_name | text | person or company name |
| email | text | |
| segment | text | Consumer, Outdoor Pro, Corporate & Team, Reseller |
| region | text | **messy**: `NA`, `na`, `" EMEA "` — conformed by the ETL |
| signup_date | date | **m/d/Y** format (`2/13/2024`) |
| marketing_opt_in | bool | |

Feeds: `customer_name`, `segment`, `region` (conformed to full names).

## 2. `erp_sales.db` — ERP · SQLite · 3,650 orders + 7,858 lines **[flattened — the grain]**

The transactional system of record. Two tables:

**`orders`**

| Column | Type | Notes |
|---|---|---|
| order_id | text | `SO10000`… |
| customer_id | text | FK → CRM |
| order_date | date | ISO |
| channel | text | Online, Retail, Wholesale, Marketplace |
| store_id | text | null except Retail |
| rep_id | text | null except Wholesale / Corporate |
| campaign_id | text | null unless campaign-attributed |
| currency | text | USD / EUR / AUD / BRL by region |
| status | text | delivered, shipped, processing, cancelled (83 cancelled) |

**`order_items`** — one row per product per order; **this is the grain of
the flat table.**

| Column | Type | Notes |
|---|---|---|
| line_id | text | `L000001`… primary key |
| order_id | text | FK → orders |
| product_id | text | FK → catalog |
| qty | int | wholesale 3–12, consumer 1–3 |
| unit_price | float | list price ±2% |
| discount_pct | float | wholesale 0.20–0.40, promo 0.10–0.25 |

## 3. `product_catalog.json` — PIM · JSON · 120 rows **[flattened]**

| Column | Type | Notes |
|---|---|---|
| product_id | text | `P1000`… |
| name | text | e.g. "Cobalt Halcyon -18C" |
| category | text | 6 categories |
| subcategory | text | 19 subcategories |
| brand | text | 5 brands |
| list_price | float | USD |
| launch_date | date | ISO |

Feeds: `product_name`, `category`, `subcategory`, `brand`.

## 4. `inventory_snapshot.csv` — WMS · CSV · 600 rows **[flattened, aggregated]**

Stock by product × 5 warehouses as of the snapshot date. The ETL sums
`on_hand` per product before joining → `stock_on_hand`.

| Column | Type |
|---|---|
| product_id | text |
| warehouse | text |
| on_hand | int |
| reorder_point | int |
| inbound_units | int |
| snapshot_date | date |

## 5. `web_analytics.jsonl` — Web analytics · JSONL · 3,642 rows **[side table]**

Daily sessions per marketing channel. Aggregated to monthly
sessions/conversions for the conversion stat.

| Field | Type |
|---|---|
| date | date |
| channel_grouping | text |
| sessions | int |
| conversions | int |
| bounce_rate | float |

## 6. `marketing_campaigns.csv` — Marketing · CSV · 12 rows **[flattened]**

Campaign master: id, name, channel (Paid Search / Social / Email /
Affiliate), start/end dates, budget. Feeds `campaign_name`,
`campaign_channel` via the order's `campaign_id`.

## 7. `ad_spend_daily.csv` — Ad platforms · CSV · 690 rows **[side table]**

Daily spend per campaign per platform (Google Ads, Meta, TikTok…), with
impressions and clicks. Rolled up to monthly spend for the
spend-vs-attributed-revenue chart.

## 8. `email_stats.json` — Email platform · JSON · 24 rows **[side table]**

Monthly sends/delivered/opens/clicks/unsubs per email campaign plus a
recurring newsletter.

## 9. `support_tickets.csv` — Helpdesk · CSV · 900 rows **[flattened, aggregated]**

| Column | Type | Notes |
|---|---|---|
| ticket_id | text | |
| created_date | date | **DD-Mon-YYYY** format (`14-Mar-2026`) |
| customer_id | text | |
| order_id | text | 72% linked to an order, weighted toward late/returned |
| category | text | Shipping delay, Return help, … |
| priority / status / csat | text | |

The ETL counts tickets per order → `tickets_on_order`.

## 10. `nps_surveys.csv` — Survey tool · CSV · 1,100 rows **[flattened, aggregated]**

`response_id, survey_date, customer_id, score (0–10), comment`. Scores are
causally depressed for customers who experienced late deliveries or
returns. The ETL keeps the **latest score per customer** → `customer_nps`.

## 11. `shipping_tracking.csv` — Carrier feeds · CSV · 2,789 rows **[flattened]**

One shipment per non-retail order: carrier (region-appropriate — UPS/FedEx,
DHL/DPD, AusPost…), ship date, promised vs actual days, delivered date.
~12% run late. Feeds `carrier`, `promised_days`, `actual_days`,
`late_delivery`.

## 12. `returns_rma.csv` — Returns portal · CSV · 392 rows **[flattened]**

One RMA per returned **line** (`line_id` FK): return date, reason (Wrong
size, Changed mind, Not as described, Damaged in transit), refund amount,
condition. Footwear and apparel return at roughly double the base rate.
Feeds `returned`, `return_reason`.

## 13. `payment_gateway.jsonl` — Payments · JSONL · 3,673 rows **[flattened]**

One row per payment *attempt* (3% of orders need a retry). Currency codes
are **lowercase** — conformed by the ETL. The captured attempt feeds
`payment_method` (Card, PayPal, Apple Pay, Gift Card, Invoice, Wire).

## 14. `hr_sales_reps.csv` — HRIS · CSV · 16 rows **[flattened]**

Rep master: id, name, team, region, hire date, annual quota. Feeds
`rep_name`, `rep_team` (defaulting to "House" for unassigned orders).

## 15. `store_locations.json` — Store master · JSON · 24 rows **[flattened]**

Store id, name ("Cobalt Denver"), city, country, region, opened date, sqft.
Feeds `store_name` ("Digital" for non-retail orders).

## 16. `fx_rates.csv` — Treasury · CSV · 80 rows **[flattened, reference]**

Monthly `usd_rate` per currency (USD/EUR/AUD/BRL, random-walked). Looked up
by **(month, currency)** to convert local revenue → `revenue_usd`.

## 17. `finance_targets.csv` — Finance plan · CSV · 80 rows **[side table]**

Monthly revenue target per region, used for the target line and attainment
numbers on the trend chart.

## 18. `supplier_pricelist.xml` — Procurement · XML · 120 rows **[flattened, reference]**

`<product id supplier unit_cost_usd lead_time_days/>` per product. Unit
costs (42–62% of list price) feed `unit_cost_usd` → `cost_usd` →
`margin_usd`.

---

## 19. `incoming/warranty_registrations.txt` — Warranty portal · TXT · 1,100 rows **[flattened via gated AI mapping]**

The unknown source: pipe-delimited, `DD.MM.YYYY` dates, `SKU-` prefixed
products, alien channel/region codes, and a prompt-injection canary. Its
columns are documented by the mapping itself — see the
[recorded proposal](../mapper/recorded/proposal.json) and
[AGENTIC_MAPPING.md](AGENTIC_MAPPING.md). It reaches the flat table only
through `warehouse/warranty_conformed.csv`, which exists only when a model's
proposed mapping passes all eleven deterministic gates. Feeds
`registered_warranty`, `warranty_years` (aggregate-first per
customer + product + purchase date).

---

# The output: `warehouse/flat_sales.csv` — 7,670 rows × 45 columns

One row per order line (cancelled orders dropped). Columns by origin:

| Column | Type | Comes from |
|---|---|---|
| line_id, order_id, order_date, month | keys/date | ERP |
| customer_id, customer_name, segment, region | dim | CRM (region conformed) |
| channel, order_status, currency | fact attrs | ERP |
| store_id, store_name | dim | Store master |
| rep_id, rep_name, rep_team | dim | HRIS |
| campaign_id, campaign_name, campaign_channel | dim | Marketing |
| product_id, product_name, category, subcategory, brand | dim | PIM |
| qty, unit_price, discount_pct | measures | ERP |
| fx_usd_rate | reference | Treasury |
| revenue_local, revenue_usd | derived | ERP × FX |
| unit_cost_usd, cost_usd, margin_usd | derived | Procurement XML |
| carrier, promised_days, actual_days, late_delivery | event | Carrier feeds |
| returned, return_reason | event | Returns portal |
| payment_method | event | Payment gateway |
| tickets_on_order | aggregate | Helpdesk (count per order) |
| customer_nps | aggregate | Surveys (latest per customer) |
| stock_on_hand | aggregate snapshot | WMS (sum per product) |
| registered_warranty, warranty_years | aggregate | Warranty portal — via the gated AI mapping |

**Reading caveats** (inherent to flat tables): `tickets_on_order` and
`customer_nps` repeat on every line of an order — dedupe by `order_id`
before summing or averaging. `stock_on_hand` is a point-in-time snapshot
repeated per row — never SUM it. See
[STAR_SCHEMA.md](STAR_SCHEMA.md#what-flattening-costs) for the full list.
