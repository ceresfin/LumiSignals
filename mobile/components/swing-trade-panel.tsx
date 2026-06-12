// Swing Trade Panel — Dashboard bottom section.
//
// Lets the user pick a symbol + mode + chart timeframe, fetches the
// front-side options-debit-spread setup from /api/swing-setup, displays
// trends per timeframe (Russian-doll stack), trade parameters, spread
// spec, and a chart at the bottom with overlay lines.
//
// Gated by EXPO_PUBLIC_SWING_PANEL_ENABLED — renders nothing when unset.
// Open Trade button gated additionally by the backend's
// `equity:orders_enabled` Redis flag (it returns HTTP 503 if off).
//
// Phase 4 of the Dashboard plan. See docs/orb-plan-snapshot-2026-05-30.md
// for the related ORB work + plan file for the full panel design.

import React, { useEffect, useMemo, useState } from 'react';
import {
  ActivityIndicator, Alert, ScrollView, StyleSheet, Text, TextInput,
  TouchableOpacity, View,
} from 'react-native';
import { WebView } from 'react-native-webview';
import AsyncStorage from '@react-native-async-storage/async-storage';

import { Colors } from '@/constants/theme';

// AsyncStorage key for the per-trade max-risk cap. One global value
// shared across all tickers/modes — the user's risk tolerance per
// click of Open Trade, not a per-symbol setting.
const MAX_RISK_KEY = 'swingPanel:maxRiskUsd';
const MAX_RISK_DEFAULT = '200';
// User's custom ticker watchlist (added via the search bar). Persisted to
// AsyncStorage so uploaded symbols survive remounts/restarts.
const WATCHLIST_KEY = 'swingPanel:watchlist';
// A ticker is anything 1-6 chars of letters (optionally a dot, e.g. BRK.B).
const TICKER_RE = /^[A-Z]{1,6}(\.[A-Z])?$/;

// Two groups so the UI can render a section label per row.
// Stocks chosen for: liquid weekly chains, sane strike intervals
// ($1-2.50), and enough IV to make 30-delta verticals worth the
// debit. Alphabetized within group for findability.
const INDEX_TICKERS = ['SPY', 'QQQ', 'IWM', 'SPX', 'XSP', 'NDX'] as const;
const STOCK_TICKERS = [
  'AAPL', 'AMD', 'AMZN', 'AVGO', 'GOOG', 'JPM', 'LLY', 'META',
  'MSFT', 'MU', 'NFLX', 'NVDA', 'TSLA', 'WMT', 'XOM',
] as const;
const SUPPORTED_TICKERS = [...INDEX_TICKERS, ...STOCK_TICKERS] as const;
// Tab labels show the trade's holding period (SCALP/INTRADAY/SWING).
// The section title "Multiple Time Frame Trade Setup" and the trade tag
// "MTF·" in Positions describe the analysis methodology — those stay.
const MODES = ['scalp', 'intraday', 'swing'] as const;
const TF_LABELS: Record<string, string> = {
  '5m': '5M', '15m': '15M', '1h': '1H', '4h': '4H',
  '1d': 'Daily', '1w': 'Weekly', '1mo': 'Monthly',
};
// Chart timeframe options per mode — mirrors the analyzer's Russian-
// doll TF stack so the chart matches the trade horizon. Default is the
// middle TF (the "main" timeframe for the mode).
const MODE_TIMEFRAMES: Record<string, string[]> = {
  scalp:    ['5m',  '15m', '1h'],
  intraday: ['15m', '1h',  '4h'],
  swing:    ['1d',  '1w',  '1mo'],
};
const DEFAULT_CHART_TF: Record<string, string> = {
  scalp: '15m', intraday: '1h', swing: '1w',
};

const API_BASE = 'https://bot.lumitrade.ai';
const SYNC_KEY = process.env.EXPO_PUBLIC_LUMI_SYNC_KEY ?? '';
const ENABLED = process.env.EXPO_PUBLIC_SWING_PANEL_ENABLED === '1';

const fmtMoney = (n: number | null | undefined) =>
  n == null ? '—' : `$${n.toFixed(2)}`;

type Setup = {
  ticker: string;
  mode: string;
  direction: 'BUY' | 'SELL' | null;
  skip_reason: string | null;
  tradeable?: boolean;   // false in "prospective" mode (no pullback yet) — Open Trade disabled but levels still show
  momentum: 'Strong' | 'Weak' | null;
  trends: Record<string, 'UP' | 'DOWN' | 'SIDE'> | null;
  trigger_level: number | null;
  underlying_price: number | null;
  vehicle: 'options' | 'shares' | null;
  options: {
    expiry: string | null;
    long_strike: number | null;
    short_strike: number | null;
    spread_type: string | null;
    width_points: number;
    net_debit_estimate: number | null;
    max_loss_per_spread: number | null;
    max_profit_per_spread: number | null;
    contracts: number;
    contracts_reason: string | null;
    breakeven: number | null;
    long_delta: number | null;
    short_delta: number | null;
  } | null;
  shares: {
    entry: number | null;
    stop: number | null;
    target: number | null;
    qty: number;
    qty_reason: string | null;
    risk_per_share: number | null;
    atr: number | null;
    atr_multiplier: number | null;
    atr_tf: string | null;
  } | null;
  warnings: string[];
  chart_overlay?: Record<string, number | null>;
};

// Render values for the RETURN / RISK / R:R cards, abstracted per
// vehicle so the same JSX renders both options and shares views.
type ReturnRiskView = {
  labelEntry: string;    labelTarget: string;
  labelUnit: string;     labelPerUnit: string;
  entry: number | null;  target: number | null;
  profitPerUnit: number | null;
  potentialProfit: number | null;
  stop: number | null;
  riskPerUnit: number | null;
  potentialLoss: number | null;
  rrRatio: number | null;
};

