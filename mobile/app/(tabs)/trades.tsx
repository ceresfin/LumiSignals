import { useEffect, useState } from 'react';
import { View, Text, FlatList, StyleSheet, RefreshControl, TouchableOpacity } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useRouter } from 'expo-router';
import { supabase } from '@/lib/supabase';
import { useAuth } from '@/contexts/auth';
import { Colors } from '@/constants/theme';

type Trade = {
  id: number;
  broker: string;
  asset_type: string;
  instrument: string;
  direction: string;
  entry_price: number;
  exit_price: number;
  realized_pl: number;
  pips: number;
  achieved_rr: number;
  close_reason: string;
  strategy: string;
  model: string;
  won: boolean;
  opened_at: string;
  closed_at: string;
  duration_mins: number;
};

const STRATEGY_TIMEFRAMES: Record<string, string> = {
  'scalp_2n20': '2m',
  'vwap_2n20': '2m',
  '2n20': '2m',
  'scalp': '15m',
  'intraday': '1h',
  'swing': '1d',
  'orb_breakout': '15m',
};

function getChartTimeframe(model?: string, strategy?: string): string {
  if (model && STRATEGY_TIMEFRAMES[model]) return STRATEGY_TIMEFRAMES[model];
  if (strategy && STRATEGY_TIMEFRAMES[strategy]) return STRATEGY_TIMEFRAMES[strategy];
  return '15m';
}

function TradeRow({ trade, onChartPress }: { trade: Trade; onChartPress: (instrument: string, tf: string) => void }) {
  const dir = trade.direction === 'LONG' || trade.direction === 'BUY' ? 'BUY' : 'SELL';
  const pl = trade.realized_pl || 0;

  return (
    <View style={styles.tradeRow}>
      <View style={styles.tradeTop}>
        <TouchableOpacity onPress={() => onChartPress(trade.instrument, getChartTimeframe(trade.model, trade.strategy))}>
          <Text style={[styles.tradePair, { textDecorationLine: 'underline' }]}>{trade.instrument}</Text>
        </TouchableOpacity>
        <View style={[styles.dirBadge, { backgroundColor: dir === 'BUY' ? '#e8f5e9' : '#fdecea' }]}>
          <Text style={[styles.dirText, { color: dir === 'BUY' ? Colors.green : Colors.red }]}>{dir}</Text>
        </View>
        <View style={{ flex: 1 }} />
        <Text style={[styles.tradePl, { color: pl >= 0 ? Colors.green : Colors.red }]}>
          {pl >= 0 ? '+' : ''}${pl.toFixed(2)}
        </Text>
        <View style={[styles.resultBadge, { backgroundColor: trade.won ? '#e8f5e9' : '#fdecea' }]}>
          <Text style={[styles.resultText, { color: trade.won ? Colors.green : Colors.red }]}>
            {trade.won ? 'WIN' : 'LOSS'}
          </Text>
        </View>
      </View>
      <View style={styles.tradeBottom}>
        <Text style={styles.tradeDetail}>
          {trade.entry_price?.toFixed(5)} → {trade.exit_price?.toFixed(5)}
        </Text>
        <Text style={styles.tradeDetail}>
          {trade.pips?.toFixed(1)} pips
        </Text>
        {trade.achieved_rr ? (
          <Text style={[styles.tradeDetail, { color: trade.achieved_rr > 0 ? Colors.green : Colors.red }]}>
            {trade.achieved_rr > 0 ? '+' : ''}{trade.achieved_rr.toFixed(1)}R
          </Text>
        ) : null}
        <Text style={styles.tradeDetail}>{trade.close_reason}</Text>
      </View>
      <View style={styles.tradeFooter}>
        <Text style={styles.tradeTime}>
          {trade.opened_at ? new Date(trade.opened_at).toLocaleString('en-US', {
            month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', hour12: true,
          }) : ''}
        </Text>
        <Text style={styles.tradeTime}>
          {(() => {
            if (trade.duration_mins) return trade.duration_mins + 'm';
            if (trade.opened_at && trade.closed_at) {
              const mins = Math.round((new Date(trade.closed_at).getTime() - new Date(trade.opened_at).getTime()) / 60000);
              if (mins > 0) return mins + 'm';
            }
            return '';
          })()}
        </Text>
        <Text style={[styles.modelBadge, {
          color: trade.model?.includes('2n20') ? Colors.amber : Colors.scalp,
        }]}>
          {trade.model?.toUpperCase() || trade.strategy?.toUpperCase()}
        </Text>
      </View>
    </View>
  );
}

