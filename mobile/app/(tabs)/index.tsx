import { useEffect, useMemo, useState } from 'react';
import { View, Text, ScrollView, StyleSheet, RefreshControl, TouchableOpacity } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { WebView } from 'react-native-webview';
import { useRouter } from 'expo-router';
import { supabase } from '@/lib/supabase';
import { useAuth } from '@/contexts/auth';
import { Colors } from '@/constants/theme';

type Trade = {
  realized_pl: number | null;
  pips: number;
  won: boolean | null;
  strategy: string;
  model: string;
  broker: string;
  asset_type: string;
  instrument: string;
  opened_at: string | null;
};

type Position = {
  strategy: string;
  asset_type: string;
  instrument: string;
  broker: string;
  model?: string;
  // Trade-level fields used by the intraday HTF chart picker.
  broker_trade_id?: string;
  direction?: string;
  entry_price?: number;
  stop_loss?: number;
  take_profit?: number;
  opened_at?: string;
};

type BrokerStats = {
  totalTrades: number;
  wins: number;
  losses: number;
  winRate: number;
  totalPl: number;
  totalPips: number;
};

type ModelKey = 'scalp' | 'intraday' | 'swing';

type ModelStats = {
  open: number;
  closed: number;
  wins: number;
  losses: number;
  winRate: number;
  realizedPl: number;
  avgWin: number;
  avgLoss: number;
};

type StrategyStats = {
  key: string;
  name: string;
  totalTrades: number;
  dateRange: string;
  byModel: Record<ModelKey, ModelStats>;
};

type PairStats = {
  instrument: string;
  trades: number;
  wins: number;
  losses: number;
  winRate: number;
  pl: number;
  pips: number;
};

function emptyStats(): BrokerStats {
  return { totalTrades: 0, wins: 0, losses: 0, winRate: 0, totalPl: 0, totalPips: 0 };
}

function calcStats(trades: Trade[]): BrokerStats {
  const closed = trades.filter(t => t.realized_pl !== null && t.realized_pl !== undefined);
  if (!closed.length) return emptyStats();
  const wins = closed.filter(t => (t.realized_pl || 0) > 0).length;
  const totalPl = closed.reduce((s, t) => s + (t.realized_pl || 0), 0);
  const totalPips = closed.reduce((s, t) => s + (t.pips || 0), 0);
  return {
    totalTrades: closed.length,
    wins,
    losses: closed.length - wins,
    winRate: Math.round((wins / closed.length) * 100),
    totalPl: Math.round(totalPl * 100) / 100,
    totalPips: Math.round(totalPips * 10) / 10,
  };
}

function emptyModelStats(): ModelStats {
  return { open: 0, closed: 0, wins: 0, losses: 0, winRate: 0, realizedPl: 0, avgWin: 0, avgLoss: 0 };
}

function modelKey(raw: string): ModelKey {
  const m = (raw || '').toLowerCase();
  if (m.includes('scalp')) return 'scalp';
  if (m.includes('intraday')) return 'intraday';
  if (m.includes('swing')) return 'swing';
  return 'scalp'; // sensible default
}

// Build the subtitle label from the SELECTED date range, not the
// min/max of trade timestamps. That way "Today" always says "Today",
// "MTD" always says "MTD: May 1 — May 12", etc.
function rangeLabel(range: 'today'|'wtd'|'mtd'|'qtd'|'ytd'|'all'): string {
  const fmt = (d: Date) => d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  if (range === 'today') return `Today (${fmt(today)})`;
  if (range === 'all')   return 'All time';
  const labelMap: Record<typeof range, string> = {
    today: 'Today', wtd: 'WTD', mtd: 'MTD', qtd: 'QTD', ytd: 'YTD', all: 'All',
  };
  const start = new Date(today);
  if (range === 'wtd') {
    const day = today.getDay();
    const back = day === 0 ? 6 : day - 1;
    start.setDate(today.getDate() - back);
  } else if (range === 'mtd') {
    start.setDate(1);
  } else if (range === 'qtd') {
    start.setMonth(Math.floor(today.getMonth() / 3) * 3, 1);
  } else if (range === 'ytd') {
    start.setMonth(0, 1);
  }
  return `${labelMap[range]}: ${fmt(start)} — ${fmt(today)}`;
}

