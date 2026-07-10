"""Thread-safe in-memory cache for the latest composite rate snapshot."""

from __future__ import annotations

import threading
from datetime import datetime, timezone

from models import RateResponse, SourceError, SourceQuote


class RateCache:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._snapshot: RateResponse | None = None

    def get(self, pair: str) -> RateResponse | None:
        with self._lock:
            if self._snapshot is None:
                return None
            if self._snapshot.pair.upper() != pair.upper():
                return None
            return self._snapshot.model_copy(deep=True)

    def set(
        self,
        pair: str,
        composite_rate: float | None,
        sources: list[SourceQuote],
        source_errors: list[SourceError],
        official_rate: float | None,
        premium_vs_official_pct: float | None,
    ) -> RateResponse:
        snap = RateResponse(
            pair=pair.upper(),
            composite_rate=composite_rate,
            premium_vs_official_pct=premium_vs_official_pct,
            official_rate=official_rate,
            sources=sources,
            source_errors=source_errors,
            computed_at=datetime.now(timezone.utc),
            stale=composite_rate is None,
        )
        with self._lock:
            self._snapshot = snap
            return snap.model_copy(deep=True)

    def last_computed_at(self) -> datetime | None:
        with self._lock:
            return None if self._snapshot is None else self._snapshot.computed_at

    def ready(self) -> bool:
        with self._lock:
            return self._snapshot is not None and self._snapshot.composite_rate is not None


rate_cache = RateCache()
