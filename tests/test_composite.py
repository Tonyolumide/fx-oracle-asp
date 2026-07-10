"""Unit tests for liquidity-weighted median (no network)."""

from datetime import datetime, timezone

from composite import liquidity_weighted_median, premium_vs_official_pct
from models import SourceQuote


def _q(rate: float, liq: float, provider: str = "p") -> SourceQuote:
    return SourceQuote(
        provider=provider,
        rate=rate,
        type="mid",
        liquidity=liq,
        timestamp=datetime.now(timezone.utc),
    )


def test_equal_weights_median_odd():
    quotes = [_q(10, 1), _q(20, 1), _q(30, 1)]
    assert liquidity_weighted_median(quotes) == 20


def test_heavy_book_pulls_median():
    # Large liquidity on high rate should dominate
    quotes = [_q(100, 1), _q(200, 100), _q(300, 1)]
    assert liquidity_weighted_median(quotes) == 200


def test_single_quote():
    assert liquidity_weighted_median([_q(1500, 50)]) == 1500.0


def test_empty():
    assert liquidity_weighted_median([]) is None


def test_premium():
    assert premium_vs_official_pct(110, 100) == 10.0
    assert premium_vs_official_pct(90, 100) == -10.0
    assert premium_vs_official_pct(None, 100) is None
    assert premium_vs_official_pct(100, None) is None