function calcStrategiesByModel(trades: Trade[], positions: Position[],
                                 dateRange?: 'today'|'wtd'|'mtd'|'qtd'|'ytd'|'all'): StrategyStats[] {
  const map: Record<string, StrategyStats> = {};

  // Closed trade aggregation — won/lost determined by realized_pl > 0 (matches website)
  trades.forEach(t => {
    const sid = strategyKey(t.strategy || '');
    if (!map[sid]) {
      map[sid] = {
        key: sid,
        name: STRATEGY_NAMES[sid] || normalizeStrategy(t.strategy || ''),
        totalTrades: 0,
        dateRange: '',
        byModel: { scalp: emptyModelStats(), intraday: emptyModelStats(), swing: emptyModelStats() },
      };
    }
    map[sid].totalTrades++;

    const isClosed = t.realized_pl !== null && t.realized_pl !== undefined;
    if (!isClosed) return;

    const mk = modelKey(t.model);
    const ms = map[sid].byModel[mk];
    const pl = t.realized_pl || 0;
    ms.closed++;
    ms.realizedPl += pl;
    if (pl > 0) {
      ms.wins++;
    } else if (pl < 0) {
      ms.losses++;
    }
  });

  // Open positions per strategy/model
  positions.forEach(p => {
    const sid = strategyKey(p.strategy || '');
    if (!map[sid]) return;
    // Position records often lack a model; default to scalp for now (matches website)
    const mk = modelKey(p.model || 'scalp');
    map[sid].byModel[mk].open++;
  });

  // Subtitle = SELECTED date range label + trade count.
  // Falls back to data-derived min/max only when no range is supplied
  // (covers the future case where this helper is reused without filter).
  Object.values(map).forEach(s => {
    const stratTrades = trades.filter(t => strategyKey(t.strategy || '') === s.key);
    if (dateRange) {
      s.dateRange = `${rangeLabel(dateRange)} (${stratTrades.length} trades)`;
    } else {
      const times = stratTrades.map(t => t.opened_at || '').filter(Boolean).sort();
      if (times.length) {
        const fmtD = (iso: string) => {
          const d = new Date(iso);
          return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
        };
        s.dateRange = `${fmtD(times[0])} — ${fmtD(times[times.length - 1])} (${stratTrades.length} trades)`;
      }
    }

    (Object.keys(s.byModel) as ModelKey[]).forEach(mk => {
      const ms = s.byModel[mk];
      const total = ms.wins + ms.losses;
      ms.winRate = total > 0 ? Math.round((ms.wins / total) * 100) : 0;
      // Sum win/loss amounts from per-model trades
      const modelTrades = stratTrades.filter(t => modelKey(t.model) === mk
                                              && t.realized_pl !== null
                                              && t.realized_pl !== undefined);
      const winSum = modelTrades.reduce((acc, t) => acc + Math.max(t.realized_pl || 0, 0), 0);
      const lossSum = modelTrades.reduce((acc, t) => acc + Math.min(t.realized_pl || 0, 0), 0);
      ms.avgWin = ms.wins > 0 ? winSum / ms.wins : 0;
      ms.avgLoss = ms.losses > 0 ? lossSum / ms.losses : 0; // negative
    });
  });

  return Object.values(map).sort((a, b) => {
    const aPl = a.byModel.scalp.realizedPl + a.byModel.intraday.realizedPl + a.byModel.swing.realizedPl;
    const bPl = b.byModel.scalp.realizedPl + b.byModel.intraday.realizedPl + b.byModel.swing.realizedPl;
    return bPl - aPl;
  });
}

