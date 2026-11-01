"""Categorical discovery must never schedule row scans."""

from src.services.categorical_proposals import queue_discovery


def test_row_discovery_is_disabled():
    assert queue_discovery(1, refresh_dismissed=True) is False
