import { useEffect, useState } from 'react';
import { Alert, View, Text, FlatList, StyleSheet, RefreshControl, TouchableOpacity, ActivityIndicator } from 'react-native';
import { WebView } from 'react-native-webview';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { supabase } from '@/lib/supabase';
import { useAuth } from '@/contexts/auth';
import { Colors } from '@/constants/theme';
import { useResponsive } from '@/hooks/use-responsive';
import { strategyBadgeText } from '@/lib/strategyLabel';
import IbStatusBanner from '@/components/ib-status-banner';
import ReconcileBanner from '@/components/reconcile-banner';

const CHART_API_BASE = 'https://bot.lumitrade.ai';
// Default timeframe per asset class. Futures scalps live on the 2m;
// FX H1 zones want the 15m; HTF swing wants the daily. We pick a sane
// default per (strategy, model) but the user can flip TFs inline.
function defaultChartTf(strategy?: string, model?: string): string {
  const s = (strategy || '').toLowerCase();
  const m = (model || '').toLowerCase();
  if (s.includes('2n20') || s.includes('orb')) return '2m';
  if (s === 'htf_levels' || s === 'htf_supply_demand') {
    if (m === 'swing') return '1d';
    if (m === 'intraday') return '15m';
    return '5m';
  }
  if (s.includes('fx_4h') || s.includes('stillwater')) return '4h';
  if (s.includes('h1_zone')) return '15m';
  return '15m';
}
function buildChartUrl(p: { instrument: string; entry_price?: number;
                            direction?: string; stop_loss?: number;
                            contracts?: number; strategy?: string;
                            opened_at?: string; },
                       tf: string): string {
  const params = new URLSearchParams({
    ticker: p.instrument,
    timespan: tf,
    count: '300',
  });
  if (p.entry_price)  params.set('entry', String(p.entry_price));
  if (p.direction)    params.set('direction', p.direction);
  if (p.stop_loss)    params.set('stop', String(p.stop_loss));
  if (p.contracts)    params.set('units', String(p.contracts));
  if (p.strategy)     params.set('strategy', p.strategy);
  if (p.opened_at) {
    const ts = Math.floor(new Date(p.opened_at).getTime() / 1000);
    if (Number.isFinite(ts) && ts > 0) params.set('entry_ts', String(ts));
  }
  return `${CHART_API_BASE}/chart?${params.toString()}`;
}
const INLINE_CHART_TFS = ['2m', '5m', '15m', '1h', '4h', '1d'];

type Position = {
  id: number;
  broker: string;
  broker_trade_id: string;
  instrument: string;
  asset_type: string;
  direction: string;
  units: number;
  contracts: number;
  entry_price: number;
  stop_loss: number;
  unrealized_pl: number;
  pips: number;
  strategy: string;
  model: string;
  spread_type: string;
  sell_strike: number;
  buy_strike: number;
  right: string;
  expiration: string;
  take_profit: number | null;
  opened_at: string;
  updated_at: string;
  metadata?: {
    zone_type?: string;
    zone_timeframe?: string;
    zone_price?: number;
    bias_score?: number;
    trigger_pattern?: string;
    trends?: Record<string, string>;
  } | null;
};

// Default chart timeframe = the trend (bias) TF for the model — the
// "middle" frame, between the trigger candle and the zone TF. Reading
// trend structure is the main reason to open the chart; the trigger is
// too noisy for orientation and the zone TF is too coarse.
//   Tidewater Scalp:    bias=15m   (trigger 5m, zones 1H)
//   Tidewater Intraday: bias=1H    (trigger 15m, zones 1D)
//   Tidewater Swing:    bias=1W    (trigger 1D, zones 1mo)
//   H1 Zone Scalp α/β:  always open at 15m. Both variants trade on 1H zones
//                        and 5m triggers; 15m is the most useful "read the
//                        setup" frame regardless of which direction-gate TF
//                        the variant happens to use. Consistency > literal
//                        bias-TF for this strategy.
const STRATEGY_TIMEFRAMES: Record<string, string> = {
  'scalp_2n20': '2m',
  'vwap_2n20': '2m',
  '2n20': '2m',
  'scalp': '15m',
  'intraday': '1h',
  'swing': '1w',
  'orb_breakout': '15m',
  // H1 Zone Scalp — model field carries the variant; both go to 15m
  'alpha': '15m',
  'beta': '15m',
  'scalp_h1zone': '15m',
};

function getChartTimeframe(model?: string, strategy?: string): string {
  if (model && STRATEGY_TIMEFRAMES[model]) return STRATEGY_TIMEFRAMES[model];
  if (strategy && STRATEGY_TIMEFRAMES[strategy]) return STRATEGY_TIMEFRAMES[strategy];
  return '15m';
}

// "Activated 2h 12m ago" / "Activated 14m ago" / "Activated just now".
// activatedAt is a unix-seconds timestamp from the watchlist API.
function formatActivatedAt(activatedAt: number): string {
  if (!activatedAt) return '';
  const ageSec = Math.max(0, Date.now() / 1000 - activatedAt);
  const m = Math.floor(ageSec / 60);
  if (m < 1) return 'just now';
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  const rem = m % 60;
  return rem ? `${h}h ${rem}m ago` : `${h}h ago`;
}

// Order trend-row keys low → high (5m, 15m, 1H, 4H, 1D, 1W, 1M).
// Backend may emit them in any order; we sort to make scanning intuitive.
const TF_RANK_MIN: Record<string, number> = {
  '1m': 1, '2m': 2, '5m': 5, '5M': 5,
  '15m': 15, '15M': 15, '30m': 30,
  '1h': 60, '1H': 60, '4h': 240, '4H': 240,
  '1d': 1440, '1D': 1440, 'D': 1440,
  '1w': 10080, '1W': 10080, 'W': 10080,
  '1mo': 43200, 'M': 43200,
};
function tfRank(key: string): number {
  const k = key.toLowerCase();
  return TF_RANK_MIN[k] ?? TF_RANK_MIN[key] ?? 9999;
}
function sortedTrendEntries(trends: Record<string, string>): [string, string][] {
  return Object.entries(trends).sort(([a], [b]) => tfRank(a) - tfRank(b));
}

// Trade-economics math for HTF zone cards — mirrors the chart dashboard.
// Returns {entryStr, targetStr, stopStr, riskStr, rewardStr, rrStr, rrColor}
// with consistent "Xp · $Y/10K" formatting (the /10K caveats reminds the
// user the $ figure scales linearly with position size).
const DEFAULT_UNITS_FOR_DOLLARS = 10000;
function formatPrice(price: number | null | undefined, instrument: string): string {
  if (price == null) return '—';
  const isJpy = instrument.includes('JPY');
  const decimals = isJpy ? 3 : (instrument.includes('_') ? 5 : 2);
  return price.toFixed(decimals);
}
function pipDollars(distance: number, instrument: string, refPrice: number): number {
  // Convert a price distance into a $ amount at DEFAULT_UNITS_FOR_DOLLARS.
  // XXX_USD pair: $ = distance × units (direct).
  // USD_XXX pair: $ = distance × units / refPrice (convert quote → USD).
  // Cross or non-FX: approximate using refPrice if available.
  const parts = instrument.split('_');
  if (parts.length === 2) {
    const [base, quote] = parts;
    if (quote === 'USD') return distance * DEFAULT_UNITS_FOR_DOLLARS;
    if (base === 'USD' && refPrice > 0) return distance * DEFAULT_UNITS_FOR_DOLLARS / refPrice;
    if (refPrice > 0) return distance * DEFAULT_UNITS_FOR_DOLLARS / refPrice;
  }
  return distance * DEFAULT_UNITS_FOR_DOLLARS;
}
function buildZoneTradePlan(z: any): {
  entry: string; target: string; stop: string;
  risk: string; reward: string; rr: string;
  rrColor: string;
  hasPlan: boolean;
} {
  const inst = z.instrument || '';
  const entry = z.projected_entry;
  const stop = z.projected_stop;
  const target = z.projected_target;
  if (entry == null || stop == null) {
    return { entry: '—', target: '—', stop: '—', risk: '—', reward: '—',
             rr: '—', rrColor: Colors.textLight, hasPlan: false };
  }
  const isJpy = inst.includes('JPY');
  const pipSize = isJpy ? 0.01 : 0.0001;
  const riskDist = Math.abs(entry - stop);
  const riskPips = riskDist / pipSize;
  const riskUsd = pipDollars(riskDist, inst, entry);
  let rewardStr = '—', rrStr = '—';
  let rrColor: string = Colors.textLight;
  if (target != null) {
    const rewardDist = Math.abs(target - entry);
    const rewardPips = rewardDist / pipSize;
    const rewardUsd = pipDollars(rewardDist, inst, entry);
    rewardStr = `${rewardPips.toFixed(1)}p · $${rewardUsd.toFixed(2)}/10K`;
    const rr = riskDist > 0 ? rewardDist / riskDist : 0;
    rrStr = `${rr.toFixed(2)}:1`;
    rrColor = rr >= 1.5 ? Colors.green : (rr >= 1.0 ? Colors.gold : Colors.red);
  }
  return {
    entry: formatPrice(entry, inst),
    target: formatPrice(target, inst),
    stop: formatPrice(stop, inst),
    risk: `${riskPips.toFixed(1)}p · $${riskUsd.toFixed(2)}/10K`,
    reward: rewardStr,
    rr: rrStr,
    rrColor,
    hasPlan: true,
  };
}