function calcPairs(trades: Trade[]): PairStats[] {
  const map: Record<string, PairStats> = {};
  trades.forEach(t => {
    const key = t.instrument || 'unknown';
    if (!map[key]) map[key] = { instrument: key, trades: 0, wins: 0, losses: 0, winRate: 0, pl: 0, pips: 0 };
    map[key].trades++;
    map[key].pl += t.realized_pl || 0;
    map[key].pips += t.pips || 0;
    if (t.won) map[key].wins++; else map[key].losses++;
  });
  return Object.values(map).map(p => ({
    ...p,
    winRate: p.trades ? Math.round((p.wins / p.trades) * 100) : 0,
    pl: Math.round(p.pl * 100) / 100,
    pips: Math.round(p.pips * 10) / 10,
  })).sort((a, b) => b.pl - a.pl);
}

// Group raw strategy names into one canonical key per strategy.
const STRATEGY_KEYS: Record<string, string> = {
  'vwap_2n20': 'vwap_2n20',
  '2n20': 'vwap_2n20',
  '2n20_exit': 'vwap_2n20',
  'htf_levels': 'htf_levels',
  'htf_supply_demand': 'htf_levels',
  'orb_breakout': 'orb_breakout',
  'manual_close': 'manual',
  'manual_test': 'manual',
  '': 'htf_levels',  // Options with no strategy tag are HTF
};

// Display name shown in the strategy card header. Matches the website's
// STRATEGY_NAMES map in saas/templates/trades.html so mobile and web
// stay in sync.
const STRATEGY_NAMES: Record<string, string> = {
  'vwap_2n20': 'VWAP Candlestick Trigger (2n20)',
  'htf_levels': 'HTF Untouched Levels',
  'orb_breakout': 'Opening Range Breakout',
  'manual': 'Manual',
};

const MODEL_LABELS: Record<ModelKey, string> = {
  scalp: 'SCALP',
  intraday: 'INTRADAY',
  swing: 'SWING',
};

const MODEL_COLORS: Record<ModelKey, string> = {
  scalp: Colors.scalp,
  intraday: Colors.intraday,
  swing: Colors.swing,
};

function strategyKey(raw: string): string {
  return STRATEGY_KEYS[raw] || raw || 'htf_levels';
}

function normalizeStrategy(raw: string): string {
  return STRATEGY_NAMES[strategyKey(raw)] || raw;
}

