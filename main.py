"""
fx-oracle-asp — read-only NGN/USDT composite FX oracle, gated by x402.

Background job polls rate sources every N minutes, computes a
liquidity-weighted median, caches it. GET /rate serves from cache only.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query

from x402.http import FacilitatorConfig, HTTPFacilitatorClient, PaymentOption
from x402.http.middleware.fastapi import PaymentMiddlewareASGI
from x402.http.types import RouteConfig
from x402.mechanisms.evm.exact import ExactEvmServerScheme
from x402.schemas import Network
from x402.server import x402ResourceServer

from cache import rate_cache
from models import HealthResponse, RateResponse
from poller import DEFAULT_PAIR, refresh_rates

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("fx-oracle")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_PROD_ENVS = frozenset({"production", "prod", "mainnet"})
_ENVIRONMENT = os.getenv("ENVIRONMENT", "development").strip().lower()
_IS_PRODUCTION = _ENVIRONMENT in _PROD_ENVS

PAY_TO_ADDRESS = os.getenv("PAY_TO_ADDRESS")
if not PAY_TO_ADDRESS:
    raise RuntimeError("PAY_TO_ADDRESS environment variable is required")

_network_env = os.getenv("NETWORK", "").strip()
_facilitator_env = os.getenv("FACILITATOR_URL", "").strip()

if _IS_PRODUCTION:
    if not _network_env or not _facilitator_env:
        raise RuntimeError(
            "In production, NETWORK and FACILITATOR_URL must be set explicitly "
            "(no silent testnet defaults). "
            "Example: NETWORK=eip155:8453 FACILITATOR_URL=https://<prod-facilitator>"
        )
    if "x402.org/facilitator" in _facilitator_env:
        raise RuntimeError(
            "FACILITATOR_URL points at the public test facilitator "
            "(x402.org). Refuse to start in production — use a mainnet facilitator."
        )
    NETWORK: Network = _network_env  # type: ignore[assignment]
    FACILITATOR_URL = _facilitator_env
else:
    NETWORK = (_network_env or "eip155:84532")  # type: ignore[assignment]
    FACILITATOR_URL = _facilitator_env or "https://x402.org/facilitator"

PRICE = "$0.008"
try:
    POLL_INTERVAL_MINUTES = int(os.getenv("POLL_INTERVAL_MINUTES", "3"))
    if POLL_INTERVAL_MINUTES < 1:
        raise ValueError("must be >= 1")
except ValueError as exc:
    raise RuntimeError(
        "POLL_INTERVAL_MINUTES must be a positive integer"
    ) from exc

# ---------------------------------------------------------------------------
# Scheduler lifecycle
# ---------------------------------------------------------------------------

scheduler = AsyncIOScheduler()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # Immediate warm of cache so first paid request is not empty
    try:
        await refresh_rates(DEFAULT_PAIR)
    except Exception:  # noqa: BLE001
        logger.exception("initial rate refresh failed (will retry on schedule)")

    scheduler.add_job(
        refresh_rates,
        trigger="interval",
        minutes=POLL_INTERVAL_MINUTES,
        args=[DEFAULT_PAIR],
        id="refresh_rates",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    logger.info(
        "scheduler started — polling every %s minute(s)", POLL_INTERVAL_MINUTES
    )
    yield
    scheduler.shutdown(wait=False)
    logger.info("scheduler stopped")


app = FastAPI(
    title="fx-oracle-asp",
    description=(
        "Liquidity-weighted NGN/USDT composite rate oracle. "
        f"GET /rate is gated by x402 ({PRICE}, exact, {NETWORK})."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# x402 payment gate (official package — same pattern as risk-score-asp)
# ---------------------------------------------------------------------------

facilitator = HTTPFacilitatorClient(FacilitatorConfig(url=FACILITATOR_URL))
server = x402ResourceServer(facilitator)
server.register(NETWORK, ExactEvmServerScheme())

routes: dict[str, RouteConfig] = {
    "GET /rate": RouteConfig(
        accepts=[
            PaymentOption(
                scheme="exact",
                pay_to=PAY_TO_ADDRESS,
                price=PRICE,
                network=NETWORK,
            ),
        ],
        mime_type="application/json",
        description="NGN/USDT composite FX rate (liquidity-weighted median)",
    ),
}

app.add_middleware(PaymentMiddlewareASGI, routes=routes, server=server)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Liveness — no payment required."""
    snap = rate_cache.get(DEFAULT_PAIR)
    return HealthResponse(
        status="ok",
        cache_ready=rate_cache.ready(),
        last_computed_at=rate_cache.last_computed_at(),
        sources_ok=[s.provider for s in snap.sources] if snap else [],
    )


@app.get("/rate", response_model=RateResponse)
async def get_rate(
    pair: str = Query(
        DEFAULT_PAIR,
        description="Currency pair. Currently only NGN/USDT is supported.",
        examples=["NGN/USDT"],
    ),
) -> RateResponse:
    """
    Serve the latest cached composite rate.

    Does **not** call upstream providers live — only the background job does.
    Requires x402 payment ($0.008, exact).
    """
    normalized = pair.upper().replace(" ", "")
    if normalized not in {"NGN/USDT", "NGN/USD"}:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported pair {pair!r}. Supported: NGN/USDT",
        )
    # Canonical key in cache
    cache_key = "NGN/USDT"
    snap = rate_cache.get(cache_key)
    if snap is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Rate cache is empty — background poller has not produced a "
                "snapshot yet. Retry shortly."
            ),
        )
    return snap


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=True)
