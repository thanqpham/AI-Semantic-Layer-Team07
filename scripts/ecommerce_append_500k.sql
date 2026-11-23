-- Append synthetic DB ID 3 data: 100k to 500k, or 500k to 1m; default is rollback.
-- Use -v apply=true to commit after inspecting a successful rehearsal.
\set ON_ERROR_STOP on
\if :{?target_orders}
\else
\set target_orders 500000
\endif
\if :{?apply}
\else
\set apply false
\endif

BEGIN ISOLATION LEVEL REPEATABLE READ;
SET LOCAL lock_timeout = '5s';
SET LOCAL max_parallel_workers_per_gather = 0;
SELECT set_config('issue51.target_orders', :'target_orders', true);
SELECT set_config('issue51.apply', :'apply', true);
SELECT set_config('issue51.base_orders',
 CASE WHEN current_setting('issue51.target_orders')::integer > 500000 THEN '500000' ELSE '100000' END, true);
LOCK TABLE orders, order_items, payments, order_facts, shipments, shipment_events,
 product_returns, return_items, refunds, coupon_redemptions, order_taxes, product_reviews,
 support_tickets, carts, cart_items, web_sessions, web_events, inventory_movements,
 operating_expenses, finance_daily, finance_monthly, aging_balances, funnel_daily,
 fulfillment_daily IN SHARE ROW EXCLUSIVE MODE;
LOCK TABLE customers, products, categories, tax_rates, promotions, warehouses,
 inventory_snapshots, supplier_invoices IN SHARE MODE;

DO $$
DECLARE goal integer := current_setting('issue51.target_orders')::integer;
        base integer := current_setting('issue51.base_orders')::integer;
BEGIN
    IF current_database() <> 'ecommerce_dashboard_demo' THEN
        RAISE EXCEPTION 'Only DB ID 3 ecommerce_dashboard_demo is supported';
    END IF;
    IF goal < 100001 OR goal > 1000000 THEN
        RAISE EXCEPTION 'Target must be between 100001 and 1000000';
    END IF;
    IF current_setting('issue51.apply')::boolean AND goal NOT IN (500000,1000000) THEN
        IF base=100000 THEN
            RAISE EXCEPTION 'Commit is supported only for the full 500000-order target';
        END IF;
        RAISE EXCEPTION 'Commit requires an exact supported target';
    END IF;
    IF (SELECT count(*) FROM orders) <> base OR (SELECT min(id) FROM orders) <> 1
       OR (SELECT max(id) FROM orders) <> base OR (SELECT count(*) FROM order_facts) <> base
       OR (SELECT count(*) FROM order_items) <> 2*base OR (SELECT max(id) FROM order_items) <> 2*base+1 THEN
        RAISE EXCEPTION 'Expected the complete %-order DB 3 baseline; refusing append',base;
    END IF;
END $$;

SELECT set_config('issue51.old_cart_max', coalesce((SELECT max(id) FROM carts),0)::text, true);
SELECT set_config('issue51.old_session_max', coalesce((SELECT max(id) FROM web_sessions),0)::text, true);

INSERT INTO orders
SELECT n,1+(n*17)%360,
 (CURRENT_DATE-729+((n-1)%730))::timestamp + make_interval(hours=>8+((n-1)/730)%12),
 CASE WHEN n%10<5 THEN 'Web' WHEN n%10<8 THEN 'Mobile' ELSE 'Marketplace' END,
 CASE WHEN n%23=0 THEN 'returned' WHEN n%17=0 THEN 'cancelled' ELSE 'completed' END
FROM generate_series(current_setting('issue51.base_orders')::integer+1,current_setting('issue51.target_orders')::integer) n;