function fmt(val: number, decimals: number = 2): string {
  return Math.abs(val).toLocaleString('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

// Builds the URL the dashboard chart WebView loads. The /chart endpoint on
// bot.lumitrade.ai is the same Lightweight Charts page used by the existing
// chart route; it draws entry/stop/target lines from URL params.
const CHART_API_BASE = 'https://bot.lumitrade.ai';
function buildIntradayChartUrl(p: Position): string {
  const params: string[] = [
    `ticker=${encodeURIComponent(p.instrument)}`,
    `timespan=1h`,
    `count=300`,
    `strategy=htf_levels`,
  ];
  if (p.direction) params.push(`direction=${encodeURIComponent(p.direction)}`);
  if (p.entry_price) params.push(`entry=${p.entry_price}`);
  if (p.stop_loss) params.push(`stop=${p.stop_loss}`);
  if (p.take_profit) params.push(`exit=${p.take_profit}`);
  return `${CHART_API_BASE}/chart?${params.join('&')}`;
}

const TABS = [
  { key: 'forex', label: 'Forex', filter: (t: Trade) => t.broker === 'oanda' || t.asset_type === 'forex' },
  { key: 'stocks', label: 'Stocks', filter: (t: Trade) => t.asset_type === 'stock' && !t.instrument?.startsWith('I:') },
  { key: 'options', label: 'Options', filter: (t: Trade) => t.asset_type === 'options' },
  { key: 'indices', label: 'Indices', filter: (t: Trade) => !!t.instrument?.startsWith('I:') },
  { key: 'futures', label: 'Futures', filter: (t: Trade) => t.asset_type === 'futures' && !t.instrument?.startsWith('I:') },
];

export default function Dashboard() {
  const { user } = useAuth();
  const router = useRouter();
  const [allTrades, setAllTrades] = useState<Trade[]>([]);
  const [allPositions, setAllPositions] = useState<Position[]>([]);
  const [activeTab, setActiveTab] = useState('forex');
  const [refreshing, setRefreshing] = useState(false);
  const [dateRange, setDateRange] = useState<'today' | 'wtd' | 'mtd' | 'qtd' | 'ytd' | 'all'>('mtd');

  // Compute the start-of-range ISO timestamp for the user's selection.
  // All times are evaluated in user-local; the trades table stores UTC,
  // so we convert to UTC for the .gte() filter.
  const getRangeStartIso = (range: typeof dateRange): string | null => {
    if (range === 'all') return null;
    const now = new Date();
    const start = new Date(now.getFullYear(), now.getMonth(), now.getDate());  // local midnight today
    if (range === 'today') return start.toISOString();
    if (range === 'wtd') {
      // Week starts Monday
      const day = start.getDay(); // 0=Sun ... 6=Sat
      const daysBack = day === 0 ? 6 : day - 1;
      start.setDate(start.getDate() - daysBack);
      return start.toISOString();
    }
    if (range === 'mtd') {
      start.setDate(1);
      return start.toISOString();
    }
    if (range === 'qtd') {
      const qMonth = Math.floor(now.getMonth() / 3) * 3;
      start.setMonth(qMonth, 1);
      return start.toISOString();
    }
    if (range === 'ytd') {
      start.setMonth(0, 1);
      return start.toISOString();
    }
    return null;
  };

  const loadData = async (range = dateRange) => {
    if (!user) return;
    try {
      const startIso = getRangeStartIso(range);
      // Trades query — filter by closed_at if a range is set, order desc so
      // newest come first within the 1000-row Supabase default limit.
      let tradesQ = supabase
        .from('trades')
        .select('realized_pl, pips, won, strategy, model, broker, asset_type, instrument, opened_at, closed_at')
        .eq('user_id', user.id)
        .order('closed_at', { ascending: false })
        .limit(5000);
      if (startIso) tradesQ = tradesQ.gte('closed_at', startIso);

      const [tradesRes, posRes] = await Promise.all([
        tradesQ,
        supabase
          .from('positions')
          .select('strategy, asset_type, instrument, broker, model, broker_trade_id, direction, entry_price, stop_loss, take_profit, opened_at')
          .eq('user_id', user.id),
      ]);
      if (tradesRes.data) setAllTrades(tradesRes.data);
      if (posRes.data) setAllPositions(posRes.data);
    } catch (e) {
      console.error('Stats load error:', e);
    }
  };

  useEffect(() => { loadData(); }, [user]);
  // Reload when date range changes
  useEffect(() => { if (user) loadData(dateRange); }, [dateRange]);

  const onRefresh = async () => {
    setRefreshing(true);
    await loadData(dateRange);
    setRefreshing(false);
  };

  const tab = TABS.find(t => t.key === activeTab)!;
  const filtered = allTrades.filter(tab.filter);
  const filteredPositions = allPositions.filter(p =>
    tab.filter({
      asset_type: p.asset_type,
      instrument: p.instrument,
      broker: p.broker,
    } as Trade));
  const stats = calcStats(filtered);
  const strategies = calcStrategiesByModel(filtered, filteredPositions, dateRange);
  const pairs = calcPairs(filtered);
  const plColor = (val: number) => val >= 0 ? Colors.green : Colors.red;
  const hasModelData = (m: ModelStats) => m.open > 0 || m.closed > 0;

  // Intraday HTF chart picker — sorted newest first.
  const intradayHtfCandidates = useMemo(() =>
    allPositions
      .filter(p => p.strategy === 'htf_levels' && p.model === 'intraday'
                && p.entry_price && p.broker_trade_id)
      .sort((a, b) => (b.opened_at || '').localeCompare(a.opened_at || '')),
    [allPositions]);

  const [selectedChartTradeId, setSelectedChartTradeId] = useState<string | null>(null);
  useEffect(() => {
    if (intradayHtfCandidates.length === 0) {
      setSelectedChartTradeId(null);
    } else if (!selectedChartTradeId
        || !intradayHtfCandidates.find(p => p.broker_trade_id === selectedChartTradeId)) {
      setSelectedChartTradeId(intradayHtfCandidates[0].broker_trade_id || null);
    }
  }, [intradayHtfCandidates, selectedChartTradeId]);
  const selectedChartPosition = intradayHtfCandidates.find(p => p.broker_trade_id === selectedChartTradeId);
  const intradayChartUrl = selectedChartPosition ? buildIntradayChartUrl(selectedChartPosition) : null;

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} />}>
        {/* Header */}
        <View style={styles.header}>
          <Text style={styles.headerTitle}>LumiSignals</Text>
          <Text style={styles.headerSubtitle}>Trading Dashboard</Text>
        </View>

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

        {/* Date Range Selector — Today / WTD / MTD / QTD / YTD / All */}
        <View style={dateRangeStyles.bar}>
          {([
            ['today', 'Today'],
            ['wtd', 'WTD'],
            ['mtd', 'MTD'],
            ['qtd', 'QTD'],
            ['ytd', 'YTD'],
            ['all', 'All'],
          ] as const).map(([k, label]) => (
            <TouchableOpacity
              key={k}
              style={[dateRangeStyles.chip, dateRange === k && dateRangeStyles.chipActive]}
              onPress={() => setDateRange(k)}
            >
              <Text style={[dateRangeStyles.chipText, dateRange === k && dateRangeStyles.chipTextActive]}>
                {label}
              </Text>
            </TouchableOpacity>
          ))}
        </View>

        {/* Stats Grid */}
        <View style={styles.statsGrid}>
          <View style={styles.statCard}>
            <Text style={styles.statValue}>{stats.totalTrades}</Text>
            <Text style={styles.statLabel}>TRADES</Text>
          </View>
          <View style={styles.statCard}>
            <Text style={[styles.statValue, { color: plColor(stats.totalPl) }]}>
              {stats.totalPl >= 0 ? '' : '-'}${fmt(stats.totalPl)}
            </Text>
            <Text style={styles.statLabel}>P&L</Text>
          </View>
          <View style={styles.statCard}>
            <Text style={[styles.statValue, { color: stats.winRate >= 50 ? Colors.green : Colors.red }]}>
              {stats.totalTrades > 0 ? stats.winRate + '%' : '--'}
            </Text>
            <Text style={styles.statLabel}>WIN RATE</Text>
          </View>
          <View style={styles.statCard}>
            <Text style={[styles.statValue, { color: plColor(stats.totalPips) }]}>
              {fmt(stats.totalPips, 1)}
            </Text>
            <Text style={styles.statLabel}>PIPS</Text>
          </View>
        </View>

        {/* Strategy Breakdown — per-strategy section, per-model card.
            Mirrors saas/templates/trades.html futStrategyBreakdown. */}
        {strategies.length > 0 && (
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Strategy Performance</Text>
            {strategies.map(s => (
              <View key={s.key} style={styles.strategyCard}>
                <View style={styles.strategyHeader}>
                  <View style={styles.strategyBadge}>
                    <Text style={styles.strategyBadgeText}>STRATEGY</Text>
                  </View>
                  <Text style={styles.strategyName}>{s.name}</Text>
                </View>
                {!!s.dateRange && (
                  <Text style={styles.strategyDateRange}>{s.dateRange}</Text>
                )}
                {(['scalp', 'intraday', 'swing'] as ModelKey[]).map(mk => {
                  const ms = s.byModel[mk];
                  if (!hasModelData(ms)) {
                    // Render a faded "Coming soon" placeholder, matching the website
                    return (
                      <View key={mk} style={[styles.modelCard, styles.modelCardEmpty]}>
                        <Text style={[styles.modelCardTitle, { color: MODEL_COLORS[mk] }]}>
                          {MODEL_LABELS[mk]}
                        </Text>
                        <Text style={styles.modelCardEmptyText}>Coming soon</Text>
                      </View>
                    );
                  }
                  return (
                    <View key={mk} style={styles.modelCard}>
                      <Text style={[styles.modelCardTitle, { color: MODEL_COLORS[mk] }]}>
                        {MODEL_LABELS[mk]}
                      </Text>
                      <View style={styles.modelStatsGrid}>
                        <View style={styles.modelStat}>
                          <Text style={styles.modelStatValue}>{ms.open}</Text>
                          <Text style={styles.modelStatLabel}>OPEN</Text>
                        </View>
                        <View style={styles.modelStat}>
                          <Text style={styles.modelStatValue}>{ms.closed}</Text>
                          <Text style={styles.modelStatLabel}>CLOSED</Text>
                        </View>
                        <View style={styles.modelStat}>
                          <Text style={[
                            styles.modelStatValue,
                            { color: ms.closed > 0 ? (ms.winRate >= 50 ? Colors.green : Colors.red) : Colors.dark },
                          ]}>
                            {ms.closed > 0 ? `${ms.winRate}%` : '—'}
                          </Text>
                          <Text style={styles.modelStatLabel}>WIN RATE</Text>
                        </View>
                        <View style={styles.modelStat}>
                          <Text style={[styles.modelStatValue, { color: plColor(ms.realizedPl) }]}>
                            {ms.realizedPl >= 0 ? '+' : '-'}${fmt(Math.abs(ms.realizedPl))}
                          </Text>
                          <Text style={styles.modelStatLabel}>REALIZED P&L</Text>
                        </View>
                        <View style={styles.modelStat}>
                          <Text style={[styles.modelStatValue, { color: Colors.green }]}>
                            ${fmt(ms.avgWin)}
                          </Text>
                          <Text style={styles.modelStatLabel}>AVG WIN</Text>
                        </View>
                        <View style={styles.modelStat}>
                          <Text style={[styles.modelStatValue, { color: Colors.red }]}>
                            ${fmt(Math.abs(ms.avgLoss))}
                          </Text>
                          <Text style={styles.modelStatLabel}>AVG LOSS</Text>
                        </View>
                      </View>
                    </View>
                  );
                })}
              </View>
            ))}
          </View>
        )}

        {/* Pair Breakdown */}
        {pairs.length > 0 && (
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Performance by Pair</Text>
            <View style={styles.pairTable}>
              <View style={styles.pairHeaderRow}>
                <Text style={[styles.pairHeaderCell, { flex: 2 }]}>Pair</Text>
                <Text style={styles.pairHeaderCell}>Trades</Text>
                <Text style={styles.pairHeaderCell}>Win%</Text>
                <Text style={styles.pairHeaderCell}>P&L</Text>
                <Text style={styles.pairHeaderCell}>Pips</Text>
              </View>
              {pairs.map(p => (
                <View key={p.instrument} style={styles.pairRow}>
                  <TouchableOpacity style={{ flex: 2 }} onPress={() => router.push({ pathname: '/chart', params: { symbol: p.instrument } })}>
                    <Text style={[styles.pairCell, { fontWeight: '600', textDecorationLine: 'underline' }]}>{p.instrument}</Text>
                  </TouchableOpacity>
                  <Text style={styles.pairCell}>{p.trades}</Text>
                  <Text style={[styles.pairCell, { color: p.winRate >= 50 ? Colors.green : Colors.red }]}>
                    {p.winRate}%
                  </Text>
                  <Text style={[styles.pairCell, { color: plColor(p.pl) }]}>
                    {p.pl >= 0 ? '' : '-'}${fmt(p.pl)}
                  </Text>
                  <Text style={[styles.pairCell, { color: plColor(p.pips) }]}>
                    {fmt(p.pips, 1)}
                  </Text>
                </View>
              ))}
            </View>
          </View>
        )}

        {stats.totalTrades === 0 && (
          <View style={styles.empty}>
            <Text style={styles.emptyText}>No {tab.label.toLowerCase()} trades yet</Text>
          </View>
        )}

        {/* HTF Intraday Chart — picker + Lightweight Charts WebView with
            entry / stop / target lines drawn via /chart URL params. */}
        {intradayHtfCandidates.length > 0 && (
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>HTF Intraday Chart</Text>
            <ScrollView
              horizontal
              showsHorizontalScrollIndicator={false}
              contentContainerStyle={styles.chartPickerRow}
            >
              {intradayHtfCandidates.map(p => {
                const active = p.broker_trade_id === selectedChartTradeId;
                return (
                  <TouchableOpacity
                    key={p.broker_trade_id}
                    onPress={() => setSelectedChartTradeId(p.broker_trade_id || null)}
                    style={[styles.chartChip, active && styles.chartChipActive]}
                  >
                    <Text style={[styles.chartChipText, active && styles.chartChipTextActive]}>
                      {p.instrument}
                    </Text>
                    <Text style={[styles.chartChipSide, active && styles.chartChipTextActive]}>
                      {p.direction === 'BUY' || p.direction === 'LONG' ? '↑' : '↓'}
                    </Text>
                  </TouchableOpacity>
                );
              })}
            </ScrollView>
            {selectedChartPosition && (
              <TouchableOpacity
                style={styles.chartMeta}
                onPress={() => router.push({
                  pathname: '/chart',
                  params: {
                    symbol: selectedChartPosition.instrument,
                    interval: '1h',
                    entry: String(selectedChartPosition.entry_price || ''),
                    stop: String(selectedChartPosition.stop_loss || ''),
                    exit: String(selectedChartPosition.take_profit || ''),
                    direction: selectedChartPosition.direction || '',
                    strategy: 'htf_levels',
                  },
                })}
              >
                <Text style={styles.chartMetaText}>
                  Entry {selectedChartPosition.entry_price?.toFixed(5) || '—'}
                  {'  ·  '}Stop {selectedChartPosition.stop_loss?.toFixed(5) || '—'}
                  {selectedChartPosition.take_profit
                    ? `  ·  Target ${selectedChartPosition.take_profit.toFixed(5)}`
                    : ''}
                </Text>
                <Text style={styles.chartExpandHint}>Tap to expand ›</Text>
              </TouchableOpacity>
            )}
            {intradayChartUrl && (
              <View style={styles.chartContainer}>
                <WebView
                  source={{ uri: intradayChartUrl }}
                  style={{ flex: 1, backgroundColor: 'transparent' }}
                  scrollEnabled={false}
                  originWhitelist={['*']}
                />
              </View>
            )}
          </View>
        )}

        <View style={{ height: 40 }} />
      </ScrollView>
    </SafeAreaView>
  );
}

