-- Synthetic PostgreSQL target database for the Metrics Dashboard.
-- Load into a NEW, EMPTY database only. Rerunning fails without replacing data.
-- Dates roll with CURRENT_DATE so the dashboard's recent-date presets stay populated.
-- Includes enterprise operations and weighted variation in this file.
BEGIN;

CREATE TABLE categories (
    id integer PRIMARY KEY,
    category_name text NOT NULL UNIQUE
);
CREATE TABLE products (
    id integer PRIMARY KEY,
    category_id integer NOT NULL REFERENCES categories(id),
    product_name text NOT NULL,
    unit_price numeric(12,2) NOT NULL CHECK (unit_price > 0),
    unit_cost numeric(12,2) NOT NULL CHECK (unit_cost >= 0)
);
CREATE TABLE customers (
    id integer PRIMARY KEY,
    customer_name text NOT NULL,
    region text NOT NULL,
    customer_segment text NOT NULL
);
CREATE TABLE orders (
    id integer PRIMARY KEY,
    customer_id integer NOT NULL REFERENCES customers(id),
    ordered_at timestamp NOT NULL,
    channel text NOT NULL,
    order_status text NOT NULL
);
CREATE TABLE order_items (
    id integer PRIMARY KEY,
    order_id integer NOT NULL REFERENCES orders(id),
    product_id integer NOT NULL REFERENCES products(id),
    quantity integer NOT NULL CHECK (quantity > 0),
    unit_price numeric(12,2) NOT NULL,
    unit_cost numeric(12,2) NOT NULL
);
CREATE TABLE payments (
    id integer PRIMARY KEY,
    order_id integer NOT NULL UNIQUE REFERENCES orders(id),
    paid_on date NOT NULL,
    payment_method text NOT NULL,
    amount numeric(14,2) NOT NULL CHECK (amount >= 0)
);
CREATE TABLE operating_expenses (
    expense_date date PRIMARY KEY,
    marketing_amount numeric(14,2) NOT NULL,
    fulfillment_amount numeric(14,2) NOT NULL,
    platform_amount numeric(14,2) NOT NULL
);
CREATE TABLE supplier_invoices (
    id integer PRIMARY KEY,
    issued_on date NOT NULL,
    due_on date NOT NULL,
    supplier_name text NOT NULL,
    amount numeric(14,2) NOT NULL CHECK (amount > 0),
    is_paid boolean NOT NULL
);
CREATE TABLE inventory_snapshots (
    month_start date NOT NULL,
    product_id integer NOT NULL REFERENCES products(id),
    units_on_hand integer NOT NULL CHECK (units_on_hand >= 0),
    inventory_value numeric(14,2) NOT NULL CHECK (inventory_value >= 0),
    PRIMARY KEY (month_start, product_id)
);

-- One row per order: easy approved metrics by date, channel, region, or segment.
CREATE TABLE order_facts (
    order_id integer PRIMARY KEY REFERENCES orders(id),
    ordered_on date NOT NULL,
    channel text NOT NULL,
    region text NOT NULL,
    customer_segment text NOT NULL,
    order_status text NOT NULL,
    net_revenue numeric(14,2) NOT NULL,
    cogs numeric(14,2) NOT NULL,
    gross_profit numeric(14,2) NOT NULL,
    paid_amount numeric(14,2) NOT NULL
);
CREATE TABLE finance_daily (
    business_date date PRIMARY KEY,
    completed_orders integer NOT NULL,
    net_revenue numeric(14,2) NOT NULL,
    cogs numeric(14,2) NOT NULL,
    gross_profit numeric(14,2) NOT NULL,
    operating_expense numeric(14,2) NOT NULL,
    net_profit numeric(14,2) NOT NULL,
    cash_collected numeric(14,2) NOT NULL
);
-- One row per month: balance and ratio values are snapshots, not additive flows.
CREATE TABLE finance_monthly (
    month_start date PRIMARY KEY,
    net_revenue numeric(14,2) NOT NULL,
    cogs numeric(14,2) NOT NULL,
    operating_expense numeric(14,2) NOT NULL,
    net_profit numeric(14,2) NOT NULL,
    receivables_balance numeric(14,2) NOT NULL,
    payables_balance numeric(14,2) NOT NULL,
    inventory_value numeric(14,2) NOT NULL,
    current_assets numeric(14,2) NOT NULL,
    current_liabilities numeric(14,2) NOT NULL,
    total_assets numeric(14,2) NOT NULL,
    total_liabilities numeric(14,2) NOT NULL,
    equity numeric(14,2) NOT NULL,
    equity_ratio_pct numeric(10,2) NOT NULL,
    debt_equity_pct numeric(10,2) NOT NULL,
    current_ratio numeric(10,2) NOT NULL,
    dso_days numeric(10,2) NOT NULL,
    dpo_days numeric(10,2) NOT NULL,
    dsi_days numeric(10,2) NOT NULL,
    net_working_capital numeric(14,2) NOT NULL,
    gross_working_capital numeric(14,2) NOT NULL
);
CREATE TABLE aging_balances (
    aging_bucket text PRIMARY KEY,
    bucket_order integer NOT NULL UNIQUE,
    receivable_amount numeric(14,2) NOT NULL,
    payable_amount numeric(14,2) NOT NULL
);

INSERT INTO categories VALUES
    (1, 'Electronics'), (2, 'Home'), (3, 'Fashion'),
    (4, 'Beauty'), (5, 'Sports'), (6, 'Books');
INSERT INTO products
SELECT n, 1 + (n - 1) % 6, 'Product ' || lpad(n::text, 2, '0'),
       35 + (n % 12) * 18, 16 + (n % 12) * 9
FROM generate_series(1, 48) AS n;
INSERT INTO customers
SELECT n, 'Customer ' || lpad(n::text, 3, '0'),
       (ARRAY['North','Central','South','West'])[1 + n % 4],
       (ARRAY['New','Returning','Loyal'])[1 + n % 3]
FROM generate_series(1, 360) AS n;

-- Eight orders per day across two years, including the current day.
INSERT INTO orders
SELECT row_number() OVER (ORDER BY d.business_date, slot)::integer,
       1 + ((d.business_date::date - (CURRENT_DATE - 729)) * 8 + slot * 17) % 360,
       d.business_date + make_interval(hours => 8 + slot, mins => (slot * 7) % 60),
       (ARRAY['Web','Marketplace','Mobile'])[1 + slot % 3],
       CASE WHEN (d.business_date::date - (CURRENT_DATE - 729) + slot) % 23 = 0 THEN 'returned'
            WHEN (d.business_date::date - (CURRENT_DATE - 729) + slot) % 17 = 0 THEN 'cancelled'
            ELSE 'completed' END
FROM generate_series(CURRENT_DATE - 729, CURRENT_DATE, interval '1 day') AS d(business_date)
CROSS JOIN generate_series(0, 7) AS slot;
INSERT INTO order_items
SELECT o.id * 2 + line_no, o.id, p.id, 1 + (o.id + line_no) % 3, p.unit_price, p.unit_cost
FROM orders AS o CROSS JOIN generate_series(0, 1) AS line_no
JOIN products AS p ON p.id = 1 + (o.id * 7 + line_no * 11) % 48;
INSERT INTO payments
SELECT o.id, o.id, o.ordered_at::date + (o.id % 3),
       (ARRAY['Card','Bank transfer','Wallet'])[1 + o.id % 3],
       SUM(i.quantity * i.unit_price)