INSERT INTO order_items
SELECT v.item_id,v.order_id,p.id,
 CASE WHEN v.item_id%10<5 THEN 1 WHEN v.item_id%10<8 THEN 2 WHEN v.item_id%10=8 THEN 3 ELSE 5 END,
 round(p.unit_price * CASE c.region WHEN 'South' THEN 1.28 WHEN 'North' THEN 1.14
       WHEN 'West' THEN 0.97 ELSE 0.88 END *
       (1+0.14*sin(2*pi()*extract(month FROM o.ordered_at)::double precision/12)::numeric+((o.id%5)-2)*0.01),2),
 round(p.unit_cost * CASE c.region WHEN 'South' THEN 1.01 WHEN 'North' THEN 1.04
       WHEN 'West' THEN 1.12 ELSE 1.07 END * (0.98+(v.item_id%5)*0.015),2)
FROM (SELECT o.id AS order_id,o.id*2+n AS item_id,n AS line FROM orders o
      CROSS JOIN generate_series(0,1) n WHERE o.id>current_setting('issue51.base_orders')::integer) v
JOIN orders o ON o.id=v.order_id JOIN customers c ON c.id=o.customer_id
JOIN products p ON p.id=1+(o.id*7+v.line*11)%48;

INSERT INTO payments
SELECT o.id,o.id,o.ordered_at::date+CASE WHEN o.id%10<6 THEN 0 WHEN o.id%10<9 THEN 2 ELSE 5 END,
 CASE WHEN o.id%10<6 THEN 'Card' WHEN o.id%10<9 THEN 'Wallet' ELSE 'Bank transfer' END,
 sum(i.quantity*i.unit_price)
FROM orders o JOIN order_items i ON i.order_id=o.id
WHERE o.id>current_setting('issue51.base_orders')::integer AND o.order_status='completed' AND o.id%7<>0 GROUP BY o.id;

INSERT INTO order_facts
SELECT o.id,o.ordered_at::date,o.channel,c.region,c.customer_segment,o.order_status,
 CASE WHEN o.order_status='completed' THEN sum(i.quantity*i.unit_price) ELSE 0 END,
 CASE WHEN o.order_status='completed' THEN sum(i.quantity*i.unit_cost) ELSE 0 END,
 CASE WHEN o.order_status='completed' THEN sum(i.quantity*(i.unit_price-i.unit_cost)) ELSE 0 END,
 coalesce(max(p.amount),0)
FROM orders o JOIN customers c ON c.id=o.customer_id JOIN order_items i ON i.order_id=o.id
LEFT JOIN payments p ON p.order_id=o.id WHERE o.id>current_setting('issue51.base_orders')::integer GROUP BY o.id,c.region,c.customer_segment;

INSERT INTO shipments
SELECT o.id,o.id,CASE WHEN o.id%10<4 THEN 1 WHEN o.id%10<7 THEN 2 WHEN o.id%10<9 THEN 3 ELSE 4 END,
 CASE WHEN o.id%10<5 THEN 'FastShip' WHEN o.id%10<8 THEN 'ParcelGo' ELSE 'LocalPost' END,
 o.ordered_at::date+1,o.ordered_at::date+1+CASE WHEN o.id%10<5 THEN 2+o.id%2
      WHEN o.id%10<8 THEN 4+o.id%2 ELSE 6+o.id%3 END,'delivered'
FROM orders o WHERE o.id>current_setting('issue51.base_orders')::integer AND o.order_status='completed';

INSERT INTO shipment_events
SELECT s.id*2+n,s.id,CASE WHEN n=0 THEN s.shipped_on ELSE s.delivered_on END,
 CASE WHEN n=0 THEN 'shipped' ELSE 'delivered' END
FROM shipments s CROSS JOIN generate_series(0,1) n WHERE s.order_id>current_setting('issue51.base_orders')::integer;

INSERT INTO product_returns
SELECT o.id,o.id,o.ordered_at::date+CASE WHEN o.id%10<5 THEN 6 WHEN o.id%10<8 THEN 10 ELSE 17 END,
 CASE WHEN o.id%10<5 THEN 'Damaged' WHEN o.id%10<8 THEN 'Wrong item' ELSE 'Changed mind' END,'approved'
FROM orders o JOIN payments p ON p.order_id=o.id WHERE o.id>current_setting('issue51.base_orders')::integer AND o.id%37=0;