const dateRangeStyles = StyleSheet.create({
  bar: {
    flexDirection: 'row',
    paddingHorizontal: 12,
    paddingTop: 8,
    paddingBottom: 4,
    gap: 6,
  },
  chip: {
    flex: 1,
    paddingVertical: 6,
    paddingHorizontal: 4,
    borderRadius: 12,
    backgroundColor: '#F5F5F0',
    borderWidth: 1,
    borderColor: '#E0E0DA',
    alignItems: 'center',
  },
  chipActive: {
    backgroundColor: '#7C8765',
    borderColor: '#7C8765',
  },
  chipText: {
    fontSize: 12,
    fontWeight: '500',
    color: '#555',
  },
  chipTextActive: {
    color: '#FFFFFF',
    fontWeight: '600',
  },
});

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: Colors.cream },
  header: { paddingHorizontal: 20, paddingTop: 12, paddingBottom: 8 },
  headerTitle: { fontSize: 28, fontWeight: '300', color: Colors.dark },
  headerSubtitle: { fontSize: 12, color: Colors.textLight, letterSpacing: 1, textTransform: 'uppercase', marginTop: 2 },
  // Tabs
  tabBar: {
    flexDirection: 'row',
    marginHorizontal: 16,
    marginVertical: 12,
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
  tabActive: {
    backgroundColor: Colors.olive,
  },
  tabText: { fontSize: 13, fontWeight: '500', color: Colors.textLight },
  tabTextActive: { color: Colors.gold },
  // Stats
  statsGrid: { flexDirection: 'row', flexWrap: 'wrap', paddingHorizontal: 16, gap: 10 },
  statCard: {
    flex: 1, minWidth: '45%',
    backgroundColor: Colors.white, borderRadius: 12, padding: 16, alignItems: 'center',
  },
  statValue: { fontSize: 22, fontWeight: '300', color: Colors.dark },
  statLabel: { fontSize: 10, color: Colors.textLight, letterSpacing: 0.5, marginTop: 4 },
  // Sections
  section: { paddingHorizontal: 16, marginTop: 20 },
  sectionTitle: { fontSize: 16, fontWeight: '500', color: Colors.dark, marginBottom: 12 },
  // Strategy cards
  strategyCard: { backgroundColor: Colors.white, borderRadius: 12, padding: 16, marginBottom: 12 },
  strategyHeader: { flexDirection: 'row', alignItems: 'center', gap: 10, marginBottom: 4 },
  strategyBadge: { backgroundColor: Colors.olive, paddingHorizontal: 10, paddingVertical: 4, borderRadius: 50 },
  strategyBadgeText: { color: Colors.gold, fontSize: 10, fontWeight: '600', letterSpacing: 0.3 },
  strategyName: { fontSize: 18, fontWeight: '500', color: Colors.dark, flexShrink: 1 },
  strategyDateRange: { fontSize: 11, color: Colors.textLight, marginTop: 2, marginBottom: 12 },
  // Per-model card under each strategy header
  modelCard: {
    backgroundColor: Colors.cream,
    borderRadius: 10,
    padding: 14,
    marginTop: 10,
  },
  modelCardEmpty: { opacity: 0.4 },
  modelCardTitle: {
    fontSize: 12,
    fontWeight: '600',
    letterSpacing: 1,
    textTransform: 'uppercase',
    paddingBottom: 8,
    marginBottom: 12,
    borderBottomWidth: 1,
    borderBottomColor: '#e8e2d8',
  },
  modelCardEmptyText: {
    textAlign: 'center',
    color: Colors.textLight,
    fontSize: 12,
    paddingVertical: 12,
  },
  modelStatsGrid: { flexDirection: 'row', flexWrap: 'wrap' },
  modelStat: { width: '50%', alignItems: 'center', paddingVertical: 8 },
  modelStatValue: { fontSize: 22, fontWeight: '300', color: Colors.dark },
  modelStatLabel: { fontSize: 10, color: Colors.textLight, letterSpacing: 0.5, marginTop: 2 },
  // Pair table
  pairTable: { backgroundColor: Colors.white, borderRadius: 12, padding: 12 },
  pairHeaderRow: { flexDirection: 'row', paddingBottom: 8, borderBottomWidth: 1, borderBottomColor: '#f0f0f0' },
  pairHeaderCell: { flex: 1, fontSize: 10, color: Colors.textLight, textTransform: 'uppercase', letterSpacing: 0.3 },
  pairRow: { flexDirection: 'row', paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: '#f8f8f5' },
  pairCell: { flex: 1, fontSize: 13, color: Colors.dark },
  // Empty
  empty: { alignItems: 'center', paddingTop: 40 },
  emptyText: { fontSize: 15, color: Colors.textLight },
  // HTF intraday chart picker + WebView
  chartPickerRow: {
    paddingVertical: 4,
    gap: 8,
  },
  chartChip: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: Colors.white,
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 50,
    marginRight: 8,
    gap: 6,
  },
  chartChipActive: { backgroundColor: Colors.olive },
  chartChipText: { fontSize: 13, fontWeight: '600', color: Colors.dark },
  chartChipTextActive: { color: Colors.gold },
  chartChipSide: { fontSize: 13, fontWeight: '600', color: Colors.textLight },
  chartMeta: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: 10,
    paddingHorizontal: 4,
  },
  chartMetaText: { fontSize: 12, color: Colors.textMedium, flex: 1 },
  chartExpandHint: { fontSize: 11, color: Colors.olive, fontWeight: '600' },
  chartContainer: {
    height: 380,
    backgroundColor: Colors.white,
    borderRadius: 12,
    overflow: 'hidden',
  },
});
