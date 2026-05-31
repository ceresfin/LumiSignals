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
  ActivityIndicator, Alert, StyleSheet, Text, TouchableOpacity, View,
} from 'react-native';
import { WebView } from 'react-native-webview';

import { Colors } from '@/constants/theme';

const SUPPORTED_TICKERS = ['SPY', 'QQQ', 'IWM', 'SPX', 'NDX'] as const;
const MODES = ['scalp', 'intraday', 'swing'] as const;
const TF_LABELS: Record<string, string> = {
  '5m': '5M', '15m': '15M', '1h': '1H',
  '1d': 'Daily', '1w': 'Weekly', '1mo': 'Monthly',
};
// Chart timeframe options per mode — mirrors the analyzer's Russian-
// doll TF stack so the chart matches the trade horizon. Default is the
// middle TF (the "main" timeframe for the mode).
const MODE_TIMEFRAMES: Record<string, string[]> = {
  scalp:    ['5m',  '15m', '1h'],
  intraday: ['15m', '1h',  '1d'],
  swing:    ['1d',  '1w',  '1mo'],
};
const DEFAULT_CHART_TF: Record<string, string> = {
  scalp: '15m', intraday: '1h', swing: '1w',
};

const API_BASE = 'https://bot.lumitrade.ai';
const SYNC_KEY = process.env.EXPO_PUBLIC_LUMI_SYNC_KEY ?? '';
const ENABLED = process.env.EXPO_PUBLIC_SWING_PANEL_ENABLED === '1';

type Setup = {
  ticker: string;
  mode: string;
  direction: 'BUY' | 'SELL' | null;
  skip_reason: string | null;
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
  warnings: string[];
  chart_overlay?: Record<string, number | null>;
};

export function SwingTradePanel() {
  if (!ENABLED) return null;

  const [ticker, setTicker] = useState<typeof SUPPORTED_TICKERS[number]>('SPX');
  const [mode, setMode] = useState<typeof MODES[number]>('swing');
  const [chartTf, setChartTf] = useState<string>('1w');
  const [setup, setSetup] = useState<Setup | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Auto-select default chart TF when mode changes
  useEffect(() => {
    setChartTf(DEFAULT_CHART_TF[mode]);
  }, [mode]);

  // Refetch on ticker/mode change
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetch(`${API_BASE}/api/swing-setup?ticker=${ticker}&mode=${mode}`)
      .then((r) => r.json())
      .then((data) => { if (!cancelled) setSetup(data as Setup); })
      .catch((e) => { if (!cancelled) setError(String(e)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [ticker, mode]);

  const chartUrl = useMemo(() => {
    const params: string[] = [
      `ticker=${encodeURIComponent(ticker)}`,
      `timespan=${chartTf}`, `count=200`, `strategy=swing_setup`,
    ];
    const overlay = setup?.chart_overlay;
    if (overlay?.long_strike) params.push(`entry=${overlay.long_strike}`);
    if (overlay?.short_strike) params.push(`exit=${overlay.short_strike}`);
    if (overlay?.trigger_level) params.push(`stop=${overlay.trigger_level}`);
    if (setup?.direction) params.push(`direction=${setup.direction}`);
    return `${API_BASE}/chart?${params.join('&')}`;
  }, [ticker, chartTf, setup]);

  const opt = setup?.options;
  const tradeReady = setup?.direction != null && (opt?.contracts ?? 0) > 0;
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

  return (
    <View style={styles.section}>
      <Text style={styles.sectionTitle}>Swing Trade Setup</Text>

      {/* Symbol picker (curated chip row) */}
      <View style={styles.chipRow}>
        {SUPPORTED_TICKERS.map((t) => (
          <TouchableOpacity key={t}
            onPress={() => setTicker(t)}
            style={[styles.chip, ticker === t && styles.chipActive]}>
            <Text style={[styles.chipText, ticker === t && styles.chipTextActive]}>{t}</Text>
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
          <Text style={styles.bigValue}>
            ${opt?.max_loss_per_spread ? Math.round(opt.max_loss_per_spread) : '—'}
          </Text>
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
            <Text style={styles.label}>Contracts</Text>
            <Text style={styles.value}>{opt?.contracts ?? '—'}</Text>
          </View>
        </View>
      </View>

      {/* Spread spec — only when options vehicle */}
      {opt && opt.long_strike && (
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

      {/* Chart */}
      <View style={styles.chartContainer}>
        <WebView
          source={{ uri: chartUrl }}
          style={styles.chart}
          scalesPageToFit
          javaScriptEnabled
        />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  section: { marginHorizontal: 12, marginTop: 20 },
  sectionTitle: { fontSize: 16, fontWeight: '500', color: Colors.dark, marginBottom: 12 },
  chipRow: { flexDirection: 'row', gap: 6, marginBottom: 10 },
  chip: { paddingVertical: 6, paddingHorizontal: 12, borderRadius: 12,
          backgroundColor: Colors.cream, borderWidth: 1, borderColor: Colors.cream },
  chipActive: { backgroundColor: Colors.olive, borderColor: Colors.olive },
  chipText: { fontSize: 13, fontWeight: '500', color: Colors.textLight },
  chipTextActive: { color: Colors.gold },
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
  chartContainer: { height: 400, borderRadius: 12, overflow: 'hidden',
                    backgroundColor: Colors.white },
  chart: { flex: 1 },
});
