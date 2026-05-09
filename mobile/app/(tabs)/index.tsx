import { useEffect, useState } from 'react';
import { View, Text, ScrollView, StyleSheet, RefreshControl, TouchableOpacity } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
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

function calcStrategiesByModel(trades: Trade[], positions: Position[]): StrategyStats[] {
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

  // Date range subtitle + averages — done after all trades counted
  Object.values(map).forEach(s => {
    const stratTrades = trades.filter(t => strategyKey(t.strategy || '') === s.key);
    const times = stratTrades.map(t => t.opened_at || '').filter(Boolean).sort();
    if (times.length) {
      const fmtD = (iso: string) => {
        const d = new Date(iso);
        return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
      };
      s.dateRange = `${fmtD(times[0])} — ${fmtD(times[times.length - 1])} (${stratTrades.length} trades)`;
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

  const loadData = async () => {
    if (!user) return;
    try {
      const [tradesRes, posRes] = await Promise.all([
        supabase
          .from('trades')
          .select('realized_pl, pips, won, strategy, model, broker, asset_type, instrument, opened_at')
          .eq('user_id', user.id),
        supabase
          .from('positions')
          .select('strategy, asset_type, instrument, broker, model')
          .eq('user_id', user.id),
      ]);
      if (tradesRes.data) setAllTrades(tradesRes.data);
      if (posRes.data) setAllPositions(posRes.data);
    } catch (e) {
      console.error('Stats load error:', e);
    }
  };

  useEffect(() => { loadData(); }, [user]);

  const onRefresh = async () => {
    setRefreshing(true);
    await loadData();
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
  const strategies = calcStrategiesByModel(filtered, filteredPositions);
  const pairs = calcPairs(filtered);
  const plColor = (val: number) => val >= 0 ? Colors.green : Colors.red;
  const hasModelData = (m: ModelStats) => m.open > 0 || m.closed > 0;

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

        <View style={{ height: 40 }} />
      </ScrollView>
    </SafeAreaView>
  );
}

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
});