FROM orders AS o JOIN order_items AS i ON i.order_id = o.id
WHERE o.order_status = 'completed' AND o.id % 7 <> 0
GROUP BY o.id;
INSERT INTO operating_expenses
SELECT d.business_date::date, 190 + (d.business_date::date - (CURRENT_DATE - 729)) % 90,
       240 + (d.business_date::date - (CURRENT_DATE - 729)) % 75, 110
FROM generate_series(CURRENT_DATE - 729, CURRENT_DATE, interval '1 day') AS d(business_date);
INSERT INTO supplier_invoices
SELECT row_number() OVER (ORDER BY m.month_start, n)::integer,
       m.month_start::date + (n * 2), m.month_start::date + (n * 2) + 30,
       'Supplier ' || (1 + n % 6), 900 + n * 115 + extract(month FROM m.month_start) * 18,
       (extract(month FROM m.month_start)::integer + n) % 3 <> 0
FROM generate_series(date_trunc('month', CURRENT_DATE - interval '23 months')::date,
                     date_trunc('month', CURRENT_DATE)::date, interval '1 month') AS m(month_start)
CROSS JOIN generate_series(1, 8) AS n;
INSERT INTO inventory_snapshots
SELECT m.month_start::date, p.id, 18 + (p.id * 7 + extract(month FROM m.month_start)::integer * 3) % 55,
       (18 + (p.id * 7 + extract(month FROM m.month_start)::integer * 3) % 55) * p.unit_cost
FROM generate_series(date_trunc('month', CURRENT_DATE - interval '23 months')::date,
                     date_trunc('month', CURRENT_DATE)::date, interval '1 month') AS m(month_start)
CROSS JOIN products AS p;

INSERT INTO order_facts
SELECT o.id, o.ordered_at::date, o.channel, c.region, c.customer_segment, o.order_status,
       CASE WHEN o.order_status = 'completed' THEN SUM(i.quantity * i.unit_price) ELSE 0 END,
       CASE WHEN o.order_status = 'completed' THEN SUM(i.quantity * i.unit_cost) ELSE 0 END,
       CASE WHEN o.order_status = 'completed' THEN SUM(i.quantity * (i.unit_price - i.unit_cost)) ELSE 0 END,
       COALESCE(MAX(p.amount), 0)
FROM orders AS o JOIN customers AS c ON c.id = o.customer_id
JOIN order_items AS i ON i.order_id = o.id
LEFT JOIN payments AS p ON p.order_id = o.id
GROUP BY o.id, c.region, c.customer_segment;
WITH sales_by_day AS (
    SELECT ordered_on, COUNT(*) FILTER (WHERE order_status = 'completed') AS completed_orders,
           SUM(net_revenue) AS net_revenue, SUM(cogs) AS cogs, SUM(gross_profit) AS gross_profit
    FROM order_facts GROUP BY ordered_on
), cash_by_day AS (
    SELECT paid_on, SUM(amount) AS cash_collected FROM payments GROUP BY paid_on
)
INSERT INTO finance_daily
SELECT e.expense_date, COALESCE(s.completed_orders, 0), COALESCE(s.net_revenue, 0),
       COALESCE(s.cogs, 0), COALESCE(s.gross_profit, 0),
       e.marketing_amount + e.fulfillment_amount + e.platform_amount,
       COALESCE(s.gross_profit, 0) - e.marketing_amount - e.fulfillment_amount - e.platform_amount,
       COALESCE(c.cash_collected, 0)
FROM operating_expenses AS e
LEFT JOIN sales_by_day AS s ON s.ordered_on = e.expense_date
LEFT JOIN cash_by_day AS c ON c.paid_on = e.expense_date;

WITH monthly AS (
    SELECT date_trunc('month', business_date)::date AS month_start,
           SUM(net_revenue) AS sales, SUM(cogs) AS costs,
           SUM(operating_expense) AS expenses, SUM(net_profit) AS profit
    FROM finance_daily GROUP BY 1
), balances AS (
    SELECT m.*, COALESCE((SELECT SUM(inventory_value) FROM inventory_snapshots AS i
                         WHERE i.month_start = m.month_start), 0) AS inventory,
           round(m.sales * 0.22, 2) AS ar, round(m.costs * 0.16, 2) AS ap
    FROM monthly AS m
), assets AS (
    SELECT b.*, b.sales * 0.65 + b.inventory + b.ar + 12000 AS ca,
           b.ap + b.expenses * 0.5 + b.sales * 0.42 AS cl
    FROM balances AS b
), totals AS (
    SELECT a.*, a.ca + a.sales * 1.2 + 100000 AS ta,
           a.cl + a.sales * 0.4 AS tl
    FROM assets AS a
)
INSERT INTO finance_monthly
SELECT month_start, sales, costs, expenses, profit, ar, ap, inventory, ca, cl, ta, tl, ta - tl,
       round((ta - tl) / NULLIF(ta, 0) * 100, 2),
       round(tl / NULLIF(ta - tl, 0) * 100, 2),
       round(ca / NULLIF(cl, 0), 2),
       round(ar / NULLIF(sales, 0) * 30, 2),
       round(ap / NULLIF(costs, 0) * 30, 2),
       round(inventory / NULLIF(costs, 0) * 30, 2), ca - cl, ca
FROM totals;

WITH buckets AS (
    SELECT label, rank FROM (VALUES ('Current', 1), ('1-30', 2), ('31-60', 3),
                                    ('61-90', 4), ('91+', 5)) AS b(label, rank)
), ar AS (
    SELECT CASE WHEN due_on >= CURRENT_DATE THEN 'Current'
                WHEN CURRENT_DATE - due_on <= 30 THEN '1-30'
                WHEN CURRENT_DATE - due_on <= 60 THEN '31-60'
                WHEN CURRENT_DATE - due_on <= 90 THEN '61-90' ELSE '91+' END AS bucket,
           SUM(amount) AS amount
    FROM (SELECT o.ordered_at::date + 30 AS due_on,
                 SUM(i.quantity * i.unit_price) AS amount
          FROM orders AS o JOIN order_items AS i ON i.order_id = o.id
          WHERE o.order_status = 'completed' AND o.id % 7 = 0
          GROUP BY o.id) AS unpaid
    GROUP BY 1
), ap AS (
    SELECT CASE WHEN due_on >= CURRENT_DATE THEN 'Current'
                WHEN CURRENT_DATE - due_on <= 30 THEN '1-30'
                WHEN CURRENT_DATE - due_on <= 60 THEN '31-60'
                WHEN CURRENT_DATE - due_on <= 90 THEN '61-90' ELSE '91+' END AS bucket,
           SUM(amount) AS amount
    FROM supplier_invoices WHERE NOT is_paid GROUP BY 1
)
INSERT INTO aging_balances
SELECT b.label, b.rank, COALESCE(ar.amount, 0), COALESCE(ap.amount, 0)
FROM buckets AS b LEFT JOIN ar ON ar.bucket = b.label LEFT JOIN ap ON ap.bucket = b.label;