export function SwingTradePanel({ initialTicker, initialMode }: {
  initialTicker?: string;
  initialMode?: typeof MODES[number];
} = {}) {
  if (!ENABLED) return null;

  // Free-form now (was limited to SUPPORTED_TICKERS) — the search bar lets
  // the user add any ticker the backend can analyze. initialTicker/initialMode
  // let callers (e.g. the MTF scanner card) deep-link straight to a setup.
  const [ticker, setTicker] = useState<string>(initialTicker || 'SPX');
  const [mode, setMode] = useState<typeof MODES[number]>(initialMode || 'swing');
  // Custom watchlist + the search/upload box text.
  const [watchlist, setWatchlist] = useState<string[]>([]);
  const [query, setQuery] = useState('');
  const [vehicle, setVehicle] = useState<'options' | 'shares'>('options');
  const [chartTf, setChartTf] = useState<string>('1w');
  const [setup, setSetup] = useState<Setup | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // User-controlled cap. Caps potential loss per trade and sizes
  // contracts/shares to fit. Default $200 matches the backend default.
  // Kept as a string so the user can clear/edit freely; parsed to a
  // float at fetch time. Persisted to AsyncStorage so it survives
  // panel remounts and app restarts.
  const [maxRiskInput, setMaxRiskInput] = useState<string>(MAX_RISK_DEFAULT);
  // Tall-mode toggle for the chart — triggered by the legend's expand
  // button in mobile_chart.html via postMessage.
  const [chartExpanded, setChartExpanded] = useState(false);

  // Supply & Demand Zones data now comes from the swing-setup response
  // (setup.zones_by_tf + setup.underlying_price). Single source of truth
  // shared with the chart's entry/target/stop levels — no separate fetch
  // and no possibility of bar-fetch divergence between endpoints.
  const zonesData = useMemo(() => {
    if (!setup) return null;
    return {
      ticker,
      current_price: setup.underlying_price,
      server: (setup as any).zones_by_tf || {},
    };
  }, [setup, ticker]);

  // Hydrate the saved value once on mount.
  useEffect(() => {
    AsyncStorage.getItem(MAX_RISK_KEY)
      .then(saved => { if (saved) setMaxRiskInput(saved); })
      .catch(() => { /* fall through to default */ });
  }, []);

  // Persist on change. Skip empty/0 values so an in-progress edit
  // doesn't clobber a previously-good value mid-keystroke.
  useEffect(() => {
    const parsed = parseFloat(maxRiskInput);
    if (Number.isFinite(parsed) && parsed > 0) {
      AsyncStorage.setItem(MAX_RISK_KEY, maxRiskInput).catch(() => {});
    }
  }, [maxRiskInput]);

  // Hydrate the saved watchlist once on mount.
  useEffect(() => {
    AsyncStorage.getItem(WATCHLIST_KEY)
      .then(saved => { if (saved) setWatchlist(JSON.parse(saved)); })
      .catch(() => { /* no saved list yet */ });
  }, []);

  // Persist the watchlist whenever it changes.
  useEffect(() => {
    AsyncStorage.setItem(WATCHLIST_KEY, JSON.stringify(watchlist)).catch(() => {});
  }, [watchlist]);

  // Parse the search box (single ticker, or comma/space/newline-separated
  // for fast bulk upload), keep valid + new ones, append to the watchlist,
  // and jump to the first one added. Built-ins aren't re-added.
  const addTickers = (raw: string) => {
    const known = new Set<string>([...SUPPORTED_TICKERS, ...watchlist]);
    const parsed = raw.toUpperCase().split(/[\s,]+/)
      .map(s => s.trim()).filter(Boolean).filter(t => TICKER_RE.test(t));
    const fresh: string[] = [];
    for (const t of parsed) {
      if (!known.has(t) && !fresh.includes(t)) fresh.push(t);
    }
    // Select the first thing typed (new or existing) so Add always navigates.
    const first = parsed[0];
    if (fresh.length) setWatchlist(prev => [...prev, ...fresh]);
    if (first) setTicker(first);
    setQuery('');
  };

  const removeTicker = (t: string) => {
    setWatchlist(prev => prev.filter(x => x !== t));
    if (ticker === t) setTicker('SPX');   // fall back if the active one is removed
  };

  // Auto-select default chart TF when mode changes
  useEffect(() => {
    setChartTf(DEFAULT_CHART_TF[mode]);
  }, [mode]);

  // Refetch on ticker / mode / maxRisk change. Debounced 400ms for
  // maxRisk so typing doesn't hammer the backend on every keystroke.
  useEffect(() => {
    let cancelled = false;
    const parsed = parseFloat(maxRiskInput);
    const effectiveRisk = Number.isFinite(parsed) && parsed > 0 ? parsed : 200;
    const timer = setTimeout(() => {
      if (cancelled) return;
      setLoading(true);
      setError(null);
      fetch(`${API_BASE}/api/swing-setup?ticker=${ticker}&mode=${mode}&max_risk_usd=${effectiveRisk}`)
        .then((r) => r.json())
        .then((data) => { if (!cancelled) setSetup(data as Setup); })
        .catch((e) => { if (!cancelled) setError(String(e)); })
        .finally(() => { if (!cancelled) setLoading(false); });
    }, 400);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [ticker, mode, maxRiskInput]);

  const opt = setup?.options;
  const sh = setup?.shares;

  const chartUrl = useMemo(() => {
    const params: string[] = [
      `ticker=${encodeURIComponent(ticker)}`,
      `timespan=${chartTf}`, `count=80`, `strategy=swing_setup`,
      // Suppress the in-chart DASHBOARD overlay table — we render the
      // same info (Direction / Entry / Stop / Target / R:R) above the
      // chart in the SPREAD card. Duplicating it on the candles just
      // blocks price action.
      `dashboard=0`,
    ];
    params.push(`vehicle=${vehicle}`);
    if (vehicle === 'shares' && sh) {
      // Stock plan — chart renders 3 simple lines: ENTRY / TARGET / STOP.
      // These come from swing_setup.py per-mode logic (HTF zone entry,
      // 3x bottom-TF ATR stop, opposite-zone target). Mode change here
      // → backend returns different sh values → chart updates.
      if (sh.entry != null)  params.push(`entry=${sh.entry}`);
      if (sh.target != null) params.push(`target=${sh.target}`);
      if (sh.stop != null)   params.push(`stop=${sh.stop}`);
    } else if (vehicle === 'options' && opt) {
      // Options spread — keep the long/short/breakeven lines.
      if (opt.long_strike) params.push(`long_strike=${opt.long_strike}`);
      if (opt.short_strike) params.push(`short_strike=${opt.short_strike}`);
      if (opt.breakeven) params.push(`breakeven=${opt.breakeven}`);
      if (opt.max_profit_per_spread) params.push(`max_profit=${opt.max_profit_per_spread}`);
      if (opt.max_loss_per_spread) params.push(`max_loss=${opt.max_loss_per_spread}`);
      if (opt.spread_type) params.push(`spread_type=${opt.spread_type}`);
    }
    if (setup?.trigger_level) params.push(`trigger_level=${setup.trigger_level}`);
    if (setup?.direction) params.push(`direction=${setup.direction}`);
    return `${API_BASE}/chart?${params.join('&')}`;
  }, [ticker, chartTf, setup, opt, sh, vehicle]);
  // tradeable defaults to true for backward-compat when the backend
  // doesn't include the field (older deploys); explicit false from the
  // backend disables Open Trade while still allowing levels to render.
  const isTradeable = setup?.tradeable !== false;
  const tradeReady = isTradeable && setup?.direction != null
    && ((vehicle === 'shares' ? (sh?.qty ?? 0) : (opt?.contracts ?? 0)) > 0);

  // Derive the RETURN / RISK / R:R view per vehicle. Shares uses
  // entry / target / stop directly; options maps net_debit→entry,
  // max_profit→target, and the spread itself defines the loss.
  const rrView: ReturnRiskView = useMemo(() => {
    if (vehicle === 'shares' && sh && sh.entry != null && sh.stop != null && sh.target != null) {
      // For shorts (SELL), target < entry and stop > entry — taking
      // absolute values keeps profit/risk positive regardless of
      // direction. Without this, SHORT setups showed negative profit
      // and negative R:R (e.g., AAPL SCALP SHORT: -$894.30 "profit").
      const profitPerShare = Math.abs(sh.target - sh.entry);
      const riskPerShare = sh.risk_per_share ?? Math.abs(sh.entry - sh.stop);
      return {
        labelEntry: 'Entry', labelTarget: 'Target',
        labelUnit: 'Share', labelPerUnit: '/ Share',
        entry: sh.entry, target: sh.target,
        profitPerUnit: profitPerShare,
        potentialProfit: profitPerShare * sh.qty,
        stop: sh.stop,
        riskPerUnit: riskPerShare,
        potentialLoss: riskPerShare * sh.qty,
        rrRatio: riskPerShare > 0 ? profitPerShare / riskPerShare : null,
      };
    }
    if (vehicle === 'options' && opt && opt.net_debit_estimate != null) {
      const profitPerContract = opt.max_profit_per_spread ?? 0;
      const riskPerContract = opt.max_loss_per_spread ?? 0;
      return {
        labelEntry: 'Net Debit', labelTarget: 'Max Profit at',
        labelUnit: 'Contract', labelPerUnit: '/ Contract',
        entry: opt.net_debit_estimate,
        target: opt.short_strike,        // strike where max profit is achieved at expiry
        profitPerUnit: profitPerContract,
        potentialProfit: profitPerContract * opt.contracts,
        stop: opt.breakeven,             // breakeven price below which spread loses
        riskPerUnit: riskPerContract,
        potentialLoss: riskPerContract * opt.contracts,
        rrRatio: riskPerContract > 0 ? profitPerContract / riskPerContract : null,
      };
    }
    return {
      labelEntry: 'Entry', labelTarget: 'Target',
      labelUnit: 'Unit', labelPerUnit: '/ Unit',
      entry: null, target: null, profitPerUnit: null, potentialProfit: null,
      stop: null, riskPerUnit: null, potentialLoss: null, rrRatio: null,
    };
  }, [vehicle, opt, sh]);
  const directionLabel = setup?.direction === 'BUY' ? 'LONG ▲'
    : setup?.direction === 'SELL' ? 'SHORT ▼' : '—';

  const onOpenTrade = () => {
    if (!setup || !opt || !tradeReady) return;
    Alert.alert(
      'Open Trade?',
      `${setup.direction} ${ticker} ${opt.spread_type}\n` +
      `${opt.long_strike} / ${opt.short_strike} × ${opt.contracts} contracts\n` +
      `Net debit $${opt.net_debit_estimate?.toFixed(2)}\n` +
      `Max loss $${opt.max_loss_per_spread?.toFixed(0)}, max profit $${opt.max_profit_per_spread?.toFixed(0)}`,
      [
        { text: 'Cancel', style: 'cancel' },
        { text: 'Open', style: 'default', onPress: () => submitOrder(setup, opt) },
      ],
    );
  };

  const submitOrder = async (s: Setup, o: NonNullable<Setup['options']>) => {
    try {
      const r = await fetch(`${API_BASE}/api/option-spread/order`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Sync-Key': SYNC_KEY },
        body: JSON.stringify({
          ticker: s.ticker, direction: s.direction,
          spread_type: o.spread_type, expiry: o.expiry,
          long_strike: o.long_strike, short_strike: o.short_strike,
          contracts: o.contracts, limit_price: o.net_debit_estimate,
          max_risk_usd: o.max_loss_per_spread,
          // Lets the backend tag the strat_pos with model=mode so the
          // Positions reconciler shows "MTF·" / "Scalp·" / "Intraday·".
          mode,
        }),
      });
      const j = await r.json();
      if (r.ok && j.order_id) {
        Alert.alert('Order Placed', `Order ID: ${j.order_id}\nCoID: ${j.coid}`);
      } else {
        Alert.alert('Order Failed', j.reason || j.error || JSON.stringify(j));
      }
    } catch (e) {
      Alert.alert('Order Failed', String(e));
    }
  };

  // Search box behavior: a single token filters the built-in chip rows
  // (find fast); a multi-token entry (comma/space) is treated as a bulk
  // upload and skips filtering. The Add button always parses + adds.
  const q = query.trim().toUpperCase();
  const isBulk = /[\s,]/.test(query.trim());
  const flt = (list: readonly string[]) =>
    (!q || isBulk) ? list : list.filter(t => t.startsWith(q));
  const fIdx = flt(INDEX_TICKERS);
  const fStk = flt(STOCK_TICKERS);
  const fWatch = flt(watchlist);
  const canAdd = query.trim().length > 0;

  const renderChip = (t: string, removable = false) => (
    <TouchableOpacity key={t}
      onPress={() => setTicker(t)}
      onLongPress={removable ? () => removeTicker(t) : undefined}
      style={[styles.chip, ticker === t && styles.chipActive]}>
      <Text style={[styles.chipText, ticker === t && styles.chipTextActive]}>{t}</Text>
    </TouchableOpacity>
  );

  return (
    <View style={styles.section}>
      <Text style={styles.sectionTitle}>Multiple Time Frame Trade Setup</Text>

      {/* Search / fast-upload bar — type one ticker to find, or paste a
          comma/space list (e.g. "AMZN, MSFT, GOOGL") to add them all. */}
      <View style={styles.searchRow}>
        <TextInput
          style={styles.searchInput}
          value={query}
          onChangeText={t => setQuery(t.toUpperCase())}
          onSubmitEditing={() => addTickers(query)}
          placeholder="Search or add tickers — AMZN, MSFT, GOOGL"
          placeholderTextColor={Colors.textLight}
          autoCapitalize="characters"
          autoCorrect={false}
          returnKeyType="done"
        />
        <TouchableOpacity
          onPress={() => addTickers(query)}
          disabled={!canAdd}
          style={[styles.addBtn, !canAdd && styles.addBtnDisabled]}>
          <Text style={styles.addBtnText}>Add</Text>
        </TouchableOpacity>
      </View>

      {/* My custom watchlist — long-press a chip to remove it. */}
      {fWatch.length > 0 && (
        <>
          <Text style={styles.pickerLabel}>MY TICKERS  ·  long-press to remove</Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false}
            contentContainerStyle={styles.chipScrollRow}>
            {fWatch.map((t) => renderChip(t, true))}
          </ScrollView>
        </>
      )}

      {/* Symbol picker — two horizontally-scrollable rows: indexes + stocks */}
      {fIdx.length > 0 && <>
        <Text style={styles.pickerLabel}>INDEXES</Text>
        <ScrollView horizontal showsHorizontalScrollIndicator={false}
          contentContainerStyle={styles.chipScrollRow}>
          {fIdx.map((t) => renderChip(t))}
        </ScrollView>
      </>}
      {fStk.length > 0 && <>
        <Text style={styles.pickerLabel}>STOCKS</Text>
        <ScrollView horizontal showsHorizontalScrollIndicator={false}
          contentContainerStyle={styles.chipScrollRow}>
          {fStk.map((t) => renderChip(t))}
        </ScrollView>
      </>}
      {/* When a single-token search matches nothing built-in/saved, hint Add. */}
      {q && !isBulk && fIdx.length === 0 && fStk.length === 0 && fWatch.length === 0 && (
        <Text style={styles.noMatch}>No saved match for "{q}" — tap Add to analyze it.</Text>
      )}

      {/* Vehicle toggle (Options is primary; Shares for ETF trades) */}
      <View style={styles.vehicleRow}>
        {(['options', 'shares'] as const).map((v) => (
          <TouchableOpacity key={v}
            onPress={() => setVehicle(v)}
            style={[styles.vehicleChip, vehicle === v && styles.vehicleChipActive]}>
            <Text style={[styles.vehicleText, vehicle === v && styles.vehicleTextActive]}>
              {v === 'options' ? 'Options' : 'Shares'}
            </Text>
          </TouchableOpacity>
        ))}
      </View>

      {/* Mode segmented control */}
      <View style={styles.segmented}>
        {MODES.map((m) => (
          <TouchableOpacity key={m}
            onPress={() => setMode(m)}
            style={[styles.segment, mode === m && styles.segmentActive]}>
            <Text style={[styles.segmentText, mode === m && styles.segmentTextActive]}>
              {m.toUpperCase()}
            </Text>
          </TouchableOpacity>
        ))}
      </View>

      {/* Timeframe (chart display only) — mode-aware: SCALP→5M/15M/1H,
          INTRADAY→15M/1H/Daily, SWING→Daily/Weekly/Monthly. */}
      <View style={styles.tfRow}>
        {MODE_TIMEFRAMES[mode].map((tf) => (
          <TouchableOpacity key={tf}
            onPress={() => setChartTf(tf)}
            style={[styles.tfCircle, chartTf === tf && styles.tfCircleActive]}>
            <Text style={[styles.tfText, chartTf === tf && styles.tfTextActive]}>
              {TF_LABELS[tf]}
            </Text>
          </TouchableOpacity>
        ))}
      </View>

      {loading && <ActivityIndicator style={{ marginVertical: 12 }} color={Colors.olive} />}
      {error && <Text style={styles.errorText}>Error: {error}</Text>}

      {/* Status banner */}
      {setup && tradeReady && (
        <View style={[styles.banner, { borderLeftColor: Colors.green }]}>
          <Text style={styles.bannerTitle}>TRADE READY</Text>
          <Text style={styles.bannerBody}>
            {directionLabel} {ticker} · {setup.momentum}
          </Text>
        </View>
      )}
      {setup?.skip_reason && (
        <View style={[styles.banner, { borderLeftColor: Colors.amber }]}>
          <Text style={styles.bannerTitle}>NO TRADE</Text>
          <Text style={styles.bannerBody}>{setup.skip_reason}</Text>
        </View>
      )}

      {/* Symbol header */}
      <View style={styles.headerCard}>
        <View>
          <Text style={styles.symbolText}>{ticker}</Text>
          <Text style={[styles.dirBadge, {
            color: setup?.direction === 'BUY' ? Colors.green
              : setup?.direction === 'SELL' ? Colors.red : Colors.textLight,
          }]}>{directionLabel}</Text>
        </View>
        <View style={{ alignItems: 'flex-end' }}>
          <Text style={styles.label}>Max Risk Per Trade</Text>
          <View style={styles.riskInputRow}>
            <Text style={styles.riskDollar}>$</Text>
            <TextInput
              value={maxRiskInput}
              onChangeText={setMaxRiskInput}
              keyboardType="numeric"
              placeholder="200"
              placeholderTextColor={Colors.textLight}
              style={styles.riskInput}
              selectTextOnFocus
              returnKeyType="done"
            />
          </View>
        </View>
      </View>

      {/* Trade parameters 2x2 */}
      <View style={styles.paramCard}>
        <Text style={styles.cardTitle}>TRADE PARAMETERS</Text>
        <View style={styles.gridRow}>
          <View style={styles.gridCell}>
            <Text style={styles.label}>Direction</Text>
            <Text style={styles.value}>
              {setup?.direction === 'BUY' ? `Long ${opt?.spread_type === 'call_debit' ? 'Call' : 'Put'}`
                : setup?.direction === 'SELL' ? `Long ${opt?.spread_type === 'put_debit' ? 'Put' : 'Call'}`
                : '—'}
            </Text>
          </View>
          <View style={styles.gridCell}>
            <Text style={styles.label}>Duration</Text>
            <Text style={styles.value}>
              {mode.charAt(0).toUpperCase() + mode.slice(1)}
            </Text>
          </View>
        </View>
        <View style={styles.gridRow}>
          <View style={styles.gridCell}>
            <Text style={styles.label}>Momentum</Text>
            <Text style={styles.value}>{setup?.momentum ?? '—'}</Text>
          </View>
          <View style={styles.gridCell}>
            <Text style={styles.label}>{vehicle === 'shares' ? 'Shares' : 'Contracts'}</Text>
            <Text style={styles.value}>
              {(vehicle === 'shares' ? sh?.qty : opt?.contracts) ?? '—'}
            </Text>
          </View>
        </View>
      </View>

      {/* Spread spec — only when options vehicle */}
      {vehicle === 'options' && opt && opt.long_strike && (
        <View style={styles.specCard}>
          <Text style={styles.cardTitle}>SPREAD</Text>
          <Text style={styles.specLine}>
            {opt.long_strike} / {opt.short_strike} · {opt.width_points} wide
          </Text>
          <Text style={styles.specLine}>
            Net debit ${opt.net_debit_estimate?.toFixed(2)} ·
            Δ long {opt.long_delta?.toFixed(2)} short {opt.short_delta?.toFixed(2)}
          </Text>
          <Text style={styles.specLine}>
            Max profit ${opt.max_profit_per_spread?.toFixed(0)} ·
            Max loss ${opt.max_loss_per_spread?.toFixed(0)}
          </Text>
          <Text style={styles.specLine}>
            Breakeven {opt.breakeven?.toFixed(2)} · Expiry {opt.expiry}
          </Text>
        </View>
      )}

      {/* RETURN / RISK side-by-side cards */}
      <View style={styles.rrRow}>
        <View style={[styles.rrCard, styles.rrCardReturn]}>
          <Text style={styles.cardTitleGreen}>RETURN</Text>
          <View style={styles.rrLineRow}>
            <Text style={styles.rrLabel}>{rrView.labelEntry}</Text>
            <Text style={styles.rrValue}>{fmtMoney(rrView.entry)}</Text>
          </View>
          <View style={styles.rrLineRow}>
            <Text style={styles.rrLabel}>{rrView.labelTarget}</Text>
            <Text style={styles.rrValue}>{fmtMoney(rrView.target)}</Text>
          </View>
          <View style={styles.rrLineRow}>
            <Text style={styles.rrLabel}>Profit {rrView.labelPerUnit}</Text>
            <Text style={styles.rrValue}>{fmtMoney(rrView.profitPerUnit)}</Text>
          </View>
          <View style={styles.rrLineRow}>
            <Text style={styles.rrLabel}>Potential Profit</Text>
            <Text style={[styles.rrValue, { color: Colors.green }]}>
              {fmtMoney(rrView.potentialProfit)}
            </Text>
          </View>
        </View>
        <View style={[styles.rrCard, styles.rrCardRisk]}>
          <Text style={styles.cardTitleRed}>RISK</Text>
          <View style={styles.rrLineRow}>
            <Text style={styles.rrLabel}>{rrView.labelEntry}</Text>
            <Text style={styles.rrValue}>{fmtMoney(rrView.entry)}</Text>
          </View>
          <View style={styles.rrLineRow}>
            <Text style={styles.rrLabel}>{vehicle === 'shares' ? 'Stop Loss' : 'Breakeven'}</Text>
            <Text style={styles.rrValue}>{fmtMoney(rrView.stop)}</Text>
          </View>
          {vehicle === 'shares' && sh?.atr != null && sh?.atr_multiplier != null && (
            <Text style={styles.rrSubline}>
              ATR{sh.atr_tf ? `(${sh.atr_tf})` : ''} ${sh.atr.toFixed(2)} × {sh.atr_multiplier} = ${(sh.atr * sh.atr_multiplier).toFixed(2)}
            </Text>
          )}
          <View style={styles.rrLineRow}>
            <Text style={styles.rrLabel}>Risk {rrView.labelPerUnit}</Text>
            <Text style={styles.rrValue}>{fmtMoney(rrView.riskPerUnit)}</Text>
          </View>
          <View style={styles.rrLineRow}>
            <Text style={styles.rrLabel}>Potential Loss</Text>
            <Text style={[styles.rrValue, { color: Colors.red }]}>
              {fmtMoney(rrView.potentialLoss)}
            </Text>
          </View>
        </View>
      </View>

      {/* RETURN TO RISK RATIO card */}
      {rrView.rrRatio != null && (
        <View style={styles.rrRatioCard}>
          <Text style={styles.cardTitleCenter}>RETURN TO RISK RATIO</Text>
          <Text style={styles.rrRatioBig}>{rrView.rrRatio.toFixed(2)}</Text>
          <Text style={styles.rrRatioLabel}>REWARD : RISK</Text>
          <View style={styles.rrBarTrack}>
            <View style={[styles.rrBarReward, {
              flex: Math.max(0.001, rrView.profitPerUnit ?? 0),
            }]} />
            <View style={[styles.rrBarRisk, {
              flex: Math.max(0.001, rrView.riskPerUnit ?? 0),
            }]} />
          </View>
          <Text style={styles.rrFootnote}>
            make ${(rrView.rrRatio).toFixed(2)} for every $1.00 risked
          </Text>
        </View>
      )}

      {/* Trends — mode-aware Russian dolls */}
      {setup?.trends && (
        <View style={styles.trendsCard}>
          <Text style={styles.cardTitle}>TRENDS</Text>
          {Object.entries(setup.trends).reverse().map(([tf, dir]) => (
            <View key={tf} style={styles.trendRow}>
              <Text style={styles.trendTf}>{TF_LABELS[tf] || tf}</Text>
              <Text style={[styles.trendDir, {
                color: dir === 'UP' ? Colors.green
                  : dir === 'DOWN' ? Colors.red : Colors.textLight,
              }]}>{dir === 'UP' ? '▲ UP' : dir === 'DOWN' ? '▼ DOWN' : '— SIDE'}</Text>
            </View>
          ))}
        </View>
      )}

      {/* ADJUST placeholder (v2) */}
      <TouchableOpacity disabled style={styles.adjustButton}>
        <Text style={styles.adjustText}>ADJUST</Text>
      </TouchableOpacity>

      {/* Action buttons */}
      <View style={styles.actionRow}>
        <TouchableOpacity
          onPress={onOpenTrade}
          disabled={!tradeReady}
          style={[styles.openButton, !tradeReady && styles.buttonDisabled]}>
          <Text style={[styles.openText, !tradeReady && styles.disabledText]}>
            Open Trade
          </Text>
        </TouchableOpacity>
        <TouchableOpacity disabled style={[styles.closeButton, styles.buttonDisabled]}>
          <Text style={[styles.closeText, styles.disabledText]}>Close</Text>
        </TouchableOpacity>
      </View>

      {/* Chart header — info button explains the overlays */}
      <View style={styles.chartHeader}>
        <Text style={styles.chartTitle}>Chart</Text>
        <TouchableOpacity
          style={styles.infoBtn}
          onPress={() => Alert.alert(
            'Chart markers',
            vehicle === 'options'
              ? 'LONG (amber) — strike you BUY. Below this at expiry = max loss.\n\n' +
                'SHORT (teal) — strike you SELL. Above this at expiry = max profit.\n\n' +
                'BE (yellow dashed) — breakeven. Price needs to reach here to recover the debit.\n\n' +
                'TRIGGER (magenta dotted) — the higher-TF zone the bias is built on.\n\n' +
                'Light green — profit ramps from $0 to max as price moves from BE to SHORT.\n\n' +
                'Bright green band — max profit zone past the short strike.\n\n' +
                'Red band — max loss zone past the long strike.\n\n' +
                'The green and red bands are sized proportionally to the dollar amounts — green is taller than red by the reward:risk ratio.'
              : 'ENTRY (amber) — limit price at the HTF supply/demand zone.\n\n' +
                'TARGET (teal) — first profit target, set to the next opposite zone or per-mode R:R floor.\n\n' +
                'STOP (red) — 3× ATR beyond the entry zone.\n\n' +
                'TRIGGER (magenta dotted) — the higher-TF zone the bias is built on.\n\n' +
                'All three lines update when you switch between SCALP, INTRADAY, SWING.'
          )}
          accessibilityRole="button"
          accessibilityLabel="Chart legend">
          <Text style={styles.infoBtnText}>i</Text>
        </TouchableOpacity>
      </View>
      <View style={[styles.chartContainer, chartExpanded && styles.chartContainerTall]}>
        <WebView
          source={{ uri: chartUrl }}
          style={styles.chart}
          scalesPageToFit
          javaScriptEnabled
          onMessage={(e) => {
            // Chart legend's expand button postMessages here.
            try {
              const msg = JSON.parse(e.nativeEvent.data);
              if (msg?.type === 'chart:toggle-expand') {
                setChartExpanded(v => !v);
              }
            } catch { /* ignore non-JSON */ }
          }}
        />
      </View>

      {/* Supply & Demand Zones — graphical view under the chart */}
      <ZonesSection data={zonesData} />
    </View>
  );
}