INSERT INTO return_items
SELECT i.id,r.id,i.id,i.quantity FROM product_returns r JOIN order_items i ON i.order_id=r.order_id
WHERE r.order_id>current_setting('issue51.base_orders')::integer;
INSERT INTO refunds
SELECT r.id,r.id,r.requested_on+CASE WHEN r.id%10<7 THEN 2 ELSE 5 END,f.net_revenue
FROM product_returns r JOIN order_facts f ON f.order_id=r.order_id WHERE r.order_id>current_setting('issue51.base_orders')::integer;
INSERT INTO coupon_redemptions
SELECT o.id,o.id,p.id,o.ordered_at::date,round(f.net_revenue*p.discount_pct/100,2)
FROM orders o JOIN order_facts f ON f.order_id=o.id JOIN promotions p ON p.id=1+o.id%8
WHERE o.id>current_setting('issue51.base_orders')::integer AND o.order_status='completed' AND o.id%13=0
 AND o.ordered_at::date BETWEEN p.starts_on AND p.ends_on;
INSERT INTO order_taxes
SELECT f.order_id,f.net_revenue,round(sum(i.quantity*i.unit_price*r.tax_pct/100),2)
FROM order_facts f JOIN order_items i ON i.order_id=f.order_id JOIN products p ON p.id=i.product_id
JOIN tax_rates r ON r.category_id=p.category_id
WHERE f.order_id>current_setting('issue51.base_orders')::integer AND f.order_status='completed' GROUP BY f.order_id,f.net_revenue;
INSERT INTO product_reviews
SELECT i.id,i.product_id,o.customer_id,o.id,
 CASE WHEN o.id%20=0 THEN 1 WHEN o.id%10=0 THEN 2 WHEN o.id%5=0 THEN 3 WHEN o.id%3=0 THEN 4 ELSE 5 END,
 o.ordered_at::date+4+i.id%9 FROM order_items i JOIN orders o ON o.id=i.order_id
WHERE o.id>current_setting('issue51.base_orders')::integer AND o.order_status='completed' AND i.id%5=0;
INSERT INTO support_tickets
SELECT n,o.customer_id,o.id,o.ordered_at::date+1+n%7,
 CASE WHEN n%10<5 THEN 'Delivery' WHEN n%10<8 THEN 'Payment' WHEN n%10=8 THEN 'Product' ELSE 'Return' END,
 CASE WHEN n%10<2 THEN 'open' ELSE 'resolved' END
FROM generate_series(1,600*current_setting('issue51.target_orders')::integer/5840) n
JOIN orders o ON o.id=n*9 WHERE o.id>current_setting('issue51.base_orders')::integer AND n>(SELECT coalesce(max(id),0) FROM support_tickets);

-- The 1m sale ID range avoids existing receipt and return IDs.
INSERT INTO inventory_movements
SELECT CASE WHEN current_setting('issue51.base_orders')::integer=500000 THEN 4000000+i.id ELSE i.id END,
 i.product_id,s.warehouse_id,i.id,o.ordered_at,'sale',-i.quantity
FROM order_items i JOIN orders o ON o.id=i.order_id JOIN shipments s ON s.order_id=o.id WHERE o.id>current_setting('issue51.base_orders')::integer;
INSERT INTO inventory_movements
SELECT 2000000+ri.id,i.product_id,s.warehouse_id,ri.order_item_id,r.requested_on+interval '1 day','return',ri.quantity
FROM return_items ri JOIN product_returns r ON r.id=ri.return_id JOIN order_items i ON i.id=ri.order_item_id
JOIN shipments s ON s.order_id=r.order_id WHERE r.order_id>current_setting('issue51.base_orders')::integer;

INSERT INTO carts
SELECT n,coalesce(o.customer_id,1+n%360),coalesce(o.ordered_at-interval '20 minutes',
 CURRENT_DATE-(n%10)*9-(n%640)+make_interval(hours=>9+n%10)),
 CASE WHEN o.id IS NOT NULL THEN 'converted' WHEN n%10<7 THEN 'abandoned' ELSE 'active' END,o.id
FROM generate_series(current_setting('issue51.old_cart_max')::integer+1,
 (4000::bigint*current_setting('issue51.target_orders')::integer/5840)::integer) n