CREATE INDEX orders_ordered_at_idx ON orders(ordered_at);
CREATE INDEX order_items_order_id_idx ON order_items(order_id);
CREATE INDEX order_facts_ordered_on_idx ON order_facts(ordered_on);
CREATE INDEX payments_paid_on_idx ON payments(paid_on);

DO $$
BEGIN
    IF (SELECT COUNT(*) FROM orders) <> 5840
       OR (SELECT COUNT(*) FROM finance_daily) <> 730
       OR (SELECT COUNT(*) FROM finance_monthly) < 24
       OR (SELECT COUNT(*) FROM aging_balances) <> 5
       OR (SELECT COUNT(*) FROM finance_daily WHERE net_revenue > 0) < 700
       OR (SELECT SUM(net_revenue - cogs - operating_expense - net_profit) FROM finance_daily) <> 0
       OR (SELECT SUM(cash_collected) FROM finance_daily) <>
          (SELECT SUM(amount) FROM payments WHERE paid_on <= CURRENT_DATE) THEN
        RAISE EXCEPTION 'Ecommerce demo seed did not produce the expected dashboard coverage';
    END IF;
END $$;

-- Enterprise ecommerce domains
CREATE TABLE brands (id integer PRIMARY KEY, brand_name text NOT NULL UNIQUE);
CREATE TABLE suppliers (id integer PRIMARY KEY, supplier_name text NOT NULL UNIQUE, region text NOT NULL);
CREATE TABLE product_variants (
    id integer PRIMARY KEY, product_id integer NOT NULL REFERENCES products(id),
    sku text NOT NULL UNIQUE, variant_name text NOT NULL, brand_id integer NOT NULL REFERENCES brands(id),
    is_active boolean NOT NULL
);
CREATE TABLE warehouses (id integer PRIMARY KEY, warehouse_name text NOT NULL UNIQUE, region text NOT NULL);
CREATE TABLE inventory_movements (
    id integer PRIMARY KEY, product_id integer NOT NULL REFERENCES products(id),
    warehouse_id integer NOT NULL REFERENCES warehouses(id), order_item_id integer REFERENCES order_items(id),
    movement_at timestamp NOT NULL, movement_type text NOT NULL, quantity_delta integer NOT NULL
);
CREATE TABLE customer_addresses (
    id integer PRIMARY KEY, customer_id integer NOT NULL REFERENCES customers(id),
    address_type text NOT NULL, region text NOT NULL, city text NOT NULL
);
CREATE TABLE promotions (
    id integer PRIMARY KEY, promotion_name text NOT NULL UNIQUE,
    discount_pct numeric(5,2) NOT NULL CHECK (discount_pct BETWEEN 0 AND 100),
    starts_on date NOT NULL, ends_on date NOT NULL
);
CREATE TABLE coupon_redemptions (
    id integer PRIMARY KEY, order_id integer NOT NULL UNIQUE REFERENCES orders(id),
    promotion_id integer NOT NULL REFERENCES promotions(id), redeemed_on date NOT NULL,
    discount_amount numeric(14,2) NOT NULL
);
CREATE TABLE carts (
    id integer PRIMARY KEY, customer_id integer NOT NULL REFERENCES customers(id),
    created_at timestamp NOT NULL, cart_status text NOT NULL,
    converted_order_id integer UNIQUE REFERENCES orders(id)
);
CREATE TABLE cart_items (
    id integer PRIMARY KEY, cart_id integer NOT NULL REFERENCES carts(id),
    product_id integer NOT NULL REFERENCES products(id), quantity integer NOT NULL CHECK (quantity > 0)
);
CREATE TABLE wishlists (id integer PRIMARY KEY, customer_id integer NOT NULL UNIQUE REFERENCES customers(id));
CREATE TABLE wishlist_items (
    id integer PRIMARY KEY, wishlist_id integer NOT NULL REFERENCES wishlists(id),
    product_id integer NOT NULL REFERENCES products(id)
);
CREATE TABLE web_sessions (
    id integer PRIMARY KEY, customer_id integer NOT NULL REFERENCES customers(id),
    started_at timestamp NOT NULL, traffic_source text NOT NULL, device_type text NOT NULL,
    converted_order_id integer REFERENCES orders(id)
);
CREATE TABLE web_events (
    id integer PRIMARY KEY, session_id integer NOT NULL REFERENCES web_sessions(id),
    occurred_at timestamp NOT NULL, event_type text NOT NULL,
    product_id integer REFERENCES products(id)
);
CREATE TABLE shipments (
    id integer PRIMARY KEY, order_id integer NOT NULL UNIQUE REFERENCES orders(id),
    warehouse_id integer NOT NULL REFERENCES warehouses(id), carrier text NOT NULL,
    shipped_on date NOT NULL, delivered_on date NOT NULL, shipment_status text NOT NULL
);
CREATE TABLE shipment_events (
    id integer PRIMARY KEY, shipment_id integer NOT NULL REFERENCES shipments(id),
    occurred_on date NOT NULL, event_type text NOT NULL
);
CREATE TABLE product_returns (
    id integer PRIMARY KEY, order_id integer NOT NULL UNIQUE REFERENCES orders(id),
    requested_on date NOT NULL, return_reason text NOT NULL, return_status text NOT NULL
);
CREATE TABLE return_items (
    id integer PRIMARY KEY, return_id integer NOT NULL REFERENCES product_returns(id),
    order_item_id integer NOT NULL UNIQUE REFERENCES order_items(id), quantity integer NOT NULL
);
CREATE TABLE refunds (
    id integer PRIMARY KEY, return_id integer NOT NULL UNIQUE REFERENCES product_returns(id),
    refunded_on date NOT NULL, amount numeric(14,2) NOT NULL CHECK (amount >= 0)
);
CREATE TABLE product_reviews (
    id integer PRIMARY KEY, product_id integer NOT NULL REFERENCES products(id),
    customer_id integer NOT NULL REFERENCES customers(id), order_id integer NOT NULL REFERENCES orders(id),
    rating integer NOT NULL CHECK (rating BETWEEN 1 AND 5), reviewed_on date NOT NULL
);
CREATE TABLE support_tickets (
    id integer PRIMARY KEY, customer_id integer NOT NULL REFERENCES customers(id),
    order_id integer NOT NULL REFERENCES orders(id), opened_on date NOT NULL,
    issue_type text NOT NULL, ticket_status text NOT NULL
);
CREATE TABLE purchase_orders (
    id integer PRIMARY KEY, supplier_id integer NOT NULL REFERENCES suppliers(id),
    warehouse_id integer NOT NULL REFERENCES warehouses(id), ordered_on date NOT NULL,
    purchase_status text NOT NULL
);
CREATE TABLE purchase_order_items (
    id integer PRIMARY KEY, purchase_order_id integer NOT NULL REFERENCES purchase_orders(id),
    product_id integer NOT NULL REFERENCES products(id), quantity integer NOT NULL,
    unit_cost numeric(12,2) NOT NULL
);
CREATE TABLE supplier_payments (
    id integer PRIMARY KEY, purchase_order_id integer NOT NULL UNIQUE REFERENCES purchase_orders(id),
    paid_on date NOT NULL, amount numeric(14,2) NOT NULL
);
CREATE TABLE tax_rates (
    id integer PRIMARY KEY, category_id integer NOT NULL UNIQUE REFERENCES categories(id),
    tax_pct numeric(5,2) NOT NULL
);
CREATE TABLE order_taxes (
    order_id integer PRIMARY KEY REFERENCES orders(id),
    taxable_amount numeric(14,2) NOT NULL, tax_amount numeric(14,2) NOT NULL
);
CREATE TABLE product_price_history (
    product_id integer NOT NULL REFERENCES products(id), month_start date NOT NULL,
    list_price numeric(12,2) NOT NULL, PRIMARY KEY (product_id, month_start)
);
CREATE TABLE funnel_daily (
    business_date date PRIMARY KEY, sessions_count integer NOT NULL,
    carts_count integer NOT NULL, conversions_count integer NOT NULL
);
CREATE TABLE fulfillment_daily (
    business_date date PRIMARY KEY, shipments_count integer NOT NULL,
    returns_count integer NOT NULL, refunds_amount numeric(14,2) NOT NULL,
    avg_delivery_days numeric(10,2)
);

