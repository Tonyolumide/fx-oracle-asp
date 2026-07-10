"""Shared Pydantic models for fx-oracle-asp."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class SourceQuote(BaseModel):
    """Normalized quote from a single upstream provider."""

    provider: str
    rate: float = Field(..., description="Units of base (NGN) per 1 quote (USDT)")
    type: Literal["buy", "sell", "mid", "official"] = "mid"
    liquidity: float = Field(
        ...,
        ge=0,
        description="Relative liquidity weight used in the composite median",
    )
    timestamp: datetime
    meta: dict[str, Any] = Field(default_factory=dict)


class SourceError(BaseModel):
    provider: str
    error: str
    timestamp: datetime


class RateResponse(BaseModel):
    pair: str
    composite_rate: float | None = Field(
        None,
        description="Liquidity-weighted median of successful source quotes",
    )
    premium_vs_official_pct: float | None = Field(
        None,
        description=(
            "(composite_rate - official_rate) / official_rate * 100. "
            "Null until the official NAFEM source is configured."
        ),
    )
    official_rate: float | None = None
    sources: list[SourceQuote]
    source_errors: list[SourceError] = Field(default_factory=list)
    computed_at: datetime
    stale: bool = Field(
        False,
        description="True if cache has never been refreshed successfully",
    )


class HealthResponse(BaseModel):
    status: str
    cache_ready: bool
    last_computed_at: datetime | None = None
    sources_ok: list[str] = Field(default_factory=list)
