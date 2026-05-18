import { useLocalSearchParams, useRouter } from 'expo-router';
import { useEffect, useState } from 'react';
import { View, Text, TouchableOpacity, StyleSheet, Linking, ActivityIndicator } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { WebView } from 'react-native-webview';
import { Colors } from '@/constants/theme';

const API_BASE = 'https://bot.lumitrade.ai';

// Trend arrows next to the ticker — same look as positions/watchlist.
// Direction comes from /api/adx/direction (Oanda candles + Wilder DMI).
// TFs vary by strategy/model to match the signal cadence the trade cares about:
//   tidewater scalp     → 5m / 15m / 1h      (5m trigger, 1H zones, 15m bias)
//   tidewater intraday  → 15m / 1h / 1d      (15m trigger, 1D zones, 1H bias)
//   tidewater weekly    → 1d / 1w / 1mo      (1D trigger, 1mo zones, 1W bias)
//   fx_4h               → 4h / 1d / 1w       (Stillwater 4H trend)
//   default             → 5m / 15m / 1h
function trendTfsFor(strategy: string | undefined, model?: string): string[] {
  const s = (strategy || '').toLowerCase();
  const m = (model || '').toLowerCase();
  // Tidewater — anchor by model since strategy is just "htf_levels"
  if (s === 'htf_levels' || s === 'htf_supply_demand') {
    if (m === 'swing') return ['1d', '1w', '1mo'];
    if (m === 'intraday') return ['15m', '1h', '1d'];
    return ['5m', '15m', '1h'];   // scalp / default
  }
  if (s.includes('swing')) return ['1d', '1w', '1mo'];
  if (s.includes('intraday')) return ['15m', '1h', '1d'];
  if (s.includes('fx_4h') || s.includes('stillwater')) return ['4h', '1d', '1w'];
  // scalp / h1_zone / 2n20 / default → 5m / 15m / 1h
  return ['5m', '15m', '1h'];
}

// Pretty TF label for the parenthetical next to the strategy name.
// "5m, 15m, 1H" not "5M, 15M, 1H".
function prettyTf(tf: string): string {
  if (tf === '1h') return '1H';
  if (tf === '4h') return '4H';
  if (tf === '1d') return '1D';
  if (tf === '1w') return '1W';
  if (tf === '1mo') return '1M';
  return tf;
}
function arrowFor(dir: string): string {
  return dir === 'UP' ? '↑' : dir === 'DOWN' ? '↓' : '→';
}
function colorFor(dir: string): string {
  return dir === 'UP' ? '#3E7F6B' : dir === 'DOWN' ? '#C26A6A' : '#888';
}

const TV_SYMBOLS: Record<string, string> = {
  'EUR_USD': 'OANDA:EURUSD',
  'USD_JPY': 'OANDA:USDJPY',
  'GBP_USD': 'OANDA:GBPUSD',
  'MES': 'CME_MINI:MES1!',
  'ES': 'CME_MINI:ES1!',
  'SPY': 'AMEX:SPY',
  'QQQ': 'NASDAQ:QQQ',
  'GOLD': 'OANDA:XAUUSD',
  'OIL': 'OANDA:WTICOUSD',
  'I:SPX': 'SP:SPX',
};

function getTvUrl(instrument: string): string {
  const sym = TV_SYMBOLS[instrument] || instrument;
  return `https://www.tradingview.com/chart/?symbol=${encodeURIComponent(sym)}`;
}