LEFT JOIN orders o ON n%4=0 AND o.id=n;

-- The 1m cart-item ID ranges avoid existing base and bonus item IDs.
INSERT INTO cart_items
SELECT CASE WHEN current_setting('issue51.base_orders')::integer=500000 THEN 4000000+c.id*2+n ELSE c.id*2+n END,
 c.id,CASE WHEN (c.id*2+n)%10<6 THEN 1+(c.id*2+n)%18 ELSE 1+(c.id*2+n)%48 END,
 CASE WHEN (c.id*2+n)%10<6 THEN 1 WHEN (c.id*2+n)%10<9 THEN 2 ELSE 4 END
FROM carts c CROSS JOIN generate_series(0,1) n WHERE c.id>current_setting('issue51.old_cart_max')::integer;
INSERT INTO cart_items
SELECT CASE WHEN current_setting('issue51.base_orders')::integer=500000 THEN 6000000+c.id ELSE 1000000+c.id END,
 c.id,CASE WHEN (1000000+c.id)%10<6 THEN 1+(1000000+c.id)%18
 ELSE 1+(1000000+c.id)%48 END,CASE WHEN (1000000+c.id)%10<6 THEN 1
 WHEN (1000000+c.id)%10<9 THEN 2 ELSE 4 END
FROM carts c WHERE c.id>current_setting('issue51.old_cart_max')::integer AND c.id%4=0;

INSERT INTO web_sessions
SELECT n,coalesce(o.customer_id,1+n%360),coalesce(o.ordered_at-interval '6 minutes',
 CURRENT_DATE-CASE WHEN n%10<4 THEN n%90 ELSE n%730 END+make_interval(hours=>7+n%13)),
 CASE WHEN n%10<5 THEN 'Organic' WHEN n%10<8 THEN 'Paid search' WHEN n%10=8 THEN 'Social' ELSE 'Email' END,
 CASE WHEN n%10<6 THEN 'Mobile' WHEN n%10<9 THEN 'Desktop' ELSE 'Tablet' END,o.id
FROM generate_series(current_setting('issue51.old_session_max')::integer+1,
 (12000::bigint*current_setting('issue51.target_orders')::integer/5840)::integer) n
LEFT JOIN orders o ON n%4=0 AND o.id=1+n%current_setting('issue51.target_orders')::integer;
INSERT INTO web_events
SELECT s.id*3+n,s.id,s.started_at+make_interval(mins=>n*3),
 CASE WHEN n=0 THEN 'product_view' WHEN n=1 THEN 'add_to_cart'
      WHEN s.converted_order_id IS NOT NULL THEN 'purchase' ELSE 'checkout' END,
 1+(s.id*3+n*7)%48
FROM web_sessions s CROSS JOIN generate_series(0,2) n WHERE s.id>current_setting('issue51.old_session_max')::integer;

-- Extend day/month buckets without replacing existing transactions.
INSERT INTO operating_expenses
SELECT d::date,0,0,0 FROM generate_series((SELECT max(expense_date)+1 FROM operating_expenses),
 CURRENT_DATE,interval '1 day') d ON CONFLICT DO NOTHING;
INSERT INTO finance_daily SELECT expense_date,0,0,0,0,0,0,0 FROM operating_expenses ON CONFLICT DO NOTHING;
INSERT INTO funnel_daily SELECT expense_date,0,0,0 FROM operating_expenses ON CONFLICT DO NOTHING;
INSERT INTO fulfillment_daily SELECT expense_date,0,0,0,NULL FROM operating_expenses ON CONFLICT DO NOTHING;
INSERT INTO finance_monthly
SELECT DISTINCT date_trunc('month',expense_date)::date,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
FROM operating_expenses ON CONFLICT DO NOTHING;

WITH sales AS (SELECT ordered_on,count(*) FILTER (WHERE order_status='completed') n,
 sum(net_revenue) rev,sum(cogs) costs,sum(gross_profit) gross FROM order_facts GROUP BY ordered_on),
 cash AS (SELECT paid_on,sum(amount) amount FROM payments GROUP BY paid_on)