INSERT INTO brands SELECT n, 'Brand ' || lpad(n::text, 2, '0') FROM generate_series(1, 12) AS n;
INSERT INTO suppliers
SELECT n, 'Supplier ' || lpad(n::text, 2, '0'),
       (ARRAY['North','Central','South','West'])[1 + n % 4]
FROM generate_series(1, 18) AS n;
INSERT INTO product_variants
SELECT p.id * 2 + variant_no, p.id, 'SKU-' || lpad(p.id::text, 3, '0') || '-' || variant_no,
       (ARRAY['Standard','Premium'])[1 + variant_no], 1 + (p.id - 1) % 12, true
FROM products AS p CROSS JOIN generate_series(0, 1) AS variant_no;
INSERT INTO warehouses VALUES
    (1, 'North DC', 'North'), (2, 'Central DC', 'Central'),
    (3, 'South DC', 'South'), (4, 'West DC', 'West');
INSERT INTO customer_addresses
SELECT c.id * 2 + address_no, c.id,
       (ARRAY['Billing','Shipping'])[1 + address_no], c.region,
       (ARRAY['Metro','Suburb','Coastal'])[1 + c.id % 3]
FROM customers AS c CROSS JOIN generate_series(0, 1) AS address_no;
INSERT INTO promotions
SELECT n, 'Campaign ' || n, 5 + n * 2,
       CURRENT_DATE - 729, CURRENT_DATE + 1
FROM generate_series(1, 8) AS n;
INSERT INTO coupon_redemptions
SELECT o.id, o.id, 1 + o.id % 8, o.ordered_at::date,
       round(f.net_revenue * p.discount_pct / 100, 2)
FROM orders AS o JOIN order_facts AS f ON f.order_id = o.id
JOIN promotions AS p ON p.id = 1 + o.id % 8
WHERE o.order_status = 'completed' AND o.id % 13 = 0;
INSERT INTO carts
SELECT n, COALESCE(o.customer_id, 1 + n % 360),
       COALESCE(o.ordered_at - interval '20 minutes',
                CURRENT_DATE - (n % 730) + make_interval(hours => 9 + n % 10)),
       CASE WHEN o.id IS NOT NULL THEN 'converted'
            WHEN n % 5 = 0 THEN 'abandoned' ELSE 'active' END, o.id
FROM generate_series(1, 4000) AS n
LEFT JOIN orders AS o ON n % 4 = 0 AND o.id = n;
INSERT INTO cart_items
SELECT c.id * 2 + line_no, c.id, 1 + (c.id * 3 + line_no * 7) % 48,
       1 + (c.id + line_no) % 3
FROM carts AS c CROSS JOIN generate_series(0, 1) AS line_no;
INSERT INTO wishlists SELECT id, id FROM customers;
INSERT INTO wishlist_items
SELECT w.id * 3 + slot, w.id, 1 + (w.id * 5 + slot * 9) % 48
FROM wishlists AS w CROSS JOIN generate_series(0, 2) AS slot;
INSERT INTO web_sessions
SELECT n, COALESCE(o.customer_id, 1 + n % 360),
       COALESCE(o.ordered_at - interval '6 minutes',
                CURRENT_DATE - (n % 730) + make_interval(hours => 7 + n % 13)),
       (ARRAY['Organic','Paid search','Email','Social'])[1 + n % 4],
       (ARRAY['Desktop','Mobile','Tablet'])[1 + n % 3], o.id
FROM generate_series(1, 12000) AS n
LEFT JOIN orders AS o ON n % 4 = 0 AND o.id = 1 + n % 5840;
INSERT INTO web_events
SELECT s.id * 3 + step, s.id, s.started_at + make_interval(mins => step * 3),
       CASE WHEN step = 0 THEN 'product_view'
            WHEN step = 1 THEN 'add_to_cart'
            WHEN s.converted_order_id IS NOT NULL THEN 'purchase' ELSE 'checkout' END,
       1 + (s.id * 3 + step) % 48
FROM web_sessions AS s CROSS JOIN generate_series(0, 2) AS step;

INSERT INTO shipments
SELECT o.id, o.id, 1 + o.id % 4,
       (ARRAY['FastShip','ParcelGo','LocalPost'])[1 + o.id % 3],
       o.ordered_at::date + 1, o.ordered_at::date + 3 + o.id % 3,
       'delivered'
FROM orders AS o WHERE o.order_status = 'completed';
INSERT INTO shipment_events
SELECT s.id * 2 + step, s.id,
       CASE WHEN step = 0 THEN s.shipped_on ELSE s.delivered_on END,
       CASE WHEN step = 0 THEN 'shipped' ELSE 'delivered' END
FROM shipments AS s CROSS JOIN generate_series(0, 1) AS step;
INSERT INTO product_returns
SELECT o.id, o.id, o.ordered_at::date + 8,
       (ARRAY['Damaged','Wrong item','Changed mind'])[1 + o.id % 3], 'approved'
FROM orders AS o JOIN payments AS p ON p.order_id = o.id
WHERE o.id % 37 = 0;
INSERT INTO return_items
SELECT i.id, r.id, i.id, i.quantity
FROM product_returns AS r JOIN order_items AS i ON i.order_id = r.order_id;
INSERT INTO refunds
SELECT r.id, r.id, r.requested_on + 2, f.net_revenue
FROM product_returns AS r JOIN order_facts AS f ON f.order_id = r.order_id;
INSERT INTO product_reviews
SELECT i.id, i.product_id, o.customer_id, o.id,
       1 + i.id % 5, o.ordered_at::date + 6
FROM order_items AS i JOIN orders AS o ON o.id = i.order_id
WHERE o.order_status = 'completed' AND i.id % 5 = 0;
INSERT INTO support_tickets
SELECT n, o.customer_id, o.id, o.ordered_at::date + 2,
       (ARRAY['Delivery','Payment','Product','Return'])[1 + n % 4],
       CASE WHEN n % 5 = 0 THEN 'open' ELSE 'resolved' END
FROM generate_series(1, 600) AS n JOIN orders AS o ON o.id = n * 9;

INSERT INTO purchase_orders
SELECT row_number() OVER (ORDER BY m.month_start, slot)::integer,
       1 + (extract(month FROM m.month_start)::integer + slot) % 18,
       1 + slot % 4, m.month_start::date + slot * 2, 'received'