export default function Trades() {
  const router = useRouter();
  const { user } = useAuth();
  const [allTrades, setAllTrades] = useState<Trade[]>([]);
  const [activeTab, setActiveTab] = useState('forex');
  const [refreshing, setRefreshing] = useState(false);

  const TABS = [
    { key: 'forex', label: 'Forex', filter: (t: Trade) => t.broker === 'oanda' || t.asset_type === 'forex' },
    { key: 'stocks', label: 'Stocks', filter: (t: Trade) => t.asset_type === 'stock' && !t.instrument?.startsWith('I:') },
    { key: 'options', label: 'Options', filter: (t: Trade) => t.asset_type === 'options' },
    { key: 'indices', label: 'Indices', filter: (t: Trade) => !!t.instrument?.startsWith('I:') },
    { key: 'futures', label: 'Futures', filter: (t: Trade) => t.asset_type === 'futures' && !t.instrument?.startsWith('I:') },
  ];

  const loadTrades = async () => {
    if (!user) return;
    try {
      const { data } = await supabase
        .from('trades')
        .select('*')
        .eq('user_id', user.id)
        .order('closed_at', { ascending: false })
        .limit(500);

      if (data) setAllTrades(data);
    } catch (e) {
      console.error('Trades load error:', e);
    }
  };

  useEffect(() => { loadTrades(); }, [user]);

  // Realtime subscription for new trades
  useEffect(() => {
    if (!user) return;
    const channel = supabase
      .channel('trades-realtime')
      .on(
        'postgres_changes',
        { event: 'INSERT', schema: 'public', table: 'trades', filter: `user_id=eq.${user.id}` },
        (payload) => {
          setAllTrades(prev => [payload.new as Trade, ...prev]);
        }
      )
      .subscribe();

    return () => { supabase.removeChannel(channel); };
  }, [user]);

  const onRefresh = async () => {
    setRefreshing(true);
    await loadTrades();
    setRefreshing(false);
  };

  const tab = TABS.find(t => t.key === activeTab)!;
  const trades = allTrades.filter(tab.filter);

  return (
    <SafeAreaView style={styles.container}>
      <View style={styles.header}>
        <Text style={styles.headerTitle}>Closed Trades</Text>
        <Text style={styles.headerCount}>{trades.length}</Text>
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

      <FlatList
        data={trades}
        keyExtractor={(item) => item.id.toString()}
        renderItem={({ item }) => <TradeRow trade={item} onChartPress={(sym, tf) => router.push({
          pathname: '/chart',
          params: {
            symbol: sym,
            interval: tf,
            entry: item.entry_price?.toString(),
            exit: item.exit_price?.toString(),
            stop: item.stop_loss?.toString(),
            direction: item.direction,
            strategy: item.strategy || item.model || '',
          }
        })} />}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} />}
        contentContainerStyle={{ paddingHorizontal: 16, paddingBottom: 20 }}
        ListEmptyComponent={
          <View style={styles.empty}>
            <Text style={styles.emptyText}>No trades yet</Text>
            <Text style={styles.emptySubtext}>Trades will appear here as the bot closes positions</Text>
          </View>
        }
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: Colors.cream },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 20,
    paddingTop: 12,
    paddingBottom: 12,
  },
  headerTitle: { fontSize: 22, fontWeight: '300', color: Colors.dark },
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
  tabActive: {
    backgroundColor: Colors.olive,
  },
  tabText: { fontSize: 13, fontWeight: '500', color: Colors.textLight },
  tabTextActive: { color: Colors.gold },
  headerCount: {
    fontSize: 13,
    color: Colors.textLight,
    backgroundColor: Colors.white,
    paddingHorizontal: 10,
    paddingVertical: 2,
    borderRadius: 50,
  },
  tradeRow: {
    backgroundColor: Colors.white,
    borderRadius: 12,
    padding: 14,
    marginBottom: 8,
  },
  tradeTop: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginBottom: 6,
  },
  tradePair: { fontSize: 15, fontWeight: '600', color: Colors.dark },
  dirBadge: { paddingHorizontal: 8, paddingVertical: 2, borderRadius: 50 },
  dirText: { fontSize: 11, fontWeight: '600' },
  tradePl: { fontSize: 16, fontWeight: '500', marginRight: 8 },
  resultBadge: { paddingHorizontal: 8, paddingVertical: 2, borderRadius: 50 },
  resultText: { fontSize: 10, fontWeight: '700' },
  tradeBottom: {
    flexDirection: 'row',
    gap: 12,
    marginBottom: 6,
  },
  tradeDetail: { fontSize: 12, color: Colors.textLight },
  tradeFooter: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  tradeTime: { fontSize: 11, color: Colors.textLight },
  modelBadge: { fontSize: 10, fontWeight: '700', letterSpacing: 0.3 },
  empty: { alignItems: 'center', paddingTop: 60 },
  emptyText: { fontSize: 16, color: Colors.textLight },
  emptySubtext: { fontSize: 13, color: Colors.textLight, marginTop: 6 },
});
