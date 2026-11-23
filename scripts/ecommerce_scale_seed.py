"""Generate a scaled ecommerce seed for a NEW, EMPTY test database."""

import argparse
import asyncio
import hashlib
from pathlib import Path


async def replace_once(seed: str, old: str, new: str) -> str:
    """Refuse unrecognized seed revisions rather than silently generating wrong data."""
    if seed.count(old) != 1:
        raise ValueError(f"Expected exactly one seed marker: {old}")
    return seed.replace(old, new, 1)


async def build_seed(seed: str, orders: int) -> str:
    """Scale transactions while retaining dimensions and daily/monthly grains."""
    if type(orders) is not int or orders < 5840 or orders > 1000000:
        raise ValueError("Order count must be between 5840 and 1000000")
    start = seed.index("INSERT INTO orders\n") if "INSERT INTO orders\n" in seed else -1
    if start < 0:
        raise ValueError("Unsupported seed: orders marker missing")
    end = seed.index("INSERT INTO order_items\n", start)
    seed = seed[:start] + await order_insert(orders) + seed[end:]
    for old, new in [(4000, 4000 * orders // 5840), (12000, 12000 * orders // 5840), (600, 600 * orders // 5840)]:
        seed = await replace_once(seed, f"generate_series(1, {old}) AS n", f"generate_series(1, {new}) AS n")
    seed = await replace_once(seed, "1 + n % 5840", f"1 + n % {orders}")
    seed = await replace_once(seed, "FROM orders) <> 5840", f"FROM orders) <> {orders}")
    seed = await scale_coverage_checks(seed, orders)
    checksum = hashlib.sha256(seed.encode()).hexdigest()
    return f"-- Scale generator v1; orders={orders}; SQL SHA256={checksum}\n" + seed


async def order_insert(orders: int) -> str:
    """Distribute an exact number of orders over the seed's 730-day window."""
    if type(orders) is not int:
        raise ValueError("Order count must be an integer")
    return f"""INSERT INTO orders
SELECT n, 1 + (n * 17) % 360,
       (CURRENT_DATE - 729 + ((n - 1) % 730))::timestamp
           + make_interval(hours => 8 + ((n - 1) / 730) % 12),
       (ARRAY['Web','Marketplace','Mobile'])[1 + n % 3],
       CASE WHEN n % 23 = 0 THEN 'returned'
            WHEN n % 17 = 0 THEN 'cancelled' ELSE 'completed' END
FROM generate_series(1, {orders}) AS n;
"""  # noqa: S608 -- Only a validated integer is interpolated into generated seed SQL.


async def scale_coverage_checks(seed: str, orders: int) -> str:
    """Retain seed assertions with the corresponding scaled row counts."""
    for table, old, new in [
        ("web_sessions", 12000, 12000 * orders // 5840),
        ("web_events", 36000, 3 * (12000 * orders // 5840)),
        ("carts", 4000, 4000 * orders // 5840),
    ]:
        seed = await replace_once(seed, f"FROM {table}) <> {old}", f"FROM {table}) <> {new}")
    return seed


async def main() -> None:
    """Write SQL without opening a database connection or replacing existing files."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--orders", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    seed = Path(__file__).with_name("ecommerce_dashboard_demo_pg.sql").read_text(encoding="utf-8")
    result = await build_seed(seed, args.orders)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as output:
        output.write(result)
    print(f"Generated {args.orders} orders; load only into a NEW, EMPTY test database.")


if __name__ == "__main__":
    asyncio.run(main())