UPDATE finance_daily d SET completed_orders=coalesce(s.n,0),net_revenue=coalesce(s.rev,0),
 cogs=coalesce(s.costs,0),gross_profit=coalesce(s.gross,0),
 operating_expense=e.marketing_amount+e.fulfillment_amount+e.platform_amount,
 net_profit=coalesce(s.gross,0)-e.marketing_amount-e.fulfillment_amount-e.platform_amount,
 cash_collected=coalesce(c.amount,0)
FROM operating_expenses e LEFT JOIN sales s ON s.ordered_on=e.expense_date
LEFT JOIN cash c ON c.paid_on=e.expense_date WHERE d.business_date=e.expense_date;

WITH monthly AS (SELECT date_trunc('month',business_date)::date month_start,sum(net_revenue) sales,
 sum(cogs) costs,sum(operating_expense) expenses,sum(net_profit) profit FROM finance_daily GROUP BY 1),
 balances AS (SELECT m.*,coalesce((SELECT sum(inventory_value) FROM inventory_snapshots i
 WHERE i.month_start=m.month_start),0) inventory,round(m.sales*.22,2) ar,round(m.costs*.16,2) ap FROM monthly m),
 assets AS (SELECT b.*,b.sales*.65+b.inventory+b.ar+12000 ca,b.ap+b.expenses*.5+b.sales*.42 cl FROM balances b),
 totals AS (SELECT a.*,a.ca+a.sales*1.2+100000 ta,a.cl+a.sales*.4 tl FROM assets a)
UPDATE finance_monthly f SET net_revenue=t.sales,cogs=t.costs,operating_expense=t.expenses,net_profit=t.profit,
 receivables_balance=t.ar,payables_balance=t.ap,inventory_value=t.inventory,current_assets=t.ca,current_liabilities=t.cl,
 total_assets=t.ta,total_liabilities=t.tl,equity=t.ta-t.tl,
 equity_ratio_pct=coalesce(round((t.ta-t.tl)/nullif(t.ta,0)*100,2),0),
 debt_equity_pct=coalesce(round(t.tl/nullif(t.ta-t.tl,0)*100,2),0),
 current_ratio=coalesce(round(t.ca/nullif(t.cl,0),2),0),dso_days=coalesce(round(t.ar/nullif(t.sales,0)*30,2),0),
 dpo_days=coalesce(round(t.ap/nullif(t.costs,0)*30,2),0),dsi_days=coalesce(round(t.inventory/nullif(t.costs,0)*30,2),0),
 net_working_capital=t.ca-t.cl,gross_working_capital=t.ca FROM totals t WHERE f.month_start=t.month_start;

WITH unpaid AS (SELECT o.ordered_at::date+30 due_on,sum(i.quantity*i.unit_price) amount FROM orders o
 JOIN order_items i ON i.order_id=o.id LEFT JOIN payments p ON p.order_id=o.id
 WHERE o.order_status='completed' AND p.id IS NULL GROUP BY o.id),
 ar AS (SELECT CASE WHEN due_on>=CURRENT_DATE THEN 'Current' WHEN CURRENT_DATE-due_on<=30 THEN '1-30'
 WHEN CURRENT_DATE-due_on<=60 THEN '31-60' WHEN CURRENT_DATE-due_on<=90 THEN '61-90' ELSE '91+' END bucket,
 sum(amount) amount FROM unpaid GROUP BY 1),
 ap AS (SELECT CASE WHEN due_on>=CURRENT_DATE THEN 'Current' WHEN CURRENT_DATE-due_on<=30 THEN '1-30'
 WHEN CURRENT_DATE-due_on<=60 THEN '31-60' WHEN CURRENT_DATE-due_on<=90 THEN '61-90' ELSE '91+' END bucket,
 sum(amount) amount FROM supplier_invoices WHERE NOT is_paid GROUP BY 1)
UPDATE aging_balances a SET receivable_amount=coalesce(b.ar,0),payable_amount=coalesce(b.ap,0)
FROM (SELECT x.aging_bucket,ar.amount ar,ap.amount ap FROM aging_balances x
 LEFT JOIN ar ON ar.bucket=x.aging_bucket LEFT JOIN ap ON ap.bucket=x.aging_bucket) b