export default function ChartScreen() {
  const { symbol, interval, entry, exit, direction, stop, units, strategy, model } = useLocalSearchParams<{
    symbol: string; interval?: string; entry?: string; exit?: string; direction?: string; stop?: string; units?: string; strategy?: string; model?: string;
  }>();
  const router = useRouter();
  const tf = interval || '15m';
  const ticker = symbol || 'EUR_USD';

  // Pretty strategy label for the header. Tidewater carries the duration
  // in the `model` field (scalp / intraday / swing) so the chart can name
  // which variant fired — without it the label is just "TIDEWATER" and you
  // can't tell whether the trade was triggered by a 5m candle at a 1H zone
  // (Scalp) or a 1D candle at a 1mo zone (Swing).
  const TIDEWATER_DURATION_NAME: Record<string, string> = {
    scalp: 'Scalp',
    intraday: 'Intraday',
    swing: 'Swing',
  };
  const STRATEGY_LABELS: Record<string, string> = {
    '2n20': '2N20',
    'vwap_2n20': '2N20',
    '2n20_exit': '2N20',
    'orb_breakout': 'ORB',
    'orb_butterfly': 'ORB BFLY',
  };
  // H1 Zone Scalp variants: model field carries alpha/beta, tag the
  // chart label so user can tell which direction-gate is active.
  const H1Z_VARIANT_NAME: Record<string, string> = {
    alpha: 'α',
    beta: 'β',
  };
  const isTidewater = strategy === 'htf_levels' || strategy === 'htf_supply_demand';
  const isH1ZoneStrat = strategy === 'scalp_h1zone' || (strategy || '').startsWith('scalp_h1zone');
  let stratLabel: string | null = null;
  if (isTidewater) {
    const duration = TIDEWATER_DURATION_NAME[(model || '').toLowerCase()] || '';
    stratLabel = duration ? `Tidewater ${duration}` : 'Tidewater';
  } else if (isH1ZoneStrat) {
    const variant = H1Z_VARIANT_NAME[(model || '').toLowerCase()] || '';
    stratLabel = variant ? `H1 Zone Scalp ${variant}` : 'H1 Zone Scalp';
  } else if (strategy) {
    stratLabel = STRATEGY_LABELS[strategy] || strategy.toUpperCase().replace('_', ' ');
  }

  // Fetch ADX direction per TF for the header arrows. TFs depend on the
  // strategy/model: tidewater-scalp 5m/15m/1h, intraday 15m/1h/1d, weekly 1d/1w/1mo.
  const headerTfs = trendTfsFor(strategy, model);
  // "Tidewater Scalp (5m, 15m, 1H)" — the parenthetical is the TF cluster
  // we render arrows for, so the strategy name reads naturally.
  if (stratLabel && isTidewater) {
    stratLabel = `${stratLabel} (${headerTfs.map(prettyTf).join(', ')})`;
  }
  const [trends, setTrends] = useState<Record<string, string>>({});
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await fetch(
          `${API_BASE}/api/adx/direction?pair=${encodeURIComponent(ticker)}&tfs=${headerTfs.join(',')}`
        );
        const d = await r.json();
        if (!cancelled && d && d.tfs) setTrends(d.tfs);
      } catch {
        // silent — header arrows are decorative
      }
    })();
    return () => { cancelled = true; };
  }, [ticker, strategy]);

  // Build chart URL with optional trade lines
  let chartUrl = `${API_BASE}/chart?ticker=${encodeURIComponent(ticker)}&timespan=${tf}&count=300`;
  if (entry) chartUrl += `&entry=${entry}`;
  if (exit) chartUrl += `&exit=${exit}`;
  if (direction) chartUrl += `&direction=${direction}`;
  if (stop) chartUrl += `&stop=${stop}`;
  if (units) chartUrl += `&units=${units}`;
  if (strategy) chartUrl += `&strategy=${strategy}`;

  const timespans = ticker === 'MES' || ticker === 'ES'
    ? [
        { key: '2m', label: '2m' },
        { key: '5m', label: '5m' },
        { key: '15m', label: '15m' },
        { key: '1h', label: '1H' },
        { key: '4h', label: '4H' },
        { key: '1d', label: '1D' },
        { key: '1w', label: '1W' },
        { key: '1mo', label: '1M' },
      ]
    : [
        { key: '2m', label: '2m' },
        { key: '5m', label: '5m' },
        { key: '15m', label: '15m' },
        { key: '1h', label: '1H' },
        { key: '4h', label: '4H' },
        { key: '1d', label: '1D' },
        { key: '1w', label: '1W' },
        { key: '1mo', label: '1M' },
      ];

  return (
    <SafeAreaView style={styles.container}>
      {/* Top row: Back / ticker + strategy / TV link */}
      <View style={styles.headerTop}>
        <TouchableOpacity onPress={() => router.back()} style={styles.backBtn}>
          <Text style={styles.backText}>Back</Text>
        </TouchableOpacity>
        <View style={styles.titleBlock}>
          <View style={styles.titleRow}>
            <Text style={styles.title} numberOfLines={1}>{ticker}</Text>
            {Object.keys(trends).length > 0 && (
              <View style={styles.trendRow}>
                {headerTfs.map(tf => {
                  const dir = trends[tf];
                  if (!dir) return null;
                  return (
                    <Text key={tf} style={[styles.trendBadge, { color: colorFor(dir) }]}>
                      {tf.toUpperCase()}{arrowFor(dir)}
                    </Text>
                  );
                })}
              </View>
            )}
          </View>
          {stratLabel && (
            <Text style={styles.subtitle} numberOfLines={1}>{stratLabel}</Text>
          )}
        </View>
        <TouchableOpacity onPress={() => Linking.openURL(getTvUrl(ticker))} style={styles.tvBtn}>
          <Text style={styles.tvBtnText}>TV</Text>
        </TouchableOpacity>
      </View>
      {/* Second row: timeframes (full row, room for 1W / 1M) */}
      <View style={styles.tfRow}>
        {timespans.map(t => (
          <TouchableOpacity
            key={t.key}
            style={[styles.tfBtn, tf === t.key && styles.tfBtnActive]}
            onPress={() => router.setParams({ interval: t.key })}
          >
            <Text style={[styles.tfText, tf === t.key && styles.tfTextActive]}>
              {t.label}
            </Text>
          </TouchableOpacity>
        ))}
      </View>
      <WebView
        key={`${ticker}-${tf}`}
        source={{ uri: chartUrl }}
        style={styles.webview}
        javaScriptEnabled
        domStorageEnabled
        startInLoadingState
        renderLoading={() => <ActivityIndicator style={{ flex: 1, backgroundColor: '#1a1a2e' }} color={Colors.olive} />}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#1a1a2e' },
  headerTop: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 20,
    paddingTop: 56,
    paddingBottom: 6,
    backgroundColor: '#1a1a2e',
    gap: 10,
  },
  backBtn: {
    paddingVertical: 6,
    paddingHorizontal: 12,
    borderRadius: 8,
    backgroundColor: '#333',
  },
  backText: { color: '#ccc', fontSize: 14 },
  // Title block stacks ticker (+ trend arrows) on top, strategy label underneath
  titleBlock: { flex: 1 },
  titleRow: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  title: { color: '#fff', fontSize: 18, fontWeight: '600' },
  trendRow: { flexDirection: 'row', gap: 6, alignItems: 'center' },
  trendBadge: { fontSize: 12, fontWeight: '700' },
  subtitle: { color: Colors.gold, fontSize: 11, fontWeight: '600', marginTop: 2, letterSpacing: 0.5 },
  tvBtn: {
    paddingVertical: 6,
    paddingHorizontal: 10,
    borderRadius: 6,
    backgroundColor: '#1d4ed8',
  },
  tvBtnText: { color: '#fff', fontSize: 12, fontWeight: '700' },
  // Timeframe row sits below the ticker so all 8 chips fit without
  // cramping the ticker. Equal flex on each chip so they distribute
  // evenly across the screen width.
  tfRow: {
    flexDirection: 'row',
    gap: 4,
    paddingHorizontal: 12,
    paddingBottom: 10,
    backgroundColor: '#1a1a2e',
  },
  tfBtn: {
    flex: 1,
    paddingVertical: 6,
    paddingHorizontal: 4,
    borderRadius: 6,
    backgroundColor: '#333',
    alignItems: 'center',
  },
  tfBtnActive: { backgroundColor: Colors.olive },
  tfText: { color: '#999', fontSize: 12, fontWeight: '500' },
  tfTextActive: { color: Colors.gold },
  webview: { flex: 1 },
});
