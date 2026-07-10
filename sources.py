"""
Upstream rate providers.

Only Yellow Card is implemented. Sources 2 and 3 (and the official NAFEM
benchmark) are explicit stubs until API docs/keys are provided — do not guess
endpoints.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

import httpx

from models import SourceError, SourceQuote

logger = logging.getLogger("fx-oracle.sources")

HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "15"))


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RateSource(ABC):
    name: str

    @abstractmethod
    async def fetch(self, pair: str) -> SourceQuote | SourceError:
        """Return a normalized quote or a structured error."""


# ---------------------------------------------------------------------------
# 1. Yellow Card — official Get Rates
#    https://docs.yellowcard.engineering/reference/get-rates
#    Rate is local currency per USD (USDT treated as 1:1 for this oracle).
# ---------------------------------------------------------------------------


class YellowCardSource(RateSource):
    name = "yellowcard"

    def __init__(self) -> None:
        self.api_key = os.getenv("YELLOWCARD_API_KEY", "").strip()
        self.api_secret = os.getenv("YELLOWCARD_API_SECRET", "").strip()
        self.base_url = os.getenv(
            "YELLOWCARD_BASE_URL", "https://api.yellowcard.io"
        ).rstrip("/")
        self.default_liquidity = float(
            os.getenv("YELLOWCARD_DEFAULT_LIQUIDITY", "1000000")
        )

    def _auth_headers(self, path: str, method: str = "GET") -> dict[str, str]:
        """YcHmacV1 signature per Yellow Card auth recipe."""
        if not self.api_key or not self.api_secret:
            raise RuntimeError(
                "YELLOWCARD_API_KEY and YELLOWCARD_API_SECRET are required "
                "for the Yellow Card rates API"
            )
        # ISO-8601 UTC with Z (docs recipe)
        date = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        mac = hmac.new(self.api_secret.encode("utf-8"), digestmod=hashlib.sha256)
        mac.update(date.encode("utf-8"))
        mac.update(path.encode("utf-8"))
        mac.update(method.upper().encode("utf-8"))
        signature = base64.b64encode(mac.digest()).decode("utf-8")
        return {
            "X-YC-Timestamp": date,
            "Authorization": f"YcHmacV1 {self.api_key}:{signature}",
            "Accept": "application/json",
        }

    async def fetch(self, pair: str) -> SourceQuote | SourceError:
        pair_u = pair.upper().replace(" ", "")
        if pair_u not in {"NGN/USDT", "NGN/USD", "USDT/NGN"}:
            return SourceError(
                provider=self.name,
                error=f"unsupported pair {pair!r} for yellowcard adapter",
                timestamp=_utcnow(),
            )

        # Always query NGN; Yellow Card quotes local-per-USD.
        path = "/business/rates"
        query = "currency=NGN"
        # Sign path without query string (Yellow Card recipe signs request path)
        try:
            headers = self._auth_headers(path, "GET")
        except RuntimeError as exc:
            return SourceError(
                provider=self.name, error=str(exc), timestamp=_utcnow()
            )

        url = f"{self.base_url}{path}?{query}"
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                resp = await client.get(url, headers=headers)
                resp.raise_for_status()
                payload = resp.json()
        except httpx.HTTPStatusError as exc:
            body = exc.response.text[:300] if exc.response is not None else ""
            return SourceError(
                provider=self.name,
                error=f"HTTP {exc.response.status_code}: {body}",
                timestamp=_utcnow(),
            )
        except Exception as exc:  # noqa: BLE001 — surface any upstream failure
            return SourceError(
                provider=self.name,
                error=f"{type(exc).__name__}: {exc}",
                timestamp=_utcnow(),
            )

        return self._normalize(payload)

    def _normalize(self, payload: dict[str, Any]) -> SourceQuote | SourceError:
        rates = payload.get("rates") or []
        ngn: dict[str, Any] | None = None
        for row in rates:
            if str(row.get("code", "")).upper() == "NGN":
                ngn = row
                break
        if ngn is None and rates:
            # Some responses may be a single object when filtered by currency
            if isinstance(rates, dict):
                ngn = rates  # type: ignore[assignment]
            elif len(rates) == 1:
                ngn = rates[0]

        if not ngn:
            return SourceError(
                provider=self.name,
                error="NGN rate not present in Yellow Card response",
                timestamp=_utcnow(),
            )

        buy = float(ngn["buy"]) if ngn.get("buy") is not None else None
        sell = float(ngn["sell"]) if ngn.get("sell") is not None else None
        if buy is None and sell is None:
            return SourceError(
                provider=self.name,
                error="buy/sell missing on NGN row",
                timestamp=_utcnow(),
            )
        if buy is not None and sell is not None:
            rate = (buy + sell) / 2.0
            qtype = "mid"
        elif buy is not None:
            rate = buy
            qtype = "buy"
        else:
            rate = float(sell)  # type: ignore[arg-type]
            qtype = "sell"

        ts_raw = ngn.get("updatedAt")
        try:
            ts = (
                datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
                if ts_raw
                else _utcnow()
            )
        except ValueError:
            ts = _utcnow()

        return SourceQuote(
            provider=self.name,
            rate=rate,
            type=qtype,  # type: ignore[arg-type]
            liquidity=self.default_liquidity,
            timestamp=ts,
            meta={
                "buy": buy,
                "sell": sell,
                "locale": ngn.get("locale"),
                "rateId": ngn.get("rateId"),
                "code": ngn.get("code", "NGN"),
                "note": "Yellow Card rate is local currency per USD; treated as NGN/USDT",
            },
        )


# ---------------------------------------------------------------------------
# 2. STUB — waiting for API docs / keys from you
# ---------------------------------------------------------------------------


class SourceTwoStub(RateSource):
    name = "source_two"

    async def fetch(self, pair: str) -> SourceQuote | SourceError:
        return SourceError(
            provider=self.name,
            error=(
                "not_configured: provide API base URL, auth, and response schema "
                "before this adapter is implemented"
            ),
            timestamp=_utcnow(),
        )


# ---------------------------------------------------------------------------
# 3. STUB — waiting for API docs / keys from you
# ---------------------------------------------------------------------------


class SourceThreeStub(RateSource):
    name = "source_three"

    async def fetch(self, pair: str) -> SourceQuote | SourceError:
        return SourceError(
            provider=self.name,
            error=(
                "not_configured: provide API base URL, auth, and response schema "
                "before this adapter is implemented"
            ),
            timestamp=_utcnow(),
        )


# ---------------------------------------------------------------------------
# Official NAFEM benchmark — STUB until you provide the source
# ---------------------------------------------------------------------------


class NafemOfficialStub:
    """Official benchmark used only for premium_vs_official_pct."""

    name = "nafem_official"

    async def fetch(self, pair: str) -> SourceQuote | SourceError:
        return SourceError(
            provider=self.name,
            error=(
                "not_configured: provide the official NAFEM rate endpoint "
                "(or static feed) before premium_vs_official_pct is populated"
            ),
            timestamp=_utcnow(),
        )


def market_sources() -> list[RateSource]:
    """Sources that participate in the liquidity-weighted composite."""
    return [
        YellowCardSource(),
        SourceTwoStub(),
        SourceThreeStub(),
    ]


def official_source() -> NafemOfficialStub:
    return NafemOfficialStub()