FROM generate_series(date_trunc('month', CURRENT_DATE - interval '23 months')::date,
                     date_trunc('month', CURRENT_DATE)::date, interval '1 month') AS m(month_start)
CROSS JOIN generate_series(0, 9) AS slot;
INSERT INTO purchase_order_items
SELECT po.id * 3 + slot, po.id, 1 + (po.id * 5 + slot * 11) % 48,
       20 + (po.id + slot) % 45, p.unit_cost
FROM purchase_orders AS po CROSS JOIN generate_series(0, 2) AS slot
JOIN products AS p ON p.id = 1 + (po.id * 5 + slot * 11) % 48;
INSERT INTO supplier_payments
SELECT po.id, po.id, po.ordered_on + 30, SUM(i.quantity * i.unit_cost)
FROM purchase_orders AS po JOIN purchase_order_items AS i ON i.purchase_order_id = po.id
WHERE po.id % 5 <> 0 GROUP BY po.id;
INSERT INTO inventory_movements
SELECT i.id, i.product_id, 1 + o.id % 4, i.id, o.ordered_at, 'sale', -i.quantity
FROM order_items AS i JOIN orders AS o ON o.id = i.order_id
WHERE o.order_status = 'completed';
INSERT INTO inventory_movements
SELECT 1000000 + i.id, i.product_id, po.warehouse_id, NULL,
       po.ordered_on + interval '5 days', 'receipt', i.quantity
FROM purchase_order_items AS i JOIN purchase_orders AS po ON po.id = i.purchase_order_id;
INSERT INTO inventory_movements
SELECT 2000000 + ri.id, i.product_id, s.warehouse_id, ri.order_item_id,
       r.requested_on + interval '1 day', 'return', ri.quantity
FROM return_items AS ri JOIN product_returns AS r ON r.id = ri.return_id
JOIN order_items AS i ON i.id = ri.order_item_id
JOIN shipments AS s ON s.order_id = r.order_id;
INSERT INTO tax_rates SELECT id, id, 5 + id % 3 FROM categories;
INSERT INTO order_taxes
SELECT f.order_id, f.net_revenue, round(f.net_revenue * 0.08, 2)
FROM order_facts AS f WHERE f.order_status = 'completed';
INSERT INTO product_price_history
SELECT p.id, m.month_start::date,
       round(p.unit_price * (0.96 + extract(month FROM m.month_start)::integer % 5 * 0.01), 2)
FROM products AS p CROSS JOIN generate_series(
    date_trunc('month', CURRENT_DATE - interval '23 months')::date,
    date_trunc('month', CURRENT_DATE)::date, interval '1 month') AS m(month_start);

WITH sessions_by_day AS (
    SELECT started_at::date AS day, COUNT(*) AS sessions_count,
           COUNT(*) FILTER (WHERE converted_order_id IS NOT NULL) AS conversions_count
    FROM web_sessions GROUP BY 1
), carts_by_day AS (
    SELECT created_at::date AS day, COUNT(*) AS carts_count FROM carts GROUP BY 1
)
INSERT INTO funnel_daily
SELECT d.business_date, COALESCE(s.sessions_count, 0), COALESCE(c.carts_count, 0),
       COALESCE(s.conversions_count, 0)
FROM finance_daily AS d
LEFT JOIN sessions_by_day AS s ON s.day = d.business_date
LEFT JOIN carts_by_day AS c ON c.day = d.business_date;
WITH shipped AS (
    SELECT shipped_on AS day, COUNT(*) AS shipments_count,
           round(AVG(delivered_on - shipped_on), 2) AS avg_delivery_days
    FROM shipments GROUP BY 1
), returned AS (
    SELECT requested_on AS day, COUNT(*) AS returns_count FROM product_returns GROUP BY 1
), refunded AS (
    SELECT refunded_on AS day, SUM(amount) AS refunds_amount FROM refunds GROUP BY 1
)
INSERT INTO fulfillment_daily
SELECT d.business_date, COALESCE(s.shipments_count, 0), COALESCE(r.returns_count, 0),
       COALESCE(f.refunds_amount, 0), s.avg_delivery_days
FROM finance_daily AS d
LEFT JOIN shipped AS s ON s.day = d.business_date
LEFT JOIN returned AS r ON r.day = d.business_date
LEFT JOIN refunded AS f ON f.day = d.business_date;

CREATE INDEX web_sessions_started_at_idx ON web_sessions(started_at);
CREATE INDEX web_events_session_id_idx ON web_events(session_id);
CREATE INDEX shipments_shipped_on_idx ON shipments(shipped_on);
CREATE INDEX purchase_orders_ordered_on_idx ON purchase_orders(ordered_on);
CREATE INDEX inventory_movements_product_id_idx ON inventory_movements(product_id);

DO $$
BEGIN
    IF (SELECT COUNT(*) FROM web_sessions) <> 12000
       OR (SELECT COUNT(*) FROM web_events) <> 36000
       OR (SELECT COUNT(*) FROM carts) <> 4000
       OR (SELECT COUNT(*) FROM purchase_orders) < 240
       OR (SELECT COUNT(*) FROM funnel_daily) <> 730
       OR (SELECT COUNT(*) FROM fulfillment_daily) <> 730
       OR (SELECT COUNT(*) FROM shipments) = 0
       OR (SELECT COUNT(*) FROM refunds) = 0 THEN
        RAISE EXCEPTION 'Enterprise ecommerce extension did not produce the expected coverage';
    END IF;
END $$;

-- Weighted operational data and reconciled dashboard facts
UPDATE customers
SET region = CASE WHEN id <= 144 THEN 'South' WHEN id <= 252 THEN 'North'
                  WHEN id <= 324 THEN 'Central' ELSE 'West' END,
    customer_segment = CASE WHEN id % 10 < 5 THEN 'New'
                            WHEN id % 10 < 8 THEN 'Returning' ELSE 'Loyal' END;
UPDATE customer_addresses AS a
SET region = c.region,
    city = CASE WHEN c.region = 'South' THEN (ARRAY['Metro','Delta','Coastal'])[1 + a.id % 3]
                WHEN c.region = 'North' THEN (ARRAY['Capital','Port','Highlands'])[1 + a.id % 3]
                WHEN c.region = 'Central' THEN (ARRAY['Central City','Coastal','Mountain'])[1 + a.id % 3]
                ELSE (ARRAY['West City','Suburb','Valley'])[1 + a.id % 3] END
FROM customers AS c WHERE a.customer_id = c.id;
UPDATE suppliers
SET region = CASE WHEN id <= 8 THEN 'South' WHEN id <= 13 THEN 'North'
                  WHEN id <= 16 THEN 'Central' ELSE 'West' END;
UPDATE products
SET category_id = CASE WHEN id <= 18 THEN 1 WHEN id <= 28 THEN 2
                       WHEN id <= 36 THEN 3 WHEN id <= 41 THEN 4
                       WHEN id <= 45 THEN 5 ELSE 6 END,
    unit_price = round((35 + (id % 12) * 18) *
        CASE WHEN id % 10 = 0 THEN 2.4 WHEN id % 3 = 0 THEN 1.35 ELSE 1 END, 2),
    unit_cost = round((16 + (id % 12) * 9) *
        CASE WHEN id % 10 = 0 THEN 2.1 WHEN id % 3 = 0 THEN 1.25 ELSE 1 END, 2);
