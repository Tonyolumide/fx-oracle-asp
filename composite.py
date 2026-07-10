"""Liquidity-weighted median and premium helpers."""

from __future__ import annotations

from models import SourceQuote


def liquidity_weighted_median(quotes: list[SourceQuote]) -> float | None:
    """
    Liquidity-weighted median of rates.

    Sort quotes by rate ascending. Walk cumulative liquidity until half the
    total weight is reached; that quote's rate is the median.

    With equal weights this reduces to a classic median. With uneven liquidity
    deeper books pull the median toward their rates.
    """
    usable = [q for q in quotes if q.liquidity > 0 and q.rate > 0]
    if not usable:
        return None

    ordered = sorted(usable, key=lambda q: q.rate)
    total = sum(q.liquidity for q in ordered)
    if total <= 0:
        return None

    half = total / 2.0
    cumulative = 0.0
    for q in ordered:
        cumulative += q.liquidity
        if cumulative >= half:
            return float(q.rate)

    return float(ordered[-1].rate)


def premium_vs_official_pct(composite: float | None, official: float | None) -> float | None:
    """Percent premium of composite over official. Positive = composite above official."""
    if composite is None or official is None or official == 0:
        return None
    return round((composite - official) / official * 100.0, 6)
