// Shared helper for composing the strategy/model display badge used
// across Positions, Trades, and Dashboard.
//
// Every trade lives in two dimensions:
//   1. DURATION — always one of three: scalp / intraday / swing.
//   2. STRATEGY name — 2N20, HTF, ORB, manual, etc.
// The display badge is "{DURATION} {STRATEGY}" — e.g. "SCALP 2N20",
// "INTRADAY HTF". Raw fields can come in many forms (model="scalp_2n20",
// model="2n20", strategy="vwap_2n20", strategy="htf_levels") so we
// normalize both halves.

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
  if (s === 'htf_levels' || s === 'htf_supply_demand' || m === 'htf') return 'HTF';
  if (s === 'orb_breakout') return 'ORB';
  if (s === 'manual' || s === 'manual_close' || s === 'manual_test') return 'MANUAL';
  return s.toUpperCase();
}

export function strategyBadgeText(strategy?: string, model?: string): string {
  if (!strategy && !model) return '';
  const duration = durationFromModel(strategy, model);
  const strat = strategyShortName(strategy, model);
  if (!strat) return duration;
  return `${duration} ${strat}`;
}
