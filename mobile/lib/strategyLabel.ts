// Shared helper for composing the strategy/model display badge used
// across Positions, Trades, and Dashboard.
//
// Strategy naming:
//   • Tidewater  — HTF Levels family (was "HTF"). Three durations:
//       Scalp    (1H zones, 5m trigger, 15m bias)
//       Intraday (1D zones, 15m trigger, 1H bias)
//       Swing    (1mo zones, 1D trigger, 1W bias)
//   • Stillwater — FX 4H trend
//   • H1 Zone Scalp — paper-only 5m H1-zone scalper
//   • 2N20 — VWAP overwhelm scalp
//   • ORB — opening range breakout
//
// Raw fields come in many forms (model="scalp", strategy="htf_levels",
// strategy="vwap_2n20", strategy="scalp_h1zone", etc.) so we normalize.

const TIDEWATER_DURATION: Record<string, string> = {
  scalp: 'Scalp',
  intraday: 'Intraday',
  swing: 'Swing',
};

export function durationFromModel(strategy?: string, model?: string): string {
  const m = (model || '').toLowerCase();
  const s = (strategy || '').toLowerCase();
  if (m.includes('intraday') || s.includes('intraday')) return 'INTRADAY';
  if (m.includes('swing') || s.includes('swing')) return 'SWING';
  if (m.includes('scalp') || s.includes('scalp')) return 'SCALP';
  // Strategies whose timeframe is implicit (no scalp/intraday/swing in
  // the model field) — 2N20 and ORB are always scalp.
  if (m === '2n20' || s === '2n20' || s === 'vwap_2n20') return 'SCALP';
  if (s === 'orb_breakout') return 'SCALP';
  return 'SCALP';
}

export function strategyShortName(strategy?: string, model?: string): string {
  const s = (strategy || '').toLowerCase();
  const m = (model || '').toLowerCase();
  if (s === 'vwap_2n20' || s === '2n20' || m.includes('2n20')) return '2N20';
  if (s === 'orb_breakout') return 'ORB';
  if (s === 'manual' || s === 'manual_close' || s === 'manual_test') return 'MANUAL';
  // HTF Levels family is now "Tidewater" — short form drops the duration
  // since the badge text handles that separately.
  if (s === 'htf_levels' || s === 'htf_supply_demand' || m === 'htf') return 'TIDEWATER';
  if (s === 'scalp_h1zone' || s.startsWith('scalp_h1zone')) return 'H1ZONE';
  return s.toUpperCase();
}

export function strategyBadgeText(strategy?: string, model?: string): string {
  if (!strategy && !model) return '';
  const s = (strategy || '').toLowerCase();
  const m = (model || '').toLowerCase();

  // Tidewater family — show as "TIDEWATER · {duration name}" where the
  // duration matches the strategy variant (Scalp / Intraday / Swing).
  if (s === 'htf_levels' || s === 'htf_supply_demand' || m === 'htf'
      || ((s.includes('htf') || m.includes('htf'))
          && (m === 'scalp' || m === 'intraday' || m === 'swing'))) {
    const anchor = TIDEWATER_DURATION[m] || TIDEWATER_DURATION[
      (s.includes('scalp') ? 'scalp'
        : s.includes('intraday') ? 'intraday'
        : s.includes('swing') ? 'swing' : '')] || '';
    return anchor ? `TIDEWATER · ${anchor.toUpperCase()}` : 'TIDEWATER';
  }

  const duration = durationFromModel(strategy, model);
  const strat = strategyShortName(strategy, model);
  if (!strat) return duration;
  return `${duration} ${strat}`;
}
