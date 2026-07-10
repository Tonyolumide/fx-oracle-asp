> **Moved:** This project now lives in the monorepo  
> **https://github.com/Tonyolumide/asp-platform** under `services/fx-oracle-asp`.  
> Prefer opening PRs there. This repo is kept for history only.

# fx-oracle-asp

Read-only **NGN/USDT** composite FX oracle. A background job polls rate sources, computes a **liquidity-weighted median**, and caches the result. `GET /rate` serves **only from cache** and is gated by **x402** micropayments.

No frontend. No trading / execution logic.

## Endpoints

| Method | Path | Payment | Description |
|--------|------|---------|-------------|
| `GET` | `/health` | free | Liveness + cache status |
| `GET` | `/rate?pair=NGN/USDT` | **$0.008** exact | Cached composite rate |

### `GET /rate` response shape

```json
{
  "pair": "NGN/USDT",
  "composite_rate": 1625.5,
  "premium_vs_official_pct": null,
  "official_rate": null,
  "sources": [
    {
      "provider": "yellowcard",
      "rate": 1625.5,
      "type": "mid",
      "liquidity": 1000000,
      "timestamp": "2026-07-09T12:00:00+00:00",
      "meta": { "buy": 1630.0, "sell": 1621.0 }
    }
  ],
  "source_errors": [
    {
      "provider": "source_two",
      "error": "not_configured: ...",
      "timestamp": "2026-07-09T12:00:00+00:00"
    }
  ],
  "computed_at": "2026-07-09T12:00:00+00:00",
  "stale": false
}
```

## Payment (x402)

| Setting | Value |
|---------|--------|
| Scheme | `exact` |
| Price | `$0.008` per call |
| Network | `NETWORK` env (default `eip155:84532` Base Sepolia) |
| Recipient | `PAY_TO_ADDRESS` |
| Facilitator | `FACILITATOR_URL` (default `https://x402.org/facilitator`) |

Uses the official `x402[fastapi,httpx,evm]` package (`PaymentMiddlewareASGI` + `ExactEvmServerScheme`).

## Rate sources

| # | Provider | Status |
|---|----------|--------|
| 1 | **Yellow Card** `GET /business/rates?currency=NGN` | Implemented ([docs](https://docs.yellowcard.engineering/reference/get-rates)) |
| 2 | *(TBD)* | Stub — waiting for API docs/keys |
| 3 | *(TBD)* | Stub — waiting for API docs/keys |
| Official | **NAFEM** benchmark | Stub — used only for `premium_vs_official_pct` |

Yellow Card returns local currency **per USD** (`buy` / `sell`). The adapter stores the **mid** as NGN per USDT (USDT ≈ USD for this oracle). Liquidity is not in the Yellow Card rates payload, so weight defaults to `YELLOWCARD_DEFAULT_LIQUIDITY` (override via env).

### Composite: liquidity-weighted median

Not a plain average. Quotes are sorted by rate; cumulative liquidity weight is walked until half of total weight is reached. That rate is `composite_rate`.

```
premium_vs_official_pct = (composite_rate - official_rate) / official_rate * 100
```

`null` until the NAFEM source is wired up.

## Setup

```bash
cd fx-oracle-asp
python -m venv .venv
# Windows: .venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Edit `.env`:

```env
PAY_TO_ADDRESS=0xYourReceivingWallet
FACILITATOR_URL=https://x402.org/facilitator
NETWORK=eip155:84532

# Required for live Yellow Card pulls
YELLOWCARD_API_KEY=...
YELLOWCARD_API_SECRET=...
YELLOWCARD_BASE_URL=https://api.yellowcard.io
```

Yellow Card also commonly requires **IP allowlisting** on the partner account.

## Run

```bash
uvicorn main:app --host 0.0.0.0 --port 8001 --reload
```

- Health: `http://localhost:8001/health`
- Docs: `http://localhost:8001/docs`

### curl

```bash
# free
curl -s http://localhost:8001/health

# unpaid → expect HTTP 402 + PAYMENT-REQUIRED header
curl -i "http://localhost:8001/rate?pair=NGN/USDT"
```

## Project layout

```
fx-oracle-asp/
├── main.py           # FastAPI app, x402 gate, APScheduler lifecycle
├── poller.py         # Background refresh job
├── sources.py        # Yellow Card + stubs for 2/3/NAFEM
├── composite.py      # Liquidity-weighted median + premium
├── cache.py          # In-memory snapshot
├── models.py         # Pydantic schemas
├── requirements.txt
├── .env.example
└── README.md
```

## Pending (need from you)

Before implementing the remaining adapters, please send:

1. **Source 2** — base URL, auth (header/API key/HMAC), example request/response for NGN/USDT (or NGN/USD), and whether a liquidity field exists.
2. **Source 3** — same as above.
3. **Official NAFEM rate** — endpoint or feed used as the benchmark for `premium_vs_official_pct`.
