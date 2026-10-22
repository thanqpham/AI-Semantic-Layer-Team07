# Retail metric benchmark from the current seed

This note records reproducible expected values for testing metric suggestions against `data/golden_retail_seed_pg.sql`.

## Scope and population

- Seed size: 5,000 orders, 15,035 order lines, 8,000 web sessions, 200 items, and 1,000 customers.
- All stores with completed, non-test orders use VND.
- Sales metrics below include orders where `Is_Completed = '1'`, `Is_Canceled = '0'`, and `Is_Test_Order = '0'`.
- Cancellation rate uses all non-test orders as its denominator.
- The seed contains no returned units or return amounts. Return-related metrics therefore have no useful positive-value test case.
- Values were calculated from the checked-in seed in an in-memory SQLite database. The PostgreSQL-specific foreign-key `ALTER TABLE` statements and seed session setting were omitted for SQLite compatibility; seed rows were not changed.

## Metric definitions and expected values

| Metric | Definition for this benchmark | Expected |
|---|---|---:|
| Net sales, excluding tax | `SUM(Price_Before_Tax - Total_Discount_Value - Return_Amount)` on the sales population | **118,205,628,750 VND** |
| Completed order count | Count of orders in the sales population | **3,116 orders** |
| Average order value | Net sales / completed order count | **37,935,054.16 VND/order** |
| Units sold, net | `SUM(Quantity - COALESCE(Return_Quantity, 0))` for non-canceled lines in the sales population | **18,920 units** |
| Gross margin | `(net sales - COGS) / net sales`; COGS is `SUM(Current_Item_Cost * (Quantity - COALESCE(Return_Quantity, 0)))` for eligible lines | **16.0668%** (gross profit **18,991,828,750 VND**) |
| Checkout conversion rate | Non-bot sessions with `Completed_Checkout = '1'` / all non-bot sessions | **62.50%** (4,834 / 7,734 sessions) |
| Order cancellation rate | Non-test orders with `Is_Canceled = '1'` / all non-test orders | **11.4106%** (563 / 4,934 orders) |

For a dimensional check, net sales and completed order count by sales channel are:

| Sales channel | Net sales (VND) | Orders |
|---|---:|---:|
| Shopee Marketplace | 24,929,741,250 | 651 |
| Lazada Marketplace | 23,586,987,375 | 615 |
| Website E-Commerce | 23,556,440,250 | 610 |
| Mobile App | 23,426,337,375 | 628 |
| POS Store Direct | 22,706,122,500 | 612 |

## Interpretation caveats

These are operational benchmark metrics, not a substitute for accounting revenue recognition or cash collected. Use “net sales, excluding tax” in prompts to remove ambiguity: the seed stores pre-discount order totals in tax-inclusive fields as well as `Price_Before_Tax`, and this benchmark deliberately uses the latter. State the same order population for the numerator and denominator of AOV. A return-rate metric cannot be meaningfully validated against this seed because all return amounts and quantities are zero.

## Primary sources

- Shopify, [Sales reports: common terms](https://help.shopify.com/en/manual/reports-and-analytics/shopify-reports/report-types/default-reports/sales-report#common-sales-report-terms) — sales, net sales, AOV, discounts, and reversals.
- Shopify, [Sales reports: sales versus payments](https://help.shopify.com/en/manual/reports-and-analytics/shopify-reports/report-types/default-reports/sales-report#sales-versus-payments) — sales reports do not measure payments received.
- Shopify, [Profit reports: gross profit by product](https://help.shopify.com/en/manual/reports-and-analytics/shopify-reports/report-types/default-reports/profit-reports#gross-profit-by-product) — gross margin calculation and cost-data caveats.
- Google Analytics, [Ecommerce events](https://developers.google.com/analytics/devguides/collection/ga4/ecommerce) — ecommerce event and item-level price/quantity conventions.
- IFRS Foundation, [IFRS 15 Revenue from Contracts with Customers](https://www.ifrs.org/issued-standards/list-of-standards/ifrs-15-revenue-from-contracts-with-customers/) — authoritative accounting revenue-recognition framework.