// Approximate USD value of a price move on a position. Handles the three
// pair shapes correctly; falls back to the quote-currency-divided-by-entry
// approximation for crosses (matches trade_tracker.py's logic).
function priceToUsd(instrument: string, units: number, entry: number, distance: number): number {
  if (!units || !distance) return 0;
  const dist = Math.abs(distance);
  // X_USD pairs (EUR_USD, GBP_USD, AUD_USD, NZD_USD): pip value is in USD.
  if (instrument.endsWith('_USD')) return units * dist;
  // USD_X pairs (USD_JPY, USD_CAD, USD_CHF): pip in quote currency,
  // approximate USD via entry price.
  if (instrument.startsWith('USD_')) return entry ? units * dist / entry : 0;
  // Cross pairs (EUR_GBP, AUD_NZD, ...): rough approximation.
  return entry ? units * dist / entry : 0;
}

// Risk / reward for a position in dollars. Reward returns 0 if no take_profit
// is set. Futures use multiplier × contracts; forex uses the pip math above.
function positionRiskReward(p: Position): { risk: number; reward: number } {
  const entry = p.entry_price || 0;
  const stop = p.stop_loss || 0;
  const tp = p.take_profit || 0;
  if (p.asset_type === 'futures') {
    // MES is $5/pt, ES is $50/pt, NQ is $20/pt.
    const mult = p.instrument === 'ES' ? 50 : p.instrument === 'NQ' ? 20 : 5;
    const contracts = p.contracts || 1;
    return {
      risk: stop ? Math.abs(entry - stop) * mult * contracts : 0,
      reward: tp ? Math.abs(tp - entry) * mult * contracts : 0,
    };
  }
  if (p.asset_type === 'forex') {
    const units = p.units || 0;
    return {
      risk: stop ? priceToUsd(p.instrument, units, entry, entry - stop) : 0,
      reward: tp ? priceToUsd(p.instrument, units, entry, tp - entry) : 0,
    };
  }
  return { risk: 0, reward: 0 };
}