// ─── Supply & Demand Zones component ─────────────────────────────
// Per-timeframe horizontal bar: [D2|D1|gap|S1|S2] with a yellow price
// marker positioned in the gap proportional to where price sits
// between D1 and S1. Distance chips on either side show the room to
// the nearest demand (▼) and supply (▲) zones. Mirrors the SNR Compare
// page's SRV data — same source, same numbers, visual layout.
const ZONE_TF_ORDER = ['M', 'W', 'D', '4H', '1H', '30M', '15M'];
const ZONE_TF_LABELS: Record<string, string> = {
  M: '1mo', W: '1w', D: '1d', '4H': '4h', '1H': '1h', '30M': '30m', '15M': '15m',
};

function ZonesSection({ data }: { data: any }) {
  if (!data?.current_price) {
    return (
      <View style={styles.zonesCard}>
        <Text style={styles.zonesTitle}>SUPPLY &amp; DEMAND ZONES</Text>
        <Text style={styles.zonesEmpty}>Loading…</Text>
      </View>
    );
  }
  const price: number = data.current_price;
  const server = data.server || {};
  return (
    <View style={styles.zonesCard}>
      <View style={styles.zonesHeaderRow}>
        <Text style={styles.zonesTitle}>SUPPLY &amp; DEMAND ZONES</Text>
        <Text style={styles.zonesNow}>now <Text style={styles.zonesNowVal}>{price.toFixed(2)}</Text></Text>
      </View>
      <Text style={styles.zonesSub}>
        Nearest untouched demand (low) and supply (high) per timeframe —
        the same levels the chart enters on. Near 100% = pressing supply,
        near 0% = sitting on demand. Italic value = no untouched level
        in window (at extreme); falls back to 12-bar range edge.
      </Text>
      {ZONE_TF_ORDER.map(tf => (
        <ZonesRow key={tf} tfKey={tf} levels={server[tf] || {}} price={price} />
      ))}
      <Text style={styles.zonesLegendText}>
        <Text style={styles.zPctHi}>green</Text>
        <Text style={styles.zonesLegendDim}> near highs · </Text>
        <Text style={styles.zPctLo}>red</Text>
        <Text style={styles.zonesLegendDim}> near lows — strong on big timeframes,
          cooling on short ones</Text>
      </Text>
    </View>
  );
}

