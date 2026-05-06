import { useEffect, useState } from 'react';
import { View, Text, ScrollView, StyleSheet, RefreshControl } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { supabase } from '@/lib/supabase';
import { useAuth } from '@/contexts/auth';
import { Colors } from '@/constants/theme';

type Stats = {
  totalTrades: number;
  wins: number;
  losses: number;
  winRate: number;
  totalPl: number;
  totalPips: number;
};

export default function Dashboard() {
  const { user } = useAuth();
  const [stats, setStats] = useState<Stats>({ totalTrades: 0, wins: 0, losses: 0, winRate: 0, totalPl: 0, totalPips: 0 });
  const [refreshing, setRefreshing] = useState(false);

  const loadStats = async () => {
    if (!user) return;
    try {
      const { data } = await supabase
        .from('trades')
        .select('realized_pl, pips, won')
        .eq('user_id', user.id);

      if (data && data.length > 0) {
        const wins = data.filter(t => t.won).length;
        const totalPl = data.reduce((s, t) => s + (t.realized_pl || 0), 0);
        const totalPips = data.reduce((s, t) => s + (t.pips || 0), 0);
        setStats({
          totalTrades: data.length,
          wins,
          losses: data.length - wins,
          winRate: Math.round((wins / data.length) * 100),
          totalPl: Math.round(totalPl * 100) / 100,
          totalPips: Math.round(totalPips * 10) / 10,
        });
      }
    } catch (e) {
      console.error('Stats load error:', e);
    }
  };

  useEffect(() => { loadStats(); }, [user]);

  const onRefresh = async () => {
    setRefreshing(true);
    await loadStats();
    setRefreshing(false);
  };

  const plColor = (val: number) => val >= 0 ? Colors.green : Colors.red;

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} />}
      >
        {/* Header */}
        <View style={styles.header}>
          <Text style={styles.headerTitle}>LumiSignals</Text>
          <Text style={styles.headerSubtitle}>Trading Dashboard</Text>
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
              {stats.winRate}%
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

        {/* Strategy Cards */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Strategy Performance</Text>
          <View style={styles.strategyCard}>
            <View style={styles.strategyHeader}>
              <View style={styles.strategyBadge}>
                <Text style={styles.strategyBadgeText}>STRATEGY</Text>
              </View>
              <Text style={styles.strategyName}>VWAP 2n20</Text>
            </View>
            <View style={styles.strategyStats}>
              <View style={styles.strategyStat}>
                <Text style={styles.strategyStatValue}>{stats.wins}</Text>
                <Text style={styles.strategyStatLabel}>Wins</Text>
              </View>
              <View style={styles.strategyStat}>
                <Text style={styles.strategyStatValue}>{stats.losses}</Text>
                <Text style={styles.strategyStatLabel}>Losses</Text>
              </View>
              <View style={styles.strategyStat}>
                <Text style={[styles.strategyStatValue, { color: plColor(stats.totalPl) }]}>
                  ${Math.abs(stats.totalPl).toFixed(2)}
                </Text>
                <Text style={styles.strategyStatLabel}>P&L</Text>
              </View>
            </View>
          </View>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: Colors.cream },
  header: {
    paddingHorizontal: 20,
    paddingTop: 12,
    paddingBottom: 20,
  },
  headerTitle: { fontSize: 28, fontWeight: '300', color: Colors.dark },
  headerSubtitle: { fontSize: 12, color: Colors.textLight, letterSpacing: 1, textTransform: 'uppercase', marginTop: 2 },
  statsGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    paddingHorizontal: 16,
    gap: 10,
  },
  statCard: {
    flex: 1,
    minWidth: '45%',
    backgroundColor: Colors.white,
    borderRadius: 12,
    padding: 16,
    alignItems: 'center',
  },
  statValue: { fontSize: 22, fontWeight: '300', color: Colors.dark },
  statLabel: { fontSize: 10, color: Colors.textLight, letterSpacing: 0.5, marginTop: 4 },
  section: { paddingHorizontal: 16, marginTop: 20 },
  sectionTitle: { fontSize: 16, fontWeight: '500', color: Colors.dark, marginBottom: 12 },
  strategyCard: {
    backgroundColor: Colors.white,
    borderRadius: 12,
    padding: 16,
  },
  strategyHeader: { flexDirection: 'row', alignItems: 'center', gap: 10, marginBottom: 14 },
  strategyBadge: {
    backgroundColor: Colors.olive,
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 50,
  },
  strategyBadgeText: { color: Colors.gold, fontSize: 10, fontWeight: '600', letterSpacing: 0.3 },
  strategyName: { fontSize: 15, fontWeight: '500', color: Colors.dark },
  strategyStats: { flexDirection: 'row', justifyContent: 'space-around' },
  strategyStat: { alignItems: 'center' },
  strategyStatValue: { fontSize: 20, fontWeight: '300', color: Colors.dark },
  strategyStatLabel: { fontSize: 10, color: Colors.textLight, marginTop: 2 },
});