function PositionRow({ position, onChartPress, onClose, closing, livePrice,
                       chartExpanded, chartTf, onToggleChart, onChangeTf }: {
  position: Position;
  onChartPress: (instrument: string, tf: string) => void;
  onClose: (p: Position) => void;
  closing: boolean;
  livePrice?: number;
  chartExpanded: boolean;
  chartTf: string;
  onToggleChart: () => void;
  onChangeTf: (tf: string) => void;
}) {
  const dir = position.direction === 'LONG' || position.direction === 'BUY' ? 'BUY' : 'SELL';
  // Prefer client-side recomputed P&L when a fresh live price is in
  // scope — the Supabase row's unrealized_pl is only as fresh as the
  // bot's last sync write (~5 s). With livePrice from the live_prices
  // realtime channel, this updates within ms of the IB CPAPI snapshot.
  // Falls back to the row's unrealized_pl when no live price yet.
  let pl = position.unrealized_pl || 0;
  // Client-side live recompute ONLY for instruments whose livePrice and
  // entry_price are the same price series (futures/forex/stocks). For an
  // OPTION the livePrice is the *underlying* and entry_price is the option's
  // net debit, so this formula is nonsense — e.g. a SPY put debit spread
  // (entry $31.26) showed (730 − 31.26)×−1 = −$698. Options always use the
  // server-computed unrealized_pl (value − cost).
  if (livePrice && position.entry_price && position.contracts
      && position.asset_type !== 'options') {
    const mult = (position as any).multiplier || (
      position.instrument === 'MES' ? 5 :
      position.instrument === 'MNQ' ? 2 :
      position.instrument === 'MGC' ? 10 :
      position.instrument === 'MCL' ? 100 :
      1
    );
    const sign = dir === 'BUY' ? 1 : -1;
    pl = (livePrice - position.entry_price) * sign * position.contracts * mult;
  }
  const isOptions = position.asset_type === 'options';
  const { risk, reward } = positionRiskReward(position);
  const rr = risk > 0 && reward > 0 ? (reward / risk).toFixed(1) : '';

  return (
    <View style={styles.posRow}>
      <View style={styles.posTop}>
        <TouchableOpacity onPress={() => onChartPress(position.instrument, getChartTimeframe(position.model, position.strategy))}>
          <Text style={[styles.posInstrument, { textDecorationLine: 'underline' }]}>{position.instrument}</Text>
        </TouchableOpacity>
        <View style={[styles.dirBadge, { backgroundColor: dir === 'BUY' ? '#e8f5e9' : '#fdecea' }]}>
          <Text style={[styles.dirText, { color: dir === 'BUY' ? Colors.green : Colors.red }]}>{dir}</Text>
        </View>
        {position.contracts > 1 ? (
          <Text style={styles.qtyText}>×{position.contracts}</Text>
        ) : null}
        <View style={[styles.brokerBadge, {
          backgroundColor: position.broker === 'oanda' ? '#e3f2fd' : '#f3e5f5',
        }]}>
          <Text style={[styles.brokerText, {
            color: position.broker === 'oanda' ? '#1565c0' : '#7b1fa2',
          }]}>
            {position.broker === 'oanda' ? 'FX' : 'IB'}
          </Text>
        </View>
        <View style={{ flex: 1 }} />
        <Text style={[styles.posPl, { color: pl >= 0 ? Colors.green : Colors.red }]}>
          {pl >= 0 ? '+' : ''}${pl.toFixed(2)}
        </Text>
      </View>

      <View style={styles.posDetails}>
        <View style={styles.posDetail}>
          <Text style={styles.posDetailLabel}>{isOptions ? 'Contracts' : 'Size'}</Text>
          <Text style={styles.posDetailValue}>
            {isOptions
              ? (position.contracts || 1)
              : (position.contracts || position.units || '--')}
          </Text>
        </View>
        <View style={styles.posDetail}>
          <Text style={styles.posDetailLabel}>Entry</Text>
          <Text style={styles.posDetailValue}>
            {position.entry_price ? position.entry_price.toFixed(position.instrument.includes('JPY') ? 3 : 5) : '--'}
          </Text>
        </View>
        {position.stop_loss ? (
          <View style={styles.posDetail}>
            <Text style={styles.posDetailLabel}>Stop</Text>
            <Text style={[styles.posDetailValue, { color: Colors.red }]}>
              {position.stop_loss.toFixed(position.instrument.includes('JPY') ? 3 : 5)}
            </Text>
          </View>
        ) : null}
        {position.pips ? (
          <View style={styles.posDetail}>
            <Text style={styles.posDetailLabel}>Pips</Text>
            <Text style={[styles.posDetailValue, { color: position.pips >= 0 ? Colors.green : Colors.red }]}>
              {position.pips.toFixed(1)}
            </Text>
          </View>
        ) : null}
        {position.opened_at ? (
          <View style={styles.posDetail}>
            <Text style={styles.posDetailLabel}>Duration</Text>
            <Text style={styles.posDetailValue}>
              {(() => {
                const mins = Math.round((Date.now() - new Date(position.opened_at).getTime()) / 60000);
                if (mins < 60) return mins + 'm';
                if (mins < 1440) return Math.floor(mins / 60) + 'h ' + (mins % 60) + 'm';
                return Math.floor(mins / 1440) + 'd ' + Math.floor((mins % 1440) / 60) + 'h';
              })()}
            </Text>
          </View>
        ) : null}
        {isOptions && position.spread_type ? (
          <View style={styles.posDetail}>
            <Text style={styles.posDetailLabel}>Spread</Text>
            <Text style={styles.posDetailValue}>{position.spread_type}</Text>
          </View>
        ) : null}
        {isOptions && position.sell_strike ? (
          <View style={styles.posDetail}>
            <Text style={styles.posDetailLabel}>Strikes</Text>
            <Text style={styles.posDetailValue}>
              {position.sell_strike}/{position.buy_strike}
            </Text>
          </View>
        ) : null}
      </View>

      {position.metadata ? (() => {
        const meta = position.metadata;
        const isSupply = (meta.zone_type || '').toLowerCase() === 'supply';
        const tfColors: Record<string, string> = { '1mo': '#ff9800', '1w': '#ffeb3b', '1d': '#2196f3', '4h': '#ce93d8', '1h': '#66bb6a' };
        const tfLabels: Record<string, string> = { '1mo': 'M', '1w': 'W', '1d': 'D', '4h': '4H', '1h': '1H' };
        const tf = (meta.zone_timeframe || '').toLowerCase();
        const tfColor = tfColors[tf] || '#888';
        const trends = meta.trends || {};
        const showZone = meta.zone_type || meta.zone_timeframe;
        if (!showZone) return null;
        return (
          <View style={styles.zoneInfoRow}>
            {meta.zone_type ? (
              <View style={[styles.zoneBadge, { backgroundColor: isSupply ? '#fdecea' : '#e8f5e9' }]}>
                <Text style={[styles.zoneBadgeText, { color: isSupply ? Colors.red : Colors.green }]}>
                  {isSupply ? 'SUPPLY' : 'DEMAND'}
                </Text>
              </View>
            ) : null}
            {meta.zone_timeframe ? (
              <View style={[styles.tfBadge, { backgroundColor: tfColor + '22', borderColor: tfColor }]}>
                <Text style={[styles.tfBadgeText, { color: tfColor }]}>
                  {tfLabels[tf] || meta.zone_timeframe.toUpperCase()}
                </Text>
              </View>
            ) : null}
            {Object.keys(trends).length > 0 ? (
              <View style={styles.trendRow}>
                {sortedTrendEntries(trends).map(([tfk, dir]) => (
                  <Text key={tfk} style={[styles.trendBadge, {
                    color: dir === 'bullish' ? Colors.green : dir === 'bearish' ? Colors.red : Colors.textLight,
                  }]}>
                    {tfk}{dir === 'bullish' ? '↑' : dir === 'bearish' ? '↓' : '→'}
                  </Text>
                ))}
              </View>
            ) : null}
            <View style={{ flex: 1 }} />
            {meta.bias_score ? (
              <Text style={styles.zoneScore}>{meta.bias_score}</Text>
            ) : null}
          </View>
        );
      })() : null}

      {(risk > 0 || reward > 0) ? (
        <View style={styles.rrRow}>
          {risk > 0 ? (
            <View style={styles.rrItem}>
              <Text style={styles.rrLabel}>RISK</Text>
              <Text style={[styles.rrValue, { color: Colors.red }]}>
                ${risk.toFixed(2)}
              </Text>
            </View>
          ) : null}
          {reward > 0 ? (
            <View style={styles.rrItem}>
              <Text style={styles.rrLabel}>REWARD</Text>
              <Text style={[styles.rrValue, { color: Colors.green }]}>
                ${reward.toFixed(2)}
              </Text>
            </View>
          ) : null}
          {rr ? (
            <View style={styles.rrItem}>
              <Text style={styles.rrLabel}>R:R</Text>
              <Text style={styles.rrValue}>{rr}</Text>
            </View>
          ) : null}
        </View>
      ) : null}

      <View style={styles.posFooter}>
        <Text style={styles.posTime}>
          {position.opened_at ? new Date(position.opened_at).toLocaleString('en-US', {
            month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', hour12: true,
          }) : ''}
        </Text>
        <Text style={[styles.modelBadge, {
          color: position.model?.includes('2n20') ? Colors.amber : Colors.scalp,
        }]}>
          {strategyBadgeText(position.strategy, position.model)}
        </Text>
        <TouchableOpacity
          onPress={onToggleChart}
          style={styles.chartToggleBtn}
          hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
        >
          <Text style={styles.chartToggleText}>
            {chartExpanded ? '▼ Chart' : '▶ Chart'}
          </Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={[styles.closeBtn, closing && { opacity: 0.4 }]}
          onPress={() => !closing && onClose(position)}
          disabled={closing}
          hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
        >
          <Text style={styles.closeBtnText}>{closing ? 'Closing…' : 'Close'}</Text>
        </TouchableOpacity>
      </View>

      {chartExpanded ? (
        <View style={styles.inlineChart}>
          <View style={styles.tfRow}>
            {INLINE_CHART_TFS.map(t => (
              <TouchableOpacity
                key={t}
                onPress={() => onChangeTf(t)}
                style={[styles.tfPill, chartTf === t && styles.tfPillActive]}
              >
                <Text style={[styles.tfPillText, chartTf === t && styles.tfPillTextActive]}>
                  {t}
                </Text>
              </TouchableOpacity>
            ))}
          </View>
          <WebView
            key={`${position.id}-${chartTf}`}
            source={{ uri: buildChartUrl({
              instrument: position.instrument,
              entry_price: position.entry_price,
              direction: position.direction,
              stop_loss: position.stop_loss,
              contracts: position.contracts,
              strategy: position.strategy,
              opened_at: position.opened_at,
            }, chartTf) }}
            style={styles.inlineChartWebview}
            javaScriptEnabled
            domStorageEnabled
            startInLoadingState
            renderLoading={() => (
              <ActivityIndicator
                style={{ flex: 1, backgroundColor: '#1a1a2e' }}
                color={Colors.olive}
              />
            )}
          />
        </View>
      ) : null}
    </View>
  );
}

