# What We Did — Trade Setups & Scanner (notes for the developer)

This is a plain-language summary. Each part has a **Tech detail** line with the
exact facts you'll need.

---

## The big idea (read this first)

Getting price data is like making phone calls to a far-away library. The slow
part was never the math — the math is super fast. The slow part is the **phone
calls**. To get prices for 700 stocks the normal way, you make **700 phone
calls**. That is what makes things slow.

We found a **magic phone number**: one single call that gives back **every**
stock's daily prices at once. So instead of 700 calls, you make **one**. Now
the whole job is fast and cheap, and you do **not** need a bigger server.

> **Tech detail:** the "grouped daily" endpoint —
> `GET /v2/aggs/grouped/locale/us/market/stocks/{date}` (Massive/Polygon).
> One call returns the daily bar for ~12,000 tickers. Crypto and FX have their
> own grouped endpoints (`.../global/market/crypto/{date}` and `.../fx/{date}`).
> Indices have **no** grouped endpoint — fetch those one at a time (only a
> handful exist, so that's fine).

---

## 1. The fast scanner (look at all 700 at once)

**Plain words:** We made a tool that looks at 700 stocks and tells you which
ones are sitting right at an important price line (a "floor" or "ceiling")
**right now**. It does this in about **1.5 seconds**.

How it works:
1. Once a day, make the one big call to get every stock's daily prices, and
   keep them in memory (a "store").
2. From those daily prices, build the weekly and monthly prices **on our own
   computer** (no extra calls).
3. Run the level math on all 700. This part is tiny and fast.

**You do NOT need to pre-compute everything in the background, and you do NOT
need a bigger/more expensive server.** The one big call + a little local math
is enough.

> **Tech detail:** see `scripts/bench_mtf_scan.py` (run with `--scan`). It warms
> a local `{ticker: [daily bars]}` store from the grouped call, then derives
> Weekly (Monday-start ISO weeks) and Monthly (calendar months) in memory, and
> runs `find_htf_levels` (in `lumisignals/untouched_levels.py`). The data plan
> allows unlimited requests — measured 0 throttling at ~170 req/s.

---

## 2. The numbers really do match TradingView

**Plain words:** The dashboard shows two columns side by side:
- **TV** = TradingView's own number. We do **not** calculate this. TradingView's
  script sends it to us directly.
- **SRV** = our own number, calculated a totally different way.

When the two columns are the same, it means our math matches TradingView's math.
We checked it carefully and they match **to the penny** on stocks (Daily,
Weekly, Monthly).

> **Tech detail:** the TV column is the payload from the `htf_strategy.pine`
> alert (strategy `tv_levels_sync`), pushed by TradingView's webhook and stored
> as-is. The SRV column is our independent `find_htf_levels` result from price
> data. The big call does **not** change any number — it returns the same daily
> bar as a one-at-a-time call; it only changes *how* you ask. Verified with the
> `--verify` mode in the scanner (diffs grouped vs SRV vs TV per timeframe).

**Two honest exceptions:**
- **Crypto** is about 0.1% off on recent highs. That's a data-feed difference
  (crypto has no single official price), not a math bug.
- **Forex** must use OANDA prices, not Polygon — because TradingView's forex
  charts use OANDA. (Out of scope here, just so you know.)

---

## 3. Two quick speed fixes in the data client

These make the **existing** system faster too, not just the scanner.

1. **Open more phone lines.** The client could only make ~10 calls at the same
   time, even if we asked for more. Bumping that number lets many calls run at
   once.
   > **Tech detail:** `requests.Session` defaults to `pool_maxsize=10`. Mount an
   > `HTTPAdapter(pool_maxsize=~32)` on the session in
   > `lumisignals/massive_client.py`.

2. **Stop asking for the same thing 3 times.** For short timeframes, the code
   fetched the 5-minute bars three separate times. Fetch them once and build the
   1-hour and 4-hour bars from that one fetch.
   > **Tech detail:** `get_candles` re-pulls 5m for 5m, 1h, and 4h. Pull 5m once,
   > derive 1h/4h locally.

---

## 4. A bug fix: TradingView values disappeared on weekends

**Plain words:** On weekends the dashboard showed "no TradingView alert" instead
of the last known values. The values were being **thrown away after one day**.
A weekend is longer than a day (markets are closed ~3 days), so by Saturday
night they were gone. We changed it to keep them for **7 days**, so the last
values stay visible all weekend (marked as "not live").

> **Tech detail:** `tv:levels:{ticker}` was written with `setex(..., 86400, ...)`
> (24h). Changed to `604800` (7 days) in both alert-write paths in `saas/app.py`.
> A fresh push still overwrites it. Already-expired keys come back on the next
> push. (This fix is in the main app, not in this bundle.)

---

## 5. What is NOT in this bundle (on purpose)

- **Option volatility / IV** — not included. The trade-setup file returns the
  price levels, direction, and a shares plan. The options/IV part is left out.
- **A saved (on-disk) daily store** — right now the scanner builds the store
  fresh each run. For production you'd save it (e.g., a small daily job) so it
  only fetches the new day each morning.

---

## TL;DR for the developer

- One big "grouped" call replaces 700 small ones. **No CPU upgrade needed.**
- Build weekly/monthly from daily **locally** — it's basically free.
- Our levels match TradingView (stocks: exact; crypto: ~0.1%; forex: use OANDA).
- Quick wins in the client: bigger connection pool, don't re-fetch 5m bars.
- The scanner is `scripts/bench_mtf_scan.py`; the level math is
  `lumisignals/untouched_levels.py`; the data client is
  `lumisignals/massive_client.py`.
