import { useEffect, useState } from 'react';
import { View, Text, FlatList, StyleSheet, RefreshControl, TouchableOpacity } from 'react-native';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { supabase } from '@/lib/supabase';
import { useAuth } from '@/contexts/auth';
import { Colors } from '@/constants/theme';

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
  opened_at: string;
  updated_at: string;
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

function PositionRow({ position, onChartPress }: { position: Position; onChartPress: (instrument: string, tf: string) => void }) {
  const dir = position.direction === 'LONG' || position.direction === 'BUY' ? 'BUY' : 'SELL';
  const pl = position.unrealized_pl || 0;
  const isOptions = position.asset_type === 'options';

  return (
    <View style={styles.posRow}>
      <View style={styles.posTop}>
        <TouchableOpacity onPress={() => onChartPress(position.instrument, getChartTimeframe(position.model, position.strategy))}>
          <Text style={[styles.posInstrument, { textDecorationLine: 'underline' }]}>{position.instrument}</Text>
        </TouchableOpacity>
        <View style={[styles.dirBadge, { backgroundColor: dir === 'BUY' ? '#e8f5e9' : '#fdecea' }]}>
          <Text style={[styles.dirText, { color: dir === 'BUY' ? Colors.green : Colors.red }]}>{dir}</Text>
        </View>
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

      <View style={styles.posFooter}>
        <Text style={styles.posTime}>
          {position.opened_at ? new Date(position.opened_at).toLocaleString('en-US', {
            month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', hour12: true,
          }) : ''}
        </Text>
        <Text style={[styles.modelBadge, {
          color: position.model?.includes('2n20') ? Colors.amber : Colors.scalp,
        }]}>
          {position.model?.toUpperCase() || position.strategy?.toUpperCase() || ''}
        </Text>
      </View>
    </View>
  );
}

export default function Positions() {
  const { user } = useAuth();
  const router = useRouter();
  const [allPositions, setAllPositions] = useState<Position[]>([]);
  const [activeTab, setActiveTab] = useState('forex');
  const [refreshing, setRefreshing] = useState(false);

  const TABS = [
    { key: 'forex', label: 'Forex', filter: (p: Position) => p.broker === 'oanda' || p.asset_type === 'forex' },
    { key: 'options', label: 'Options', filter: (p: Position) => p.asset_type === 'options' },
    { key: 'futures', label: 'Futures', filter: (p: Position) => p.asset_type === 'futures' },
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

  useEffect(() => { loadPositions(); }, [user]);

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

  const onRefresh = async () => {
    setRefreshing(true);
    await loadPositions();
    setRefreshing(false);
  };

  const tab = TABS.find(t => t.key === activeTab)!;
  const positions = allPositions.filter(tab.filter);
  const totalPl = positions.reduce((s, p) => s + (p.unrealized_pl || 0), 0);

  return (
    <SafeAreaView style={styles.container}>
      <View style={styles.header}>
        <View>
          <Text style={styles.headerTitle}>Open Positions</Text>
          <Text style={styles.headerSubtitle}>
            {positions.length} position{positions.length !== 1 ? 's' : ''}
          </Text>
        </View>
        <View style={styles.plSummary}>
          <Text style={styles.plLabel}>Unrealized</Text>
          <Text style={[styles.plTotal, { color: totalPl >= 0 ? Colors.green : Colors.red }]}>
            {totalPl >= 0 ? '+' : ''}${totalPl.toFixed(2)}
          </Text>
        </View>
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
        data={positions}
        keyExtractor={(item) => item.id.toString()}
        renderItem={({ item }) => <PositionRow position={item} onChartPress={(sym, tf) => router.push({
          pathname: '/chart',
          params: {
            symbol: sym,
            interval: tf,
            entry: item.entry_price?.toString(),
            stop: item.stop_loss?.toString(),
            direction: item.direction,
            strategy: item.strategy || item.model || '',
          }
        })} />}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} />}
        contentContainerStyle={{ paddingHorizontal: 16, paddingBottom: 20 }}
        ListEmptyComponent={
          <View style={styles.empty}>
            <Text style={styles.emptyText}>No open positions</Text>
            <Text style={styles.emptySubtext}>Positions appear here when the bot opens a trade</Text>
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
  empty: { alignItems: 'center', paddingTop: 60 },
  emptyText: { fontSize: 16, color: Colors.textLight },
  emptySubtext: { fontSize: 13, color: Colors.textLight, marginTop: 6, textAlign: 'center' },
});