export default function Positions() {
  const { user } = useAuth();
  const router = useRouter();
  const { contentStyle } = useResponsive();
  const [allPositions, setAllPositions] = useState<Position[]>([]);
  const [activeTab, setActiveTab] = useState('forex');
  const [refreshing, setRefreshing] = useState(false);
  const [zones, setZones] = useState<any[]>([]);
  const [audit, setAudit] = useState<any | null>(null);
  const [auditExpanded, setAuditExpanded] = useState(false);
  // Per-position "closing" lock so a Close tap is honored exactly once
  // until either the row disappears from the next sync OR 30 s pass.
  const [closingIds, setClosingIds] = useState<Set<string | number>>(new Set());

  // Latest market price per ticker, fed by the live_prices Supabase
  // realtime channel. PositionRow uses these to recompute P&L without
  // waiting for the bot's per-position write cycle. Updates land within
  // ms of the bot's CPAPI snapshot.
  const [livePrices, setLivePrices] = useState<Record<string, number>>({});

  // Single-expand chart state: only one position's chart is mounted at
  // a time to avoid loading multiple WebViews simultaneously. `chartTf`
  // remembers per-position TF selection so flipping cards doesn't reset
  // the user's choice.
  const [expandedChartId, setExpandedChartId] = useState<string | number | null>(null);
  const [chartTf, setChartTf] = useState<Record<string | number, string>>({});

  // Belt-and-suspenders refresh every 5 s: bump the tick AND refetch
  // the positions rows from Supabase. Without the refetch a stalled
  // realtime push leaves the card showing data from initial mount —
  // observed 2026-05-27 with a 22-min-old position still rendering as
  // 5m duration. Setting interval to 5 s keeps both duration AND P&L
  // within ~5 s of Supabase. Each tick adds 1 PostgREST read; trivial
  // against the project rate limit.
  const [, setTick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => {
      setTick(t => t + 1);
      loadPositions();
    }, 5_000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user]);

  const TABS = [
    { key: 'forex', label: 'Forex', filter: (p: Position) => p.broker === 'oanda' || p.asset_type === 'forex' },
    { key: 'stocks', label: 'Stocks', filter: (p: Position) => p.asset_type === 'stock' && !p.instrument?.startsWith('I:') },
    { key: 'options', label: 'Options', filter: (p: Position) => p.asset_type === 'options' },
    { key: 'indices', label: 'Indices', filter: (p: Position) => !!p.instrument?.startsWith('I:') },
    { key: 'futures', label: 'Futures', filter: (p: Position) => p.asset_type === 'futures' && !p.instrument?.startsWith('I:') },
  ];

  const loadPositions = async () => {
    if (!user) return;
    try {
      const { data } = await supabase
        .from('positions')
        .select('*')
        .eq('user_id', user.id)
        .order('opened_at', { ascending: false });

      if (data) setAllPositions(data);
    } catch (e) {
      console.error('Positions load error:', e);
    }
  };

  const loadZones = async () => {
    try {
      const resp = await fetch('https://bot.lumitrade.ai/api/watchlist/zones');
      const data = await resp.json();
      setZones(data.zones || []);
    } catch { }
  };

  // Independent IB-vs-Bot reconciliation. Pulled fresh from server which
  // reads IB's latest position snapshot and compares to the bot's
  // strat_pos coverage. Mismatches surface as orphan/phantom/etc.
  const loadAudit = async () => {
    try {
      const resp = await fetch('https://bot.lumitrade.ai/api/positions/audit');
      const data = await resp.json();
      if (data.ok) setAudit(data);
    } catch { }
  };

  useEffect(() => { loadPositions(); loadZones(); loadAudit(); }, [user]);
  useEffect(() => {
    const interval = setInterval(() => { loadZones(); loadAudit(); }, 30000);
    return () => clearInterval(interval);
  }, []);

  // Realtime: live position updates
  useEffect(() => {
    if (!user) return;
    const channel = supabase
      .channel('positions-realtime')
      .on(
        'postgres_changes',
        { event: '*', schema: 'public', table: 'positions', filter: `user_id=eq.${user.id}` },
        () => { loadPositions(); }
      )
      .subscribe();

    return () => { supabase.removeChannel(channel); };
  }, [user]);

  // Live prices subscription — UPDATE events on the `live_prices` table
  // each time the bot pushes a fresh CPAPI snapshot. Updates the local
  // `livePrices` map so PositionRow can recompute P&L instantly.
  useEffect(() => {
    if (!user) return;
    // Seed with whatever's already in the table on mount so we don't wait
    // for the first push to populate.
    supabase
      .from('live_prices')
      .select('ticker, price')
      .then(({ data }) => {
        if (data) {
          const seed: Record<string, number> = {};
          for (const r of data) {
            if (r.ticker && r.price != null) seed[r.ticker] = Number(r.price);
          }
          setLivePrices(prev => ({ ...seed, ...prev }));
        }
      });

    const channel = supabase
      .channel('live-prices-realtime')
      .on(
        'postgres_changes',
        { event: '*', schema: 'public', table: 'live_prices' },
        (payload: any) => {
          const row = (payload?.new || payload?.record) as { ticker?: string; price?: number } | undefined;
          if (row?.ticker && row.price != null) {
            const ticker = row.ticker;
            const price = Number(row.price);
            setLivePrices(prev => (prev[ticker] === price ? prev : { ...prev, [ticker]: price }));
          }
        },
      )
      .subscribe();

    return () => { supabase.removeChannel(channel); };
  }, [user]);

  const onRefresh = async () => {
    setRefreshing(true);
    await Promise.all([loadPositions(), loadZones(), loadAudit()]);
    setRefreshing(false);
  };

  const tab = TABS.find(t => t.key === activeTab)!;
  const positions = allPositions.filter(tab.filter);
  const totalPl = positions.reduce((s, p) => s + (p.unrealized_pl || 0), 0);

  // Total exposure summary in the header. Futures/options trade in contracts;
  // forex in units (often 25k+). We surface whichever is relevant so when the
  // bot accumulates (e.g. several BUYs not yet closed) the header makes the
  // real exposure obvious instead of just saying "1 position".
  const totalContracts = positions.reduce((s, p) => s + (p.contracts || 0), 0);
  const totalUnits = positions.reduce((s, p) => s + (p.units || 0), 0);
  const exposureLabel = (() => {
    if (activeTab === 'forex') {
      if (totalUnits >= 1000) return `${Math.round(totalUnits / 1000)}k units`;
      if (totalUnits > 0) return `${totalUnits} units`;
      return '';
    }
    if (activeTab === 'options') {
      return totalContracts > 0 ? `${totalContracts} spread${totalContracts !== 1 ? 's' : ''}` : '';
    }
    // Futures / Stocks / Indices
    return totalContracts > 0 ? `${totalContracts} contract${totalContracts !== 1 ? 's' : ''}` : '';
  })();

  // Manual close button — confirms via native Alert, posts to the server's
  // /api/positions/close endpoint, which routes per broker/asset_type.
  const handleClose = (p: Position) => {
    // Refuse if we're already closing this row
    if (closingIds.has(p.id)) return;
    const pl = p.unrealized_pl || 0;
    const plStr = (pl >= 0 ? '+' : '') + '$' + pl.toFixed(2);
    const dir = p.direction === 'LONG' || p.direction === 'BUY' ? 'BUY' : 'SELL';
    Alert.alert(
      'Close trade?',
      `${p.instrument} ${dir} — unrealized ${plStr}`,
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Close',
          style: 'destructive',
          onPress: async () => {
            // Lock the button until next sync removes the row OR 30s pass
            setClosingIds(prev => new Set(prev).add(p.id));
            setTimeout(() => {
              setClosingIds(prev => {
                const next = new Set(prev);
                next.delete(p.id);
                return next;
              });
            }, 30000);
            try {
              const syncKey = process.env.EXPO_PUBLIC_LUMI_SYNC_KEY || '';
              const resp = await fetch('https://bot.lumitrade.ai/api/positions/close', {
                method: 'POST',
                headers: {
                  'Content-Type': 'application/json',
                  'X-Sync-Key': syncKey,
                },
                body: JSON.stringify({
                  broker: p.broker,
                  asset_type: p.asset_type,
                  instrument: p.instrument,
                  broker_trade_id: p.broker_trade_id,
                  direction: p.direction,
                  strategy: p.strategy,
                  contracts: p.contracts || 1,
                  // Options-only fields (no-op for forex/futures)
                  spread_type: p.spread_type,
                  right: p.right,
                  expiration: p.expiration,
                  sell_strike: p.sell_strike,
                  buy_strike: p.buy_strike,
                }),
              });
              const result = await resp.json();
              if (!resp.ok) {
                Alert.alert('Close failed', result.error || `HTTP ${resp.status}`);
                return;
              }
              // Optimistic UI: remove the row immediately (sync will confirm in ~10s)
              setAllPositions(prev => prev.filter(row => row.id !== p.id));
              // Backstop refresh in case the server already wrote a state update.
              setTimeout(() => loadPositions(), 1500);
            } catch (e: any) {
              Alert.alert('Close failed', e?.message || String(e));
            }
          },
        },
      ],
    );
  };

  // Filter zones by active tab
  const isForexZone = (z: any) => z.instrument?.includes('_');
  const isIndexZone = (z: any) => z.instrument?.startsWith('I:');
  const isFuturesZone = (z: any) => ['MES', 'ES', 'NQ', 'GOLD', 'OIL'].includes(z.instrument);
  const isStockZone = (z: any) => !isForexZone(z) && !isIndexZone(z) && !isFuturesZone(z);

  const filteredZones = zones.filter(z => {
    if (activeTab === 'forex') return isForexZone(z);
    if (activeTab === 'stocks') return isStockZone(z);
    if (activeTab === 'options') return false;
    if (activeTab === 'indices') return isIndexZone(z);
    if (activeTab === 'futures') return isFuturesZone(z);
    return true;
  });

  return (
    <SafeAreaView style={styles.container}>
      <View style={styles.header}>
        <View>
          <Text style={styles.headerTitle}>Open Positions</Text>
          <Text style={styles.headerSubtitle}>
            {positions.length} position{positions.length !== 1 ? 's' : ''}
            {exposureLabel ? ` · ${exposureLabel}` : ''}
          </Text>
        </View>
        <View style={styles.plSummary}>
          <Text style={styles.plLabel}>Unrealized</Text>
          <Text style={[styles.plTotal, { color: totalPl >= 0 ? Colors.green : Colors.red }]}>
            {totalPl >= 0 ? '+' : ''}${totalPl.toFixed(2)}
          </Text>
        </View>
      </View>

      <ReconcileBanner />
      <IbStatusBanner />

      {/* Broker Tabs */}
      <View style={styles.tabBar}>
        {TABS.map(t => (
          <TouchableOpacity
            key={t.key}
            style={[styles.tab, activeTab === t.key && styles.tabActive]}
            onPress={() => setActiveTab(t.key)}
          >
            <Text style={[styles.tabText, activeTab === t.key && styles.tabTextActive]}>
              {t.label}
            </Text>
          </TouchableOpacity>
        ))}
      </View>

      <FlatList
        data={positions}
        keyExtractor={(item) => item.id.toString()}
        renderItem={({ item }) => <PositionRow
          position={item}
          onClose={handleClose}
          closing={closingIds.has(item.id)}
          livePrice={livePrices[item.instrument]}
          chartExpanded={expandedChartId === item.id}
          chartTf={chartTf[item.id] || defaultChartTf(item.strategy, item.model)}
          onToggleChart={() => setExpandedChartId(prev => prev === item.id ? null : item.id)}
          onChangeTf={(tf) => setChartTf(prev => ({ ...prev, [item.id]: tf }))}
          onChartPress={(sym, tf) => router.push({
            pathname: '/chart',
            params: {
              symbol: sym,
              interval: tf,
              entry: item.entry_price?.toString(),
              stop: item.stop_loss?.toString(),
              exit: item.take_profit?.toString(),
              // Units lets the chart dashboard compute $ Risk/Reward
              // instead of just pip distances.
              units: item.units?.toString(),
              direction: item.direction,
              strategy: item.strategy || item.model || '',
              model: item.model || '',
            }
          })}
        />}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} />}
        contentContainerStyle={[{ paddingHorizontal: 16, paddingBottom: 20 }, contentStyle]}
        ListEmptyComponent={
          <View style={styles.empty}>
            <Text style={styles.emptyText}>No open positions</Text>
            <Text style={styles.emptySubtext}>Positions appear here when the bot opens a trade</Text>
          </View>
        }
        ListFooterComponent={
          <>
          {/* IB-vs-Bot Reconciliation — independent audit pulled directly
              from IB's position snapshot. Always visible so you can
              verify FLAT means actually flat, plus catch orphans /
              phantoms / direction mismatches. */}
          {audit && (
            <View style={styles.auditSection}>
              <TouchableOpacity onPress={() => setAuditExpanded(v => !v)}>
                <View style={styles.auditHeader}>
                  <Text style={styles.auditTitle}>
                    🔍 IB Direct{(() => {
                      const s = audit.summary || {};
                      if (s.is_flat) return '  ✓ FLAT (no positions at IB)';
                      const mm = (audit.rows || []).filter((r: any) =>
                        r.status !== 'matched' && r.status !== 'flat').length;
                      const counts = `${s.long_count || 0}L / ${s.short_count || 0}S`;
                      return mm > 0
                        ? `  ⚠️ ${counts} · ${mm} mismatch${mm > 1 ? 'es' : ''}`
                        : `  ✓ ${counts} · all matched`;
                    })()}
                  </Text>
                  <Text style={styles.auditChevron}>{auditExpanded ? '▼' : '▶'}</Text>
                </View>
              </TouchableOpacity>
              {auditExpanded && (
                <View style={{ marginTop: 8 }}>
                  <View style={styles.auditLegend}>
                    <Text style={styles.auditLegendText}>
                      Compares your live IB account to what the bot is tracking,
                      per instrument.{'\n'}
                      <Text style={{ fontWeight: '600' }}>IB</Text> = the broker
                      (the truth) · <Text style={{ fontWeight: '600' }}>Bot</Text>
                      {' '}= what the bot thinks it holds.{'\n'}
                      <Text style={{ color: Colors.green, fontWeight: '600' }}>Matched</Text>
                      {' '}= they agree. A red row is an{' '}
                      <Text style={{ fontWeight: '600' }}>orphan</Text> (IB has it,
                      bot doesn’t) or{' '}
                      <Text style={{ fontWeight: '600' }}>phantom</Text> (bot has
                      it, IB is flat) to look into.
                    </Text>
                  </View>
                  {(!audit.rows || audit.rows.length === 0) && (
                    <View style={styles.auditRow}>
                      <Text style={[styles.auditInst, { textAlign: 'center', color: Colors.green }]}>
                        ✓ No open positions at IB
                      </Text>
                      <Text style={[styles.auditDetail, { textAlign: 'center' }]}>
                        Account is truly flat across all asset classes
                      </Text>
                    </View>
                  )}
                  {(audit.rows || []).map((row: any) => {
                    const isOPT = row.asset_type === 'OPT';

                    // Build the IBKR-style vertical descriptor when the
                    // backend has provided the structured fields:
                    //   "VERTICAL SPX 100 2 JUN 26 (0) 7610/7615 C"
                    // Falls back to parsing `description` for older API
                    // payloads (pre–structured-fields deploy).
                    let optTitle = '';
                    let bias: 'bull' | 'bear' | '' = '';
                    let dte: number | null = null;  // hoisted so the DTE badge can render below the title
                    if (isOPT) {
                      const longK = Number(row.long_strike) || 0;
                      const shortK = Number(row.short_strike) || 0;
                      const expRaw = String(row.expiration || '');  // YYYYMMDD
                      const right = String(row.right || '').toUpperCase();
                      const mult = Number(row.multiplier) || 100;
                      const spreadType = String(row.spread_type || row.description || '');

                      // Bias from spread_type semantics. We don't put this
                      // INTO the IBKR-format line (IBKR drops it too), but
                      // we surface it as a small suffix tag for trade-setup
                      // clarity.
                      const lc = spreadType.toLowerCase();
                      const callDebit = lc.includes('call') && lc.includes('debit');
                      const putCredit = lc.includes('put') && lc.includes('credit');
                      const callCredit = lc.includes('call') && lc.includes('credit');
                      const putDebit = lc.includes('put') && lc.includes('debit');
                      if (lc.includes('bull') || callDebit || putCredit ||
                          lc === 'long call' || lc === 'short put') {
                        bias = 'bull';
                      } else if (lc.includes('bear') || callCredit || putDebit ||
                                 lc === 'long put' || lc === 'short call') {
                        bias = 'bear';
                      }

                      // Format expiry "YYYYMMDD" → "2 JUN 26". DTE goes in its
                      // own badge below the title (used to be inline `(3)`).
                      let expStr = '';
                      if (/^\d{8}$/.test(expRaw)) {
                        const y = parseInt(expRaw.slice(0, 4), 10);
                        const mo = parseInt(expRaw.slice(4, 6), 10) - 1;
                        const d = parseInt(expRaw.slice(6, 8), 10);
                        const exp = new Date(Date.UTC(y, mo, d));
                        const MONTHS = ['JAN','FEB','MAR','APR','MAY','JUN','JUL','AUG','SEP','OCT','NOV','DEC'];
                        expStr = `${d} ${MONTHS[mo]} ${String(y).slice(-2)}`;
                        const today = new Date();
                        const todayUTC = Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate());
                        dte = Math.round((exp.getTime() - todayUTC) / 86400000);
                      }

                      // VERTICAL = two-leg, same-expiry, same-right spread.
                      // Anything with both strikes nonzero qualifies.
                      // IBKR convention: strikes shown low/high.
                      const isVertical = longK > 0 && shortK > 0;
                      if (isVertical) {
                        const lo = Math.min(longK, shortK);
                        const hi = Math.max(longK, shortK);
                        const strikes = `${lo % 1 === 0 ? lo.toFixed(0) : lo}/${hi % 1 === 0 ? hi.toFixed(0) : hi}`;
                        optTitle = `VERTICAL ${row.instrument} ${mult.toFixed(0)} ${expStr} ${strikes} ${right}`.trim();
                      } else if (longK > 0 || shortK > 0) {
                        // Single leg — show strike + right in similar format
                        const k = longK || shortK;
                        const side = longK > 0 ? 'LONG' : 'SHORT';
                        const kStr = k % 1 === 0 ? k.toFixed(0) : `${k}`;
                        optTitle = `${side} ${row.instrument} ${mult.toFixed(0)} ${expStr} ${kStr} ${right}`.trim();
                      } else if (row.description) {
                        // Fallback: backend hasn't deployed the structured
                        // fields yet; show whatever description we have.
                        optTitle = `${row.instrument} · ${row.description}`;
                      }
                    }

                    // Format ib_avg. For OPT spreads, net_cost is dollars-per-spread:
                    //   positive  → net debit (paid)
                    //   negative  → net credit (received)
                    // For everything else (FUT/STK), keep the legacy raw-number display.
                    // Returns a JSX fragment so we can bold + color the
                    // "credit" / "debit" word inline.
                    const renderIbAvg = () => {
                      if (row.ib_avg === null || row.ib_avg === undefined) return null;
                      if (!isOPT) return <>{` @ ${row.ib_avg.toFixed(2)}`}</>;
                      const avg = row.ib_avg;
                      const total = Math.abs(avg) * Math.abs(row.ib_qty || 0);
                      if (avg > 0) {
                        return (
                          <>
                            {` @ $${avg.toFixed(2)} net `}
                            <Text style={[styles.uPL, { color: Colors.green }]}>debit</Text>
                            {`/spread (paid $${total.toFixed(2)})`}
                          </>
                        );
                      }
                      if (avg < 0) {
                        return (
                          <>
                            {` @ $${Math.abs(avg).toFixed(2)} net `}
                            <Text style={[styles.uPL, { color: Colors.red }]}>credit</Text>
                            {`/spread (received $${total.toFixed(2)})`}
                          </>
                        );
                      }
                      return <>{' @ $0.00'}</>;
                    };

                    return (
                    <View key={row.display_key || row.instrument} style={[
                      styles.auditRow,
                      row.status !== 'matched' && row.status !== 'flat' && styles.auditRowMismatch,
                    ]}>
                      <View style={styles.auditRowTop}>
                        <Text style={styles.auditInst}>
                          {isOPT && optTitle
                            ? optTitle
                            : `${row.instrument}${row.asset_type ? ` · ${row.asset_type}` : ''}${
                                row.ib_qty > 0 ? ' · LONG' : row.ib_qty < 0 ? ' · SHORT' : ''
                              }`}
                          {isOPT && bias === 'bull' ? '  📈 Bull' :
                            isOPT && bias === 'bear' ? '  📉 Bear' : ''}
                        </Text>
                        <Text style={[
                          styles.auditStatus,
                          { color: (row.status === 'matched' || row.status === 'flat') ? Colors.green : '#c0392b' },
                        ]}>
                          {row.status_label}
                        </Text>
                      </View>
                      {dte !== null && (
                        <Text style={[
                          styles.dteBadge,
                          // 0 DTE expires today → red urgency.
                          // 1-2 DTE → amber.
                          // 3+ DTE → default.
                          dte <= 0 ? { color: Colors.red } :
                          dte <= 2 ? { color: Colors.amber } : null,
                        ]}>
                          {dte} DTE
                        </Text>
                      )}
                      <Text style={styles.auditDetail}>
                        IB: {row.ib_qty > 0 ? '+' : ''}{row.ib_qty}
                        {renderIbAvg()}
                        {row.ib_unrealized_pl !== null && row.ib_unrealized_pl !== undefined && (
                          <>
                            {'   uPL '}
                            <Text style={[
                              styles.uPL,
                              { color: row.ib_unrealized_pl >= 0 ? Colors.green : Colors.red },
                            ]}>
                              {row.ib_unrealized_pl >= 0 ? '+' : ''}${row.ib_unrealized_pl.toFixed(2)}
                            </Text>
                          </>
                        )}
                      </Text>
                      {/* uPL vs max-profit progress. Per-spread max_profit
                          comes from the backend; multiply by qty for the
                          position total. Renders nothing when max_profit
                          is missing (non-OPT rows / pre-deploy clients). */}
                      {(() => {
                        const maxPerSpread = Number(row.max_profit) || 0;
                        const qty = Math.abs(Number(row.ib_qty) || 0);
                        const totalMax = maxPerSpread * qty;
                        const up = Number(row.ib_unrealized_pl);
                        if (!totalMax || !Number.isFinite(up)) return null;
                        const pct = Math.round((up / totalMax) * 100);
                        return (
                          <Text style={styles.auditDetail}>
                            Target: <Text style={styles.uPL}>+${totalMax.toFixed(2)}</Text>
                            {'   '}
                            <Text style={styles.uPL}>{pct}%</Text> of max
                          </Text>
                        );
                      })()}
                      <Text style={styles.auditDetail}>
                        Bot: {row.tracked_signed > 0 ? '+' : ''}{row.tracked_signed}
                        {row.strats.length > 0
                          ? `   [${row.strats.map((s: any) => {
                              // Bucket → Scalp / Intraday / Swing / Trend.
                              // Source of truth: metadata.model when the Pine
                              // signal sets it (e.g. htf_levels). Fallback:
                              // infer from the strategy name itself, so
                              // futures_2n20 / scalp_h1zone / fx_trend_4h
                              // get sensible tags even when Pine never sent
                              // a model field.
                              const m = String(s.model || '').toLowerCase();
                              const strat = String(s.strategy || '').toLowerCase();
                              let bucket = '';
                              // Dashboard mode (model field) is authoritative:
                              // the user picked SCALP / INTRADAY / SWING on
                              // the MTF panel and that's exactly the mode
                              // sent to the backend. The 'swing' tab is
                              // labeled MTF in Positions to match the panel
                              // section title.
                              if (m === 'scalp') bucket = 'Scalp';
                              else if (m === 'intraday') bucket = 'Intraday';
                              else if (m === 'swing' || m === 'mtf') bucket = 'MTF';
                              // Pine-strategy models (longer strings)
                              else if (m.includes('scalp')) bucket = 'Scalp';
                              else if (m.includes('intraday')) bucket = 'Intraday';
                              else if (m.includes('swing')) bucket = 'Swing';
                              else if (m === 'trend') bucket = 'Swing';
                              // Strategy-name fallback when model is missing
                              else if (strat === 'swing_setup') bucket = 'MTF';
                              else if (strat.includes('scalp') || strat.includes('2n20')) bucket = 'Scalp';
                              else if (strat.includes('intraday')) bucket = 'Intraday';
                              else if (strat.includes('swing') || strat.includes('trend')) bucket = 'Swing';
                              else if (m) bucket = s.model;
                              // htf_levels carries its own "HTF " prefix so
                              // the user reads "HTF Swing" rather than just
                              // "Swing" for high-timeframe setups.
                              const isHTF = strat === 'htf_levels' || strat.startsWith('htf_');
                              const tag = bucket ? `${isHTF ? 'HTF ' : ''}${bucket}·` : '';
                              // Manual MTF trades read "MTF", not "manual".
                              const stratName = strat.startsWith('manual') ? 'MTF' : s.strategy;
                              return `${tag}${stratName}=${s.direction}${s.contracts}`;
                            }).join(', ')}]`
                          : '   (none)'}
                      </Text>
                      {/* Two timestamps — different stories:
                          • Opened  = earliest IB fill (objective execution)
                          • Tracked = strat_pos opened_at (intent / adopt /
                            retag time set by the bot or reconciler).
                          Same line each if they collapse to the same value;
                          otherwise both rendered so divergence is visible. */}
                      {(() => {
                        const fmt = (ms: number) => {
                          const d = new Date(ms);
                          const today = new Date();
                          const sameDay = d.toDateString() === today.toDateString();
                          const time = d.toLocaleTimeString([], {
                            hour: '2-digit', minute: '2-digit',
                            second: '2-digit', hour12: false,
                          });
                          const datePart = sameDay
                            ? 'today'
                            : d.toLocaleDateString([], { month: 'short', day: 'numeric' });
                          return `${datePart} ${time}`;
                        };
                        // Opened = earliest IB fill (use min, since fills
                        // are sorted newest-first the last entry isn't
                        // always the earliest if entries got trimmed).
                        let openedMs = NaN;
                        if (row.recent_fills?.length) {
                          const ts = row.recent_fills
                            .map((f: any) => Number(f.time_ms) || 0)
                            .filter((n: number) => n > 0);
                          if (ts.length) openedMs = Math.min(...ts);
                        }
                        // Tracked = strat_pos opened_at (first strat).
                        const trackedIso = row.strats?.[0]?.opened_at || '';
                        const trackedMs = trackedIso ? Date.parse(trackedIso) : NaN;
                        const haveOpen = Number.isFinite(openedMs);
                        const haveTrack = Number.isFinite(trackedMs);
                        if (haveOpen && haveTrack) {
                          // Within 60s → same moment, render once.
                          if (Math.abs(openedMs - trackedMs) < 60_000) {
                            return (<Text style={styles.auditDetail}>Opened: {fmt(openedMs)}</Text>);
                          }
                          return (
                            <>
                              <Text style={styles.auditDetail}>Opened: {fmt(openedMs)}</Text>
                              <Text style={styles.auditDetail}>Tracked: {fmt(trackedMs)}</Text>
                            </>
                          );
                        }
                        if (haveOpen) return (<Text style={styles.auditDetail}>Opened: {fmt(openedMs)}</Text>);
                        if (haveTrack) return (<Text style={styles.auditDetail}>Opened: {fmt(trackedMs)}</Text>);
                        return null;
                      })()}
                      {row.recent_fills && row.recent_fills.length > 0 && (
                        <View style={styles.fillsBox}>
                          <Text style={styles.fillsHeader}>
                            Recent IB fills ({row.recent_fills.length})
                          </Text>
                          {row.recent_fills.map((f: any, i: number) => {
                            // Format ms-since-epoch → local clock time HH:MM:SS
                            const t = f.time_ms
                              ? new Date(f.time_ms).toLocaleTimeString([], {
                                  hour: '2-digit', minute: '2-digit',
                                  second: '2-digit', hour12: false,
                                })
                              : '—';
                            const isUntagged = f.source === 'untagged';
                            const isStop = f.source === 'bracket_stop';
                            const isTarget = f.source === 'bracket_target';
                            const isBot = typeof f.source === 'string' && f.source.startsWith('bot:');
                            // Only surface a tag when it's meaningful; a bare
                            // "other"/manual fill just clutters the row.
                            const tag =
                              isUntagged ? '⚠️ untagged'
                                : isStop ? '🛡 stop hit'
                                : isTarget ? '🎯 target hit'
                                : isBot ? f.source.replace('bot:', '')
                                : (f.source && !['other', 'manual', 'untracked'].includes(f.source)
                                    ? f.source : '');
                            // Decode the broker side code into plain words.
                            const sideCode = String(f.side || '').toUpperCase();
                            const sideWord = sideCode === 'B' ? 'Bought'
                              : sideCode === 'S' ? 'Sold'
                              : sideCode === 'X' ? 'Expired'
                              : sideCode === 'U' ? 'Assigned'
                              : (f.side || '');
                            const isZeroPx = !Number(f.price);  // expiry/assign land at 0
                            return (
                              <Text
                                key={i}
                                style={[
                                  styles.fillRow,
                                  isUntagged && styles.fillUntagged,
                                ]}
                              >
                                {t}  {sideWord} {f.qty}
                                {isZeroPx ? '' : ` @ ${Number(f.price).toFixed(2)}`}
                                {tag ? `  ·  ${tag}` : ''}
                              </Text>
                            );
                          })}
                        </View>
                      )}
                    </View>
                    );
                  })}
                  {audit.last_synced && (
                    <Text style={styles.auditSynced}>
                      IB snapshot age: {Math.floor((Date.now() - new Date(audit.last_synced).getTime()) / 1000)}s
                    </Text>
                  )}
                </View>
              )}
            </View>
          )}
          <View style={styles.watchlistSection}>
            <Text style={styles.watchlistTitle}>
              HTF Zones {filteredZones.length > 0 ? `(${filteredZones.filter(z => z.status === 'activated').length} activated)` : ''}
            </Text>
            {filteredZones.length === 0 ? (
              <Text style={{ color: Colors.textLight, fontSize: 13 }}>No zones being monitored</Text>
            ) : (
              filteredZones.map((z, i) => {
                const isActivated = z.status === 'activated';
                const isSupply = z.zone_type === 'supply';
                const tfColors: Record<string, string> = { '1mo': '#ff9800', '1w': '#ffeb3b', '1d': '#2196f3', '4h': '#ce93d8', '1h': '#66bb6a' };
                const tfLabels: Record<string, string> = { '1mo': 'M', '1w': 'W', '1d': 'D', '4h': '4H', '1h': '1H' };
                const tfColor = tfColors[z.zone_timeframe] || '#888';
                const trends = z.trends || {};

                return (
                  <TouchableOpacity
                    key={`${z.instrument}-${z.zone_type}-${z.zone_timeframe}-${i}`}
                    style={[styles.zoneCard, isActivated && styles.zoneCardActivated]}
                    onPress={() => {
                      // Open the chart at the strategy's bias (trend) TF —
                      // not the zone TF — so the user lands on the same
                      // frame they read for direction. Pass strategy +
                      // model separately so the chart label reads
                      // "Tidewater Scalp" etc. instead of "SCALP HTF".
                      const biasTfByModel: Record<string, string> = {
                        scalp: '15m',
                        intraday: '1h',
                        swing: '1w',
                      };
                      const chartTf = biasTfByModel[(z.model || '').toLowerCase()]
                        || z.zone_timeframe;
                      const params: any = {
                        symbol: z.instrument,
                        interval: chartTf,
                        strategy: 'htf_levels',
                        model: z.model || '',
                        direction: z.trade_direction,
                      };
                      // Activation timestamp lets the chart drop a triangle
                      // at the bar where price first entered the zone band.
                      if (z.activated_at) params.activated_at = String(z.activated_at);
                      // Projected entry/stop from the watched zone — let
                      // the chart render them as the planned trade lines
                      if (z.projected_entry != null) params.entry = String(z.projected_entry);
                      if (z.projected_stop != null) params.stop = String(z.projected_stop);
                      if (z.projected_target != null) params.exit = String(z.projected_target);
                      router.push({ pathname: '/chart', params });
                    }}
                  >
                    <View style={styles.zoneTop}>
                      <Text style={styles.zoneTicker}>{z.instrument}</Text>
                      <View style={[styles.zoneBadge, { backgroundColor: isSupply ? '#fdecea' : '#e8f5e9' }]}>
                        <Text style={[styles.zoneBadgeText, { color: isSupply ? Colors.red : Colors.green }]}>
                          {isSupply ? 'SUPPLY' : 'DEMAND'}
                        </Text>
                      </View>
                      <View style={[styles.tfBadge, { backgroundColor: tfColor + '22', borderColor: tfColor }]}>
                        <Text style={[styles.tfBadgeText, { color: tfColor }]}>
                          {tfLabels[z.zone_timeframe] || z.zone_timeframe}
                        </Text>
                      </View>
                      {isActivated && (
                        <View style={styles.activatedDot} />
                      )}
                      <View style={{ flex: 1 }} />
                      <Text style={styles.zoneScore}>{z.bias_score}</Text>
                    </View>
                    <View style={styles.zoneBottom}>
                      <Text style={styles.zonePrice}>
                        @ {z.zone_price.toFixed(z.instrument.includes('JPY') ? 3 : (z.instrument.includes('_') ? 5 : 2))}
                      </Text>
                      <Text style={styles.zoneModel}>
                        {strategyBadgeText('htf_levels', z.model)}
                      </Text>
                      <View style={styles.trendRow}>
                        {sortedTrendEntries(trends).map(([tf, dir]) => (
                          <Text key={tf} style={[styles.trendBadge, {
                            color: dir === 'bullish' ? Colors.green : dir === 'bearish' ? Colors.red : Colors.textLight
                          }]}>
                            {tf}{dir === 'bullish' ? '↑' : dir === 'bearish' ? '↓' : '→'}
                          </Text>
                        ))}
                      </View>
                    </View>
                    {(() => {
                      const plan = buildZoneTradePlan(z);
                      if (!plan.hasPlan) return null;
                      return (
                        <>
                          <View style={styles.zonePlanRow}>
                            <Text style={styles.zonePlanLabel}>E</Text>
                            <Text style={styles.zonePlanValue}>{plan.entry}</Text>
                            <Text style={styles.zonePlanLabel}>T</Text>
                            <Text style={[styles.zonePlanValue, { color: '#ff9800' }]}>{plan.target}</Text>
                            <Text style={styles.zonePlanLabel}>S</Text>
                            <Text style={[styles.zonePlanValue, { color: Colors.red }]}>{plan.stop}</Text>
                          </View>
                          <View style={styles.zonePlanRow}>
                            <Text style={styles.zonePlanLabel}>Risk</Text>
                            <Text style={[styles.zonePlanValue, { color: Colors.red }]}>{plan.risk}</Text>
                            <Text style={styles.zonePlanLabel}>Reward</Text>
                            <Text style={[styles.zonePlanValue, { color: Colors.green }]}>{plan.reward}</Text>
                            <Text style={styles.zonePlanLabel}>R:R</Text>
                            <Text style={[styles.zonePlanValue, { color: plan.rrColor, fontWeight: '700' }]}>{plan.rr}</Text>
                          </View>
                        </>
                      );
                    })()}
                    {isActivated && z.activated_at ? (
                      <Text style={styles.zoneActivatedAt}>
                        Activated {formatActivatedAt(z.activated_at)}
                      </Text>
                    ) : null}
                  </TouchableOpacity>
                );
              })
            )}
          </View>
          </>
        }
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: Colors.cream },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    paddingHorizontal: 20,
    paddingTop: 12,
    paddingBottom: 12,
  },
  headerTitle: { fontSize: 22, fontWeight: '300', color: Colors.dark },
  headerSubtitle: { fontSize: 12, color: Colors.textLight, marginTop: 2 },
  tabBar: {
    flexDirection: 'row',
    marginHorizontal: 16,
    marginBottom: 12,
    backgroundColor: Colors.white,
    borderRadius: 10,
    padding: 3,
  },
  tab: {
    flex: 1,
    paddingVertical: 10,
    alignItems: 'center',
    borderRadius: 8,
  },
  tabActive: { backgroundColor: Colors.olive },
  tabText: { fontSize: 13, fontWeight: '500', color: Colors.textLight },
  tabTextActive: { color: Colors.gold },
  plSummary: { alignItems: 'flex-end' },
  plLabel: { fontSize: 10, color: Colors.textLight, letterSpacing: 0.5, textTransform: 'uppercase' },
  plTotal: { fontSize: 20, fontWeight: '300' },
  posRow: {
    backgroundColor: Colors.white,
    borderRadius: 12,
    padding: 14,
    marginBottom: 8,
  },
  posTop: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginBottom: 10,
  },
  posInstrument: { fontSize: 16, fontWeight: '600', color: Colors.dark },
  dirBadge: { paddingHorizontal: 8, paddingVertical: 2, borderRadius: 50 },
  dirText: { fontSize: 11, fontWeight: '600' },
  brokerBadge: { paddingHorizontal: 8, paddingVertical: 2, borderRadius: 50 },
  brokerText: { fontSize: 10, fontWeight: '600' },
  posPl: { fontSize: 18, fontWeight: '500' },
  posDetails: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 16,
    marginBottom: 8,
  },
  posDetail: {},
  posDetailLabel: { fontSize: 10, color: Colors.textLight, textTransform: 'uppercase', letterSpacing: 0.3 },
  posDetailValue: { fontSize: 14, color: Colors.dark, marginTop: 1 },
  posFooter: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    borderTopWidth: 1,
    borderTopColor: '#f5f3ee',
    paddingTop: 8,
  },
  posTime: { fontSize: 11, color: Colors.textLight },
  modelBadge: { fontSize: 10, fontWeight: '700', letterSpacing: 0.3 },
  zoneInfoRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginTop: 10,
    paddingTop: 8,
    borderTopWidth: 1,
    borderTopColor: '#f0ebe2',
    gap: 8,
  },
  rrRow: {
    flexDirection: 'row',
    marginTop: 10,
    paddingTop: 8,
    borderTopWidth: 1,
    borderTopColor: '#f0ebe2',
    gap: 18,
  },
  rrItem: { flexDirection: 'column' },
  rrLabel: {
    fontSize: 9,
    fontWeight: '600',
    color: Colors.textLight,
    letterSpacing: 0.6,
  },
  rrValue: {
    fontSize: 14,
    fontWeight: '500',
    color: Colors.dark,
    marginTop: 2,
  },
  qtyText: {
    fontSize: 13,
    fontWeight: '600',
    color: Colors.dark,
    marginLeft: -4,
  },
  closeBtn: {
    marginLeft: 10,
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 4,
    borderWidth: 1,
    borderColor: Colors.red,
  },
  closeBtnText: {
    fontSize: 11,
    fontWeight: '600',
    color: Colors.red,
    letterSpacing: 0.5,
  },
  chartToggleBtn: {
    marginLeft: 8,
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 4,
    borderWidth: 1,
    borderColor: Colors.olive,
  },
  chartToggleText: {
    fontSize: 11,
    fontWeight: '600',
    color: Colors.olive,
    letterSpacing: 0.3,
  },
  inlineChart: {
    marginTop: 10,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: '#e5e5e5',
    paddingTop: 8,
  },
  tfRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 6,
    marginBottom: 6,
  },
  tfPill: {
    paddingHorizontal: 9,
    paddingVertical: 3,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#ccc',
    backgroundColor: '#f7f7f7',
  },
  tfPillActive: {
    backgroundColor: Colors.olive,
    borderColor: Colors.olive,
  },
  tfPillText: {
    fontSize: 11,
    color: Colors.dark,
    fontWeight: '600',
  },
  tfPillTextActive: { color: '#fff' },
  inlineChartWebview: {
    height: 360,
    backgroundColor: '#1a1a2e',
    borderRadius: 6,
    overflow: 'hidden',
  },
  watchlistSection: { marginTop: 24, paddingBottom: 20 },

  // IB-vs-Bot audit card
  auditSection: {
    marginTop: 16,
    padding: 12,
    backgroundColor: '#FFFFFF',
    borderRadius: 10,
    borderWidth: 1,
    borderColor: '#E0E0DA',
  },
  auditHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  auditTitle: { fontSize: 14, fontWeight: '600', color: Colors.text },
  auditChevron: { fontSize: 12, color: Colors.textLight },
  auditRow: {
    paddingVertical: 8,
    paddingHorizontal: 10,
    marginTop: 6,
    borderRadius: 6,
    backgroundColor: '#F8F8F4',
  },
  auditRowMismatch: { backgroundColor: '#fdecea' },
  // Title + status stacked vertically so long VERTICAL descriptors
  // ("VERTICAL AMZN 100 5 JUN 26 (3) 250/255 P  📉 Bear") get the full
  // row width to wrap into, and the status label never clips off-screen.
  auditRowTop: { flexDirection: 'column' },
  auditInst: { fontSize: 12, fontWeight: '700', color: Colors.text },
  auditStatus: { fontSize: 11, fontWeight: '700', marginTop: 2, textAlign: 'right' },
  auditDetail: { fontSize: 12, color: Colors.textLight, marginTop: 2 },
  auditLegend: {
    backgroundColor: Colors.cream, borderRadius: 8, padding: 10, marginBottom: 10,
  },
  auditLegendText: { fontSize: 11, lineHeight: 17, color: Colors.textMedium },
  uPL: { fontWeight: '700' },
  dteBadge: { fontSize: 12, fontWeight: '700', color: Colors.textMedium, marginTop: 3 },
  auditSynced: { fontSize: 11, color: Colors.textLight, marginTop: 6, fontStyle: 'italic', textAlign: 'right' },
  fillsBox: { marginTop: 8, paddingTop: 6, borderTopWidth: 1,
              borderTopColor: '#e8d8d6' },
  fillsHeader: { fontSize: 11, color: Colors.textLight, marginBottom: 3,
                 fontWeight: '600', letterSpacing: 0.3 },
  fillRow: { fontSize: 11, color: Colors.dark, marginTop: 2,
             fontVariant: ['tabular-nums'] },
  fillUntagged: { color: '#c0392b', fontWeight: '600' },
  watchlistTitle: { fontSize: 16, fontWeight: '500', color: Colors.dark, marginBottom: 12 },
  zoneCard: {
    backgroundColor: Colors.white, borderRadius: 12, padding: 14,
    marginBottom: 8, borderLeftWidth: 3, borderLeftColor: '#e0ddd8',
  },
  zoneCardActivated: {
    borderLeftColor: Colors.green,
    backgroundColor: '#f8fdf8',
  },
  zoneTop: { flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: 6 },
  zoneTicker: { fontSize: 15, fontWeight: '600', color: Colors.dark },
  zoneBadge: { paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4 },
  zoneBadgeText: { fontSize: 10, fontWeight: '700' },
  tfBadge: { paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4, borderWidth: 1 },
  tfBadgeText: { fontSize: 10, fontWeight: '700' },
  activatedDot: { width: 8, height: 8, borderRadius: 4, backgroundColor: Colors.green },
  zoneScore: { fontSize: 14, fontWeight: '600', color: Colors.olive },
  zoneBottom: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  zonePrice: { fontSize: 13, color: Colors.textMedium },
  zoneModel: { fontSize: 10, fontWeight: '700', color: Colors.textLight, letterSpacing: 0.3 },
  zonePlanRow: { flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 4, flexWrap: 'wrap' },
  zonePlanLabel: { fontSize: 10, color: Colors.textLight, letterSpacing: 0.3, textTransform: 'uppercase' },
  zonePlanValue: { fontSize: 11, color: Colors.dark, fontFamily: 'Menlo', marginRight: 4 },
  zoneActivatedAt: { fontSize: 10, color: Colors.olive, fontStyle: 'italic', marginTop: 6 },
  trendRow: { flexDirection: 'row', gap: 4 },
  trendBadge: { fontSize: 11, fontWeight: '600' },
  empty: { alignItems: 'center', paddingTop: 60 },
  emptyText: { fontSize: 16, color: Colors.textLight },
  emptySubtext: { fontSize: 13, color: Colors.textLight, marginTop: 6, textAlign: 'center' },
});
