# Trend Direction Implementations — Audit + Fix Plan

As of 2026-05-31 there are **four** different trend-direction
implementations across the LumiSignals codebase, with subtle
correctness differences and inconsistent results for the same
inputs. This document records what's where, what's broken, and the
plan to converge them.

## TL;DR

| Implementation | Where | Used by | Direction correct? | ADX value correct? |
|---|---|---|---|---|
| `calculate_adx_direction` | `lumisignals/untouched_levels.py:248` | HTF Levels (stock side), swing_scanner | ✅ yes | ❌ ~14× inflated |
| `calculate_structure_direction` | `lumisignals/untouched_levels.py:94` | FX H1 Zone Scalp, FX Levels via router | ✅ yes (HH+HL) | n/a (strength 0-100, not ADX) |
| `calculate_trend_direction` | `lumisignals/untouched_levels.py:222` | All callers that route by instrument | ✅ via dispatch | inherits each impl's behavior |
| `_pine_adx_direction` | `lumisignals/swing_setup.py` (Dashboard panel) | `compute_setup()` | ✅ yes | ✅ proper 0-100 (Pine ta.dmi match) |

## The bug in `calculate_adx_direction`

**Direction is correct.** `+DI > -DI + 2` → UP; `+DI < -DI - 2` →
DOWN; else SIDE. Same algorithm as Pine's adx_dashboard.pine. The
+DI / -DI ratio works out because both numerator (+DM-smoothed) and
denominator (TR-smoothed) use the same accumulator-style "Wilder
smoothing" — the ratio is correct even though the individual
quantities aren't proper averages.

**ADX strength value is broken** (~14× too large). The function
applies the same accumulator-style Wilder TR-smoothing formula to
the DX series:

```python
def wilder_smooth(values, period):
    smoothed = [sum(values[:period])]                       # SUM, not mean
    for v in values[period:]:
        smoothed.append(smoothed[-1] - smoothed[-1] / period + v)
    return smoothed
```

DX values are already 0-100, so accumulating them over a 14-period
window produces output in the 0-1400 range. Empirically on
2026-05-31, this function returned ADX = 394-451 for major equities
on monthly bars (should be 28-32 per Pine `ta.dmi`).

**Proper Wilder smoothing** for averaging (Pine's `ta.rma`):

```python
def rma(values, n):
    if len(values) < n:
        return []
    first = sum(values[:n]) / n                              # MEAN
    out = [first]
    for v in values[n:]:
        out.append((out[-1] * (n - 1) + v) / n)
    return out
```

The `lumisignals/swing_setup.py:_pine_adx_dmi` implementation uses
proper RMA and produces values that match Pine.

### Consequence today

Strategies that read **direction only** from
`calculate_adx_direction` are unaffected:
- HTF Levels stock-side (`levels_strategy.py:_get_trade_builder_data`)
  uses direction for trend filter, ignores strength.
- `swing_scanner.py` candle-confirmation gating uses direction.

Strategies that read **strength** (ADX numeric value) get garbage.
None currently do — but if the mobile Strategies tab or any future
caller bases logic on the returned numeric, it will misbehave.

## Recommended convergence plan

**Goal:** one canonical ADX implementation everywhere; Pine match;
correct strength values.

### Step 1 (when convenient; not urgent)

Fix `calculate_adx_direction` in `untouched_levels.py` by replacing
the `wilder_smooth` call on the DX series with proper RMA. The
direction return value is already correct; only the strength field
changes. Verify no regression in HTF Levels / swing_scanner output
(direction unchanged so should be safe).

Concretely, replace:

```python
adx_smooth = wilder_smooth(dx_list, period)
adx_value = adx_smooth[-1] if adx_smooth else 0.0
```

with the equivalent of `_pine_adx_dmi`'s RMA logic. Better yet:
extract `_pine_adx_dmi` and `_pine_adx_direction` from
`swing_setup.py` into a shared module (perhaps `lumisignals/adx.py`)
that both `untouched_levels.py` and `swing_setup.py` import.

### Step 2

Once `calculate_adx_direction` is fixed, the dashboard panel's local
copy in `swing_setup.py` can be replaced with an import from the
shared module — no behavior change.

### Step 3 (optional, longer term)

Decide whether the FX strategies should also adopt Pine ADX, or
keep N=15 swing structure. The choice was deliberate — see the
docstring at `untouched_levels.py:118-121`:

> "Designed as a drop-in replacement for calculate_adx_direction for
> FX assets, where ADX's Wilder smoothing keeps single-bar volatility
> spikes (e.g. BoJ intervention candles) in memory for ~27 daily bars
> and pulls the +DI/-DI reading the wrong way."

For FX the structure approach is empirically better (the spike-
sensitivity argument). For equities the user prefers Pine ADX (matches
their TradingView dashboard reading).

The router `calculate_trend_direction(candles, instrument)` already
does asset-aware dispatch — leave it in place but make sure both
branches return correctly-normalized values.

## Reference: Pine ADX dashboard script

The canonical reference is `pinescripts/adx_dashboard.pine`. Key
parameters that must match across implementations:

- **Period**: 14 (DMI period == ADX smoothing period)
- **Direction buffer**: ±2 (`+DI > -DI + 2` for UP)
- **Momentum labels by ADX strength**:
  - ≥ 50: "Unusually Very Strong"
  - ≥ 30: "Very Strong"
  - ≥ 25: "Strong"
  - ≥ 20: "Moderate"
  - ≥ 15: "Weak"
  - ≥ 10: "Very Weak"
  - < 10: "No to Very Weak"

## How we got here

- 2026-04-ish: `untouched_levels.calculate_adx_direction` written with
  accumulator-style Wilder smoothing applied uniformly to TR, DM, and
  DX. The TR/DM use is correct (those are accumulated quantities by
  Wilder's design); the DX use is wrong.
- 2026-05-15: FX strategies migrated from ADX to `calculate_structure_direction`
  (task #41) because ADX's volatility-spike sensitivity gave bad
  reads on FX news days.
- 2026-05-31: Dashboard panel built (`swing_setup.py`); user pointed
  at `pinescripts/adx_dashboard.pine` as the canonical reference.
  `_pine_adx_dmi` and `_pine_adx_direction` written from scratch
  using proper Wilder RMA. Bug in the shared function discovered
  in the process; this doc + a follow-up task created instead of
  patching the shared function inline (to avoid HTF Levels regression
  risk).