WHERE a.aging_bucket=b.aging_bucket;

WITH s AS (SELECT started_at::date bucket_date,count(*) n,
 count(*) FILTER (WHERE converted_order_id IS NOT NULL) conv FROM web_sessions GROUP BY 1),
 c AS (SELECT created_at::date bucket_date,count(*) n FROM carts GROUP BY 1)
UPDATE funnel_daily f SET sessions_count=coalesce(s.n,0),carts_count=coalesce(c.n,0),conversions_count=coalesce(s.conv,0)
FROM operating_expenses d LEFT JOIN s ON s.bucket_date=d.expense_date LEFT JOIN c ON c.bucket_date=d.expense_date
WHERE f.business_date=d.expense_date;
WITH s AS (SELECT shipped_on bucket_date,count(*) n,round(avg(delivered_on-shipped_on),2) avg_days FROM shipments GROUP BY 1),
 r AS (SELECT requested_on bucket_date,count(*) n FROM product_returns GROUP BY 1),
 x AS (SELECT refunded_on bucket_date,sum(amount) amount FROM refunds GROUP BY 1)
UPDATE fulfillment_daily f SET shipments_count=coalesce(s.n,0),returns_count=coalesce(r.n,0),
 refunds_amount=coalesce(x.amount,0),avg_delivery_days=s.avg_days FROM operating_expenses d
LEFT JOIN s ON s.bucket_date=d.expense_date LEFT JOIN r ON r.bucket_date=d.expense_date
LEFT JOIN x ON x.bucket_date=d.expense_date WHERE f.business_date=d.expense_date;

DO $$
DECLARE goal integer := current_setting('issue51.target_orders')::integer;
BEGIN
 IF (SELECT count(*) FROM orders)<>goal OR (SELECT count(*) FROM order_facts)<>goal
 OR (SELECT count(*) FROM order_items)<>goal*2
 OR EXISTS (SELECT 1 FROM orders o LEFT JOIN order_facts f ON f.order_id=o.id WHERE f.order_id IS NULL)
 OR EXISTS (SELECT 1 FROM order_facts WHERE gross_profit<>net_revenue-cogs)
 OR EXISTS (SELECT 1 FROM order_facts f JOIN orders o ON o.id=f.order_id
   JOIN (SELECT order_id,sum(quantity*unit_price) rev,sum(quantity*unit_cost) cost
         FROM order_items WHERE order_id>current_setting('issue51.base_orders')::integer GROUP BY order_id) i ON i.order_id=o.id
   LEFT JOIN payments p ON p.order_id=o.id WHERE f.order_id>current_setting('issue51.base_orders')::integer AND (
   f.net_revenue<>CASE WHEN o.order_status='completed' THEN i.rev ELSE 0 END OR
   f.cogs<>CASE WHEN o.order_status='completed' THEN i.cost ELSE 0 END OR
   f.paid_amount<>coalesce(p.amount,0) OR (p.id IS NOT NULL AND p.amount<>i.rev)))
 OR (SELECT sum(net_revenue) FROM order_facts)<>(SELECT sum(net_revenue) FROM finance_daily)
 OR (SELECT sum(net_revenue) FROM finance_daily)<>(SELECT sum(net_revenue) FROM finance_monthly)
 OR (SELECT sum(cash_collected) FROM finance_daily)<>(SELECT sum(amount) FROM payments WHERE paid_on<=CURRENT_DATE)
 OR (SELECT sum(sessions_count) FROM funnel_daily)<>(SELECT count(*) FROM web_sessions)
 OR (SELECT sum(shipments_count) FROM fulfillment_daily)<>(SELECT count(*) FROM shipments WHERE shipped_on<=CURRENT_DATE)
 THEN RAISE EXCEPTION 'Post-load reconciliation failed; all changes will be rolled back'; END IF;
END $$;

\if :apply
COMMIT;
\echo COMMIT_OK
\else
ROLLBACK;
\echo DRY_RUN_OK
\endif