UPDATE product_variants
SET brand_id = CASE WHEN product_id <= 18 THEN 1 + product_id % 4
                    ELSE 1 + product_id % 12 END,
    is_active = id % 11 <> 0;
UPDATE orders
SET channel = CASE WHEN id % 10 < 5 THEN 'Web'
                   WHEN id % 10 < 8 THEN 'Mobile' ELSE 'Marketplace' END;
UPDATE payments AS p
SET payment_method = CASE WHEN p.id % 10 < 6 THEN 'Card'
                          WHEN p.id % 10 < 9 THEN 'Wallet' ELSE 'Bank transfer' END,
    paid_on = o.ordered_at::date + CASE WHEN p.id % 10 < 6 THEN 0
                                       WHEN p.id % 10 < 9 THEN 2 ELSE 5 END
FROM orders AS o WHERE o.id = p.order_id;
UPDATE promotions SET discount_pct = CASE WHEN id <= 2 THEN 20
                                          WHEN id <= 5 THEN 12 ELSE 6 END;
UPDATE operating_expenses
SET marketing_amount = 120 + (expense_date - (CURRENT_DATE - 729)) % 95
                       + CASE WHEN extract(month FROM expense_date) IN (11, 12) THEN 310 ELSE 0 END,
    fulfillment_amount = 170 + (expense_date - (CURRENT_DATE - 729)) % 65
                         + CASE WHEN extract(dow FROM expense_date) IN (0, 6) THEN 110 ELSE 0 END,
    platform_amount = 75 + (expense_date - (CURRENT_DATE - 729)) % 35;
UPDATE supplier_invoices
SET amount = round((900 + (id % 8) * 115 + extract(month FROM issued_on) * 18) *
                   CASE WHEN id % 11 = 0 THEN 2.3 WHEN id % 4 = 0 THEN 1.4 ELSE 1 END, 2),
    due_on = issued_on + CASE WHEN id % 5 = 0 THEN 60
                             WHEN id % 3 = 0 THEN 45 ELSE 30 END,
    is_paid = id % 10 < 7;
UPDATE inventory_snapshots AS i
SET units_on_hand = 8 + ((i.product_id * 7 + extract(month FROM i.month_start)::integer * 3) % 55)
                    * CASE WHEN p.category_id = 1 THEN 3 WHEN p.category_id = 2 THEN 2 ELSE 1 END,
    inventory_value = (8 + ((i.product_id * 7 + extract(month FROM i.month_start)::integer * 3) % 55)
                    * CASE WHEN p.category_id = 1 THEN 3 WHEN p.category_id = 2 THEN 2 ELSE 1 END)
                    * p.unit_cost
FROM products AS p WHERE p.id = i.product_id;
UPDATE product_price_history AS h
SET list_price = round(p.unit_price *
    (1 + 0.1 * sin(2 * pi() * extract(month FROM h.month_start)::double precision / 12)::numeric), 2)
FROM products AS p WHERE p.id = h.product_id;
UPDATE tax_rates SET tax_pct = CASE category_id WHEN 1 THEN 10 WHEN 4 THEN 6 ELSE 8 END;

UPDATE purchase_orders
SET supplier_id = CASE WHEN id % 10 < 5 THEN 1 + id % 4
                       WHEN id % 10 < 8 THEN 5 + id % 5 ELSE 10 + id % 9 END,
    warehouse_id = CASE WHEN id % 10 < 4 THEN 1 WHEN id % 10 < 7 THEN 2
                        WHEN id % 10 < 9 THEN 3 ELSE 4 END;
UPDATE purchase_order_items AS i
SET quantity = 12 + (i.id * 7 % 50) * CASE WHEN p.category_id = 1 THEN 3 ELSE 1 END,
    unit_cost = p.unit_cost
FROM products AS p WHERE p.id = i.product_id;
UPDATE supplier_payments AS sp
SET amount = t.amount,
    paid_on = po.ordered_on + CASE WHEN sp.id % 10 < 6 THEN 15 ELSE 45 END
FROM (SELECT purchase_order_id, SUM(quantity * unit_cost) AS amount
      FROM purchase_order_items GROUP BY purchase_order_id) AS t,
     purchase_orders AS po
WHERE sp.purchase_order_id = t.purchase_order_id AND po.id = sp.purchase_order_id;

UPDATE carts AS c
SET created_at = CURRENT_DATE - (c.id % 10) * 9 - (c.id % 640)
                 + make_interval(hours => 9 + c.id % 10),
    cart_status = CASE WHEN c.id % 10 < 7 THEN 'abandoned' ELSE 'active' END
WHERE c.converted_order_id IS NULL;
INSERT INTO cart_items
SELECT 1000000 + c.id, c.id, 1 + c.id % 18, 1
FROM carts AS c WHERE c.id % 4 = 0 ON CONFLICT (id) DO NOTHING;
UPDATE cart_items
SET quantity = CASE WHEN id % 10 < 6 THEN 1 WHEN id % 10 < 9 THEN 2 ELSE 4 END,
    product_id = CASE WHEN id % 10 < 6 THEN 1 + id % 18 ELSE 1 + id % 48 END;
INSERT INTO wishlist_items
SELECT 1000000 + w.id, w.id, 1 + w.id % 18
FROM wishlists AS w WHERE w.id % 3 = 0 ON CONFLICT (id) DO NOTHING;
UPDATE wishlist_items
SET product_id = CASE WHEN id % 10 < 7 THEN 1 + id % 18 ELSE 1 + id % 48 END;
UPDATE web_sessions AS s
SET started_at = CURRENT_DATE - CASE WHEN s.id % 10 < 4 THEN s.id % 90
                                      ELSE s.id % 730 END
                 + make_interval(hours => 7 + s.id % 13),
    traffic_source = CASE WHEN s.id % 10 < 5 THEN 'Organic'
                          WHEN s.id % 10 < 8 THEN 'Paid search'
                          WHEN s.id % 10 = 8 THEN 'Social' ELSE 'Email' END,
    device_type = CASE WHEN s.id % 10 < 6 THEN 'Mobile'
                       WHEN s.id % 10 < 9 THEN 'Desktop' ELSE 'Tablet' END
WHERE s.converted_order_id IS NULL;
UPDATE web_events AS e SET occurred_at = s.started_at + make_interval(mins => (e.id % 3) * 3)
FROM web_sessions AS s WHERE e.session_id = s.id;

UPDATE shipments
SET warehouse_id = CASE WHEN id % 10 < 4 THEN 1 WHEN id % 10 < 7 THEN 2
                        WHEN id % 10 < 9 THEN 3 ELSE 4 END,
    carrier = CASE WHEN id % 10 < 5 THEN 'FastShip'
                   WHEN id % 10 < 8 THEN 'ParcelGo' ELSE 'LocalPost' END,
    delivered_on = shipped_on + CASE WHEN id % 10 < 5 THEN 2 + id % 2
                                     WHEN id % 10 < 8 THEN 4 + id % 2 ELSE 6 + id % 3 END;
