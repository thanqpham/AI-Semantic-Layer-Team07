"""Check scaled seed generation without connecting to a database."""

import asyncio
import unittest
from pathlib import Path

from scripts.ecommerce_scale_seed import build_seed


class ScaleSeedTests(unittest.TestCase):
    def test_exact_order_generator_and_dependent_populations(self) -> None:
        seed = Path("scripts/ecommerce_dashboard_demo_pg.sql").read_text(encoding="utf-8")
        result = asyncio.run(build_seed(seed, 100000))
        self.assertIn("generate_series(1, 100000) AS n", result)
        self.assertNotIn("CROSS JOIN generate_series(0, 7) AS slot;", result)
        self.assertIn("generate_series(1, 68493)", result)
        self.assertIn("generate_series(1, 205479)", result)
        self.assertIn("Ecommerce data variation failed reconciliation", result)
        self.assertIn("FROM orders) <> 100000", result)
        self.assertIn("FROM web_sessions) <> 205479", result)
        self.assertIn("FROM web_events) <> 616437", result)
        self.assertIn("FROM carts) <> 68493", result)

    def test_rejects_unsupported_seed_and_size(self) -> None:
        with self.assertRaises(ValueError):
            asyncio.run(build_seed("", 100000))
        with self.assertRaises(ValueError):
            asyncio.run(build_seed("seed", -1))
        with self.assertRaises(ValueError):
            asyncio.run(build_seed("seed", "100000; DROP TABLE orders"))
