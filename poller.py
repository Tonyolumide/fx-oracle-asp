"""Background poll job: fetch sources → weighted median → cache."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from cache import rate_cache
from composite import liquidity_weighted_median, premium_vs_official_pct
from models import SourceError, SourceQuote
from sources import market_sources, official_source

logger = logging.getLogger("fx-oracle.poller")

DEFAULT_PAIR = "NGN/USDT"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def refresh_rates(pair: str = DEFAULT_PAIR) -> None:
    """Poll all market sources + official benchmark; write cache snapshot."""
    pair = pair.upper().replace(" ", "")
    quotes: list[SourceQuote] = []
    errors: list[SourceError] = []

    for src in market_sources():
        try:
            result = await src.fetch(pair)
        except Exception as exc:  # noqa: BLE001
            logger.exception("source %s raised", src.name)
            errors.append(
                SourceError(
                    provider=src.name,
                    error=f"unhandled: {type(exc).__name__}: {exc}",
                    timestamp=_utcnow(),
                )
            )
            continue

        if isinstance(result, SourceQuote):
            quotes.append(result)
            logger.info(
                "source=%s rate=%s liquidity=%s",
                result.provider,
                result.rate,
                result.liquidity,
            )
        else:
            errors.append(result)
            logger.warning("source=%s error=%s", result.provider, result.error)

    official_rate: float | None = None
    try:
        official = await official_source().fetch(pair)
        if isinstance(official, SourceQuote):
            official_rate = official.rate
            # Keep official out of the composite input list; only premium fields use it.
        else:
            errors.append(official)
    except Exception as exc:  # noqa: BLE001
        errors.append(
            SourceError(
                provider="nafem_official",
                error=f"unhandled: {type(exc).__name__}: {exc}",
                timestamp=_utcnow(),
            )
        )

    composite = liquidity_weighted_median(quotes)
    premium = premium_vs_official_pct(composite, official_rate)

    snap = rate_cache.set(
        pair=pair,
        composite_rate=composite,
        sources=quotes,
        source_errors=errors,
        official_rate=official_rate,
        premium_vs_official_pct=premium,
    )
    logger.info(
        "cache updated pair=%s composite=%s sources=%d errors=%d",
        snap.pair,
        snap.composite_rate,
        len(snap.sources),
        len(snap.source_errors),
    )