UPDATE shipment_events AS e
SET occurred_on = CASE WHEN e.event_type = 'shipped' THEN s.shipped_on ELSE s.delivered_on END
FROM shipments AS s WHERE e.shipment_id = s.id;
UPDATE product_returns AS r
SET return_reason = CASE WHEN r.id % 10 < 5 THEN 'Damaged'
                         WHEN r.id % 10 < 8 THEN 'Wrong item' ELSE 'Changed mind' END,
    requested_on = o.ordered_at::date + CASE WHEN r.id % 10 < 5 THEN 6
                                             WHEN r.id % 10 < 8 THEN 10 ELSE 17 END
FROM orders AS o WHERE o.id = r.order_id;
UPDATE product_reviews AS r
SET rating = CASE WHEN r.order_id % 20 = 0 THEN 1 WHEN r.order_id % 10 = 0 THEN 2
                  WHEN r.order_id % 5 = 0 THEN 3 WHEN r.order_id % 3 = 0 THEN 4 ELSE 5 END,
    reviewed_on = o.ordered_at::date + 4 + r.id % 9
FROM orders AS o WHERE o.id = r.order_id;
UPDATE support_tickets AS t
SET issue_type = CASE WHEN t.id % 10 < 5 THEN 'Delivery'
                      WHEN t.id % 10 < 8 THEN 'Payment'
                      WHEN t.id % 10 = 8 THEN 'Product' ELSE 'Return' END,
    ticket_status = CASE WHEN t.id % 10 < 2 THEN 'open' ELSE 'resolved' END,
    opened_on = o.ordered_at::date + 1 + t.id % 7
FROM orders AS o WHERE o.id = t.order_id;

UPDATE order_items AS i SET quantity = CASE WHEN i.id % 10 < 5 THEN 1
                                            WHEN i.id % 10 < 8 THEN 2
                                            WHEN i.id % 10 = 8 THEN 3 ELSE 5 END;
UPDATE order_items AS i
SET unit_price = round(p.unit_price *
        CASE c.region WHEN 'South' THEN 1.28 WHEN 'North' THEN 1.14
                      WHEN 'West' THEN 0.97 ELSE 0.88 END *
        (1 + 0.14 * sin(2 * pi() * extract(month FROM o.ordered_at)::double precision / 12)::numeric
           + ((o.id % 5) - 2) * 0.01), 2),
    unit_cost = round(p.unit_cost *
        CASE c.region WHEN 'South' THEN 1.01 WHEN 'North' THEN 1.04
                      WHEN 'West' THEN 1.12 ELSE 1.07 END *
        (0.98 + (i.id % 5) * 0.015), 2)
FROM orders AS o, customers AS c, products AS p
WHERE o.id = i.order_id AND c.id = o.customer_id AND p.id = i.product_id;

UPDATE payments AS p
SET amount = totals.amount
FROM (SELECT order_id, SUM(quantity * unit_price) AS amount
      FROM order_items GROUP BY order_id) AS totals
WHERE p.order_id = totals.order_id;

WITH totals AS (
    SELECT order_id, SUM(quantity * unit_price) AS revenue,
           SUM(quantity * unit_cost) AS costs
    FROM order_items GROUP BY order_id
)
UPDATE order_facts AS f
SET region = c.region, customer_segment = c.customer_segment, channel = o.channel,
    net_revenue = CASE WHEN f.order_status = 'completed' THEN t.revenue ELSE 0 END,
    cogs = CASE WHEN f.order_status = 'completed' THEN t.costs ELSE 0 END,
    gross_profit = CASE WHEN f.order_status = 'completed' THEN t.revenue - t.costs ELSE 0 END,
    paid_amount = COALESCE(p.amount, 0)
FROM totals AS t LEFT JOIN payments AS p ON p.order_id = t.order_id,
     orders AS o JOIN customers AS c ON c.id = o.customer_id
WHERE f.order_id = t.order_id AND o.id = f.order_id;

WITH sales AS (
    SELECT ordered_on, COUNT(*) FILTER (WHERE order_status = 'completed') AS completed_orders,
           SUM(net_revenue) AS revenue, SUM(cogs) AS costs, SUM(gross_profit) AS gross_profit
    FROM order_facts GROUP BY ordered_on
), cash AS (
    SELECT paid_on, SUM(amount) AS amount FROM payments GROUP BY paid_on
)
UPDATE finance_daily AS d
SET completed_orders = COALESCE(s.completed_orders, 0),
    net_revenue = COALESCE(s.revenue, 0), cogs = COALESCE(s.costs, 0),
    gross_profit = COALESCE(s.gross_profit, 0),
    operating_expense = e.marketing_amount + e.fulfillment_amount + e.platform_amount,
    net_profit = COALESCE(s.gross_profit, 0) - e.marketing_amount - e.fulfillment_amount - e.platform_amount,
    cash_collected = COALESCE(c.amount, 0)
FROM sales AS s LEFT JOIN cash AS c ON c.paid_on = s.ordered_on,
     operating_expenses AS e
WHERE d.business_date = s.ordered_on AND e.expense_date = d.business_date;

WITH monthly AS (
    SELECT date_trunc('month', business_date)::date AS month_start,
           SUM(net_revenue) AS sales, SUM(cogs) AS costs,
           SUM(operating_expense) AS expenses, SUM(net_profit) AS profit
    FROM finance_daily GROUP BY 1
), balances AS (
    SELECT m.*, COALESCE((SELECT SUM(inventory_value) FROM inventory_snapshots AS i
                         WHERE i.month_start = m.month_start), 0) AS inventory,
           round(m.sales * 0.22, 2) AS ar, round(m.costs * 0.16, 2) AS ap
    FROM monthly AS m
), assets AS (
    SELECT b.*, b.sales * 0.65 + b.inventory + b.ar + 12000 AS ca,
           b.ap + b.expenses * 0.5 + b.sales * 0.42 AS cl
    FROM balances AS b
), totals AS (
    SELECT a.*, a.ca + a.sales * 1.2 + 100000 AS ta,
           a.cl + a.sales * 0.4 AS tl
    FROM assets AS a
)
UPDATE finance_monthly AS f
SET net_revenue = t.sales, cogs = t.costs, operating_expense = t.expenses,
    net_profit = t.profit, receivables_balance = t.ar, payables_balance = t.ap,
    inventory_value = t.inventory, current_assets = t.ca, current_liabilities = t.cl,
    total_assets = t.ta, total_liabilities = t.tl, equity = t.ta - t.tl,
    equity_ratio_pct = round((t.ta - t.tl) / NULLIF(t.ta, 0) * 100, 2),
    debt_equity_pct = round(t.tl / NULLIF(t.ta - t.tl, 0) * 100, 2),
    current_ratio = round(t.ca / NULLIF(t.cl, 0), 2),
    dso_days = round(t.ar / NULLIF(t.sales, 0) * 30, 2),
    dpo_days = round(t.ap / NULLIF(t.costs, 0) * 30, 2),
    dsi_days = round(t.inventory / NULLIF(t.costs, 0) * 30, 2),
    net_working_capital = t.ca - t.cl, gross_working_capital = t.ca
FROM totals AS t WHERE f.month_start = t.month_start;

