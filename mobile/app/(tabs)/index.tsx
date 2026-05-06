import { useEffect, useState } from 'react';
import { View, Text, ScrollView, StyleSheet, RefreshControl, TouchableOpacity } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { supabase } from '@/lib/supabase';
import { useAuth } from '@/contexts/auth';
import { Colors } from '@/constants/theme';

type Trade = {
  realized_pl: number;
  pips: number;
  won: boolean;
  strategy: string;
  model: string;
  broker: string;
  asset_type: string;
  instrument: string;
};

type BrokerStats = {
  totalTrades: number;
  wins: number;
  losses: number;
  winRate: number;
  totalPl: number;
  totalPips: number;
};

type StrategyStats = {
  name: string;
  wins: number;
  losses: number;
  pl: number;
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
  if (!trades.length) return emptyStats();
  const wins = trades.filter(t => t.won).length;
  const totalPl = trades.reduce((s, t) => s + (t.realized_pl || 0), 0);
  const totalPips = trades.reduce((s, t) => s + (t.pips || 0), 0);
  return {
    totalTrades: trades.length,
    wins,
    losses: trades.length - wins,
    winRate: Math.round((wins / trades.length) * 100),
    totalPl: Math.round(totalPl * 100) / 100,
    totalPips: Math.round(totalPips * 10) / 10,
  };
}

function calcStrategies(trades: Trade[]): StrategyStats[] {
  const map: Record<string, StrategyStats> = {};
  trades.forEach(t => {
    const key = (t.strategy || 'unknown');
    if (!map[key]) map[key] = { name: key, wins: 0, losses: 0, pl: 0 };
    map[key].pl += t.realized_pl || 0;
    if (t.won) map[key].wins++; else map[key].losses++;
  });
  return Object.values(map).sort((a, b) => b.pl - a.pl);
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

const STRATEGY_LABELS: Record<string, string> = {
  'vwap_2n20': 'VWAP 2n20',
  'htf_levels': 'HTF Untouched Levels',
  'orb_breakout': 'Opening Range Breakout',
};

const TABS = [
  { key: 'forex', label: 'Forex', filter: (t: Trade) => t.broker === 'oanda' || t.asset_type === 'forex' },
  { key: 'options', label: 'Options', filter: (t: Trade) => t.asset_type === 'options' },
  { key: 'futures', label: 'Futures', filter: (t: Trade) => t.asset_type === 'futures' },
];

export default function Dashboard() {
  const { user } = useAuth();
  const [allTrades, setAllTrades] = useState<Trade[]>([]);
  const [activeTab, setActiveTab] = useState('forex');
  const [refreshing, setRefreshing] = useState(false);

  const loadTrades = async () => {
    if (!user) return;
    try {
      const { data } = await supabase
        .from('trades')
        .select('realized_pl, pips, won, strategy, model, broker, asset_type, instrument')
        .eq('user_id', user.id);
      if (data) setAllTrades(data);
    } catch (e) {
      console.error('Stats load error:', e);
    }
  };

  useEffect(() => { loadTrades(); }, [user]);

  const onRefresh = async () => {
    setRefreshing(true);
    await loadTrades();
    setRefreshing(false);
  };

  const tab = TABS.find(t => t.key === activeTab)!;
  const filtered = allTrades.filter(tab.filter);
  const stats = calcStats(filtered);
  const strategies = calcStrategies(filtered);
  const pairs = calcPairs(filtered);
  const plColor = (val: number) => val >= 0 ? Colors.green : Colors.red;

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
              ${Math.abs(stats.totalPl).toFixed(2)}
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
              {stats.totalPips.toFixed(1)}
            </Text>
            <Text style={styles.statLabel}>PIPS</Text>
          </View>
        </View>

        {/* Strategy Breakdown */}
        {strategies.length > 0 && (
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Strategy Performance</Text>
            {strategies.map(s => (
              <View key={s.name} style={styles.strategyCard}>
                <View style={styles.strategyHeader}>
                  <View style={styles.strategyBadge}>
                    <Text style={styles.strategyBadgeText}>STRATEGY</Text>
                  </View>
                  <Text style={styles.strategyName}>{STRATEGY_LABELS[s.name] || s.name}</Text>
                </View>
                <View style={styles.strategyStats}>
                  <View style={styles.strategyStat}>
                    <Text style={styles.strategyStatValue}>{s.wins}</Text>
                    <Text style={styles.strategyStatLabel}>Wins</Text>
                  </View>
                  <View style={styles.strategyStat}>
                    <Text style={styles.strategyStatValue}>{s.losses}</Text>
                    <Text style={styles.strategyStatLabel}>Losses</Text>
                  </View>
                  <View style={styles.strategyStat}>
                    <Text style={[styles.strategyStatValue, { color: plColor(s.pl) }]}>
                      ${Math.abs(s.pl).toFixed(2)}
                    </Text>
                    <Text style={styles.strategyStatLabel}>P&L</Text>
                  </View>
                </View>
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
                  <Text style={[styles.pairCell, { flex: 2, fontWeight: '600' }]}>{p.instrument}</Text>
                  <Text style={styles.pairCell}>{p.trades}</Text>
                  <Text style={[styles.pairCell, { color: p.winRate >= 50 ? Colors.green : Colors.red }]}>
                    {p.winRate}%
                  </Text>
                  <Text style={[styles.pairCell, { color: plColor(p.pl) }]}>
                    ${p.pl.toFixed(2)}
                  </Text>
                  <Text style={[styles.pairCell, { color: plColor(p.pips) }]}>
                    {p.pips.toFixed(1)}
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
  strategyCard: { backgroundColor: Colors.white, borderRadius: 12, padding: 16, marginBottom: 8 },
  strategyHeader: { flexDirection: 'row', alignItems: 'center', gap: 10, marginBottom: 14 },
  strategyBadge: { backgroundColor: Colors.olive, paddingHorizontal: 10, paddingVertical: 4, borderRadius: 50 },
  strategyBadgeText: { color: Colors.gold, fontSize: 10, fontWeight: '600', letterSpacing: 0.3 },
  strategyName: { fontSize: 15, fontWeight: '500', color: Colors.dark },
  strategyStats: { flexDirection: 'row', justifyContent: 'space-around' },
  strategyStat: { alignItems: 'center' },
  strategyStatValue: { fontSize: 20, fontWeight: '300', color: Colors.dark },
  strategyStatLabel: { fontSize: 10, color: Colors.textLight, marginTop: 2 },
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