function ZonesRow({ tfKey, levels, price }: { tfKey: string; levels: any; price: number }) {
  // D1/S1 are the analyzer's untouched levels. When a TF is at ATH
  // (very common for SPX-style indexes in an uptrend) supply is null
  // because no prior bar's high pierces the in-progress high. Same on
  // the other side for ATL. Fall back to the 12-bar literal range
  // extreme so the bar pegs at 100% / 0% instead of going blank.
  const loRaw = levels.demand;
  const hiRaw = levels.supply;
  const lo = loRaw ?? levels.range_low;
  const hi = hiRaw ?? levels.range_high;
  const loIsFallback = loRaw == null && lo != null;
  const hiIsFallback = hiRaw == null && hi != null;
  const hasRange = lo != null && hi != null && hi > lo;

  // % position within the high–low range.
  // Clamped so an out-of-range price still shows at 0/100.
  let pct = 50;
  if (hasRange) {
    const raw = ((price - lo) / (hi - lo)) * 100;
    pct = Math.max(0, Math.min(100, raw));
  }

  // Color tier — near highs = green, near lows = red, middle = amber.
  const tier = pct >= 70 ? 'hi' : pct <= 30 ? 'lo' : 'mid';
  const fillStyle =
    tier === 'hi' ? styles.zFillHi
      : tier === 'lo' ? styles.zFillLo
      : styles.zFillMid;
  const dotStyle =
    tier === 'hi' ? styles.zDotHi
      : tier === 'lo' ? styles.zDotLo
      : styles.zDotMid;
  const pctStyle =
    tier === 'hi' ? styles.zPctHi
      : tier === 'lo' ? styles.zPctLo
      : styles.zPctMid;

  return (
    <View style={styles.zRow}>
      <Text style={styles.zLabel}>{ZONE_TF_LABELS[tfKey] || tfKey}</Text>
      <Text style={[styles.zLoVal, loIsFallback && styles.zValFallback]}>
        {lo != null ? lo.toFixed(2) : '—'}
      </Text>

      <View style={styles.zBar}>
        {hasRange && (
          <View style={[styles.zFill, fillStyle, { width: `${pct}%` }]} />
        )}
        {hasRange && (
          <View style={[styles.zDot, dotStyle, { left: `${pct}%` }]} />
        )}
      </View>

      <Text style={[styles.zHiVal, hiIsFallback && styles.zValFallback]}>
        {hi != null ? hi.toFixed(2) : '—'}
      </Text>
      <Text style={[styles.zPct, pctStyle]}>
        {hasRange ? `${pct.toFixed(0)}%` : '—'}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  section: { marginHorizontal: 12, marginTop: 20 },
  sectionTitle: { fontSize: 16, fontWeight: '500', color: Colors.dark, marginBottom: 12 },
  chipScrollRow: { flexDirection: 'row', gap: 6, paddingVertical: 2,
                   paddingRight: 12 },
  pickerLabel: { fontSize: 11, fontWeight: '500', color: Colors.textLight,
                 letterSpacing: 0.6, marginTop: 6, marginBottom: 4 },
  chip: { paddingVertical: 6, paddingHorizontal: 12, borderRadius: 12,
          backgroundColor: Colors.cream, borderWidth: 1, borderColor: Colors.cream },
  chipActive: { backgroundColor: Colors.olive, borderColor: Colors.olive },
  chipText: { fontSize: 13, fontWeight: '500', color: Colors.textLight },
  chipTextActive: { color: Colors.gold },
  searchRow: { flexDirection: 'row', gap: 8, alignItems: 'center', marginBottom: 4 },
  searchInput: { flex: 1, paddingVertical: 8, paddingHorizontal: 12, borderRadius: 10,
                 borderWidth: 1, borderColor: Colors.cream, backgroundColor: Colors.white,
                 fontSize: 14, color: Colors.dark },
  addBtn: { paddingVertical: 9, paddingHorizontal: 18, borderRadius: 10,
            backgroundColor: Colors.olive },
  addBtnDisabled: { opacity: 0.4 },
  addBtnText: { color: Colors.gold, fontWeight: '600', fontSize: 13 },
  noMatch: { fontSize: 12, color: Colors.textLight, marginTop: 6, fontStyle: 'italic' },
  segmented: { flexDirection: 'row', backgroundColor: Colors.cream, borderRadius: 10,
               padding: 3, marginBottom: 10 },
  segment: { flex: 1, paddingVertical: 8, borderRadius: 8, alignItems: 'center' },
  segmentActive: { backgroundColor: Colors.olive },
  segmentText: { fontSize: 13, fontWeight: '500', color: Colors.textLight, letterSpacing: 0.5 },
  segmentTextActive: { color: Colors.gold },
  tfRow: { flexDirection: 'row', justifyContent: 'space-around', marginBottom: 12 },
  tfCircle: { width: 64, height: 64, borderRadius: 32, borderWidth: 1,
              borderColor: Colors.olive, alignItems: 'center', justifyContent: 'center' },
  tfCircleActive: { backgroundColor: Colors.olive },
  tfText: { fontSize: 12, fontWeight: '500', color: Colors.olive },
  tfTextActive: { color: Colors.gold },
  errorText: { color: Colors.red, fontSize: 12, marginVertical: 8 },
  banner: { padding: 10, marginBottom: 10, borderLeftWidth: 4, backgroundColor: Colors.white,
            borderRadius: 6 },
  bannerTitle: { fontSize: 11, fontWeight: '600', letterSpacing: 0.5, color: Colors.dark },
  bannerBody: { fontSize: 13, color: Colors.dark, marginTop: 2 },
  headerCard: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-end',
                backgroundColor: Colors.white, borderRadius: 12, padding: 16, marginBottom: 10 },
  symbolText: { fontSize: 28, fontWeight: '300', color: Colors.dark },
  dirBadge: { fontSize: 12, fontWeight: '600', marginTop: 2 },
  bigValue: { fontSize: 22, fontWeight: '300', color: Colors.dark, marginTop: 2 },
  riskInputRow: { flexDirection: 'row', alignItems: 'baseline', marginTop: 2 },
  riskDollar: { fontSize: 22, fontWeight: '300', color: Colors.dark, marginRight: 1 },
  riskInput: { fontSize: 22, fontWeight: '300', color: Colors.dark,
               minWidth: 70, paddingVertical: 0, paddingHorizontal: 4,
               textAlign: 'right',
               borderBottomWidth: 1, borderBottomColor: Colors.cream },
  paramCard: { backgroundColor: Colors.white, borderRadius: 12, padding: 12, marginBottom: 10 },
  cardTitle: { fontSize: 10, fontWeight: '600', letterSpacing: 0.5, color: Colors.textLight,
               marginBottom: 8 },
  label: { fontSize: 10, fontWeight: '500', letterSpacing: 0.5, color: Colors.textLight,
           textTransform: 'uppercase' },
  value: { fontSize: 18, fontWeight: '500', color: Colors.dark, marginTop: 2 },
  gridRow: { flexDirection: 'row' },
  gridCell: { flex: 1, paddingVertical: 8 },
  specCard: { backgroundColor: Colors.cream, borderRadius: 12, padding: 12, marginBottom: 10 },
  specLine: { fontSize: 12, color: Colors.dark, marginVertical: 1 },
  trendsCard: { backgroundColor: Colors.white, borderRadius: 12, padding: 12, marginBottom: 10 },
  trendRow: { flexDirection: 'row', justifyContent: 'space-between', paddingVertical: 4 },
  trendTf: { fontSize: 12, fontWeight: '500', color: Colors.textLight },
  trendDir: { fontSize: 12, fontWeight: '600' },
  adjustButton: { backgroundColor: Colors.cream, padding: 12, borderRadius: 10,
                  alignItems: 'center', marginBottom: 10, opacity: 0.5 },
  adjustText: { fontSize: 12, fontWeight: '600', color: Colors.textLight, letterSpacing: 0.5 },
  actionRow: { flexDirection: 'row', gap: 8, marginBottom: 12 },
  openButton: { flex: 1, backgroundColor: Colors.olive, padding: 14, borderRadius: 10,
                alignItems: 'center' },
  openText: { fontSize: 14, fontWeight: '600', color: Colors.gold },
  closeButton: { flex: 1, backgroundColor: Colors.cream, padding: 14, borderRadius: 10,
                 alignItems: 'center' },
  closeText: { fontSize: 14, fontWeight: '600', color: Colors.textLight },
  buttonDisabled: { opacity: 0.4 },
  disabledText: {},
  chartHeader: { flexDirection: 'row', alignItems: 'center',
                 justifyContent: 'space-between', marginBottom: 6,
                 marginTop: 4, paddingHorizontal: 2 },
  chartTitle: { fontSize: 14, fontWeight: '500', color: Colors.textLight,
                letterSpacing: 0.5, textTransform: 'uppercase' },
  infoBtn: { width: 22, height: 22, borderRadius: 11,
             backgroundColor: Colors.cream, alignItems: 'center',
             justifyContent: 'center', borderWidth: 1,
             borderColor: Colors.textLight },
  infoBtnText: { fontSize: 12, fontWeight: '600',
                 color: Colors.textLight, fontStyle: 'italic',
                 fontFamily: 'serif' },
  chartContainer: { height: 400, borderRadius: 12, overflow: 'hidden',
                    backgroundColor: Colors.white },
  chartContainerTall: { height: 700 },   // toggled by chart legend expand
  chart: { flex: 1 },

  // Supply & Demand Zones
  zonesCard: { marginTop: 14, padding: 12, backgroundColor: '#fbf8ef',
               borderColor: '#ede5cf', borderWidth: 1, borderRadius: 8 },
  zonesHeaderRow: { flexDirection: 'row', justifyContent: 'space-between',
                    alignItems: 'baseline' },
  zonesTitle: { fontSize: 11, fontWeight: '600', letterSpacing: 0.5,
                color: Colors.textLight },
  zonesNow: { fontSize: 12, color: Colors.textLight },
  zonesNowVal: { color: Colors.dark, fontWeight: '600' },
  zonesSub: { fontSize: 10, color: Colors.textLight, marginTop: 4,
              marginBottom: 10, lineHeight: 14 },
  zonesEmpty: { fontSize: 11, color: Colors.textLight, marginTop: 8,
                fontStyle: 'italic' },
  // Range-position bar: [label] [low] [bar] [high] [%]
  zRow: { flexDirection: 'row', alignItems: 'center', marginBottom: 8, gap: 8 },
  zLabel: { width: 32, fontSize: 12, fontWeight: '600', color: Colors.dark },
  zLoVal: { width: 60, fontSize: 11, color: Colors.textLight, textAlign: 'right' },
  zHiVal: { width: 60, fontSize: 11, color: Colors.textLight, textAlign: 'left' },
  zValFallback: { fontStyle: 'italic', opacity: 0.7 },
  zBar: { flex: 1, height: 6, backgroundColor: '#e8e3d3',
          borderRadius: 3, position: 'relative', overflow: 'visible' },
  zFill: { position: 'absolute', left: 0, top: 0, bottom: 0,
           borderRadius: 3 },
  zDot: { position: 'absolute', top: -4, width: 14, height: 14,
          borderRadius: 7, transform: [{ translateX: -7 }],
          borderWidth: 1.5, borderColor: '#fbf8ef' },
  // Lumitrade palette — muted sage / mustard / dusty coral. Keeps the
  // green/red color logic readable while sitting harmoniously on the
  // vanilla card background.
  zFillHi:  { backgroundColor: '#87b287' },   // sage
  zFillMid: { backgroundColor: '#c5a347' },   // mustard gold
  zFillLo:  { backgroundColor: '#ce9590' },   // dusty coral
  zDotHi:   { backgroundColor: '#5a8a5a' },
  zDotMid:  { backgroundColor: '#9c803a' },
  zDotLo:   { backgroundColor: '#b87870' },
  zPct: { width: 42, fontSize: 12, fontWeight: '600', textAlign: 'right' },
  zPctHi:  { color: '#5a8a5a' },
  zPctMid: { color: '#9c803a' },
  zPctLo:  { color: '#b87870' },
  zonesLegendText: { marginTop: 10, paddingTop: 8, borderTopWidth: 1,
                     borderTopColor: '#e8e3d3', fontSize: 10,
                     textAlign: 'center', lineHeight: 14 },
  zonesLegendDim: { color: Colors.textLight, fontWeight: '400' },
  vehicleRow: { flexDirection: 'row', gap: 6, marginBottom: 10 },
  vehicleChip: { flex: 1, paddingVertical: 8, borderRadius: 12,
                 backgroundColor: Colors.cream, alignItems: 'center',
                 borderWidth: 1, borderColor: Colors.cream },
  vehicleChipActive: { backgroundColor: Colors.olive, borderColor: Colors.olive },
  vehicleText: { fontSize: 13, fontWeight: '500', color: Colors.textLight },
  vehicleTextActive: { color: Colors.gold },
  rrRow: { flexDirection: 'row', gap: 8, marginBottom: 10 },
  rrCard: { flex: 1, backgroundColor: Colors.white, borderRadius: 12,
            padding: 12, borderTopWidth: 3 },
  rrCardReturn: { borderTopColor: Colors.green },
  rrCardRisk: { borderTopColor: Colors.red },
  cardTitleGreen: { fontSize: 10, fontWeight: '600', letterSpacing: 0.5,
                    color: Colors.green, marginBottom: 8 },
  cardTitleRed: { fontSize: 10, fontWeight: '600', letterSpacing: 0.5,
                  color: Colors.red, marginBottom: 8 },
  cardTitleCenter: { fontSize: 10, fontWeight: '600', letterSpacing: 0.5,
                     color: Colors.textLight, marginBottom: 8,
                     textAlign: 'center' },
  rrLineRow: { flexDirection: 'row', justifyContent: 'space-between',
               paddingVertical: 3 },
  rrLabel: { fontSize: 11, color: Colors.textLight, flexShrink: 1 },
  rrValue: { fontSize: 12, fontWeight: '600', color: Colors.dark },
  rrSubline: { fontSize: 10, color: Colors.textLight, marginTop: -2,
               marginBottom: 4, fontStyle: 'italic' },
  rrRatioCard: { backgroundColor: Colors.white, borderRadius: 12,
                 padding: 16, marginBottom: 10, alignItems: 'center' },
  rrRatioBig: { fontSize: 36, fontWeight: '300', color: Colors.dark,
                marginVertical: 4 },
  rrRatioLabel: { fontSize: 10, fontWeight: '500', letterSpacing: 1,
                  color: Colors.textLight, marginBottom: 8 },
  rrBarTrack: { flexDirection: 'row', width: '100%', height: 10,
                borderRadius: 5, overflow: 'hidden', marginBottom: 6 },
  rrBarReward: { backgroundColor: Colors.green },
  rrBarRisk: { backgroundColor: Colors.red },
  rrFootnote: { fontSize: 11, color: Colors.textLight },
});