WITH unpaid AS (
    SELECT o.ordered_at::date + 30 AS due_on, SUM(i.quantity * i.unit_price) AS amount
    FROM orders AS o JOIN order_items AS i ON i.order_id = o.id
    WHERE o.order_status = 'completed' AND o.id % 7 = 0 GROUP BY o.id
), ar_buckets AS (
    SELECT CASE WHEN due_on >= CURRENT_DATE THEN 'Current'
                WHEN CURRENT_DATE - due_on <= 30 THEN '1-30'
                WHEN CURRENT_DATE - due_on <= 60 THEN '31-60'
                WHEN CURRENT_DATE - due_on <= 90 THEN '61-90' ELSE '91+' END AS bucket,
           SUM(amount) AS amount FROM unpaid GROUP BY 1
), ap_buckets AS (
    SELECT CASE WHEN due_on >= CURRENT_DATE THEN 'Current'
                WHEN CURRENT_DATE - due_on <= 30 THEN '1-30'
                WHEN CURRENT_DATE - due_on <= 60 THEN '31-60'
                WHEN CURRENT_DATE - due_on <= 90 THEN '61-90' ELSE '91+' END AS bucket,
           SUM(amount) AS amount FROM supplier_invoices WHERE NOT is_paid GROUP BY 1
)
UPDATE aging_balances AS a
SET receivable_amount = COALESCE(b.ar_amount, 0),
    payable_amount = COALESCE(b.ap_amount, 0)
FROM (SELECT a2.aging_bucket, ar.amount AS ar_amount, ap.amount AS ap_amount
      FROM aging_balances AS a2 LEFT JOIN ar_buckets AS ar ON ar.bucket = a2.aging_bucket
      LEFT JOIN ap_buckets AS ap ON ap.bucket = a2.aging_bucket) AS b
WHERE a.aging_bucket = b.aging_bucket;

UPDATE coupon_redemptions AS c
SET discount_amount = round(f.net_revenue * p.discount_pct / 100, 2)
FROM order_facts AS f, promotions AS p
WHERE f.order_id = c.order_id AND p.id = c.promotion_id;
UPDATE refunds AS r SET amount = f.net_revenue,
    refunded_on = pr.requested_on + CASE WHEN r.id % 10 < 7 THEN 2 ELSE 5 END
FROM product_returns AS pr JOIN order_facts AS f ON f.order_id = pr.order_id
WHERE r.return_id = pr.id;
UPDATE order_taxes AS t
SET taxable_amount = f.net_revenue, tax_amount = tax.tax_amount
FROM order_facts AS f,
     (SELECT i.order_id,
             round(SUM(i.quantity * i.unit_price * r.tax_pct / 100), 2) AS tax_amount
      FROM order_items AS i JOIN products AS p ON p.id = i.product_id
      JOIN tax_rates AS r ON r.category_id = p.category_id
      GROUP BY i.order_id) AS tax
WHERE t.order_id = f.order_id AND tax.order_id = t.order_id;
UPDATE inventory_movements AS m
SET quantity_delta = CASE WHEN m.movement_type = 'sale' THEN -i.quantity
                          ELSE i.quantity END,
    warehouse_id = s.warehouse_id
FROM order_items AS i JOIN shipments AS s ON s.order_id = i.order_id
WHERE m.order_item_id = i.id AND m.movement_type IN ('sale', 'return');
UPDATE inventory_movements AS m
SET quantity_delta = i.quantity, warehouse_id = po.warehouse_id
FROM purchase_order_items AS i JOIN purchase_orders AS po ON po.id = i.purchase_order_id
WHERE m.movement_type = 'receipt' AND m.id = 1000000 + i.id;
WITH sessions AS (
    SELECT started_at::date AS day, COUNT(*) AS sessions_count,
           COUNT(*) FILTER (WHERE converted_order_id IS NOT NULL) AS conversions_count
    FROM web_sessions GROUP BY 1
), cart_counts AS (
    SELECT created_at::date AS day, COUNT(*) AS carts_count FROM carts GROUP BY 1
)
UPDATE funnel_daily AS f
SET sessions_count = COALESCE(v.sessions_count, 0),
    carts_count = COALESCE(v.carts_count, 0),
    conversions_count = COALESCE(v.conversions_count, 0)
FROM (SELECT f2.business_date, s.sessions_count, c.carts_count, s.conversions_count
      FROM funnel_daily AS f2 LEFT JOIN sessions AS s ON s.day = f2.business_date
      LEFT JOIN cart_counts AS c ON c.day = f2.business_date) AS v
WHERE f.business_date = v.business_date;
WITH daily AS (SELECT refunded_on, SUM(amount) AS amount FROM refunds GROUP BY refunded_on)
UPDATE fulfillment_daily AS f
SET refunds_amount = COALESCE(d.amount, 0),
    shipments_count = COALESCE(d.shipments_count, 0),
    returns_count = COALESCE(d.returns_count, 0),
    avg_delivery_days = d.avg_delivery_days
FROM (SELECT f2.business_date, d2.amount, s.shipments_count,
             r.returns_count, s.avg_delivery_days
      FROM fulfillment_daily AS f2 LEFT JOIN daily AS d2 ON d2.refunded_on = f2.business_date
      LEFT JOIN (SELECT shipped_on, COUNT(*) AS shipments_count,
                        round(AVG(delivered_on - shipped_on), 2) AS avg_delivery_days
                 FROM shipments GROUP BY shipped_on) AS s ON s.shipped_on = f2.business_date
      LEFT JOIN (SELECT requested_on, COUNT(*) AS returns_count
                 FROM product_returns GROUP BY requested_on) AS r ON r.requested_on = f2.business_date) AS d
WHERE f.business_date = d.business_date;

DO $$
DECLARE spread numeric;
BEGIN
    SELECT max(margin_pct) - min(margin_pct) INTO spread
    FROM (SELECT SUM(gross_profit) / NULLIF(SUM(net_revenue), 0) * 100 AS margin_pct
          FROM order_facts GROUP BY region) AS regional;
    IF spread < 10
       OR (SELECT COUNT(*) FROM customers WHERE region = 'South') <=
          (SELECT COUNT(*) FROM customers WHERE region = 'West')
       OR (SELECT COUNT(*) FROM web_sessions WHERE device_type = 'Mobile') <=
          (SELECT COUNT(*) FROM web_sessions WHERE device_type = 'Tablet')
       OR (SELECT SUM(net_revenue - cogs - gross_profit) FROM order_facts) <> 0
       OR (SELECT SUM(net_revenue - cogs - operating_expense - net_profit) FROM finance_daily) <> 0
       OR (SELECT SUM(cash_collected) FROM finance_daily) <>
          (SELECT SUM(amount) FROM payments WHERE paid_on <= CURRENT_DATE)
       OR (SELECT SUM(net_revenue) FROM finance_monthly) <>
          (SELECT SUM(net_revenue) FROM finance_daily)
       OR (SELECT SUM(sessions_count) FROM funnel_daily) <> (SELECT COUNT(*) FROM web_sessions)
       OR (SELECT SUM(shipments_count) FROM fulfillment_daily) <>
          (SELECT COUNT(*) FROM shipments WHERE shipped_on <= CURRENT_DATE) THEN
        RAISE EXCEPTION 'Ecommerce data variation failed reconciliation';
    END IF;
END $$;
COMMIT;
