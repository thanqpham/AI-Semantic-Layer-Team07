"""Versioned local pricing catalog for reproducible benchmark cost estimates."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CostEstimate:
    """Hold a cost result without claiming unavailable prices are zero."""

    cost_usd: float | None
    status: str


@dataclass(frozen=True)
class PricingRate:
    """Describe one provider/model token price schedule in USD per million tokens."""

    provider: str
    model_prefix: str
    input_per_million_usd: float | None = None
    cached_input_per_million_usd: float | None = None
    output_per_million_usd: float | None = None
    reasoning_per_million_usd: float | None = None
    cost_status: str = "estimated"


class PricingCatalog:
    """Resolve provider/model rates and calculate deterministic local estimates."""

    def __init__(self, version: str, rates: tuple[PricingRate, ...]) -> None:
        self.version = version
        self._rates = rates

    def estimate(
        self,
        provider: str | None,
        model: str | None,
        input_tokens: int | None,
        output_tokens: int | None,
        cached_input_tokens: int | None,
        reasoning_tokens: int | None,
    ) -> CostEstimate:
        """Calculate an estimate only when the provider supplied billable token counts."""
        rate = self._rate(provider, model)
        if rate is None or input_tokens is None or output_tokens is None:
            return CostEstimate(None, "unavailable")
        if rate.cost_status == "free":
            return CostEstimate(0.0, "free")
        if rate.input_per_million_usd is None or rate.output_per_million_usd is None:
            return CostEstimate(None, "unavailable")
        return CostEstimate(
            _cost(rate, input_tokens, output_tokens, cached_input_tokens, reasoning_tokens), "estimated"
        )

    def _rate(self, provider: str | None, model: str | None) -> PricingRate | None:
        provider_name = (provider or "").casefold()
        model_name = (model or "").casefold()
        return next(
            (
                rate
                for rate in self._rates
                if rate.provider.casefold() == provider_name and model_name.startswith(rate.model_prefix.casefold())
            ),
            None,
        )


def load_pricing_catalog(path: Path | None = None) -> PricingCatalog:
    """Load the repository-pinned pricing catalog without performing network I/O."""
    catalog_path = path or Path(__file__).with_name("pricing_catalog.json")
    payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    rates = tuple(PricingRate(**item) for item in payload["rates"])
    return PricingCatalog(version=str(payload["version"]), rates=rates)


def _cost(
    rate: PricingRate,
    input_tokens: int,
    output_tokens: int,
    cached_input_tokens: int | None,
    reasoning_tokens: int | None,
) -> float:
    cached = min(cached_input_tokens or 0, input_tokens)
    input_cost = (input_tokens - cached) * rate.input_per_million_usd / 1_000_000
    cached_cost = cached * (rate.cached_input_per_million_usd or rate.input_per_million_usd) / 1_000_000
    output_cost = output_tokens * rate.output_per_million_usd / 1_000_000
    reasoning_cost = (reasoning_tokens or 0) * (rate.reasoning_per_million_usd or 0) / 1_000_000
    return input_cost + cached_cost + output_cost + reasoning_cost
